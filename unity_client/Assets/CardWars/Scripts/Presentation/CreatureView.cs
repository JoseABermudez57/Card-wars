using System.Collections.Generic;
using CardWars.Core;
using UnityEngine;

namespace CardWars.Presentation
{
    /// <summary>
    /// Una criatura en mesa. Separa:
    ///   - raíz (posición en la mesa; la mueve BoardView para embestir),
    ///   - pivote (rota para mirar al rival; aquí se aplica la sacudida),
    ///   - modelo (escala al aparecer/morir; primitivas o modelo 3D real),
    ///   - barra de vida (sin rotar, siempre legible).
    /// Con modelo real y clips, CreatureAnimator reproduce reposo/ataque/golpe/muerte.
    /// Todo avanza con Tick(dt).
    /// </summary>
    public class CreatureView : MonoBehaviour
    {
        private readonly List<Material> _materials = new List<Material>();
        private readonly List<(Material material, Color baseColor)> _tintable = new List<(Material, Color)>();
        private Transform _pivot;
        private Transform _model;
        private Bar _bar;
        private CreatureAnimator _animator;
        private float _flash;
        private float _shake;
        private float _time;

        public int Uid { get; private set; }
        public string OwnerId { get; private set; }
        public string DisplayName { get; private set; }
        public int Hp { get; private set; }
        public int MaxHp { get; private set; }
        public Vector3 Home { get; set; }

        /// <summary>True si usa un modelo 3D con animaciones (no primitivas).</summary>
        public bool HasAnimations => _animator != null;

        /// <summary>Punto en el mundo para etiquetas (encima de la barra).</summary>
        public Vector3 LabelAnchor => transform.position + Vector3.up * 2.7f;

        public static CreatureView Create(CardInstance card, string ownerId, Transform parent, Vector3 home,
                                          bool facesForward, CreaturePrefabRegistry registry)
        {
            var go = new GameObject($"Creature {card.Name} #{card.Uid}");
            go.transform.SetParent(parent, false);
            go.transform.localPosition = home;
            var view = go.AddComponent<CreatureView>();
            view.Init(card, ownerId, home, facesForward, registry);
            return view;
        }

        private void Init(CardInstance card, string ownerId, Vector3 home, bool facesForward,
                          CreaturePrefabRegistry registry)
        {
            Uid = card.Uid;
            OwnerId = ownerId;
            DisplayName = card.Name;
            MaxHp = Mathf.Max(1, card.MaxHp);
            Home = home;

            _pivot = new GameObject("Pivot").transform;
            _pivot.SetParent(transform, false);
            _pivot.localRotation = Quaternion.Euler(0f, facesForward ? 0f : 180f, 0f);
            _model = CreatureVisuals.Build(card.ModelKey, _pivot, registry, _materials, out var entry).transform;

            if (entry != null && entry.HasAnimations)
            {
                var animator = _model.GetComponentInChildren<Animator>();
                if (animator == null)
                {
                    animator = _model.GetChild(0).gameObject.AddComponent<Animator>();
                }
                _animator = CreatureAnimator.Attach(gameObject, animator, entry);
            }

            foreach (var r in _model.GetComponentsInChildren<Renderer>())
            {
                foreach (var m in r.sharedMaterials)
                {
                    if (m != null && m.HasProperty("_BaseColor"))
                    {
                        _tintable.Add((m, m.color));
                    }
                }
            }
            _bar = new Bar(gameObject, new Vector3(0f, 2.35f, 0f), 1.1f, _materials);
            SetHp(card.Hp);
        }

        public void SetHp(int hp)
        {
            Hp = Mathf.Max(0, hp);
            _bar.Set(Hp / (float)MaxHp);
        }

        /// <summary>Impacto: destello rojo + sacudida (+ animación de golpe si hay).</summary>
        public void Hit()
        {
            _flash = 1f;
            _shake = HasAnimations ? 0.5f : 1f;  // con animación real basta una sacudida leve
            if (_animator != null) _animator.PlayHit();
        }

        public void PlayAttack()
        {
            if (_animator != null) _animator.PlayAttack();
        }

        public void PlayDeath()
        {
            if (_animator != null) _animator.PlayDeath();
        }

        /// <summary>Escala del modelo (aparecer / morir), relativa a su tamaño normalizado.</summary>
        public void SetModelScale(float scale)
        {
            _pivot.localScale = Vector3.one * Mathf.Max(0f, scale);
        }

        public void SetModelOffset(Vector3 offset)
        {
            _pivot.localPosition = offset;
            _baseOffset = offset;
        }

        private Vector3 _baseOffset;

        public void Tick(float dt)
        {
            _time += dt;
            if (_animator != null)
            {
                _animator.Tick(dt);
            }
            if (_flash > 0f || _shake > 0f)
            {
                _flash = Mathf.Max(0f, _flash - dt * 3f);
                _shake = Mathf.Max(0f, _shake - dt * 3.5f);
                var offset = new Vector3(Mathf.Sin(_time * 70f), 0f, Mathf.Cos(_time * 53f)) * 0.12f * _shake;
                _pivot.localPosition = _baseOffset + offset;
                var hitColor = new Color(1f, 0.25f, 0.2f);
                foreach (var (material, baseColor) in _tintable)
                {
                    if (material != null)
                    {
                        material.color = Color.Lerp(baseColor, hitColor, _flash * 0.8f);
                    }
                }
            }
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
