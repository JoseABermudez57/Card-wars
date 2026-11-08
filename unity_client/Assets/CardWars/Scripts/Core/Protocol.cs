using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

// Contrato del protocolo v1 (ver backend/protocol.py y el README del servidor).
// Los nombres de campo se traducen a snake_case automáticamente (Json.cs).
namespace CardWars.Core
{
    public static class Protocol
    {
        public const int Version = 1;
    }

    public static class MessageType
    {
        // cliente -> servidor
        public const string Join = "join";
        public const string PlayCard = "play_card";
        public const string Attack = "attack";
        public const string Rematch = "rematch";
        public const string Sync = "sync";
        public const string Frame = "frame";
        // servidor -> cliente
        public const string Welcome = "welcome";
        public const string StateUpdate = "state_update";
        public const string StateSync = "state_sync";
        public const string CardDetected = "card_detected";
        public const string Error = "error";
    }

    public static class GameStatus
    {
        public const string Waiting = "waiting";
        public const string InProgress = "in_progress";
        public const string Finished = "finished";
    }

    public static class GameEventType
    {
        public const string PlayerJoined = "player_joined";
        public const string GameStarted = "game_started";
        public const string CardPlayed = "card_played";
        public const string CreatureDamaged = "creature_damaged";
        public const string CreatureDestroyed = "creature_destroyed";
        public const string PlayerDamaged = "player_damaged";
        public const string TurnChanged = "turn_changed";
        public const string PlayerEliminated = "player_eliminated";
        public const string GameOver = "game_over";
        public const string PlayerDisconnected = "player_disconnected";
        public const string PlayerReconnected = "player_reconnected";
        public const string PlayerLeft = "player_left";
        public const string RematchRequested = "rematch_requested";
    }

    public static class ErrorCode
    {
        public const string NotYourTurn = "not_your_turn";
        public const string StaleAction = "stale_action";
        public const string GameFull = "game_full";
        public const string CardNotInHand = "card_not_in_hand";
        public const string CreatureInPlay = "creature_in_play";
        public const string NotJoined = "not_joined";
        public const string UnsupportedVersion = "unsupported_version";
    }

    /// <summary>Sobre común de todos los mensajes: {v, type, action_id?, seq?, payload}.</summary>
    public class Envelope
    {
        public int V = Protocol.Version;
        public string Type;
        public string ActionId;
        public int? Seq;
        public JObject Payload;
    }

    // ------------------------------------------------------------- catálogo
    public class CardDefinition
    {
        public string CardId;
        public string Name;
        public int MaxHp;
        public int Attack;
        public int MarkerId;
        public string ModelKey;   // en Unity: clave de Addressable / prefab del modelo 3D
    }

    public class CardInstance : CardDefinition
    {
        public int Uid;           // identifica ESTA criatura en mesa (animaciones, objetivos)
        public int Hp;
    }

    public class Catalog
    {
        public int Version;
        public List<CardDefinition> Cards = new List<CardDefinition>();
    }

    // --------------------------------------------------------------- estado
    public class PlayerState
    {
        public string PlayerId;
        public string Name;
        public int Life;
        public List<CardInstance> Field = new List<CardInstance>();
        public List<string> Discard = new List<string>();
        public int HandCount;
        public List<string> Hand;  // null si no eres tú (información oculta)
        public bool Connected;
        public bool Eliminated;
        public bool WantsRematch;

        [JsonIgnore]
        public CardInstance Creature => Field != null && Field.Count > 0 ? Field[0] : null;
    }

    public class GameState
    {
        public string GameId;
        public int Seq;
        public string Status;
        public int MaxPlayers;
        public int TurnNumber;
        public string CurrentPlayerId;
        public string WinnerId;
        public string EndReason;
        public List<PlayerState> Players = new List<PlayerState>();
    }

    public class GameEvent
    {
        public string Type;
        public JObject Payload;

        public T PayloadAs<T>() => Json.ToObject<T>(Payload);
    }

    // ------------------------------------------------ payloads servidor -> cliente
    public class WelcomePayload
    {
        public string PlayerId;
        public string SessionToken;
        public string GameId;
        public int ProtocolVersion;
        public Catalog Catalog;
        public bool VisionAvailable;
    }

    public class StateUpdatePayload
    {
        public List<GameEvent> Events = new List<GameEvent>();
        public GameState State;
    }

    public class StateSyncPayload
    {
        public GameState State;
    }

    public class CardDetectedPayload
    {
        public int? FrameId;
        public List<int> MarkerIds = new List<int>();
        public List<CardDefinition> Cards = new List<CardDefinition>();
    }

    public class ErrorPayload
    {
        public string Code;
        public string Message;
    }

    // ------------------------------------------------------- payloads de eventos
    /// <summary>player_joined, player_disconnected, player_reconnected, player_left,
    /// player_eliminated (con Reason), rematch_requested.</summary>
    public class PlayerRefEvent
    {
        public string PlayerId;
        public string Name;
        public string Reason;
    }

    /// <summary>game_started, turn_changed.</summary>
    public class TurnEvent
    {
        public string CurrentPlayerId;
        public int TurnNumber;
    }

    public class CardPlayedEvent
    {
        public string PlayerId;
        public CardInstance Card;
        public string Source;     // "ui" | "camera"
    }

    public class CreatureDamagedEvent
    {
        public int AttackerUid;
        public int TargetUid;
        public int Damage;
        public int RemainingHp;
    }

    public class CreatureDestroyedEvent
    {
        public int Uid;
        public string OwnerId;
    }

    public class PlayerDamagedEvent
    {
        public int AttackerUid;
        public string PlayerId;
        public int Damage;
        public int RemainingLife;
    }

    public class GameOverEvent
    {
        public string WinnerId;
        public string Reason;
    }

    // ------------------------------------------------ payloads cliente -> servidor
    public class JoinPayload
    {
        public string Name;
        public string SessionToken;
        public string GameId;
    }

    public class PlayCardPayload
    {
        public string CardId;
        public int ExpectedTurn;
        public string Source;
        public string TargetId;
    }

    public class AttackPayload
    {
        public int ExpectedTurn;
        public string TargetId;
    }

    public class FramePayload
    {
        public string Image;      // JPEG en base64
        public int FrameId;
    }
}
