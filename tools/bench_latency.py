"""实测手势检测耗时：摄像头取帧 → MediaPipe 推理，逐帧计时。

用法（需要摄像头）：
    python tools/bench_latency.py
"""

import os
import sys
import time

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "game"))

from hand_tracking import HandTracker  # noqa: E402


def bench(res, frames=40):
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else 0
    cap = cv2.VideoCapture(0, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, res[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])
    tracker = HandTracker(num_hands=1)
    # 预热 5 帧，排除首次推理的初始化开销
    for _ in range(5):
        ok, frame = cap.read()
        if not ok:
            tracker.close()
            cap.release()
            return None
        tracker.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    times = []
    for _ in range(frames):
        ok, frame = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        t0 = time.perf_counter()
        tracker.process(rgb)
        times.append((time.perf_counter() - t0) * 1000)
    tracker.close()
    cap.release()
    if not times:
        return None
    return sum(times) / len(times), max(times)


def main():
    for res in [(640, 480), (480, 360), (320, 240)]:
        r = bench(res)
        if r is None:
            print(f"{res}: 未取得摄像头画面")
            continue
        avg, mx = r
        print(
            f"res={res}  avg_detect={avg:.1f} ms  max={mx:.1f} ms  "
            f"({1000 / avg:.1f} fps 推理能力)  30fps 帧预算=33ms"
        )


if __name__ == "__main__":
    main()
