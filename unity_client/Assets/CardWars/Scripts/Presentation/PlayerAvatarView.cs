using System.Collections.Generic;
using UnityEngine;

namespace CardWars.Presentation
{
    /// <summary>
    /// Tótem que representa a un jugador (su vida) y el anillo de su casilla
    /// (dorado cuando es su turno).
    /// </summary>
    public class PlayerAvatarView : MonoBehaviour
    {
        public const int MaxLife = 100;

        private readonly List<Material> _materials = new List<Material>();
        private Bar _bar;
        private Transform _crystal;
        private Renderer _crystalRenderer;
        private Renderer _ringRenderer;
        private Color _crystalColor;
        private float _flash;
        private float _shake;
        private float _bounce;
        private float _time;

        public string PlayerId { get; private set; }
        public string DisplayName { get; private set; } = "";
        public int Life { get; private set; } = MaxLife;
        public bool Connected { get; private set; } = true;
        public bool HasPlayer => PlayerId != null;

        public Vector3 LabelAnchor => transform.position + Vector3.up * 2.15f;

        /// <summary>Punto al que embisten las criaturas que atacan a este jugador.</summary>
        public Vector3 StrikePoint => transform.position + Vector3.up * 0.8f;

        public static PlayerAvatarView Create(Transform parent, Vector3 position, Transform slot, Color color)
        {
            var go = new GameObject("Player Avatar");
            go.transform.SetParent(parent, false);
            go.transform.localPosition = position;
            var view = go.AddComponent<PlayerAvatarView>();
            view.Build(slot, color);
            return view;
        }

        private void Build(Transform slot, Color color)
        {
            _crystalColor = color;
            CreatureVisuals.Part(PrimitiveType.Cylinder, gameObject, new Vector3(0f, 0.15f, 0f),
                                 new Vector3(0.9f, 0.15f, 0.9f), Vector3.zero,
                                 CreatureVisuals.Mat(new Color(0.18f, 0.18f, 0.22f), _materials));
            var crystal = CreatureVisuals.Part(PrimitiveType.Cube, gameObject, new Vector3(0f, 1.0f, 0f),
                                               new Vector3(0.55f, 0.9f, 0.55f), new Vector3(0f, 45f, 0f),
                                               CreatureVisuals.Mat(color, _materials));
            _crystal = crystal.transform;
            _crystalRenderer = crystal.GetComponent<Renderer>();
            _bar = new Bar(gameObject, new Vector3(0f, 1.85f, 0f), 1.6f, _materials);

            // Anillo de turno bajo la casilla de la criatura.
            var ring = CreatureVisuals.Part(PrimitiveType.Cylinder, slot.gameObject, new Vector3(0f, 0.01f, 0f),
                                            new Vector3(1.5f, 0.01f, 1.5f), Vector3.zero,
                                            CreatureVisuals.Mat(new Color(0.25f, 0.25f, 0.3f), _materials));
            _ringRenderer = ring.GetComponent<Renderer>();
            Show(null, null, MaxLife, true);
        }

        public void Show(string playerId, string displayName, int life, bool connected)
        {
            PlayerId = playerId;
            DisplayName = displayName ?? "";
            Connected = connected;
            SetLife(life);
            _crystal.gameObject.SetActive(playerId != null);
            _crystalRenderer.sharedMaterial.color = connected ? _crystalColor : Color.Lerp(_crystalColor, Color.gray, 0.75f);
        }

        public void SetLife(int life)
        {
            Life = Mathf.Max(0, life);
            _bar.Set(Life / (float)MaxLife);
        }

        public void SetActiveTurn(bool active)
        {
            _ringRenderer.sharedMaterial.color = active ? new Color(0.95f, 0.78f, 0.35f) : new Color(0.25f, 0.25f, 0.3f);
        }

        public void Hit()
        {
            _flash = 1f;
            _shake = 1f;
        }

        public void Celebrate()
        {
            _bounce = 1f;
        }

        public void Tick(float dt)
        {
            _time += dt;
            _flash = Mathf.Max(0f, _flash - dt * 3f);
            _shake = Mathf.Max(0f, _shake - dt * 3.5f);
            _bounce = Mathf.Max(0f, _bounce - dt * 0.6f);
            var shake = new Vector3(Mathf.Sin(_time * 70f), 0f, 0f) * 0.15f * _shake;
            var hop = Mathf.Abs(Mathf.Sin(_time * 9f)) * 0.5f * _bounce;
            _crystal.localPosition = new Vector3(0f, 1.0f + hop, 0f) + shake;
            _crystal.localRotation = Quaternion.Euler(0f, 45f + _time * 30f, 0f);  // gira despacio
            var baseColor = Connected ? _crystalColor : Color.Lerp(_crystalColor, Color.gray, 0.75f);
            _crystalRenderer.sharedMaterial.color = Color.Lerp(baseColor, new Color(1f, 0.25f, 0.2f), _flash * 0.85f);
        }

        private void OnDestroy()
        {
            foreach (var m in _materials)
            {
                CreatureVisuals.SafeDestroy(m);
            }
        }
    }
}
