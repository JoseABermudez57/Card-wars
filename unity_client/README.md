# Cliente Unity

**Esta carpeta es el proyecto Unity** (Unity 6, URP): ábrela directamente con Unity Hub.

Cliente nativo de Card Wars que habla el **protocolo v1** con el mismo servidor Python
que los teléfonos con navegador. Puede jugar **contra** un jugador web en la misma sala.

Objetivo: validar que el protocolo funciona en C#/Unity antes de añadir AR, modelos 3D y UI real.

## Estructura

```
unity_client/                        <- proyecto Unity (Assets, Packages, ProjectSettings)
├── Assets/Scenes/SampleScene.unity  escena con el cliente montado
├── Assets/CardWars/                 todo el código y assets del juego
│   ├── Scripts/Core/                C# puro, SIN UnityEngine (probado con dotnet)
│   │   ├── Protocol.cs              DTOs y constantes del protocolo v1
│   │   ├── Json.cs                  Newtonsoft con snake_case automático
│   │   ├── Transport.cs             IGameTransport + WebSocketTransport (ClientWebSocket)
│   │   ├── GameClient.cs            join/reconexión, seq, acciones idempotentes, Poll()
│   │   └── EventDescriber.cs        eventos -> texto
│   ├── Scripts/Presentation/        mesa 3D: criaturas, tótems de vida, animaciones
│   │   ├── BoardView.cs             eventos -> línea de tiempo; reconcilia con el estado
│   │   ├── CreatureView.cs          criatura: modelo, barra de vida, golpe
│   │   ├── PlayerAvatarView.cs      tótem del jugador + anillo de turno
│   │   ├── CreatureVisuals.cs       model_key -> prefab o muñeco de primitivas
│   │   ├── CreaturePrefabRegistry.cs  ScriptableObject model_key -> modelo + clips
│   │   ├── CreatureAnimator.cs      reposo/ataque/golpe/muerte con Playables (Tick manual)
│   │   └── Timeline.cs              cola de animaciones avanzada con Tick(dt)
│   ├── Scripts/Unity/               capa fina de Unity
│   │   ├── CardWarsClient.cs        MonoBehaviour: Poll en Update, PlayerPrefs, reintentos
│   │   └── SimpleGameUI.cs          interfaz IMGUI (sin Canvas ni prefabs)
│   ├── Editor/CardWarsMenu.cs       menú CardWars → Add Client To Scene
│   ├── Editor/CardWarsModelSetup.cs menú CardWars → Setup Quaternius Models
│   ├── Models/Quaternius/           Dragon/Warrior/Wizard.fbx + texturas (CC0) + CREDITS.txt
│   └── link.xml                     evita que IL2CPP elimine los DTOs
└── dotnet/                          fuera de Assets: Unity lo ignora
    ├── CardWars.Core/               compila Core con las reglas de Unity (netstandard2.1, C# 9)
    └── CardWars.Bots/               bots que juegan partidas reales contra el servidor
```

## Decisiones

| Decisión | Por qué |
|---|---|
| **WebSocket puro** (`/ws`), no Socket.IO | No hay cliente Socket.IO oficial para C#. El protocolo v1 no usa nada propio de Socket.IO, así que basta un WebSocket. |
| **`ClientWebSocket`** de .NET | Viene con Unity (Android, iOS, escritorio; Mono e IL2CPP), sin paquetes de terceros. **No sirve en WebGL.** |
| **Puerto nativo 5001 sin HTTPS** | Una app nativa no necesita HTTPS para la cámara, y Unity rechaza certificados autofirmados. Los navegadores siguen en `https://…:5000`. |
| **Core sin UnityEngine** | Se compila y se prueba con `dotnet` (bots contra el servidor real). Es el mismo código que corre en Unity. |
| **`Poll()` en `Update`** | El transporte recibe en un hilo de fondo y solo encola. El estado y los eventos se procesan en el hilo principal, el único donde se puede tocar Unity. |
| **Newtonsoft + snake_case automático** | `JsonUtility` de Unity no soporta diccionarios ni payloads distintos por tipo de evento. |
| **IMGUI** para la UI | Cero configuración de escena. Es desechable: la UI real se suscribe a `CardWarsClient.StateChanged` igual. |

## Puesta en marcha (Unity 6000.6)

1. **Servidor** (desde `card_ar_poc/`): `.venv/bin/python backend/app.py`
   Imprime la URL para Unity: `ws://192.168.x.x:5001/ws`.
2. **Unity Hub → Add → Add project from disk** → elige la carpeta `card_ar_poc/unity_client`.
   La primera vez Unity regenera `Library/` (unos minutos). Newtonsoft ya está en `Packages/manifest.json`.
3. Abre `Assets/Scenes/SampleScene` (ya trae el cliente) y pulsa **Play** → **Conectar**.

### En otro proyecto Unity (reutilizar el cliente)
1. **Window → Package Manager → + → Add package by name…** → `com.unity.nuget.newtonsoft-json`
2. Copia `Assets/CardWars` **con sus `.meta`** a `Assets/` del otro proyecto.
3. En la escena: menú **CardWars → Add Client To Scene** (o clic derecho en la Jerarquía → **CardWars Client**) y guarda (Ctrl+S).
   Crea cliente + panel + mesa 3D. Si ya existía el cliente, añade solo lo que falte.
   (Equivale a *GameObject → Create Empty* + *Add Component* `CardWarsClient` y `SimpleGameUI`.)
4. **Play**, escribe la URL (en el mismo PC: `ws://localhost:5001/ws`) y pulsa **Conectar**.

