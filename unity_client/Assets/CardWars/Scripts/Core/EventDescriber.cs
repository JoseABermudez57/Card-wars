using System.Collections.Generic;

namespace CardWars.Core
{
    /// <summary>
    /// Traduce eventos a texto legible (registro de combate). Las animaciones
    /// 3D se engancharán a los mismos eventos; esto es su versión en texto.
    /// Sin emojis: la fuente por defecto de Unity no los dibuja.
    /// </summary>
    public static class EventDescriber
    {
        public static string Describe(GameEvent ev, GameState previous, GameState current)
        {
            var players = new List<PlayerState>();
            if (previous?.Players != null) players.AddRange(previous.Players);
            if (current?.Players != null) players.AddRange(current.Players);

            string PlayerName(string id)
            {
                var p = players.FindLast(x => x.PlayerId == id);
                return p?.Name ?? "?";
            }

            string CreatureName(int uid)
            {
                for (var i = players.Count - 1; i >= 0; i--)
                {
                    foreach (var c in players[i].Field ?? new List<CardInstance>())
                    {
                        if (c.Uid == uid) return c.Name;
                    }
                }
                return "criatura";
            }

            switch (ev.Type)
            {
                case GameEventType.PlayerJoined:
                    return $"{PlayerName(ev.PayloadAs<PlayerRefEvent>().PlayerId)} se unió";
                case GameEventType.GameStarted:
                    return $"¡Empieza la partida! Abre {PlayerName(ev.PayloadAs<TurnEvent>().CurrentPlayerId)}";
                case GameEventType.CardPlayed:
                {
                    var e = ev.PayloadAs<CardPlayedEvent>();
                    var how = e.Source == "camera" ? " (cámara)" : "";
                    return $"{PlayerName(e.PlayerId)} juega {e.Card.Name}{how}";
                }
                case GameEventType.CreatureDamaged:
                {
                    var e = ev.PayloadAs<CreatureDamagedEvent>();
                    return $"{CreatureName(e.AttackerUid)} golpea a {CreatureName(e.TargetUid)}: -{e.Damage} (le quedan {e.RemainingHp})";
                }
                case GameEventType.CreatureDestroyed:
                {
                    var e = ev.PayloadAs<CreatureDestroyedEvent>();
                    return $"{CreatureName(e.Uid)} de {PlayerName(e.OwnerId)} fue destruido";
                }
                case GameEventType.PlayerDamaged:
                {
                    var e = ev.PayloadAs<PlayerDamagedEvent>();
                    return $"{CreatureName(e.AttackerUid)} golpea a {PlayerName(e.PlayerId)}: -{e.Damage} vida (le quedan {e.RemainingLife})";
                }
                case GameEventType.TurnChanged:
                {
                    var e = ev.PayloadAs<TurnEvent>();
                    return $"Turno {e.TurnNumber}: {PlayerName(e.CurrentPlayerId)}";
                }
                case GameEventType.PlayerEliminated:
                {
                    var e = ev.PayloadAs<PlayerRefEvent>();
                    var why = e.Reason == "life" ? "sin vida"
                            : e.Reason == "no_creatures" ? "sin criaturas ni cartas"
                            : e.Reason == "abandon" ? "por abandono" : e.Reason;
                    return $"{PlayerName(e.PlayerId)} eliminado ({why})";
                }
                case GameEventType.GameOver:
                {
                    var e = ev.PayloadAs<GameOverEvent>();
                    return e.WinnerId == null ? "Empate" : $"Gana {PlayerName(e.WinnerId)}";
                }
                case GameEventType.PlayerDisconnected:
                    return $"{PlayerName(ev.PayloadAs<PlayerRefEvent>().PlayerId)} se desconectó";
                case GameEventType.PlayerReconnected:
                    return $"{PlayerName(ev.PayloadAs<PlayerRefEvent>().PlayerId)} volvió";
                case GameEventType.PlayerLeft:
                    return $"{PlayerName(ev.PayloadAs<PlayerRefEvent>().PlayerId)} salió";
                case GameEventType.CardDrawn:
                {
                    var e = ev.PayloadAs<CardDrawnEvent>();
                    return e.Card != null
                        ? $"{PlayerName(e.PlayerId)} roba {e.Card.Name} (quedan {e.DeckCount} en el mazo)"
                        : $"{PlayerName(e.PlayerId)} roba una carta";
                }
                case GameEventType.RematchRequested:
                    return $"{PlayerName(ev.PayloadAs<PlayerRefEvent>().PlayerId)} quiere revancha";
                default:
                    return null;  // eventos nuevos del servidor: se ignoran sin romper
            }
        }
    }
}
