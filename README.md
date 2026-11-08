# Card Wars — POC

Prueba de concepto de un juego de cartas de criaturas, **multijugador en red local**, con
**identificación de cartas físicas** por cámara (marcadores ArUco).

El objetivo no es el juego final, sino validar la arquitectura que heredará la versión en
**Unity + AR Foundation**: servidor autoritativo, protocolo de mensajes estable y visión
desacoplada del juego.

---

## Inicio rápido

```bash
cd card_ar_poc

# 1. Entorno (una vez)
python3 -m venv .venv                 # si falla: sudo apt install python3.12-venv
.venv/bin/pip install -r backend/requirements.txt

# 2. Cartas imprimibles (una vez)
.venv/bin/python -m vision.card_detector generate
#    -> printables/sheet_A4.png : imprimir al 100 % (sin "ajustar a página"), papel mate

# 3. Servidor
.venv/bin/python backend/app.py
#    Abre en los teléfonos:  https://192.168.x.x:5000   (navegador, Socket.IO)
#    Unity / nativo:         ws://192.168.x.x:5001/ws    (WebSocket puro)
```

En cada teléfono (misma wifi que el PC): abrir la URL, aceptar el aviso del certificado
autofirmado (*Avanzado → Continuar*), escribir un nombre. Con dos jugadores la partida empieza.

Opciones del servidor: `--port 5000`, `--native-port 5001` (`0` = desactivar),
`--no-https` (todo por HTTP en un solo puerto; sin cámara en vivo en el navegador),
`--grace 60` (segundos de gracia tras una desconexión).

**Cliente Unity:** ver [`unity_client/README.md`](unity_client/README.md).

> ¿El teléfono no carga? Misma wifi (no datos móviles), firewall (`sudo ufw allow 5000/tcp`),
> y algunas redes de invitados aíslan dispositivos: usa el móvil como punto de acceso.

---

## Reglas

1. Cada jugador empieza con **60 de vida** y una mano con **Dragón, Guerrero y Mago**.
2. En tu turno haces **una** acción:
   - **Sin criatura en mesa → jugar una carta** (tocándola o enseñándola a la cámara).
     Sale de tu mano, entra en mesa y **ataca de inmediato**.
   - **Con criatura en mesa → atacar** con ella.
3. El ataque golpea a la criatura rival; si la mata, **el daño sobrante pasa al jugador**.
   Sin criatura rival, el golpe va directo al jugador. Las criaturas destruidas van al descarte.
4. Pierdes si tu vida llega a 0, si empieza tu turno sin criatura ni cartas, o si te
   desconectas más de 60 s durante la partida.

| Carta    | Vida | Ataque | Marcador ArUco |
|----------|-----:|-------:|:--------------:|
| Dragón   | 100  | 30     | 0              |
| Guerrero | 120  | 20     | 1              |
| Mago     | 80   | 40     | 2              |

Las partidas **siempre terminan**: no hay curación y cada turno hace ≥ 20 de daño
(lo verifica un test con 200 partidas aleatorias).

### Equilibrio

Medido con `tools/balance_report.py` (usa las reglas reales de `backend/game`):

| Vida inicial | P1 gana (5000 partidas aleatorias) | Matriz 36 órdenes fijos | Partidas decididas por vida |
|---:|---:|---:|---:|
| 100 (antes) | 16 % | P1 6 – P2 30 | 0 % |
| 50 | 92 % | P1 33 – P2 3 | 75 % |
| **60 (actual)** | **48 %** | **P1 17 – P2 19** | **32 %** |
| 70 | 23 % | P1 8 – P2 28 | 6 % |

- **Causa del desequilibrio original:** con 100 de vida, el daño al jugador nunca decidía nada (todas las
  partidas acababan por "sin criaturas"). Era una guerra de desgaste entre criaturas, y quien juega una criatura
  frente a otra ya en mesa le pega primero: P2 lo conseguía en su primer turno; el primer golpe de P1 iba a la
  cara y no servía.
- **Se probaron** "primer turno sin ataque" (no cambia nada), "mareo de invocación" (P1 64 %) y
  "contraataque del defensor" (P1 70 %): o no corrigen o se pasan. Bajar la vida a 60 equilibra sin reglas
  nuevas y hace que el daño directo importe. Como los daños son múltiplos de 10, la vida solo tiene saltos de 10.
- **Decisiones con peso:** abrir con Guerrero es fuerte (~58–69 % de victorias), con Mago arriesgado
  (~36–47 %); ninguna apertura gana siempre.
- **Límite conocido:** con información completa y 3 cartas, el juego está "resuelto" (con juego perfecto gana P2).
  Para que deje de estarlo hace falta azar o información oculta (mazos barajados, robar cartas).
- `tests/test_balance.py` falla si un cambio de cartas o reglas rompe este equilibrio.

---

## Estructura

