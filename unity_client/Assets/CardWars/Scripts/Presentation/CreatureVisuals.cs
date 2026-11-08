using System.Collections.Generic;
using UnityEngine;

namespace CardWars.Presentation
{
    /// <summary>
    /// Fábrica de visuales: model_key -> GameObject.
    /// 1) Si el registro tiene un prefab para ese model_key, lo usa (modelos 3D reales).
    /// 2) Si no, construye un "muñeco" con primitivas. Así el juego funciona sin assets.
    /// </summary>
    public static class CreatureVisuals
    {
        public static GameObject Build(string modelKey, Transform parent, CreaturePrefabRegistry registry,
                                       List<Material> ownedMaterials, out CreaturePrefabRegistry.Entry entry)
        {
            entry = registry != null ? registry.FindEntry(modelKey) : null;
            if (entry != null)
            {
                return BuildFromPrefab(entry, parent, ownedMaterials);
            }

            var root = new GameObject("Model (" + modelKey + ")");
            root.transform.SetParent(parent, false);
            switch (modelKey)
            {
                case "dragon":
                {
                    var red = Mat(new Color(0.80f, 0.18f, 0.14f), ownedMaterials);
                    var dark = Mat(new Color(0.45f, 0.08f, 0.06f), ownedMaterials);
                    Part(PrimitiveType.Capsule, root, new Vector3(0f, 0.55f, 0f), new Vector3(0.7f, 0.55f, 0.7f), new Vector3(90f, 0f, 0f), red);
                    Part(PrimitiveType.Sphere, root, new Vector3(0f, 0.95f, 0.55f), Vector3.one * 0.45f, Vector3.zero, red);
                    Part(PrimitiveType.Cube, root, new Vector3(0f, 0.9f, 0.82f), new Vector3(0.25f, 0.15f, 0.25f), Vector3.zero, dark);
                    Part(PrimitiveType.Cube, root, new Vector3(-0.6f, 0.95f, -0.05f), new Vector3(0.9f, 0.05f, 0.55f), new Vector3(0f, 0f, 25f), dark);
                    Part(PrimitiveType.Cube, root, new Vector3(0.6f, 0.95f, -0.05f), new Vector3(0.9f, 0.05f, 0.55f), new Vector3(0f, 0f, -25f), dark);
                    Part(PrimitiveType.Cube, root, new Vector3(0f, 0.45f, -0.75f), new Vector3(0.15f, 0.15f, 0.6f), new Vector3(-20f, 0f, 0f), red);
                    break;
                }
                case "warrior":
                {
                    var blue = Mat(new Color(0.22f, 0.42f, 0.85f), ownedMaterials);
                    var steel = Mat(new Color(0.70f, 0.72f, 0.78f), ownedMaterials);
                    var skin = Mat(new Color(0.93f, 0.76f, 0.60f), ownedMaterials);
                    Part(PrimitiveType.Cube, root, new Vector3(0f, 0.55f, 0f), new Vector3(0.65f, 0.9f, 0.45f), Vector3.zero, blue);
                    Part(PrimitiveType.Sphere, root, new Vector3(0f, 1.2f, 0f), Vector3.one * 0.42f, Vector3.zero, skin);
                    Part(PrimitiveType.Cube, root, new Vector3(0f, 1.38f, 0f), new Vector3(0.45f, 0.12f, 0.45f), Vector3.zero, steel);
                    Part(PrimitiveType.Cube, root, new Vector3(-0.42f, 0.6f, 0.15f), new Vector3(0.08f, 0.7f, 0.55f), Vector3.zero, steel);
                    Part(PrimitiveType.Cube, root, new Vector3(0.42f, 0.75f, 0.3f), new Vector3(0.06f, 0.06f, 0.9f), Vector3.zero, steel);
                    break;
                }
                case "mage":
                {
                    var purple = Mat(new Color(0.50f, 0.22f, 0.78f), ownedMaterials);
                    var skin = Mat(new Color(0.93f, 0.76f, 0.60f), ownedMaterials);
                    var wood = Mat(new Color(0.45f, 0.30f, 0.16f), ownedMaterials);
                    var orb = Mat(new Color(0.35f, 0.95f, 1.00f), ownedMaterials);
                    Part(PrimitiveType.Cylinder, root, new Vector3(0f, 0.5f, 0f), new Vector3(0.65f, 0.5f, 0.65f), Vector3.zero, purple);
                    Part(PrimitiveType.Sphere, root, new Vector3(0f, 1.2f, 0f), Vector3.one * 0.38f, Vector3.zero, skin);
                    Part(PrimitiveType.Cylinder, root, new Vector3(0f, 1.48f, 0f), new Vector3(0.5f, 0.03f, 0.5f), Vector3.zero, purple);
                    Part(PrimitiveType.Cylinder, root, new Vector3(0f, 1.68f, 0f), new Vector3(0.22f, 0.2f, 0.22f), Vector3.zero, purple);
                    Part(PrimitiveType.Cylinder, root, new Vector3(0.45f, 0.75f, 0.1f), new Vector3(0.06f, 0.75f, 0.06f), Vector3.zero, wood);
                    Part(PrimitiveType.Sphere, root, new Vector3(0.45f, 1.55f, 0.1f), Vector3.one * 0.2f, Vector3.zero, orb);
                    break;
                }
                default:
                {
                    var gray = Mat(new Color(0.6f, 0.6f, 0.6f), ownedMaterials);
                    Part(PrimitiveType.Cube, root, new Vector3(0f, 0.5f, 0f), Vector3.one * 0.8f, Vector3.zero, gray);
                    break;
                }
            }
            return root;
        }

