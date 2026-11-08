using System;
using System.Collections.Generic;
using System.Linq;
using CardWars.Core;
using CardWars.UnityClient;
using UnityEngine;

namespace CardWars.Presentation
{
    /// <summary>
    /// Mesa 3D: criaturas, tótems de vida, turnos y animaciones.
    ///
    /// Regla de oro (la misma del cliente web):
    ///   * los EVENTOS se animan, en orden, en una línea de tiempo;
    ///   * al final de cada lote se RECONCILIA con el estado completo.
    /// Si una animación falla o se pierde un evento, la mesa acaba igual que la verdad del servidor.
    ///
    /// Puede alimentarse desde CardWarsClient (automático) o llamando a Present()
    /// directamente (repeticiones, tests, capturas fuera de Play).
    /// </summary>
    public class BoardView : MonoBehaviour
    {
        [Tooltip("Opcional. Si está vacío se busca en este GameObject o en la escena.")]
        public CardWarsClient client;

        [Tooltip("Modelos 3D por model_key. Vacío = Resources/CreaturePrefabRegistry si existe; si no, primitivas.")]
        public CreaturePrefabRegistry prefabs;

        [Tooltip("Coloca la Main Camera mirando a la mesa al empezar.")]
        public bool configureCamera = true;

        [Tooltip("Desplaza el encuadre de la cámara para que la mesa quede a la derecha del panel de la izquierda.")]
        public float cameraShift = 1.7f;

        [Range(0.25f, 3f)]
        public float animationSpeed = 1f;

        private static readonly Vector3 MySlot = new Vector3(0f, 0f, -1.5f);
        private static readonly Vector3 RivalSlot = new Vector3(0f, 0f, 1.7f);
        private static readonly Vector3 MyAvatarPos = new Vector3(-2.6f, 0f, -1.5f);
        private static readonly Vector3 RivalAvatarPos = new Vector3(-2.6f, 0f, 1.7f);

        private readonly Dictionary<int, CreatureView> _creatures = new Dictionary<int, CreatureView>();
        private readonly List<FloatingText> _floating = new List<FloatingText>();
        private readonly List<Material> _materials = new List<Material>();
        private readonly Timeline _timeline = new Timeline();
        private Transform _root;
        private PlayerAvatarView _myAvatar;
        private PlayerAvatarView _rivalAvatar;
        private string _myId;
        private string _banner;
        private bool _subscribed;

        private sealed class FloatingText
        {
            public Vector3 World;
            public string Text;
            public Color Color;
            public float Age;
            public float Life;
        }

        public bool IsAnimating => !_timeline.IsIdle;

        // ------------------------------------------------------------ ciclo de vida
        private void Awake()
        {
            EnsureBuilt();
        }

        private void OnEnable()
        {
            // Ojo: nada de `??` con objetos de Unity (su "null" es un objeto falso en el Editor).
            if (client == null)
            {
                client = GetComponent<CardWarsClient>();
            }
            if (client == null)
            {
                client = FindAnyObjectByType<CardWarsClient>();
            }
            if (client != null && !_subscribed)
            {
                client.StateChanged += OnClientState;
                _subscribed = true;
            }
        }

        private void Start()
        {
            // Si el cliente ya tenía estado antes de que existiera la mesa, la dibujamos.
            var game = client != null ? client.Client : null;
            if (game?.State != null)
            {
                Present(game.State, Array.Empty<GameEvent>(), game.PlayerId);
            }
        }

        private void OnDisable()
        {
            if (client != null && _subscribed)
            {
                client.StateChanged -= OnClientState;
                _subscribed = false;
            }
        }

        private void Update()
        {
            Tick(Time.deltaTime);
        }

        private void OnClientState(GameState state, IReadOnlyList<GameEvent> events)
        {
            Present(state, events, client.Client.PlayerId);
        }

        /// <summary>Avanza animaciones y efectos. Update lo llama solo; fuera de Play, a mano.</summary>
        public void Tick(float dt)
        {
            dt *= animationSpeed;
            _timeline.Tick(dt);
            foreach (var view in _creatures.Values)
            {
                if (view != null) view.Tick(dt);
            }
            if (_myAvatar != null) _myAvatar.Tick(dt);
            if (_rivalAvatar != null) _rivalAvatar.Tick(dt);
            for (var i = _floating.Count - 1; i >= 0; i--)
            {
                _floating[i].Age += dt;
                if (_floating[i].Age >= _floating[i].Life) _floating.RemoveAt(i);
            }
        }

