using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace CardWars.Core
{
    /// <summary>
    /// Cliente del protocolo v1. C# puro (sin UnityEngine): se prueba con `dotnet`
    /// fuera de Unity y se reutiliza tal cual dentro.
    ///
    /// Modelo de hilos: el transporte recibe en segundo plano y solo ENCOLA.
    /// Todo el estado se modifica y todos los eventos se disparan dentro de
    /// <see cref="Poll"/>, en el hilo que lo llame (en Unity: Update, hilo principal).
    /// Así ningún callback toca objetos de Unity desde otro hilo.
    ///
    /// Igual que el cliente web, es un cliente "tonto": envía intenciones y
    /// muestra el estado que manda el servidor. No calcula reglas.
    /// </summary>
    public sealed class GameClient : IDisposable
    {
        public static readonly TimeSpan ActionTimeout = TimeSpan.FromSeconds(5);

        private struct Inbound
        {
            public string Text;
            public string ClosedReason;
        }

        private readonly IGameTransport _transport;
        private readonly ISessionStore _sessions;
        private readonly ConcurrentQueue<Inbound> _inbox = new ConcurrentQueue<Inbound>();
        private readonly Dictionary<string, CardDefinition> _catalog = new Dictionary<string, CardDefinition>();
        private string _serverKey = "";
        private DateTime _pendingSince;

        /// <summary>El servidor aceptó el join (nuevo o reconexión).</summary>
        public event Action<WelcomePayload> Welcomed;

        /// <summary>Nuevo estado. `events` está vacío en una resincronización.</summary>
        public event Action<GameState, IReadOnlyList<GameEvent>> StateChanged;

        /// <summary>(error, action_id de la acción que lo provocó o null).</summary>
        public event Action<ErrorPayload, string> ErrorReceived;

        public event Action<CardDetectedPayload> CardDetected;

        /// <summary>La conexión se perdió (no se dispara al desconectar a propósito).</summary>
        public event Action<string> Disconnected;

        public GameClient(IGameTransport transport, ISessionStore sessions = null)
        {
            _transport = transport ?? throw new ArgumentNullException(nameof(transport));
            _sessions = sessions ?? new InMemorySessionStore();
            _transport.MessageReceived += text => _inbox.Enqueue(new Inbound { Text = text });
            _transport.Closed += reason => _inbox.Enqueue(new Inbound { ClosedReason = reason ?? "cerrada" });
        }

        public string PlayerId { get; private set; }
        public string GameId { get; private set; }
        public GameState State { get; private set; }
        public int LastSeq { get; private set; } = -1;
        public string PendingActionId { get; private set; }
        public bool VisionAvailable { get; private set; }
        public bool IsConnected => _transport.IsOpen;
        public IReadOnlyDictionary<string, CardDefinition> Catalog => _catalog;

        // ------------------------------------------------------------ consultas
        public PlayerState Me => State?.Players?.FirstOrDefault(p => p.PlayerId == PlayerId);

        /// <summary>El primer rival (partidas de 2). Con N jugadores usar <see cref="Opponents"/>.</summary>
        public PlayerState Rival => Opponents.FirstOrDefault();

        public IEnumerable<PlayerState> Opponents =>
            State?.Players?.Where(p => p.PlayerId != PlayerId) ?? Enumerable.Empty<PlayerState>();

        public bool IsMyTurn =>
            State != null && State.Status == GameStatus.InProgress && State.CurrentPlayerId == PlayerId;

        public bool CanPlayCard => IsMyTurn && Me != null && Me.Creature == null && PendingActionId == null;

        public bool CanAttack => IsMyTurn && Me != null && Me.Creature != null && PendingActionId == null;

        // ------------------------------------------------------------ conexión
        /// <summary>Conecta y entra en la partida. Si hay token guardado para este
        /// servidor, el servidor nos devuelve nuestro puesto (reconexión).</summary>
        public async Task ConnectAsync(Uri serverUri, string playerName, string gameId = null,
                                       CancellationToken ct = default)
        {
            _serverKey = serverUri.GetLeftPart(UriPartial.Authority);
            GameId = gameId;
            await _transport.ConnectAsync(serverUri, ct);
            await SendAsync(MessageType.Join, new JoinPayload
            {
                Name = playerName,
                SessionToken = _sessions.LoadToken(_serverKey),
                GameId = gameId,
            }, null, ct);
        }

        public Task DisconnectAsync()
        {
            ClearPending();
            return _transport.CloseAsync();
        }

        // ------------------------------------------------------------ bucle
        /// <summary>Procesa los mensajes recibidos. Llamar cada frame (Update).</summary>
        public void Poll()
        {
            while (_inbox.TryDequeue(out var item))
            {
                if (item.ClosedReason != null)
                {
                    ClearPending();
                    Disconnected?.Invoke(item.ClosedReason);
                }
                else
                {
                    Handle(item.Text);
                }
            }

            // Respuesta perdida: pedimos al servidor la verdad en vez de quedarnos colgados.
            if (PendingActionId != null && DateTime.UtcNow - _pendingSince > ActionTimeout)
            {
                ClearPending();
                _ = TrySendAsync(MessageType.Sync, null);
            }
        }

        private void Handle(string text)
        {
            Envelope env;
            try
            {
                env = Json.Deserialize<Envelope>(text);
            }
            catch (Exception)
            {
                return;  // mensaje corrupto: se ignora
            }
            if (env == null || env.V != Protocol.Version)
            {
                return;
            }

            switch (env.Type)
            {
                case MessageType.Welcome:
                {
                    var welcome = Json.ToObject<WelcomePayload>(env.Payload);
                    PlayerId = welcome.PlayerId;
                    GameId = welcome.GameId;
                    VisionAvailable = welcome.VisionAvailable;
                    LastSeq = -1;  // el servidor pudo reiniciarse: su seq vuelve a empezar
                    _catalog.Clear();
                    foreach (var card in welcome.Catalog?.Cards ?? new List<CardDefinition>())
                    {
                        _catalog[card.CardId] = card;
                    }
                    _sessions.SaveToken(_serverKey, welcome.SessionToken);
                    Welcomed?.Invoke(welcome);
                    break;
                }
                case MessageType.StateUpdate:
                {
                    if (env.Seq == null || env.Seq.Value <= LastSeq)
                    {
                        return;  // viejo o duplicado
                    }
                    var update = Json.ToObject<StateUpdatePayload>(env.Payload);
                    Apply(env.Seq.Value, update.State, update.Events ?? new List<GameEvent>());
                    break;
                }
                case MessageType.StateSync:
                {
                    var sync = Json.ToObject<StateSyncPayload>(env.Payload);
                    Apply(env.Seq ?? LastSeq, sync.State, Array.Empty<GameEvent>());
                    break;
                }
                case MessageType.CardDetected:
                    CardDetected?.Invoke(Json.ToObject<CardDetectedPayload>(env.Payload));
                    break;
                case MessageType.Error:
                {
                    var error = Json.ToObject<ErrorPayload>(env.Payload);
                    if (env.ActionId != null && env.ActionId == PendingActionId)
                    {
                        ClearPending();
                    }
                    ErrorReceived?.Invoke(error, env.ActionId);
                    break;
                }
            }
        }

        private void Apply(int seq, GameState state, IReadOnlyList<GameEvent> events)
        {
            if (state == null)
            {
                return;
            }
            LastSeq = seq;
            State = state;
            ClearPending();
            StateChanged?.Invoke(state, events);
        }

        // ------------------------------------------------------------ acciones
        /// <summary>Juega una carta de la mano. Devuelve false si localmente ya se
        /// sabe que no es posible (el servidor valida de todos modos).</summary>
        public Task<bool> PlayCardAsync(string cardId, string source = "ui", string targetId = null)
        {
            var me = Me;
            if (!CanPlayCard || me.Hand == null || !me.Hand.Contains(cardId))
            {
                return Task.FromResult(false);
            }
            return SendActionAsync(MessageType.PlayCard, new PlayCardPayload
            {
                CardId = cardId,
                ExpectedTurn = State.TurnNumber,
                Source = source,
                TargetId = targetId,
            });
        }

        public Task<bool> AttackAsync(string targetId = null)
        {
            if (!CanAttack)
            {
                return Task.FromResult(false);
            }
            return SendActionAsync(MessageType.Attack, new AttackPayload
            {
                ExpectedTurn = State.TurnNumber,
                TargetId = targetId,
            });
        }

        public Task<bool> RematchAsync() => TrySendAsync(MessageType.Rematch, null);

        public Task<bool> SyncAsync() => TrySendAsync(MessageType.Sync, null);

        /// <summary>Envía un frame JPEG (base64) para detección en el servidor.
        /// Con AR Foundation la detección será local y esto dejará de usarse.</summary>
        public Task<bool> SendFrameAsync(string jpegBase64, int frameId) =>
            TrySendAsync(MessageType.Frame, new FramePayload { Image = jpegBase64, FrameId = frameId });

        /// <summary>Envío sin validación local. Solo para depuración y pruebas.</summary>
        public Task SendRawAsync(string type, object payload, string actionId = null) =>
            SendAsync(type, payload, actionId, CancellationToken.None);

        private async Task<bool> SendActionAsync(string type, object payload)
        {
            var actionId = Guid.NewGuid().ToString("N");
            PendingActionId = actionId;
            _pendingSince = DateTime.UtcNow;
            try
            {
                await SendAsync(type, payload, actionId, CancellationToken.None);
                return true;
            }
            catch (Exception)
            {
                if (PendingActionId == actionId)
                {
                    ClearPending();
                }
                return false;
            }
        }

        private async Task<bool> TrySendAsync(string type, object payload)
        {
            try
            {
                await SendAsync(type, payload, null, CancellationToken.None);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private Task SendAsync(string type, object payload, string actionId, CancellationToken ct)
        {
            var env = new Envelope
            {
                Type = type,
                ActionId = actionId,
                Payload = payload == null ? new JObject() : Json.ToJObject(payload),
            };
            return _transport.SendAsync(Json.Serialize(env), ct);
        }

        private void ClearPending()
        {
            PendingActionId = null;
        }

        public void Dispose()
        {
            _transport.Dispose();
        }
    }
}
