using System.Collections.Generic;
using System.IO;
using System.Linq;
using CardWars.Presentation;
using UnityEditor;
using UnityEngine;

namespace CardWars.EditorTools
{
    /// <summary>
    /// CardWars > Setup Quaternius Models
    ///
    /// Configura los FBX de Quaternius (CC0) de Assets/CardWars/Models/Quaternius y
    /// rellena Resources/CreaturePrefabRegistry, que BoardView carga solo:
    ///   1. Avatar genérico => el modelo tiene Animator.
    ///   2. La animación de reposo en bucle.
    ///   3. Materiales URP propios (texturas del pack; paleta roja para el dragón,
    ///      cuyos colores del FBX llegan casi negros) remapeados en el importador.
    ///   4. Registro model_key -> modelo + clips (reposo, ataque, golpe, muerte).
    /// Es idempotente: se puede volver a ejecutar sin romper nada.
    /// </summary>
    public static class CardWarsModelSetup
    {
        private const string Root = "Assets/CardWars/Models/Quaternius";
        private const string MaterialsDir = Root + "/Materials";
        private const string TexturesDir = Root + "/Textures";
        private const string ResourcesDir = "Assets/CardWars/Resources";
        private const string RegistryPath = ResourcesDir + "/CreaturePrefabRegistry.asset";

        private sealed class Spec
        {
            public string ModelKey;   // model_key del catálogo del servidor (data/cards.json)
            public string File;
            public string Idle, Attack, Hit, Death;
            public float Height;
            public float MaxWidth;
        }

        private static readonly Spec[] Specs =
        {
            new Spec { ModelKey = "dragon", File = "Dragon", Idle = "Dragon_Flying", Attack = "Dragon_Attack",
                       Hit = "Dragon_Hit", Death = "Dragon_Death", Height = 2.0f, MaxWidth = 2.6f },
            new Spec { ModelKey = "warrior", File = "Warrior", Idle = "Idle_Weapon", Attack = "Sword_Attack",
                       Hit = "RecieveHit", Death = "Death", Height = 1.9f, MaxWidth = 2.2f },
            new Spec { ModelKey = "mage", File = "Wizard", Idle = "Idle_Weapon", Attack = "Staff_Attack",
                       Hit = "RecieveHit", Death = "Death", Height = 1.9f, MaxWidth = 2.2f },
        };

        // El dragón trae colores de material casi negros: paleta propia.
        private static readonly Dictionary<string, Color> DragonPalette = new Dictionary<string, Color>
        {
            { "Main", new Color(0.72f, 0.16f, 0.12f) },
            { "Belly", new Color(0.93f, 0.76f, 0.34f) },
            { "Wings", new Color(0.40f, 0.08f, 0.07f) },
            { "Claws", new Color(0.16f, 0.12f, 0.10f) },
            { "Eyes", new Color(0.98f, 0.86f, 0.20f) },
        };

        [MenuItem("CardWars/Setup Quaternius Models")]
        public static void Setup()
        {
            EnsureFolder(MaterialsDir);
            EnsureFolder(ResourcesDir);
            var lit = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");

            foreach (var spec in Specs)
            {
                var path = $"{Root}/{spec.File}.fbx";
                var importer = AssetImporter.GetAtPath(path) as ModelImporter;
                if (importer == null)
                {
                    Debug.LogWarning($"[CardWars] No encuentro {path}: se omite.");
                    continue;
                }

                importer.animationType = ModelImporterAnimationType.Generic;
                importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;

                var clips = importer.clipAnimations.Length > 0 ? importer.clipAnimations : importer.defaultClipAnimations;
                foreach (var clip in clips)
                {
                    clip.loopTime = ClipMatches(clip.name, spec.Idle);
                }
                importer.clipAnimations = clips;

                // Materiales embebidos (solo existen mientras no se hayan remapeado).
                foreach (var embedded in AssetDatabase.LoadAllAssetsAtPath(path).OfType<Material>())
                {
                    var materialPath = $"{MaterialsDir}/{spec.File}_{embedded.name}.mat";
                    var material = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
                    if (material == null)
                    {
                        material = new Material(lit);
                        AssetDatabase.CreateAsset(material, materialPath);
                    }
                    var texture = AssetDatabase.LoadAssetAtPath<Texture2D>($"{TexturesDir}/{embedded.name}.png");
                    if (texture != null)
                    {
                        material.SetTexture("_BaseMap", texture);
                        material.color = Color.white;
                    }
                    else
                    {
                        material.color = spec.ModelKey == "dragon" && DragonPalette.TryGetValue(embedded.name, out var c)
                            ? c : embedded.color.gamma;
                    }
                    if (material.HasProperty("_Smoothness")) material.SetFloat("_Smoothness", 0.2f);
                    EditorUtility.SetDirty(material);
                    importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), embedded.name), material);
                }
                importer.SaveAndReimport();
            }

            AssetDatabase.SaveAssets();
            var registry = AssetDatabase.LoadAssetAtPath<CreaturePrefabRegistry>(RegistryPath);
            if (registry == null)
            {
                registry = ScriptableObject.CreateInstance<CreaturePrefabRegistry>();
                AssetDatabase.CreateAsset(registry, RegistryPath);
            }
            registry.entries.RemoveAll(e => e == null || Specs.Any(s => s.ModelKey == e.modelKey));
            foreach (var spec in Specs)
            {
                var path = $"{Root}/{spec.File}.fbx";
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab == null) continue;
                var all = AssetDatabase.LoadAllAssetsAtPath(path).OfType<AnimationClip>()
                                       .Where(c => !c.name.StartsWith("__preview")).ToList();
                registry.entries.Add(new CreaturePrefabRegistry.Entry
                {
                    modelKey = spec.ModelKey,
                    prefab = prefab,
                    height = spec.Height,
                    maxWidth = spec.MaxWidth,
                    idle = all.FirstOrDefault(c => ClipMatches(c.name, spec.Idle)),
                    attack = all.FirstOrDefault(c => ClipMatches(c.name, spec.Attack)),
                    hit = all.FirstOrDefault(c => ClipMatches(c.name, spec.Hit)),
                    death = all.FirstOrDefault(c => ClipMatches(c.name, spec.Death)),
                });
            }
            EditorUtility.SetDirty(registry);
            AssetDatabase.SaveAssets();

            foreach (var e in registry.entries)
            {
                Debug.Log($"[CardWars] {e.modelKey}: {(e.prefab ? e.prefab.name : "-")} idle={Name(e.idle)} " +
                          $"attack={Name(e.attack)} hit={Name(e.hit)} death={Name(e.death)}");
            }
            Debug.Log("[CardWars] Modelos configurados. Pulsa Play: BoardView usa el registro automáticamente.");
        }

        /// <summary>"CharacterArmature|Idle_Weapon" coincide con "Idle_Weapon".</summary>
        private static bool ClipMatches(string clipName, string wanted) =>
            clipName == wanted || clipName.EndsWith("|" + wanted);

        private static string Name(AnimationClip clip) => clip != null ? clip.name : "-";

        private static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            var parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
            if (!string.IsNullOrEmpty(parent)) EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
        }
    }
}
