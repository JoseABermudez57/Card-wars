using System.Collections.Generic;
using CardWars.Core;
using UnityEngine;

namespace CardWars.UnityClient
{
    /// <summary>
    /// Interfaz mínima con IMGUI (OnGUI): no necesita Canvas, prefabs ni escena.
    /// Añádela junto a CardWarsClient en un GameObject vacío y dale a Play.
    /// Es deliberadamente fea: solo valida el protocolo. La UI real (uGUI/UI Toolkit)
    /// y los modelos 3D se suscriben a CardWarsClient.StateChanged igual que esta.
    /// </summary>
    [RequireComponent(typeof(CardWarsClient))]
    public class SimpleGameUI : MonoBehaviour
    {
        private const float ReferenceHeight = 720f;
        private CardWarsClient _client;
        private Vector2 _scroll;

        /// <summary>Con mesa 3D (BoardView) el panel se estrecha y no repite lo que ya se ve en la mesa.</summary>
        private bool _compact;

        private void Awake()
        {
            _client = GetComponent<CardWarsClient>();
        }

        private void Start()
        {
            _compact = FindAnyObjectByType<CardWars.Presentation.BoardView>() != null;
        }

        private void OnGUI()
        {
            // Escala para que se lea igual en un portátil que en un móvil.
            var scale = Mathf.Max(1f, Screen.height / ReferenceHeight);
            GUI.matrix = Matrix4x4.Scale(new Vector3(scale, scale, 1f));
            var width = Screen.width / scale;
            var height = Screen.height / scale;

            GUI.skin.label.fontSize = 16;
            GUI.skin.button.fontSize = 16;
            GUI.skin.textField.fontSize = 16;
            GUI.skin.label.wordWrap = true;

            GUILayout.BeginArea(new Rect(10f, 10f, Mathf.Min(width - 20f, _compact ? 330f : 560f), height - 20f));
            _scroll = GUILayout.BeginScrollView(_scroll);

            GUILayout.Label($"<b>Card Wars · Unity</b>   [{_client.Status}]", RichLabel(20));
            var game = _client.Client;
            if (!game.IsConnected)
            {
                DrawConnectForm();
            }
            else
            {
                DrawGame(game);
            }
            DrawLog();

            GUILayout.EndScrollView();
            GUILayout.EndArea();
        }

        private void DrawConnectForm()
        {
            GUILayout.Label("Servidor (ws://IP_DEL_PC:5001/ws)");
            _client.serverUrl = GUILayout.TextField(_client.serverUrl);
            GUILayout.Label("Nombre");
            _client.playerName = GUILayout.TextField(_client.playerName, 20);
            GUILayout.Label("Sala (vacío = la de los teléfonos)");
            _client.gameId = GUILayout.TextField(_client.gameId, 32);
            if (GUILayout.Button("Conectar", GUILayout.Height(48f)))
            {
                _client.Connect();
            }
        }

        private void DrawGame(GameClient game)
        {
            var state = game.State;
            if (state == null)
            {
                GUILayout.Label("Esperando estado del servidor…");
                return;
            }

            GUILayout.Label(StatusText(game, state), RichLabel(18));
            if (!_compact)
            {
                DrawPlayer("Rival", game.Rival, state);
                DrawPlayer("Tú", game.Me, state);
            }

            var me = game.Me;
            if (state.Status == GameStatus.InProgress && me != null)
            {
                if (me.Creature != null)
                {
                    GUI.enabled = game.CanAttack;
                    if (GUILayout.Button($"Atacar con {me.Creature.Name}", GUILayout.Height(56f)))
                    {
                        _ = game.AttackAsync();
                    }
                    GUI.enabled = true;
                }
                else
                {
                    GUILayout.Label("Tu mano:");
                    GUILayout.BeginHorizontal();
                    foreach (var cardId in me.Hand ?? new List<string>())
                    {
                        if (!game.Catalog.TryGetValue(cardId, out var card))
                        {
                            continue;
                        }
                        GUI.enabled = game.CanPlayCard;
                        if (GUILayout.Button($"{card.Name}\nATK {card.Attack} · HP {card.MaxHp}", GUILayout.Height(72f)))
                        {
                            _ = game.PlayCardAsync(cardId);
                        }
                        GUI.enabled = true;
                    }
                    GUILayout.EndHorizontal();
                }
            }

            if (state.Status == GameStatus.Finished && me != null)
            {
                var rivalGone = state.Players.Count < state.MaxPlayers;
                GUI.enabled = !rivalGone && !me.WantsRematch;
                var label = rivalGone ? "Tu rival se fue" : me.WantsRematch ? "Esperando al rival…" : "Revancha";
                if (GUILayout.Button(label, GUILayout.Height(48f)))
                {
                    _ = game.RematchAsync();
                }
                GUI.enabled = true;
            }

            GUILayout.Space(8f);
            if (GUILayout.Button("Desconectar"))
            {
                _client.Disconnect();
            }
        }

        private static string StatusText(GameClient game, GameState state)
        {
            switch (state.Status)
            {
                case GameStatus.Waiting:
                    return "Esperando rival…";
                case GameStatus.Finished:
                    if (state.WinnerId == null) return "<b>Empate</b>";
                    return state.WinnerId == game.PlayerId ? "<b>¡Victoria!</b>" : "<b>Derrota</b>";
                default:
                    return game.IsMyTurn ? $"<b>Tu turno</b> (turno {state.TurnNumber})"
                                         : $"Turno de {game.Rival?.Name} (turno {state.TurnNumber})";
            }
        }

        private static void DrawPlayer(string title, PlayerState player, GameState state)
        {
            GUILayout.BeginVertical(GUI.skin.box);
            if (player == null)
            {
                GUILayout.Label($"{title}: esperando…");
            }
            else
            {
                var turn = state.CurrentPlayerId == player.PlayerId ? "  <color=yellow>[turno]</color>" : "";
                var offline = player.Connected ? "" : "  <color=red>[desconectado]</color>";
                GUILayout.Label($"<b>{title}: {player.Name}</b>{turn}{offline}", RichLabel(16));
                GUILayout.Label($"Vida: {player.Life}   Mano: {player.HandCount}   Descarte: {player.Discard?.Count ?? 0}");
                var c = player.Creature;
                GUILayout.Label(c == null ? "Mesa: (vacía)" : $"Mesa: {c.Name}  ATK {c.Attack}  HP {c.Hp}/{c.MaxHp}");
            }
            GUILayout.EndVertical();
        }

        private void DrawLog()
        {
            GUILayout.Space(8f);
            GUILayout.Label("<b>Registro</b>", RichLabel(16));
            var count = Mathf.Min(_client.Log.Count, _compact ? 6 : 10);
            for (var i = 0; i < count; i++)
            {
                GUILayout.Label(_client.Log[i]);
            }
        }

        private static GUIStyle RichLabel(int size)
        {
            return new GUIStyle(GUI.skin.label) { richText = true, fontSize = size, wordWrap = true };
        }
    }
}