        // ------------------------------------------------------------ escena estática
        /// <summary>Construye mesa, casillas y tótems (idempotente).</summary>
        public void EnsureBuilt()
        {
            if (_root != null)
            {
                return;
            }
            if (prefabs == null)
            {
                prefabs = CreaturePrefabRegistry.LoadDefault();
            }
            _root = new GameObject("Board").transform;
            _root.SetParent(transform, false);
            _root.localPosition = Vector3.zero;

            var table = CreatureVisuals.Part(PrimitiveType.Cube, _root.gameObject, new Vector3(-0.6f, -0.1f, 0.1f),
                                             new Vector3(7.2f, 0.2f, 7.4f), Vector3.zero,
                                             CreatureVisuals.Mat(new Color(0.20f, 0.30f, 0.24f), _materials));
            table.name = "Table";
            CreatureVisuals.Part(PrimitiveType.Cube, _root.gameObject, new Vector3(-0.6f, 0.005f, 0.1f),
                                 new Vector3(7.0f, 0.01f, 0.05f), Vector3.zero,
                                 CreatureVisuals.Mat(new Color(0.75f, 0.7f, 0.5f), _materials));

            var mySlot = new GameObject("My Slot").transform;
            mySlot.SetParent(_root, false);
            mySlot.localPosition = MySlot;
            var rivalSlot = new GameObject("Rival Slot").transform;
            rivalSlot.SetParent(_root, false);
            rivalSlot.localPosition = RivalSlot;

            _myAvatar = PlayerAvatarView.Create(_root, MyAvatarPos, mySlot, new Color(0.2f, 0.75f, 0.8f));
            _myAvatar.name = "My Avatar";
            _rivalAvatar = PlayerAvatarView.Create(_root, RivalAvatarPos, rivalSlot, new Color(0.95f, 0.55f, 0.2f));
            _rivalAvatar.name = "Rival Avatar";

            if (configureCamera && Camera.main != null)
            {
                // Mira al centro de la mesa, desplazada a la izquierda `cameraShift` unidades:
                // así la mesa aparece a la derecha y el panel IMGUI no la tapa.
                var focus = _root.position + new Vector3(-0.6f - cameraShift, 0.2f, -0.1f);
                var cam = Camera.main.transform;
                cam.position = focus + new Vector3(0f, 6.6f, -7.2f);
                cam.LookAt(focus);
                Camera.main.fieldOfView = 50f;
            }
        }

        // ------------------------------------------------------------ eventos -> animación
        /// <summary>Encola la animación de `events` y la reconciliación con `state`.</summary>
        public void Present(GameState state, IReadOnlyList<GameEvent> events, string myPlayerId)
        {
            EnsureBuilt();
            if (state == null)
            {
                return;
            }
            _myId = myPlayerId;

            foreach (var ev in events ?? Array.Empty<GameEvent>())
            {
                switch (ev.Type)
                {
                    case GameEventType.GameStarted:
                        _timeline.Enqueue(0f, begin: () => { ClearCreatures(); _banner = null; });
                        break;

                    case GameEventType.CardPlayed:
                    {
                        var e = ev.PayloadAs<CardPlayedEvent>();
                        _timeline.Enqueue(0.5f,
                            begin: () => Spawn(e.Card, e.PlayerId).SetModelScale(0f),
                            update: t => WithCreature(e.Card.Uid, v =>
                            {
                                v.SetModelScale(Ease.OutBack(t));
                                v.SetModelOffset(Vector3.up * (1f - Ease.OutQuad(t)) * 1.2f);
                            }));
                        break;
                    }

                    case GameEventType.CreatureDamaged:
                    {
                        var e = ev.PayloadAs<CreatureDamagedEvent>();
                        EnqueueLunge(e.AttackerUid,
                            () => _creatures.TryGetValue(e.TargetUid, out var t) && t != null ? t.transform.position : (Vector3?)null,
                            () => WithCreature(e.TargetUid, target =>
                            {
                                target.Hit();
                                target.SetHp(e.RemainingHp);
                                Float(target.transform.position + Vector3.up * 1.6f, "-" + e.Damage, new Color(1f, 0.35f, 0.3f));
                            }));
                        break;
                    }

                    case GameEventType.PlayerDamaged:
                    {
                        var e = ev.PayloadAs<PlayerDamagedEvent>();
                        EnqueueLunge(e.AttackerUid,
                            () => AvatarOf(e.PlayerId)?.StrikePoint,
                            () =>
                            {
                                var avatar = AvatarOf(e.PlayerId);
                                if (avatar == null) return;
                                avatar.Hit();
                                avatar.SetLife(e.RemainingLife);
                                Float(avatar.transform.position + Vector3.up * 1.4f, "-" + e.Damage + " vida", new Color(1f, 0.2f, 0.2f));
                            });
                        break;
                    }

                    case GameEventType.CreatureDestroyed:
                    {
                        var e = ev.PayloadAs<CreatureDestroyedEvent>();
                        // Con modelo animado: animación de muerte y, después, encoger y hundirse.
                        // Con primitivas: encoger y hundirse directamente.
                        _timeline.Enqueue(1.1f,
                            begin: () => WithCreature(e.Uid, v => v.PlayDeath()),
                            update: t => WithCreature(e.Uid, v =>
                            {
                                var k = v.HasAnimations ? Mathf.Clamp01((t - 0.55f) / 0.45f) : Mathf.Clamp01(t / 0.55f);
                                v.SetModelScale(1f - Ease.InOutQuad(k));
                                v.SetModelOffset(Vector3.down * k * 0.6f);
                            }),
                            end: () => Remove(e.Uid));
                        break;
                    }

                    case GameEventType.TurnChanged:
                    {
                        var e = ev.PayloadAs<TurnEvent>();
                        _timeline.Enqueue(0.15f, begin: () => SetActiveTurn(e.CurrentPlayerId));
                        break;
                    }

                    case GameEventType.GameOver:
                    {
                        var e = ev.PayloadAs<GameOverEvent>();
                        _timeline.Enqueue(0.8f, begin: () =>
                        {
                            SetActiveTurn(null);
                            _banner = e.WinnerId == null ? "Empate" : e.WinnerId == _myId ? "¡Victoria!" : "Derrota";
                            AvatarOf(e.WinnerId)?.Celebrate();
                        });
                        break;
                    }
                }
            }

            _timeline.Enqueue(0f, begin: () => Reconcile(state));
        }