        /// <summary>
        /// Instancia un modelo real y lo normaliza: cada FBX viene a su escala y con su
        /// origen; aquí se escala a `entry.height` (sin pasar de `maxWidth`), con los pies
        /// en el suelo y centrado. Contenedor (escala) > instancia (desplazamiento).
        /// </summary>
        private static GameObject BuildFromPrefab(CreaturePrefabRegistry.Entry entry, Transform parent,
                                                  List<Material> ownedMaterials)
        {
            var container = new GameObject("Model (" + entry.modelKey + ")");
            container.transform.SetParent(parent, false);
            container.transform.localRotation = Quaternion.Euler(0f, entry.yawOffset, 0f);
            var instance = Object.Instantiate(entry.prefab, container.transform, false);
            instance.name = entry.prefab.name;

            var renderers = instance.GetComponentsInChildren<Renderer>();
            if (renderers.Length > 0)
            {
                // Límites medidos en el espacio local del contenedor (aún a escala 1).
                var min = Vector3.positiveInfinity;
                var max = Vector3.negativeInfinity;
                foreach (var r in renderers)
                {
                    var b = r.bounds;
                    for (var i = 0; i < 8; i++)
                    {
                        var corner = new Vector3(i % 2 == 0 ? b.min.x : b.max.x,
                                                 (i / 2) % 2 == 0 ? b.min.y : b.max.y,
                                                 i / 4 == 0 ? b.min.z : b.max.z);
                        var local = container.transform.InverseTransformPoint(corner);
                        min = Vector3.Min(min, local);
                        max = Vector3.Max(max, local);
                    }
                }
                var size = max - min;
                var scale = Mathf.Min(entry.height / Mathf.Max(0.01f, size.y),
                                      entry.maxWidth / Mathf.Max(0.01f, Mathf.Max(size.x, size.z)));
                instance.transform.localPosition = new Vector3(-(min.x + max.x) / 2f, -min.y, -(min.z + max.z) / 2f);
                container.transform.localScale = Vector3.one * scale;
            }

            // Materiales propios por instancia: el destello de golpe no debe teñir a
            // las demás criaturas del mismo tipo (ni modificar el asset del proyecto).
            foreach (var r in renderers)
            {
                var materials = r.sharedMaterials;
                for (var i = 0; i < materials.Length; i++)
                {
                    if (materials[i] == null) continue;
                    materials[i] = new Material(materials[i]);
                    ownedMaterials?.Add(materials[i]);
                }
                r.sharedMaterials = materials;
                if (r is SkinnedMeshRenderer skinned)
                {
                    skinned.updateWhenOffscreen = true;  // límites correctos durante la animación
                }
            }
            return container;
        }

        /// <summary>Primitiva sin collider (no los necesitamos y cuestan).</summary>
        public static GameObject Part(PrimitiveType type, GameObject parent, Vector3 position, Vector3 scale,
                                      Vector3 euler, Material material)
        {
            var go = GameObject.CreatePrimitive(type);
            go.name = type.ToString();
            SafeDestroy(go.GetComponent<Collider>());
            go.transform.SetParent(parent.transform, false);
            go.transform.localPosition = position;
            go.transform.localRotation = Quaternion.Euler(euler);
            go.transform.localScale = scale;
            go.GetComponent<Renderer>().sharedMaterial = material;
            return go;
        }

        /// <summary>Material URP Lit de un color. Se registra en `owned` para destruirlo luego.</summary>
        public static Material Mat(Color color, List<Material> owned)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var material = new Material(shader) { color = color };
            owned?.Add(material);
            return material;
        }

        /// <summary>Destroy en Play, DestroyImmediate en el Editor (capturas fuera de Play).</summary>
        public static void SafeDestroy(Object obj)
        {
            if (obj == null)
            {
                return;
            }
            if (Application.isPlaying)
            {
                Object.Destroy(obj);
            }
            else
            {
                Object.DestroyImmediate(obj);
            }
        }
    }

    /// <summary>Barra 3D (fondo + relleno anclado a la izquierda).</summary>
    public sealed class Bar
    {
        private readonly Transform _fill;
        private readonly Renderer _fillRenderer;
        private readonly float _width;

        public Bar(GameObject parent, Vector3 position, float width, List<Material> owned)
        {
            _width = width;
            var root = new GameObject("Bar");
            root.transform.SetParent(parent.transform, false);
            root.transform.localPosition = position;
            CreatureVisuals.Part(PrimitiveType.Cube, root, Vector3.zero, new Vector3(width + 0.06f, 0.12f, 0.06f),
                                 Vector3.zero, CreatureVisuals.Mat(new Color(0.08f, 0.08f, 0.1f), owned));
            var fill = CreatureVisuals.Part(PrimitiveType.Cube, root, new Vector3(0f, 0f, -0.02f),
                                            new Vector3(width, 0.08f, 0.06f), Vector3.zero,
                                            CreatureVisuals.Mat(new Color(0.3f, 0.85f, 0.4f), owned));
            _fill = fill.transform;
            _fillRenderer = fill.GetComponent<Renderer>();
        }

        public void Set(float fraction)
        {
            fraction = Mathf.Clamp01(fraction);
            _fill.localScale = new Vector3(Mathf.Max(0.0001f, _width * fraction), 0.08f, 0.06f);
            _fill.localPosition = new Vector3(-_width * (1f - fraction) / 2f, 0f, -0.02f);
            _fillRenderer.sharedMaterial.color = fraction > 0.5f ? new Color(0.3f, 0.85f, 0.4f)
                                               : fraction > 0.25f ? new Color(0.95f, 0.75f, 0.2f)
                                               : new Color(0.9f, 0.25f, 0.2f);
            _fill.gameObject.SetActive(fraction > 0f);
        }
    }
}
