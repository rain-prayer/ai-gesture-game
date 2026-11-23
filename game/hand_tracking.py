import os
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "models", "hand_landmarker.task")

WRIST = 0
FINGERS = {
    "index": (8, 6),
    "middle": (12, 10),
    "ring": (16, 14),
    "pinky": (20, 18),
}
THUMB_TIP = 4
THUMB_IP = 3


def _pdist(ax, ay, bx, by):
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def finger_extended_count(landmarks, frame_w=None, frame_h=None):
    """Count how many of the 4 fingers (index/middle/ring/pinky) are extended."""
    if landmarks is None or len(landmarks) < 21:
        return 0

    def px(i):
        return landmarks[i].x * (frame_w or 1), landmarks[i].y * (frame_h or 1)

    wx, wy = px(WRIST)
    count = 0
    for _name, (tip, pip) in FINGERS.items():
        tx, ty = px(tip)
        px_, py_ = px(pip)
        if _pdist(tx, ty, wx, wy) > _pdist(px_, py_, wx, wy) * 1.0:
            count += 1
    return count


def classify_gesture(landmarks, frame_w=None, frame_h=None):
    """3+ extended -> 'open'; 0 extended -> 'fist'; else 'none'."""
    if landmarks is None or len(landmarks) < 21:
        return "none"
    count = finger_extended_count(landmarks, frame_w, frame_h)
    if count >= 3:
        return "open"
    if count <= 0:
        return "fist"
    return "none"


def is_hand_flat(landmarks, frame_w=None, frame_h=None):
    """True when the wrist -> middle-MCP vector is more horizontal than
    vertical, i.e. the open hand is held level/sideways rather than upright."""
    if landmarks is None or len(landmarks) < 10:
        return False
    wx = landmarks[WRIST].x * (frame_w or 1)
    wy = landmarks[WRIST].y * (frame_h or 1)
    mx = landmarks[9].x * (frame_w or 1)
    my = landmarks[9].y * (frame_h or 1)
    return abs(mx - wx) > abs(my - wy)


def hand_orientation(landmarks, frame_w=None, frame_h=None):
    """Return 'up' (fingertips above wrist), 'down' (fingertips below wrist),
    or 'level' (roughly horizontal), using wrist -> middle fingertip."""
    if landmarks is None or len(landmarks) < 13:
        return "level"
    wy = landmarks[WRIST].y * (frame_h or 1)
    ty = landmarks[12].y * (frame_h or 1)
    dy = ty - wy
    threshold = (frame_h or 1) * 0.08
    if dy < -threshold:
        return "up"
    if dy > threshold:
        return "down"
    return "level"


class HandTracker:
    def __init__(self, num_hands=2, min_confidence=0.45):
        base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=min_confidence,
            min_tracking_confidence=0.5,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)
        self._ts = 0

    def process(self, rgb_frame):
        self._ts += 33
        h, w = rgb_frame.shape[:2]
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = self.landmarker.detect_for_video(mp_image, self._ts)
        hands = []
        for lm in (result.hand_landmarks or []):
            hands.append({
                "landmarks": lm,
                "gesture": classify_gesture(lm, w, h),
                "flat": is_hand_flat(lm, w, h),
                "dir": hand_orientation(lm, w, h),
                "count": finger_extended_count(lm, w, h),
                "cy": sum(p.y for p in lm) / len(lm),
            })
        return hands

    def close(self):
        self.landmarker.close()
