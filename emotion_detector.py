import base64
import json
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf

MODEL_PATH = Path("model_best.keras") if Path("model_best.keras").exists() else Path("model_best.keras")
LABELS_PATH = Path("emotion_labels.json")

if not MODEL_PATH.exists():
    raise FileNotFoundError(
        f"Model wajib tidak ditemukan: {MODEL_PATH.resolve()} "
        "(pastikan file model terbaru hasil training tersedia)"
    )

if not LABELS_PATH.exists():
    raise FileNotFoundError(
        f"Label map tidak ditemukan: {LABELS_PATH.resolve()}"
    )

model = tf.keras.models.load_model(MODEL_PATH)
with LABELS_PATH.open("r", encoding="utf-8") as f:
    class_names = json.load(f)

last_modified = MODEL_PATH.stat().st_mtime
print(
    f"[emotion_detector] Loaded model: {MODEL_PATH.resolve()} | "
    f"last_modified_ts={last_modified}"
)

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')


def _preprocess_frame(frame_bgr):
    """
    Preprocess adaptif mengikuti input model:
    - crop area tengah
    - resize ke 48x48
    - otomatis grayscale (1 channel) atau RGB (3 channel) sesuai model.input_shape
    """
    h, w = frame_bgr.shape[:2]
    side = min(h, w)
    cx, cy = w // 2, h // 2
    x1 = max(0, cx - side // 2)
    y1 = max(0, cy - side // 2)
    x2 = x1 + side
    y2 = y1 + side
    center_crop = frame_bgr[y1:y2, x1:x2]

    input_shape = getattr(model, "input_shape", None)
    channels = 1
    img_h, img_w = 48, 48
    if isinstance(input_shape, (list, tuple)) and len(input_shape) >= 4:
        shape = input_shape[0] if isinstance(input_shape[0], (list, tuple)) else input_shape
        if len(shape) >= 4:
            if shape[1] and shape[2]:
                img_h, img_w = int(shape[1]), int(shape[2])
            if shape[-1] in (1, 3):
                channels = shape[-1]

    resized = cv2.resize(center_crop, (img_w, img_h))

    if channels == 1:
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype("float32") / 255.0
        x = np.expand_dims(gray, axis=-1)   # (H, W, 1)
    else:
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype("float32")
        # MobileNetV2 expects [-1, 1] range
        x = (rgb / 127.5) - 1.0             # (H, W, 3)

    x = np.expand_dims(x, axis=0)  # (1, H, W, C)
    return x


def detect_emotion_from_base64(image_base64):
    """
    Terima gambar dalam format base64 dari webcam browser,
    lalu deteksi emosi dan kembalikan hasilnya.
    """
    try:
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]

        image_bytes = base64.b64decode(image_base64)
        np_array = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

        if frame is None:
            return None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(faces) == 0:
            return None

        x0, y0, fw, fh = faces[0]
        face_crop = frame[y0:y0+fh, x0:x0+fw]
        x = _preprocess_frame(face_crop)
        preds = model.predict(x, verbose=0)[0]

        # Hanya pakai 6 emosi (tanpa disgust).
        ACTIVE_EMOTIONS = {"angry", "fear", "happy", "neutral", "sad", "surprise"}
        emotions = {
            class_names[i]: float(preds[i])
            for i in range(len(class_names))
            if class_names[i] in ACTIVE_EMOTIONS
        }

        # Renormalisasi agar total tetap 1.0 setelah disgust dibuang.
        total = sum(emotions.values()) or 1.0
        emotions = {k: v / total for k, v in emotions.items()}

        dominant_idx = max(emotions, key=emotions.get)
        dominant     = dominant_idx
        confidence   = emotions[dominant]

        happy_score    = emotions.get("happy", 0.0)
        sad_score      = emotions.get("sad", 0.0)
        fear_score     = emotions.get("fear", 0.0)
        angry_score    = emotions.get("angry", 0.0)
        surprise_score = emotions.get("surprise", 0.0)
        neutral_score  = emotions.get("neutral", 0.0)

        # Bandingkan grup gabungan vs neutral agar perbandingan adil
        # (neutral = 1 kelas, Confused = sad+fear, Frustrated = angry+surprise).
        confused_max   = max(sad_score, fear_score)
        frustrated_max = max(angry_score, surprise_score)

        strong_happy   = happy_score >= 0.40
        near_tie_happy = (happy_score >= 0.25
                          and happy_score >= max(confused_max, frustrated_max, neutral_score) - 0.08)

        if strong_happy or near_tie_happy:
            dominant   = "happy"
            confidence = happy_score

        return {
            "emotions": emotions,
            "dominant": dominant,
            "confidence": confidence,
        }

    except Exception as e:
        print(f"Error detecting emotion: {e}")
        return None
