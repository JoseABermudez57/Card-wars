using System;
using System.Collections.Generic;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace CardWars.Core
{
    /// <summary>
    /// Transporte de mensajes de texto. GameClient no sabe si debajo hay WebSocket,
    /// un mock de pruebas o, mañana, otra cosa.
    /// </summary>
    public interface IGameTransport : IDisposable
    {
        /// <summary>Se invoca desde un hilo de fondo.</summary>
        event Action<string> MessageReceived;

        /// <summary>Se invoca desde un hilo de fondo cuando la conexión se pierde.</summary>
        event Action<string> Closed;

        bool IsOpen { get; }

        Task ConnectAsync(Uri uri, CancellationToken ct);

        Task SendAsync(string text, CancellationToken ct);

        Task CloseAsync();
    }

    /// <summary>
    /// WebSocket con System.Net.WebSockets.ClientWebSocket: incluido en Unity
    /// (Mono e IL2CPP; Android, iOS y escritorio) sin paquetes de terceros.
    /// No funciona en WebGL (ahí haría falta NativeWebSocket o similar).
    /// </summary>
    public sealed class WebSocketTransport : IGameTransport
    {
        public event Action<string> MessageReceived;
        public event Action<string> Closed;

        private readonly SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);
        private ClientWebSocket _ws;
        private CancellationTokenSource _cts;

        public bool IsOpen
        {
            get
            {
                var ws = _ws;
                return ws != null && ws.State == WebSocketState.Open;
            }
        }

        public async Task ConnectAsync(Uri uri, CancellationToken ct)
        {
            Abort();  // ClientWebSocket no se puede reutilizar tras cerrarse
            var ws = new ClientWebSocket();
            ws.Options.KeepAliveInterval = TimeSpan.FromSeconds(20);
            await ws.ConnectAsync(uri, ct).ConfigureAwait(false);
            var cts = new CancellationTokenSource();
            _ws = ws;
            _cts = cts;
            _ = Task.Run(() => ReceiveLoop(ws, cts.Token));
        }

        private async Task ReceiveLoop(ClientWebSocket ws, CancellationToken ct)
        {
            var buffer = new byte[16 * 1024];
            var reason = "conexión cerrada";
            try
            {
                using (var message = new MemoryStream())
                {
                    while (!ct.IsCancellationRequested && ws.State == WebSocketState.Open)
                    {
                        message.SetLength(0);
                        WebSocketReceiveResult result;
                        do
                        {
                            result = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), ct).ConfigureAwait(false);
                            if (result.MessageType == WebSocketMessageType.Close)
                            {
                                reason = string.IsNullOrEmpty(ws.CloseStatusDescription)
                                    ? "el servidor cerró la conexión" : ws.CloseStatusDescription;
                                try
                                {
                                    await ws.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None)
                                            .ConfigureAwait(false);
                                }
                                catch (Exception) { /* ya cerrada */ }
                                return;
                            }
                            message.Write(buffer, 0, result.Count);
                        } while (!result.EndOfMessage);

                        if (result.MessageType == WebSocketMessageType.Text)
                        {
                            MessageReceived?.Invoke(Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length));
                        }
                    }
                }
            }
            catch (OperationCanceledException)
            {
                reason = "cancelado";
            }
            catch (Exception e)
            {
                reason = e.Message;
            }
            finally
            {
                // Solo avisamos si sigue siendo la conexión actual (no una sustituida
                // por una reconexión ni cerrada a propósito).
                if (ReferenceEquals(ws, _ws))
                {
                    Closed?.Invoke(reason);
                }
            }
        }

        public async Task SendAsync(string text, CancellationToken ct)
        {
            var ws = _ws;
            if (ws == null || ws.State != WebSocketState.Open)
            {
                throw new InvalidOperationException("No conectado");
            }
            var bytes = Encoding.UTF8.GetBytes(text);
            // ClientWebSocket no admite dos SendAsync simultáneos.
            await _sendLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                await ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, ct).ConfigureAwait(false);
            }
            finally
            {
                _sendLock.Release();
            }
        }

        public async Task CloseAsync()
        {
            var ws = _ws;
            _ws = null;  // cierre voluntario: el bucle no dispara Closed
            if (ws == null)
            {
                return;
            }
            try
            {
                if (ws.State == WebSocketState.Open)
                {
                    using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2)))
                    {
                        await ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "bye", timeout.Token).ConfigureAwait(false);
                    }
                }
            }
            catch (Exception) { /* da igual: cerramos de todos modos */ }
            finally
            {
                _cts?.Cancel();
                ws.Dispose();
            }
        }

        private void Abort()
        {
            var ws = _ws;
            _ws = null;
            _cts?.Cancel();
            if (ws != null)
            {
                ws.Abort();
                ws.Dispose();
            }
        }

        public void Dispose()
        {
            Abort();
        }
    }

    /// <summary>Dónde guardar el session_token para reconectar al mismo puesto.</summary>
    public interface ISessionStore
    {
        string LoadToken(string serverKey);

        void SaveToken(string serverKey, string token);
    }

    public sealed class InMemorySessionStore : ISessionStore
    {
        private readonly Dictionary<string, string> _tokens = new Dictionary<string, string>();

        public string LoadToken(string serverKey) =>
            _tokens.TryGetValue(serverKey, out var token) ? token : null;

        public void SaveToken(string serverKey, string token) => _tokens[serverKey] = token;
    }
}
