using System;
using System.Collections.Generic;
using CardWars.Core;
using UnityEngine;

namespace CardWars.UnityClient
{
    /// <summary>
    /// Puente entre GameClient (C# puro) y Unity:
    ///  - llama a Poll() en Update => todos los eventos llegan en el hilo principal;
    ///  - guarda el session_token en PlayerPrefs => reconexión al mismo puesto;
    ///  - reintenta la conexión si se cae;
    ///  - reexpone StateChanged para las vistas (UI hoy, modelos 3D y animaciones mañana).
    /// </summary>
    public class CardWarsClient : MonoBehaviour
    {
        [Tooltip("Puerto NATIVO del servidor (HTTP): ws://IP_DEL_PC:5001/ws")]
        public string serverUrl = "ws://192.168.1.80:5001/ws";

        public string playerName = "Unity";

        [Tooltip("Sala. Vacío = la sala por defecto, la misma que usan los teléfonos con navegador.")]
        public string gameId = "";

        public bool connectOnStart;

        [Tooltip("Segundos antes de reintentar si se pierde la conexión. 0 = no reintentar.")]
        public float reconnectDelay = 2f;

        public GameClient Client { get; private set; }

        public string Status { get; private set; } = "Desconectado";

        /// <summary>Registro de combate, el más reciente primero.</summary>
        public readonly List<string> Log = new List<string>();

        /// <summary>Para vistas: (estado nuevo, eventos que lo produjeron).</summary>
        public event Action<GameState, IReadOnlyList<GameEvent>> StateChanged;

        private bool _wantConnected;
        private bool _connecting;
        private float _reconnectAt = -1f;
        private GameState _previous;

        private void Awake()
        {
            Client = new GameClient(new WebSocketTransport(), new PlayerPrefsSessionStore());
            Client.Welcomed += _ =>
            {
                Status = "Conectado";
                AddLog($"Conectado como {playerName}");
            };
            Client.StateChanged += OnStateChanged;
            Client.ErrorReceived += (error, _) =>
            {
                AddLog($"Error: {error.Message}");
                if (error.Code == ErrorCode.GameFull)
                {
                    _wantConnected = false;  // no insistir
                    Disconnect();
                }
            };
            Client.Disconnected += reason =>
            {
                Status = "Desconectado";
                AddLog($"Conexión perdida: {reason}");
                ScheduleReconnect();
            };
        }

        private void Start()
        {
            if (connectOnStart)
            {
                Connect();
            }
        }

        private void Update()
        {
            Client.Poll();
            if (_reconnectAt > 0f && Time.unscaledTime >= _reconnectAt && !_connecting)
            {
                _reconnectAt = -1f;
                if (_wantConnected)
                {
                    Connect();
                }
            }
        }

        public async void Connect()
        {
            if (_connecting)
            {
                return;
            }
            _wantConnected = true;
            _connecting = true;
            Status = "Conectando…";
            try
            {
                var room = string.IsNullOrWhiteSpace(gameId) ? null : gameId.Trim();
                await Client.ConnectAsync(new Uri(serverUrl), playerName, room);
            }
            catch (Exception e)
            {
                Status = "Sin conexión";
                AddLog($"No se pudo conectar: {e.Message}");
                ScheduleReconnect();
            }
            finally
            {
                _connecting = false;
            }
        }

        public async void Disconnect()
        {
            _wantConnected = false;
            _reconnectAt = -1f;
            await Client.DisconnectAsync();
            Status = "Desconectado";
        }

        private void ScheduleReconnect()
        {
            if (_wantConnected && reconnectDelay > 0f)
            {
                _reconnectAt = Time.unscaledTime + reconnectDelay;
            }
        }

        private void OnStateChanged(GameState state, IReadOnlyList<GameEvent> events)
        {
            foreach (var ev in events)
            {
                var line = EventDescriber.Describe(ev, _previous, state);
                if (line != null)
                {
                    AddLog(line);
                }
            }
            _previous = state;
            StateChanged?.Invoke(state, events);
        }

        private void AddLog(string line)
        {
            Log.Insert(0, line);
            if (Log.Count > 30)
            {
                Log.RemoveAt(Log.Count - 1);
            }
            Debug.Log("[CardWars] " + line);
        }

        private void OnDestroy()
        {
            Client?.Dispose();
        }
    }

    /// <summary>Token de sesión por servidor en PlayerPrefs (sobrevive a cerrar la app).</summary>
    public class PlayerPrefsSessionStore : ISessionStore
    {
        private const string Prefix = "cardwars.session.";

        public string LoadToken(string serverKey)
        {
            var token = PlayerPrefs.GetString(Prefix + serverKey, "");
            return string.IsNullOrEmpty(token) ? null : token;
        }

        public void SaveToken(string serverKey, string token)
        {
            PlayerPrefs.SetString(Prefix + serverKey, token ?? "");
            PlayerPrefs.Save();
        }
    }
}