```
card_ar_poc/
├── data/cards.json            # catálogo: ÚNICA fuente de verdad (servidor, cliente, Unity)
├── backend/
│   ├── app.py                 # transporte: Flask + Flask-SocketIO, HTTPS, desconexiones
│   ├── protocol.py            # contrato de mensajes (sobre JSON versionado)
│   ├── game/                  # reglas — Python puro, sin red ni OpenCV
│   │   ├── cards.py           #   CardDefinition, CardCatalog, CardInstance
│   │   ├── player.py          #   Player (vida, mano, criatura, descarte)
│   │   └── game_manager.py    #   Game (turnos, combate, eventos), GameManager (salas)
│   └── requirements.txt
├── client/                    # web móvil (HTML/CSS/JS sin frameworks)
│   ├── index.html · app.js · style.css
│   └── vendor/socket.io.min.js  # incluido: funciona en la LAN sin internet
├── unity_client/              # cliente Unity mínimo (C#) + bots de prueba con dotnet
├── vision/card_detector.py    # imagen -> marker_ids; generador de cartas; prueba webcam
├── printables/                # (generado) cartas PNG para imprimir
├── tests/                     # unitarios, integración, visión, equilibrio y smoke test por red
└── tools/balance_report.py    # informe de equilibrio (matriz, minimax, Monte Carlo)
```

---

## Arquitectura

```
 Teléfono (web) ─┐                          ┌─ Unity (nativo)
                 │ Socket.IO  :5000 HTTPS   │ WebSocket puro  :5001 /ws
                 ▼                          ▼
        ┌─────────────── Servidor Python (PC en la LAN) ───────────────┐
        │ app.py      transporte: mismo protocolo v1 por ambos canales  │
        │   ├── game/            REGLAS (fuente de verdad)              │
        │   └── vision/          frame JPEG -> marker_id                │
        └───────────────────────────────────────────────────────────────┘
```

### Decisiones clave

| Decisión | Por qué |
|---|---|
| **Servidor autoritativo** | El cliente envía *intenciones* (`play_card`), el servidor valida y calcula. Sin trampas ni desincronización; Unity será otro cliente igual de "tonto". |
| **`game/` en Python puro** | Testeable sin red; independiente de Flask/OpenCV. |
| **Eventos + snapshot** | Cada cambio emite `events` (para animar) y el `state` completo (para dibujar sin errores y reconectar). |
| **`seq` monotónico, emitido bajo el lock de la partida** | Orden garantizado; el cliente descarta lo viejo. |
| **`action_id` + `expected_turn`** | Acciones idempotentes: un doble toque o un reintento no juega dos veces. |
| **`session_token` secreto emitido por el servidor** | Reconectar exige el token; el `player_id` es público. |
| **Vista por jugador (`view(viewer_id)`)** | Información oculta: no ves la mano del rival. |
| **Visión en el servidor** | Un navegador no ejecuta OpenCV de Python. El móvil envía frames de 640 px. En Unity la detección pasará al dispositivo. |
| **Detectar ≠ jugar** | `card_detected` propone; el jugador confirma `play_card`. Una carta que pasa por delante no se juega sola. |
| **Control de flujo de frames** | Máx. 1 frame en vuelo, ~3 fps, y solo cuando puedes jugar carta. Sin colas ni latencia acumulada. |
| **`async_mode="threading"`** (no eventlet) | Eventlet está en mantenimiento y da problemas en Python ≥ 3.12. `simple-websocket` da WebSocket real sin monkey-patching. |
| **HTTPS autofirmado persistente** | `getUserMedia` (cámara) solo funciona en HTTPS. Se regenera si cambia la IP. Respaldo sin HTTPS: botón *Foto* (`<input capture>`). |

---

## Protocolo (v1)

Un único canal (`"msg"` en Socket.IO; un frame de texto en `/ws`, WebSocket puro) y un sobre JSON.
Ambos transportes comparten sala: un jugador web puede jugar contra uno de Unity.

```json
{"v": 1, "type": "play_card", "action_id": "7f3c…",
 "payload": {"card_id": "dragon", "expected_turn": 3, "source": "camera"}}
```

| Dirección | `type` | `payload` |
|---|---|---|
| C → S | `join` | `{name, session_token?, game_id?}` |
| C → S | `play_card` | `{card_id, expected_turn, source: "ui"\|"camera", target_id?}` + `action_id` |
| C → S | `attack` | `{expected_turn, target_id?}` + `action_id` |
| C → S | `rematch` · `sync` | `{}` |
| C → S | `frame` | `{image: JPEG base64/data URL, frame_id}` |
| S → C | `welcome` | `{player_id, session_token, game_id, catalog, vision_available}` |
| S → C | `state_update` + `seq` | `{events: [{type, payload}], state}` — aplicar si `seq` > último |
| S → C | `state_sync` + `seq` | `{state}` — aplicar siempre |
| S → C | `card_detected` | `{frame_id, marker_ids, cards}` — se responde a **todo** frame |
| S → C | `error` + `action_id` | `{code, message}` — `code` estable (`not_your_turn`, `stale_action`…) |

