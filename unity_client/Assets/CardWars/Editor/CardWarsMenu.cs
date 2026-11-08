using CardWars.Presentation;
using CardWars.UnityClient;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace CardWars.EditorTools
{
    /// <summary>
    /// Comandos del Editor para montar la escena de prueba. Está en una carpeta
    /// Editor/, así que no entra en las builds del juego.
    ///
    /// El mismo comando aparece en tres sitios (rutas solo ASCII):
    ///   - Barra de menús:  CardWars > Add Client To Scene
    ///   - Barra de menús:  Tools > CardWars > Add Client To Scene
    ///   - Jerarquía (clic derecho) y GameObject:  CardWars Client
    ///
    /// Si la escena ya tiene un cliente, le añade los componentes que falten
    /// (útil al actualizar: p. ej. la mesa 3D BoardView).
    /// </summary>
    public static class CardWarsMenu
    {
        private const string Label = "Add Client To Scene";

        [MenuItem("CardWars/" + Label)]
        private static void FromCardWarsMenu() => AddClientToScene();

        [MenuItem("Tools/CardWars/" + Label)]
        private static void FromToolsMenu() => AddClientToScene();

        // Prioridad 10 => también aparece en el clic derecho de la Jerarquía.
        [MenuItem("GameObject/CardWars Client", false, 10)]
        private static void FromGameObjectMenu() => AddClientToScene();

        public static void AddClientToScene()
        {
            var existing = Object.FindAnyObjectByType<CardWarsClient>();
            GameObject go;
            if (existing != null)
            {
                go = existing.gameObject;
            }
            else
            {
                go = new GameObject("CardWars Client");
                Undo.RegisterCreatedObjectUndo(go, "Add CardWars Client");
                go.AddComponent<CardWarsClient>();
            }

            var added = AddIfMissing<SimpleGameUI>(go) | AddIfMissing<BoardView>(go);
            Selection.activeGameObject = go;
            EditorGUIUtility.PingObject(go);
            EditorSceneManager.MarkSceneDirty(go.scene);
            Debug.Log(existing == null || added
                ? "[CardWars] Cliente listo (UI + mesa 3D). Guarda la escena (Ctrl+S) y pulsa Play."
                : "[CardWars] La escena ya tenía el cliente completo: seleccionado.");
        }

        private static bool AddIfMissing<T>(GameObject go) where T : Component
        {
            if (go.GetComponent<T>() != null)
            {
                return false;
            }
            Undo.AddComponent<T>(go);
            return true;
        }
    }
}