        private void EnqueueLunge(int attackerUid, Func<Vector3?> targetWorld, Action onImpact)
        {
            CreatureView attacker = null;
            var home = Vector3.zero;
            var offset = Vector3.zero;
            var impacted = false;
            _timeline.Enqueue(0.75f,
                begin: () =>
                {
                    _creatures.TryGetValue(attackerUid, out attacker);
                    var target = targetWorld();
                    if (attacker == null || target == null) return;
                    attacker.PlayAttack();
                    home = attacker.Home;
                    var delta = _root.InverseTransformPoint(target.Value) - home;
                    delta.y = 0f;
                    offset = delta.normalized * Mathf.Max(0f, delta.magnitude - 1.3f);  // parar antes de tocar
                },
                update: t =>
                {
                    if (attacker != null)
                    {
                        attacker.transform.localPosition = home + offset * Ease.Lunge(t, 0.45f);
                    }
                    if (!impacted && t >= 0.45f)
                    {
                        impacted = true;
                        onImpact();
                    }
                });
        }

        // ------------------------------------------------------------ reconciliación
        /// <summary>Hace que la mesa coincida exactamente con el estado (la verdad).</summary>
        private void Reconcile(GameState state)
        {
            var me = state.Players.FirstOrDefault(p => p.PlayerId == _myId) ?? state.Players.FirstOrDefault();
            var rival = state.Players.FirstOrDefault(p => p != me);
            _myAvatar.Show(me?.PlayerId, me?.Name, me?.Life ?? PlayerAvatarView.MaxLife, me?.Connected ?? true);
            _rivalAvatar.Show(rival?.PlayerId, rival?.Name, rival?.Life ?? PlayerAvatarView.MaxLife, rival?.Connected ?? true);

            var alive = new HashSet<int>();
            foreach (var player in state.Players)
            {
                var card = player.Creature;
                if (card == null) continue;
                alive.Add(card.Uid);
                if (!_creatures.TryGetValue(card.Uid, out var view) || view == null)
                {
                    view = Spawn(card, player.PlayerId);
                }
                view.SetHp(card.Hp);
                view.SetModelScale(1f);
                view.SetModelOffset(Vector3.zero);
                view.transform.localPosition = view.Home;
            }
            foreach (var uid in _creatures.Keys.ToList())
            {
                if (!alive.Contains(uid)) Remove(uid);
            }

            SetActiveTurn(state.Status == GameStatus.InProgress ? state.CurrentPlayerId : null);
            if (state.Status != GameStatus.Finished)
            {
                _banner = null;
            }
            else if (_banner == null)
            {
                _banner = state.WinnerId == null ? "Empate" : state.WinnerId == _myId ? "¡Victoria!" : "Derrota";
            }
        }