Para tener rival, abre `https://IP:5000` en un teléfono o navegador: **web contra Unity** en la sala por defecto.

### En un teléfono Android
- *Player Settings → Other Settings → Internet Access* = **Require**.
- *Scripting Backend* IL2CPP: `link.xml` ya preserva los DTOs.
- Si la conexión `ws://` falla en el dispositivo, prueba *Allow downloads over HTTP* = **Always allowed**.
  Esto está **sin verificar en un dispositivo**.

## Mesa 3D (presentación)

`BoardView` dibuja la partida en 3D y anima los eventos del servidor:

| Evento | Animación |
|---|---|
| `card_played` | la criatura aparece en su casilla (crece con rebote) |
| `creature_damaged` | el atacante embiste; el objetivo destella en rojo, tiembla y baja su barra |
| `player_damaged` | el atacante embiste al tótem del jugador; baja su barra de vida |
| `creature_destroyed` | la criatura encoge y se hunde |
| `turn_changed` | el anillo dorado pasa a la casilla del jugador activo |
| `game_over` | cartel ¡Victoria! / Derrota y el tótem ganador salta |

Decisiones:
- **Los eventos se animan y el estado manda.** Cada lote de eventos se encola en una `Timeline`
  y al final se *reconcilia* con el `state` completo: si se pierde una animación, la mesa
  termina igual que la verdad del servidor.
- **`Tick(dt)` en vez de corrutinas.** Es determinista y se puede ejecutar fuera de Play.
  Así se verificó: una partida real capturada del servidor se reprodujo en Unity en modo batch
  y se renderizó fotograma a fotograma.
- **Modelos 3D reales con fallback.** Si existe `Resources/CreaturePrefabRegistry`, `BoardView`
  lo usa; las claves sin modelo usan muñecos de primitivas (el juego nunca se queda sin visual).
- **Cámara.** `configureCamera` coloca la Main Camera; `cameraShift` desplaza el encuadre
  para que el panel de la izquierda no tape la mesa.

## Modelos 3D (Quaternius, CC0)

| `model_key` | Modelo | Reposo | Ataque | Golpe | Muerte |
|---|---|---|---|---|---|
| `dragon` | `Dragon.fbx` | `Dragon_Flying` | `Dragon_Attack` | `Dragon_Hit` | `Dragon_Death` |
| `warrior` | `Warrior.fbx` | `Idle_Weapon` | `Sword_Attack` | `RecieveHit` | `Death` |
| `mage` | `Wizard.fbx` | `Idle_Weapon` | `Staff_Attack` | `RecieveHit` | `Death` |

Licencia **CC0 1.0** (dominio público), descargados de OpenGameArt; detalles en `Models/Quaternius/CREDITS.txt`.

**En un proyecto nuevo:** copia `Assets/CardWars` y ejecuta **CardWars → Setup Quaternius Models**. Genera
(y es repetible):
1. Avatar genérico ⇒ cada modelo tiene `Animator`.
2. Reposo en bucle.
3. Materiales URP propios en `Models/Quaternius/Materials` (texturas del pack; paleta roja para el dragón,
   cuyos colores del FBX llegan casi negros), remapeados en el importador.
4. `Resources/CreaturePrefabRegistry.asset` con modelo + clips por `model_key`.

Decisiones:
- **Playables en vez de AnimatorController**: cuatro clips por criatura no justifican una máquina de estados;
  el grafo avanza con `Tick(dt)` como la `Timeline` (determinista, verificable fuera de Play).
- **Normalización**: cada FBX trae su escala/origen; se escala a `height` (sin pasar de `maxWidth`),
  pies en el suelo, centrado. Ajustable por entrada en el registro, junto con `yawOffset`.
- **Materiales por instancia**: el destello de golpe no tiñe a otras criaturas ni modifica el asset.
- **Añadir una criatura nueva**: carta en `data/cards.json` con su `model_key` → entrada en el registro con
  su prefab y clips. Sin tocar código.

## Probar sin Unity

```bash
# terminal 1 (card_ar_poc/)
.venv/bin/python backend/app.py

# terminal 2
dotnet run --project unity_client/dotnet/CardWars.Bots -- ws://localhost:5001/ws
```

Escenarios, cada uno en su propia sala (no molesta a jugadores reales):
- partida completa con el registro de combate;
- 10 partidas aleatorias en las que ambos clientes terminan con el mismo `seq`, vidas y ganador;
- errores con código (`not_your_turn`);
- una acción duplicada no se aplica dos veces;
- reconexión con token al mismo puesto;
- revancha.

## Uso desde código (para la UI real o AR)

```csharp
var client = GetComponent<CardWarsClient>();
client.StateChanged += (state, events) =>
{
    foreach (var ev in events)
    {
        if (ev.Type == GameEventType.CreatureDamaged)
        {
            var e = ev.PayloadAs<CreatureDamagedEvent>();
            // buscar el modelo 3D con uid == e.TargetUid y reproducir la animación de golpe
        }
    }
    // y después dibujar `state`: siempre es la verdad completa
};

// Intenciones (el servidor valida):
await client.Client.PlayCardAsync("dragon", source: "camera");
await client.Client.AttackAsync();
```

## Siguientes pasos
- **AR Foundation image tracking**: reconocer la ilustración de la carta y llamar a
  `PlayCardAsync(cardId, "camera")`. El servidor no cambia.
- `model_key` del catálogo → prefab/Addressable de la criatura, anclado a la carta detectada.
- Animaciones disparadas por eventos (`card_played`, `creature_damaged`, `creature_destroyed`…).
