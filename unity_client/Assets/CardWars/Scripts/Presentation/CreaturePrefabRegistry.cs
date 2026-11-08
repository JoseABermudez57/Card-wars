using System;
using System.Collections.Generic;
using UnityEngine;

namespace CardWars.Presentation
{
    /// <summary>
    /// model_key (del catálogo del servidor) -> modelo 3D + animaciones.
    ///
    /// BoardView carga automáticamente Resources/CreaturePrefabRegistry si no se le
    /// asigna otro. El menú CardWars > Setup Quaternius Models lo rellena; también se
    /// puede crear a mano: Assets > Create > CardWars > Creature Prefab Registry.
    /// Las claves sin entrada usan el muñeco de primitivas.
    /// </summary>
    [CreateAssetMenu(menuName = "CardWars/Creature Prefab Registry", fileName = "CreaturePrefabRegistry")]
    public class CreaturePrefabRegistry : ScriptableObject
    {
        [Serializable]
        public class Entry
        {
            public string modelKey;
            public GameObject prefab;

            [Tooltip("Altura en unidades de mesa (el modelo se escala a esto).")]
            [Min(0.1f)]
            public float height = 1.6f;

            [Tooltip("Ancho máximo (alas, armas...). Gana el límite más estricto.")]
            [Min(0.1f)]
            public float maxWidth = 2.2f;

            [Tooltip("Giro extra si el modelo no mira hacia +Z.")]
            public float yawOffset;

            [Header("Animaciones (opcionales)")]
            public AnimationClip idle;
            public AnimationClip attack;
            public AnimationClip hit;
            public AnimationClip death;

            public bool HasAnimations => idle != null || attack != null || hit != null || death != null;
        }

        public List<Entry> entries = new List<Entry>();

        public Entry FindEntry(string modelKey)
        {
            foreach (var entry in entries)
            {
                if (entry != null && entry.prefab != null && entry.modelKey == modelKey)
                {
                    return entry;
                }
            }
            return null;
        }

        public GameObject Find(string modelKey) => FindEntry(modelKey)?.prefab;

        /// <summary>El registro por defecto (Resources/CreaturePrefabRegistry), o null.</summary>
        public static CreaturePrefabRegistry LoadDefault() => Resources.Load<CreaturePrefabRegistry>("CreaturePrefabRegistry");
    }
}
