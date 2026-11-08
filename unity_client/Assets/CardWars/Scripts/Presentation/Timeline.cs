using System;
using System.Collections.Generic;

namespace CardWars.Presentation
{
    /// <summary>
    /// Cola secuencial de pasos de animación. Cada paso tiene duración y callbacks
    /// begin / update(t de 0 a 1) / end. Se avanza con Tick(dt): sin corrutinas, así
    /// es determinista y se puede ejecutar paso a paso fuera de Play (capturas, tests).
    ///
    /// Si se acumulan pasos (llegan eventos más rápido de lo que se animan), acelera
    /// para no quedarse atrás del estado real.
    /// </summary>
    public sealed class Timeline
    {
        private sealed class Step
        {
            public float Duration;
            public Action Begin;
            public Action<float> Update;
            public Action End;
        }

        private readonly Queue<Step> _queue = new Queue<Step>();
        private Step _current;
        private float _elapsed;

        public bool IsIdle => _current == null && _queue.Count == 0;

        public int Pending => _queue.Count + (_current == null ? 0 : 1);

        public void Enqueue(float duration, Action<float> update = null, Action begin = null, Action end = null)
        {
            _queue.Enqueue(new Step { Duration = Math.Max(0f, duration), Begin = begin, Update = update, End = end });
        }

        public void Tick(float dt)
        {
            dt *= 1f + Math.Max(0, _queue.Count - 3) * 0.5f;  // ponerse al día si hay cola
            while (true)
            {
                if (_current == null)
                {
                    if (_queue.Count == 0)
                    {
                        return;
                    }
                    _current = _queue.Dequeue();
                    _elapsed = 0f;
                    _current.Begin?.Invoke();
                }

                var remaining = _current.Duration - _elapsed;
                if (dt < remaining)
                {
                    _elapsed += dt;
                    _current.Update?.Invoke(_elapsed / _current.Duration);
                    return;
                }

                dt -= remaining;
                _current.Update?.Invoke(1f);
                _current.End?.Invoke();
                _current = null;
            }
        }

        /// <summary>Ejecuta todo lo pendiente al instante (p. ej. al reconectar).</summary>
        public void FinishAll()
        {
            Tick(float.MaxValue / 4f);
        }
    }

    /// <summary>Curvas de animación.</summary>
    public static class Ease
    {
        public static float OutQuad(float t) => 1f - (1f - t) * (1f - t);

        public static float InOutQuad(float t) => t < 0.5f ? 2f * t * t : 1f - (float)Math.Pow(-2f * t + 2f, 2) / 2f;

        public static float OutBack(float t)
        {
            const float c1 = 1.70158f;
            const float c3 = c1 + 1f;
            var u = t - 1f;
            return 1f + c3 * u * u * u + c1 * u * u;
        }

        /// <summary>0 -> 1 (en `peak`) -> 0: ida y vuelta de una embestida.</summary>
        public static float Lunge(float t, float peak = 0.35f) =>
            t < peak ? OutQuad(t / peak) : 1f - InOutQuad((t - peak) / (1f - peak));
    }
}
