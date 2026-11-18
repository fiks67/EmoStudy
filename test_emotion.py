import cv2
import numpy as np

from emotion_detector import model, class_names, _preprocess_frame, MODEL_PATH


def apply_postprocess(emotions, dominant, confidence):
    """
    Samakan aturan post-processing dengan runtime di emotion_detector.py
    agar hasil test konsisten dengan endpoint /api/detect-emotion.
    """
    happy_score = emotions.get("happy", 0.0)
    negative_scores = [
        emotions.get("sad", 0.0),
        emotions.get("disgust", 0.0),
        emotions.get("angry", 0.0),
        emotions.get("fear", 0.0),
    ]
    top_negative = max(negative_scores) if negative_scores else 0.0

    strong_happy = happy_score >= 0.40
    near_tie_happy = happy_score >= 0.28 and (top_negative - happy_score) <= 0.06

    if strong_happy or near_tie_happy:
        return "happy", float(happy_score)

    return dominant, confidence


def main():
    print(f"Menggunakan model: {MODEL_PATH.resolve()}")
    cap = cv2.VideoCapture(0)

    # Biarkan webcam warm up, skip beberapa frame awal
    for _ in range(30):
        cap.read()

    ret, frame = cap.read()

    if ret:
        cv2.imwrite("captured.jpg", frame)
        print("Frame disimpan ke captured.jpg")

        x = _preprocess_frame(frame)
        preds = model.predict(x, verbose=0)[0]

        emotions = {class_names[i]: float(preds[i]) for i in range(len(class_names))}
        dominant_idx = int(np.argmax(preds))
        dominant_raw = class_names[dominant_idx]
        confidence_raw = float(preds[dominant_idx])

        dominant_final, confidence_final = apply_postprocess(
            emotions, dominant_raw, confidence_raw
        )

        top3 = sorted(emotions.items(), key=lambda kv: kv[1], reverse=True)[:3]

        print(f"Dominant RAW   : {dominant_raw} ({confidence_raw:.4f})")
        print(f"Dominant FINAL : {dominant_final} ({confidence_final:.4f})")
        print("Top-3 skor emosi:")
        for label, score in top3:
            print(f"- {label}: {score:.4f}")
        print(f"Detail penuh: {emotions}")
    else:
        print("Gagal membuka webcam")

    cap.release()


if __name__ == "__main__":
    main()