Eventos de juego: `player_joined`, `game_started`, `card_played`, `creature_damaged`,
`creature_destroyed`, `player_damaged`, `turn_changed`, `player_eliminated`, `game_over`,
`player_disconnected`, `player_reconnected`, `player_left`, `rematch_requested`.

**Regla de oro:** no usar funciones específicas de Socket.IO (acks, rooms en cliente) en la
lógica, para que Unity pueda usar WebSocket puro.

---

## Visión: cómo se identifican las cartas

Cada carta lleva impreso un **marcador ArUco** (`DICT_4X4_50`). El servidor decodifica el
frame, OpenCV lee el `marker_id` y `data/cards.json` lo traduce a una carta.

- 4×4 bits: celdas grandes, robusto a distancia, desenfoque y ángulo.
- Imprimir el marcador ≥ 30 mm, con **margen blanco** alrededor, en papel **mate**. Enseñarlo a 20–40 cm.
- El marcador identifica el **tipo** de carta, no la copia. Para coleccionables o antitrampas
  haría falta un id único por copia (diccionario mayor o QR + tabla serie → dueño).
- Rendimiento medido: **~2 ms por frame** (decodificar + detectar a 640 px).

```bash
.venv/bin/python -m vision.card_detector webcam              # prueba en vivo ('q' = salir)
.venv/bin/python -m vision.card_detector image foto.jpg --out anotada.jpg
```

---

## Pruebas

```bash
.venv/bin/python -m unittest discover -s tests -v            # 45 tests
.venv/bin/python tools/balance_report.py                     # informe de equilibrio
.venv/bin/python tests/smoke_lan.py https://localhost:5000   # 2 clientes por red real
dotnet run --project unity_client/dotnet/CardWars.Bots -- ws://localhost:5001/ws   # cliente C#
```

| Archivo | Qué cubre |
|---|---|
| `test_game.py` | Reglas, turnos, `seq`, idempotencia, información oculta, revancha, abandono, terminación |
| `test_server.py` | Protocolo, difusión, errores con resync, reconexión con token, expiración por gracia |
| `test_vision.py` | Detección con perspectiva, rotación, ruido, blur y JPEG; falsos positivos; latencia; extremo a extremo |
| `test_ws_transport.py` | `/ws` real: JSON inválido, 2 nativos, partida mixta web + nativo, expiración |
| `test_balance.py` | Equilibrio: ventaja de asiento, matriz de órdenes, vida relevante, ninguna apertura dominante |
| `smoke_lan.py` | Dos clientes por WebSocket + HTTPS reales |
| `unity_client/dotnet/CardWars.Bots` | El código C# de Unity jugando partidas completas contra el servidor |

> `smoke_lan.py` deja dos jugadores en la sala "default"; se liberan solos a los 60 s.

---

## Limitaciones conocidas del POC

- Una sola sala (`default`), estado en memoria, un proceso. Reiniciar el servidor borra la partida.
- Servidor de desarrollo (Werkzeug). Al cerrar un WebSocket registra líneas `ERROR … Bad request syntax`
  / `SSL error`: ruido inofensivo.
- Dos pestañas del mismo navegador comparten sesión (`localStorage`): son el mismo jugador.
- Las cartas impresas no llevan tildes (fuentes de OpenCV).
- El servidor no puede verificar que la carta física existe: la defensa es validar contra la mano.
- El puerto nativo (5001) va sin cifrar: aceptable en una LAN de pruebas, no en internet.
- **Equilibrio:** ajustado (vida 60, ver *Reglas → Equilibrio*); con juego perfecto aún gana P2.

---

## Camino hacia Unity

Decidido: **servidor dedicado** (las reglas se quedan en Python; Unity es cliente).

| Paso | Qué cambia | Qué NO cambia |
|---|---|---|
| Cliente Unity | ✅ **Hecho** (`unity_client/`): protocolo v1 por WebSocket puro (`ClientWebSocket`) + Newtonsoft | Servidor, reglas, catálogo |
| Transporte | ✅ **Hecho**: endpoint `/ws` de WebSocket puro junto a Socket.IO, solo en `app.py` | `game/`, protocolo |
| Detección | **AR Foundation no lee ArUco**: usar *image tracking* con la ilustración de la carta (diseñar cartas con arte rico; el ArUco puede convivir en una esquina). El cliente envía `play_card` con `source: "camera"` directamente | Servidor (el frame→marker deja de usarse) |
| Modelos 3D | `model_key` del catálogo → Addressable/prefab; `MarkerDetection.corners` / pose de AR para anclarlo | Protocolo |
| Animaciones | Cada evento (`creature_damaged`, `creature_destroyed`…) dispara una animación | Servidor |
| Más jugadores | `max_players` + `target_id` (ya soportados por `Game`); UI de selección de objetivo | Protocolo |
| Persistencia / mazos | `session_token` → token de cuenta; `Player.hand` se llena desde el mazo guardado | Reglas de combate |
| Escala | Varias salas vía `GameManager`; si crece: Redis como message queue + sesiones pegadas | Reglas |
| Paridad de reglas | Si algún día se portan a C# (host en móvil): casos de prueba JSON compartidos | — |
