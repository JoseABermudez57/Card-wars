"""Identificación de cartas físicas mediante marcadores ArUco (OpenCV).

Responsabilidad única: imagen -> lista de marker_id. NO sabe de cartas ni de
partidas; la traducción marker_id -> carta la hace el catálogo (data/cards.json).
Así, cambiar ArUco por image tracking (AR Foundation) o QR no toca el juego.

Uso como herramienta (desde card_ar_poc/):

    .venv/bin/python -m vision.card_detector generate            # cartas imprimibles
    .venv/bin/python -m vision.card_detector webcam [--camera 0] # prueba en vivo
    .venv/bin/python -m vision.card_detector image foto.jpg      # prueba con una foto
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT_DIR / "data" / "cards.json"

# 4x4 bits, 50 ids: pocas celdas grandes => robusto a distancia, blur y ángulo,
# y con mucha distancia de Hamming entre códigos (casi imposible confundirlos).
DEFAULT_DICTIONARY = cv2.aruco.DICT_4X4_50


@dataclass(frozen=True)
class MarkerDetection:
    marker_id: int
    corners: np.ndarray   # (4, 2) en píxeles: base para posicionar un modelo 3D (pose)

    @property
    def center(self) -> tuple[float, float]:
        x, y = self.corners.mean(axis=0)
        return float(x), float(y)


class CardDetector:
    """Detector ArUco. Thread-safe: un ArucoDetector por hilo (el servidor
    procesa frames de varios jugadores en hilos distintos)."""

    def __init__(self, dictionary: int = DEFAULT_DICTIONARY) -> None:
        self.dictionary = cv2.aruco.getPredefinedDictionary(dictionary)
        self.params = cv2.aruco.DetectorParameters()
        self._local = threading.local()

    def _detector(self):
        det = getattr(self._local, "detector", None)
        if det is None:
            det = self._local.detector = cv2.aruco.ArucoDetector(self.dictionary, self.params)
        return det

    def detect(self, image: np.ndarray) -> list[MarkerDetection]:
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids, _rejected = self._detector().detectMarkers(gray)
        if ids is None:
            return []
        return [MarkerDetection(int(i), c.reshape(4, 2)) for i, c in zip(ids.ravel(), corners)]

    def detect_ids(self, image: np.ndarray) -> list[int]:
        return sorted({d.marker_id for d in self.detect(image)})

    def detect_jpeg(self, data: bytes) -> list[int]:
        """Interfaz que usa el servidor: bytes JPEG/PNG -> ids únicos ordenados."""
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("No se pudo decodificar la imagen")
        return self.detect_ids(image)


# --------------------------------------------------------------- impresión
DPI = 300
MM = DPI / 25.4
CARD_W, CARD_H = round(63 * MM), round(88 * MM)   # tamaño estándar de carta
MARKER_MM = 35                                     # >= 30 mm para detectar a ~1 m


def _ascii(text: str) -> str:
    """Las fuentes Hershey de OpenCV no tienen tildes: 'Dragón' -> 'Dragon'."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _put_centered(img, text, y, scale, thickness, color=(30, 30, 30)):
    font = cv2.FONT_HERSHEY_DUPLEX
    (w, _h), _ = cv2.getTextSize(text, font, scale, thickness)
    cv2.putText(img, text, ((img.shape[1] - w) // 2, y), font, scale, color, thickness, cv2.LINE_AA)


def render_card(card: dict, dictionary: int = DEFAULT_DICTIONARY) -> np.ndarray:
    """Carta imprimible 63x88 mm a 300 DPI con nombre, stats y marcador.
    Imprimir al 100 % (sin "ajustar a página")."""
    img = np.full((CARD_H, CARD_W, 3), 255, np.uint8)
    cv2.rectangle(img, (12, 12), (CARD_W - 13, CARD_H - 13), (40, 40, 40), 6)
    _put_centered(img, _ascii(card["name"]).upper(), 140, 2.0, 4)
    _put_centered(img, f"ATK {card['attack']}   HP {card['max_hp']}", 230, 1.3, 3, (60, 60, 160))

    side = round(MARKER_MM * MM)
    marker = cv2.aruco.generateImageMarker(
        cv2.aruco.getPredefinedDictionary(dictionary), card["marker_id"], side, borderBits=1)
    x0, y0 = (CARD_W - side) // 2, 300
    # Alrededor queda papel blanco (zona de silencio): el detector la necesita.
    img[y0:y0 + side, x0:x0 + side] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)

    _put_centered(img, f"marker {card['marker_id']}  |  {card['card_id']}", CARD_H - 60, 0.9, 2,
                  (120, 120, 120))
    return img


def render_sheet(cards: list[dict]) -> np.ndarray:
    """Hoja A4 a 300 DPI con las cartas en cuadrícula (3 por fila)."""
    sheet_w, sheet_h = round(210 * MM), round(297 * MM)
    sheet = np.full((sheet_h, sheet_w, 3), 255, np.uint8)
    gap = round(5 * MM)
    cols = 3
    x_start = (sheet_w - (cols * CARD_W + (cols - 1) * gap)) // 2
    for i, card in enumerate(cards):
        r, c = divmod(i, cols)
        x, y = x_start + c * (CARD_W + gap), round(15 * MM) + r * (CARD_H + gap)
        if y + CARD_H > sheet_h:
            raise ValueError("Demasiadas cartas para una hoja")
        sheet[y:y + CARD_H, x:x + CARD_W] = render_card(card)
    return sheet


def load_cards(path: Path = CATALOG_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cards"]


# ---------------------------------------------------------------- CLI
def cmd_generate(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cards = load_cards()
    for card in cards:
        path = out / f"card_{card['marker_id']}_{card['card_id']}.png"
        cv2.imwrite(str(path), render_card(card))
        print("  ", path)
    sheet = out / "sheet_A4.png"
    cv2.imwrite(str(sheet), render_sheet(cards))
    print("  ", sheet, "<- imprime esta al 100 % (A4, 300 DPI)")


def _annotate(frame, detections, names):
    if detections:
        cv2.aruco.drawDetectedMarkers(
            frame, [d.corners.reshape(1, 4, 2).astype(np.float32) for d in detections],
            np.array([[d.marker_id] for d in detections]))
    for d in detections:
        x, y = map(int, d.center)
        label = names.get(d.marker_id, f"desconocido ({d.marker_id})")
        cv2.putText(frame, label, (x - 60, y), cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, label, (x - 60, y), cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)


def _names() -> dict[int, str]:
    return {c["marker_id"]: _ascii(c["name"]) for c in load_cards()}


def cmd_image(args) -> None:
    detector, names = CardDetector(), _names()
    frame = cv2.imread(args.path)
    if frame is None:
        raise SystemExit(f"No se pudo leer {args.path}")
    t0 = time.perf_counter()
    detections = detector.detect(frame)
    ms = (time.perf_counter() - t0) * 1000
    for d in detections:
        print(f"marker {d.marker_id} -> {names.get(d.marker_id, '¿?')}  centro={d.center}")
    print(f"{len(detections)} marcador(es) en {ms:.1f} ms ({frame.shape[1]}x{frame.shape[0]})")
    if args.out:
        _annotate(frame, detections, names)
        cv2.imwrite(args.out, frame)
        print("Anotada en", args.out)


def cmd_webcam(args) -> None:
    detector, names = CardDetector(), _names()
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit(f"No se pudo abrir la cámara {args.camera}")
    print("Enseña una carta a la cámara. 'q' para salir.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t0 = time.perf_counter()
            detections = detector.detect(frame)
            ms = (time.perf_counter() - t0) * 1000
            _annotate(frame, detections, names)
            cv2.putText(frame, f"deteccion: {ms:.1f} ms", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
            cv2.imshow("Card detector (q = salir)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="Detector de cartas ArUco")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="genera cartas imprimibles")
    g.add_argument("--out", default=str(ROOT_DIR / "printables"))
    g.set_defaults(func=cmd_generate)
    i = sub.add_parser("image", help="detecta en una imagen")
    i.add_argument("path")
    i.add_argument("--out", help="guardar imagen anotada")
    i.set_defaults(func=cmd_image)
    w = sub.add_parser("webcam", help="detección en vivo con la webcam")
    w.add_argument("--camera", type=int, default=0)
    w.set_defaults(func=cmd_webcam)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
