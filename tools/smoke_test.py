"""无摄像头自检（smoke test）。

验证三件事：
1. 仓库里的模型 / 贴图 / 音效资源是否齐全；
2. 手势分类规则（伸直手指计数 → open / fist / none）是否正确；
3. 游戏主循环能否在无窗口（SDL dummy）模式下跑满指定帧数。

用法：
    python tools/smoke_test.py
退出码 0 = 全部通过，1 = 有检查失败。
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_DIR = os.path.join(ROOT, "game")

failures = []


def check(name, fn):
    try:
        detail = fn()
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    except Exception as exc:  # noqa: BLE001
        failures.append(name)
        print(f"[FAIL] {name} — {exc}")


class _Landmark:
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x = x
        self.y = y


def _make_hand(extended_fingers):
    """构造 21 个关键点：伸直的指尖离手腕更远，握住的指尖离手腕更近。"""
    wrist_y = 0.9
    pip_y = 0.7
    tip_far, tip_near = 0.4, 0.85
    tips = {8: 0, 12: 1, 16: 2, 20: 3}
    pips = {6: 0, 10: 1, 14: 2, 18: 3}
    landmarks = [_Landmark(0.5, wrist_y) for _ in range(21)]
    for idx, finger in tips.items():
        landmarks[idx] = _Landmark(0.5, tip_far if finger in extended_fingers else tip_near)
    for idx in pips:
        landmarks[idx] = _Landmark(0.5, pip_y)
    return landmarks


def test_resources():
    required = [
        os.path.join(GAME_DIR, "main.py"),
        os.path.join(GAME_DIR, "hand_tracking.py"),
        os.path.join(GAME_DIR, "models", "hand_landmarker.task"),
        os.path.join(GAME_DIR, "sounds", "jump.wav"),
        os.path.join(GAME_DIR, "sounds", "bgm.wav"),
        os.path.join(GAME_DIR, "assets", "green.png"),
    ]
    missing = [p for p in required if not os.path.exists(p)]
    if missing:
        raise AssertionError("缺少文件: " + ", ".join(os.path.relpath(p, ROOT) for p in missing))
    return f"{len(required)} 个关键文件齐全"


def test_gesture_classifier():
    sys.path.insert(0, GAME_DIR)
    from hand_tracking import classify_gesture, finger_extended_count

    cases = [
        ({0, 1, 2, 3}, 4, "open"),
        (set(), 0, "fist"),
        ({0, 1}, 2, "none"),
    ]
    for fingers, expected_count, expected_gesture in cases:
        hand = _make_hand(fingers)
        count = finger_extended_count(hand)
        gesture = classify_gesture(hand)
        assert count == expected_count, f"伸直数应为 {expected_count}，实际 {count}"
        assert gesture == expected_gesture, f"手势应为 {expected_gesture}，实际 {gesture}"
    return "open / fist / none 三档判定正确"


def test_game_loop():
    env = dict(os.environ)
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    proc = subprocess.run(
        [sys.executable, "main.py", "--headless-frames", "300"],
        cwd=GAME_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"主循环退出码 {proc.returncode}\n{output[-800:]}"
    assert "HEADLESS_DONE" in output, f"未看到主循环完成标记\n{output[-800:]}"
    line = next((ln for ln in output.splitlines() if "HEADLESS_DONE" in ln), "")
    return line.strip()


def main():
    check("资源完整性", test_resources)
    check("手势分类规则", test_gesture_classifier)
    check("游戏主循环（300 帧）", test_game_loop)
    print()
    if failures:
        print(f"结果：{len(failures)} 项失败")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
