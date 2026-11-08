"""Pruebas del detector con imágenes sintéticas "realistas":
perspectiva, rotación, fondo con ruido, blur, 640 px y JPEG calidad 70
(lo mismo que envía el cliente web).

    .venv/bin/python -m unittest tests.test_vision -v
"""
import base64
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

try:
    import cv2
    import numpy as np

    from vision.card_detector import CardDetector, load_cards, render_card, render_sheet
except ImportError:
    cv2 = None


def photo_of(card_imgs, angle=15, tilt=0.15, blur=3, seed=0, width=640):
    """Coloca cartas en una "mesa" ruidosa con perspectiva y las comprime como el móvil."""
    rng = np.random.default_rng(seed)
    table = rng.integers(60, 200, (1080, 1920, 3), dtype=np.uint8)
    table = cv2.GaussianBlur(table, (21, 21), 0)
    n = len(card_imgs)
    for i, card in enumerate(card_imgs):
        h, w = card.shape[:2]
        scale = 0.45
        cw, ch = w * scale, h * scale
        cx, cy = 1920 * (i + 1) / (n + 1), 540
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        # rectángulo rotado + "inclinación" (el borde superior más estrecho = perspectiva)
        pts = np.float32([[-cw / 2 * (1 - tilt), -ch / 2], [cw / 2 * (1 - tilt), -ch / 2],
                          [cw / 2, ch / 2], [-cw / 2, ch / 2]])
        a = np.deg2rad(angle)
        rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]], np.float32)
        dst = (pts @ rot.T + [cx, cy]).astype(np.float32)
        m = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(card, m, (1920, 1080))
        mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (1920, 1080))
        table[mask > 0] = warped[mask > 0]
    if blur:
        table = cv2.GaussianBlur(table, (blur, blur), 0)
    small = cv2.resize(table, (width, round(1080 * width / 1920)), interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
    assert ok
    return jpeg.tobytes()


@unittest.skipIf(cv2 is None, "OpenCV no instalado")
class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = CardDetector()
        cls.cards = load_cards()
        cls.renders = {c["card_id"]: render_card(c) for c in cls.cards}

    def test_each_card_detected_in_realistic_photo(self):
        for card in self.cards:
            for angle in (0, 25, -40, 90, 180):
                with self.subTest(card=card["card_id"], angle=angle):
                    jpeg = photo_of([self.renders[card["card_id"]]], angle=angle)
                    self.assertEqual(self.detector.detect_jpeg(jpeg), [card["marker_id"]])

    def test_three_cards_in_one_frame(self):
        jpeg = photo_of(list(self.renders.values()), angle=-10)
        self.assertEqual(self.detector.detect_jpeg(jpeg), [0, 1, 2])

    def test_no_card_no_false_positive(self):
        for seed in range(5):
            rng = np.random.default_rng(seed)
            noise = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)
            ok, jpeg = cv2.imencode(".jpg", noise, [cv2.IMWRITE_JPEG_QUALITY, 70])
            self.assertEqual(self.detector.detect_jpeg(jpeg.tobytes()), [])

    def test_invalid_bytes_raise_value_error(self):
        with self.assertRaises(ValueError):
            self.detector.detect_jpeg(b"esto no es una imagen")

    def test_printable_sheet_contains_all_markers(self):
        sheet = render_sheet(self.cards)
        self.assertEqual(self.detector.detect_ids(sheet), [0, 1, 2])

    def test_latency_budget(self):
        jpeg = photo_of([self.renders["dragon"]])
        runs = 30
        t0 = time.perf_counter()
        for _ in range(runs):
            self.detector.detect_jpeg(jpeg)
        ms = (time.perf_counter() - t0) * 1000 / runs
        print(f"\n    decodificar + detectar 640px: {ms:.1f} ms/frame")
        self.assertLess(ms, 100)

    def test_server_end_to_end_with_real_detector(self):
        from app import create_app
        from protocol import PROTOCOL_VERSION
        app, socketio, _ = create_app(detector=self.detector)
        client = socketio.test_client(app)
        client.emit("msg", {"v": PROTOCOL_VERSION, "type": "join", "payload": {"name": "Ana"}})
        image = "data:image/jpeg;base64," + base64.b64encode(
            photo_of([self.renders["mage"]], angle=30)).decode()
        client.emit("msg", {"v": PROTOCOL_VERSION, "type": "frame",
                            "payload": {"image": image, "frame_id": 1}})
        msgs = [r["args"][0] for r in client.get_received() if r["name"] == "msg"]
        det = next(m for m in msgs if m["type"] == "card_detected")["payload"]
        self.assertEqual([c["card_id"] for c in det["cards"]], ["mage"])


if __name__ == "__main__":
    unittest.main()