        // ------------------------------------------------------------ helpers
        private bool IsMine(string playerId) => playerId == _myAvatar.PlayerId || (_myAvatar.PlayerId == null && playerId == _myId);

        private PlayerAvatarView AvatarOf(string playerId)
        {
            if (playerId == null) return null;
            return IsMine(playerId) ? _myAvatar : _rivalAvatar;
        }

        private CreatureView Spawn(CardInstance card, string ownerId)
        {
            Remove(card.Uid);
            var mine = IsMine(ownerId);
            var view = CreatureView.Create(card, ownerId, _root, mine ? MySlot : RivalSlot, mine, prefabs);
            _creatures[card.Uid] = view;
            return view;
        }

        private void Remove(int uid)
        {
            if (_creatures.TryGetValue(uid, out var view))
            {
                _creatures.Remove(uid);
                if (view != null) CreatureVisuals.SafeDestroy(view.gameObject);
            }
        }

        private void ClearCreatures()
        {
            foreach (var uid in _creatures.Keys.ToList()) Remove(uid);
        }

        private void WithCreature(int uid, Action<CreatureView> action)
        {
            if (_creatures.TryGetValue(uid, out var view) && view != null) action(view);
        }

        private void SetActiveTurn(string playerId)
        {
            _myAvatar.SetActiveTurn(playerId != null && IsMine(playerId));
            _rivalAvatar.SetActiveTurn(playerId != null && !IsMine(playerId));
        }

        private void Float(Vector3 world, string text, Color color)
        {
            _floating.Add(new FloatingText { World = world, Text = text, Color = color, Life = 1.2f });
        }

        // ------------------------------------------------------------ etiquetas (IMGUI)
        private void OnGUI()
        {
            var cam = Camera.main;
            if (cam == null || _root == null) return;
            GUI.matrix = Matrix4x4.identity;
            var scale = Mathf.Max(1f, Screen.height / 720f);

            foreach (var view in _creatures.Values)
            {
                if (view == null) continue;
                Label(cam, view.LabelAnchor, $"{view.DisplayName}  {view.Hp}/{view.MaxHp}", Color.white, 15, scale);
            }
            foreach (var avatar in new[] { _myAvatar, _rivalAvatar })
            {
                if (avatar == null || !avatar.HasPlayer) continue;
                var who = avatar == _myAvatar ? " (tú)" : "";
                Label(cam, avatar.LabelAnchor, $"{avatar.DisplayName}{who}  Vida {avatar.Life}", new Color(1f, 0.9f, 0.6f), 15, scale);
            }
            foreach (var f in _floating)
            {
                var k = f.Age / f.Life;
                var color = f.Color;
                color.a = 1f - k * k;
                Label(cam, f.World + Vector3.up * k * 1.2f, f.Text, color, 26, scale);
            }
            if (_banner != null)
            {
                var style = new GUIStyle(GUI.skin.label)
                {
                    fontSize = Mathf.RoundToInt(56 * scale),
                    fontStyle = FontStyle.Bold,
                    alignment = TextAnchor.MiddleCenter,
                };
                var rect = new Rect(0f, Screen.height * 0.08f, Screen.width, 90f * scale);
                Shadowed(rect, _banner, style, new Color(1f, 0.85f, 0.3f));
            }
        }

        private static void Label(Camera cam, Vector3 world, string text, Color color, int size, float scale)
        {
            var sp = cam.WorldToScreenPoint(world);
            if (sp.z <= 0f) return;
            var style = new GUIStyle(GUI.skin.label)
            {
                fontSize = Mathf.RoundToInt(size * scale),
                fontStyle = FontStyle.Bold,
                alignment = TextAnchor.MiddleCenter,
            };
            var w = 320f * scale;
            var h = 40f * scale;
            Shadowed(new Rect(sp.x - w / 2f, Screen.height - sp.y - h / 2f, w, h), text, style, color);
        }

        private static void Shadowed(Rect rect, string text, GUIStyle style, Color color)
        {
            var previous = GUI.color;
            GUI.color = new Color(0f, 0f, 0f, color.a * 0.85f);
            GUI.Label(new Rect(rect.x + 2f, rect.y + 2f, rect.width, rect.height), text, style);
            GUI.color = color;
            GUI.Label(rect, text, style);
            GUI.color = previous;
        }

        private void OnDestroy()
        {
            foreach (var m in _materials) CreatureVisuals.SafeDestroy(m);
        }
    }
}
