using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;

namespace CardWars.Presentation
{
    /// <summary>
    /// Reproduce los clips de una criatura (reposo / ataque / golpe / muerte) con el
    /// API de Playables: no necesita AnimatorController ni máquina de estados.
    ///
    /// El grafo avanza en modo manual con Tick(dt), igual que la Timeline de BoardView:
    /// determinista y funciona también fuera de Play (capturas, tests).
    /// </summary>
    public class CreatureAnimator : MonoBehaviour
    {
        private PlayableGraph _graph;
        private AnimationPlayableOutput _output;
        private AnimationClipPlayable _playable;
        private AnimationClip _current;
        private bool _currentIsIdle;
        private bool _holdLastFrame;
        private CreaturePrefabRegistry.Entry _clips;

        public static CreatureAnimator Attach(GameObject host, Animator animator, CreaturePrefabRegistry.Entry clips)
        {
            var anim = host.AddComponent<CreatureAnimator>();
            anim.Init(animator, clips);
            return anim;
        }

        private void Init(Animator animator, CreaturePrefabRegistry.Entry clips)
        {
            _clips = clips;
            animator.applyRootMotion = false;  // la posición la decide la mesa, no el clip
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            _graph = PlayableGraph.Create("CreatureAnimator " + name);
            _graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
            _output = AnimationPlayableOutput.Create(_graph, "Animation", animator);
            PlayIdle();
            _graph.Play();
            _graph.Evaluate(0f);
        }

        public void PlayIdle() => Play(_clips.idle, isIdle: true, hold: false);

        public void PlayAttack() => Play(_clips.attack, isIdle: false, hold: false);

        public void PlayHit() => Play(_clips.hit, isIdle: false, hold: false);

        /// <summary>Muerte: se queda en el último fotograma.</summary>
        public void PlayDeath() => Play(_clips.death, isIdle: false, hold: true);

        private void Play(AnimationClip clip, bool isIdle, bool hold)
        {
            if (!_graph.IsValid())
            {
                return;
            }
            if (clip == null)
            {
                if (!isIdle && _clips.idle != null && !_currentIsIdle)
                {
                    PlayIdle();
                }
                return;
            }
            if (_playable.IsValid())
            {
                _playable.Destroy();
            }
            _playable = AnimationClipPlayable.Create(_graph, clip);
            _playable.SetApplyFootIK(false);
            _output.SetSourcePlayable(_playable);
            _current = clip;
            _currentIsIdle = isIdle;
            _holdLastFrame = hold;
        }

        public void Tick(float dt)
        {
            if (!_graph.IsValid())
            {
                return;
            }
            if (_playable.IsValid() && _current != null)
            {
                var length = Mathf.Max(0.01f, _current.length);
                var time = (float)_playable.GetTime();
                if (time >= length)
                {
                    if (_currentIsIdle)
                    {
                        _playable.SetTime(time % length);       // bucle
                    }
                    else if (_holdLastFrame)
                    {
                        _playable.SetTime(length);              // congelar
                        _playable.SetSpeed(0);
                    }
                    else
                    {
                        PlayIdle();                             // one-shot terminado
                    }
                }
            }
            _graph.Evaluate(dt);
        }

        private void OnDestroy()
        {
            if (_graph.IsValid())
            {
                _graph.Destroy();
            }
        }
    }
}
