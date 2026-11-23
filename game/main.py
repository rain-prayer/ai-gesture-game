"""AI 手势跳跃（AI Gesture Jump）。

一款用摄像头手势控制的 2D 横版平台跳跃游戏：
- 识别层：MediaPipe HandLandmarker（21 个手部关键点，免训练）+ OpenCV 取帧；
- 逻辑层：手指伸直计数 + 去抖 / 边沿触发 / 迟滞 / 边界降级；
- 表现层：Pygame 渲染、物理碰撞、程序化音效、存档与商城系统。

运行：python game/main.py
自检：python game/main.py --headless-frames 300
"""

import os
import sys
import json
import threading
import random

import pygame

HEADLESS = "--headless-frames" in sys.argv
if HEADLESS:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"

from hand_tracking import HandTracker

WIDTH, HEIGHT = 640, 480
GROUND_Y = 400
FPS = 60

GRAVITY = 0.9
JUMP_V = -19
PLAYER_W, PLAYER_H = 36, 44
PLAYER_X = 120

OB_W, OB_H = 20, 60
OB_H_HALF = 30
HIT_W, HIT_H = 14, 52
BASE_SPEED = 4
BASE_INTERVAL = 115
MIN_INTERVAL = 70

WALL_W, WALL_H = 30, 185
GAP_BOTTOM = 40
PLAT_W, PLAT_H = 1600, 14     # 2.5-screen bridge, fixed length = 640*2.5; thinner bridge
PLAT_TOP_OFF = 160
BUMP_W, BUMP_H = 24, 30
CROUCH_H = 24

# Fixed level pattern (not random): 3 pillars, duck, pillar, duck, gap, platform, flag.
PATTERN = ["pillar", "pillar", "pillar", "duck", "pillar", "duck", "gap", "platform", "flag"]

# -------- 模式 / 难度配置 --------
DIFFS = {
    "easy":   {"speed": 3, "interval": 155, "lives": 6, "label": "简单"},
    "normal": {"speed": 4, "interval": 115, "lives": 5, "label": "标准"},
    "hard":   {"speed": 5, "interval": 85,  "lives": 3, "label": "困难"},
}
MODES = {
    "level":   {"label": "闯关"},
    "endless": {"label": "无尽"},
    "timed":   {"label": "限时"},
}
MODE_ORDER = ["level", "endless", "timed"]
DIFF_ORDER = ["easy", "normal", "hard"]
SKINS = {
    "green": {"label": "经典绿", "shell": (96, 160, 96), "shell2": (70, 125, 70), "head": (88, 145, 88), "price": 0, "shape": "turtle"},
    "neon":  {"label": "烈焰喵", "shell": (222, 92, 62), "shell2": (172, 62, 42), "head": (205, 115, 72), "price": 40, "shape": "cat"},
    "ice":   {"label": "冰晶龟", "shell": (92, 172, 222), "shell2": (62, 132, 182), "head": (112, 182, 222), "price": 40, "shape": "turtle"},
    "gold":  {"label": "黄金兔", "shell": (232, 192, 82), "shell2": (192, 152, 52), "head": (222, 202, 92), "price": 40, "shape": "rabbit"},
    "neo":   {"label": "霓虹喵", "shell": (162, 92, 222), "shell2": (122, 62, 172), "head": (182, 122, 222), "price": 40, "shape": "cat"},
}
SKIN_ORDER = ["green", "neon", "ice", "gold", "neo"]
SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "save.json")


def load_save():
    try:
        with open(SAVE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    slots = data.get("slots", {})
    if not slots:
        slots = {str(i): {"mode": "level", "diff": "normal", "best": 0} for i in range(1, 11)}
    active = str(data.get("active", 1))
    if active not in slots:
        active = "1"
    owned = [s for s in data.get("owned", ["green"]) if s in SKINS]
    if "green" not in owned:
        owned.insert(0, "green")
    skin = data.get("skin", "green")
    if skin not in SKINS:
        skin = "green"
    if skin not in owned:
        owned.append(skin)
    return {"slots": slots, "active": active,
            "points": int(data.get("points", 0)),
            "owned": owned, "skin": skin}


def _write_save(data):
    try:
        with open(SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def get_slot(slot):
    return load_save()["slots"].get(str(slot), {"mode": "level", "diff": "normal", "best": 0})


def save_to_slot(slot, mode, diff, best):
    data = load_save()
    data["slots"][str(slot)] = {"mode": mode, "diff": diff, "best": best}
    data["active"] = str(slot)
    _write_save(data)
    return best


def delete_slot(slot):
    data = load_save()
    data["slots"][str(slot)] = {"mode": "level", "diff": "normal", "best": 0}
    _write_save(data)


def next_empty_slot():
    data = load_save()
    for i in range(1, 11):
        s = data["slots"].get(str(i))
        if not s or s.get("best", 0) == 0:
            return str(i)
    return "10"


def add_points(n):
    data = load_save()
    data["points"] = int(data.get("points", 0)) + n
    _write_save(data)
    return data["points"]


def get_points():
    return load_save()["points"]


def own_skin(skin):
    data = load_save()
    if skin not in data["owned"]:
        data["owned"].append(skin)
        _write_save(data)


def set_skin(skin):
    data = load_save()
    data["skin"] = skin
    _write_save(data)


def slot_best(slot):
    return get_slot(slot)["best"]

# Robustness: a gesture must be stable this many frames before it counts.
DEBOUNCE_FRAMES = 4
# Single-open-hand crouch: the hand centre must be in the lower part of the frame.
CROUCH_Y = 0.52

SKY = (30, 34, 44)
HILL = (42, 52, 68)
HILL2 = (38, 46, 60)
GROUND = (60, 70, 90)
GROUND_DASH = (90, 100, 122)


def load_font(size):
    """加载支持中文的系统字体；找不到时回退到 pygame 默认字体。"""
    candidates = [
        # Windows
        r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                continue
    for name in ("microsoftyahei", "simhei", "pingfang", "notosanscjksc", "wenquanyimicrohei"):
        matched = pygame.font.match_font(name)
        if matched:
            try:
                return pygame.font.Font(matched, size)
            except Exception:
                continue
    return pygame.font.Font(None, size)


SPRITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_sprite_cache = {}


def get_sprite(name):
    """Load assets/<name>.png once; return None if missing so we fall back to drawing."""
    if name not in _sprite_cache:
        path = os.path.join(SPRITE_DIR, name + ".png")
        try:
            if os.path.exists(path):
                _sprite_cache[name] = pygame.image.load(path).convert_alpha()
            else:
                _sprite_cache[name] = None
        except Exception:
            _sprite_cache[name] = None
    return _sprite_cache[name]


def speed_for_score(score):
    return BASE_SPEED


def interval_for_score(score):
    return max(BASE_INTERVAL - score * 1.5, MIN_INTERVAL)


def _shell_pattern(surf, r, pat, dark, light):
    """Draw decorative shell patterns per skin (visual only, hitbox unchanged)."""
    if pat == "spots":
        for (px, py, rr) in [(2.2, 0.3, 4), (0.55, 0.55, 5), (0.75, 0.3, 3), (0.42, 0.8, 3)]:
            pygame.draw.circle(surf, dark, (r.x + r.w * px / 2.5, r.y + r.h * py), rr)
    elif pat == "flakes":
        for (px, py) in [(0.2, 0.3), (0.4, 0.62), (0.6, 0.35), (0.75, 0.66), (0.5, 0.8)]:
            pygame.draw.circle(surf, light, (r.x + r.w * px, r.y + r.h * py), 2)
    elif pat == "stars":
        for (px, py) in [(0.3, 0.32), (0.6, 0.55), (0.4, 0.75)]:
            pygame.draw.circle(surf, (255, 242, 175), (r.x + r.w * px, r.y + r.h * py), 3)
    elif pat == "lines":
        for py in (0.32, 0.52, 0.72):
            pygame.draw.line(surf, light, (r.x + 6, r.y + r.h * py), (r.right - 6, r.y + r.h * py), 2)


def draw_animal(surf, cx, fy, sk, crouch):
    """Draw the skin's animal model by its shape. Hitbox (rect) is unchanged."""
    shell, shell2, head = sk["shell"], sk["shell2"], sk["head"]
    shape = sk.get("shape", "turtle")
    light = tuple(min(255, c + 55) for c in shell)
    if crouch:
        body = pygame.Rect(0, 0, 52, 22); body.midbottom = (cx, fy)
        pygame.draw.ellipse(surf, shell, body)
        pygame.draw.ellipse(surf, light, (body.x + 8, body.y + 2, body.w - 16, 6))
        pygame.draw.circle(surf, head, (body.right - 3, body.centery), 8)
        pygame.draw.circle(surf, (20, 20, 20), (body.right - 6, body.centery - 3), 2)
        return
    if shape == "cat":
        body = pygame.Rect(0, 0, 40, 30); body.midbottom = (cx - 2, fy)
        pygame.draw.ellipse(surf, shell, body)
        pygame.draw.ellipse(surf, light, (body.x + 4, body.y + 4, body.w - 14, 6))
        pygame.draw.lines(surf, shell2, False,
                          [(body.x + 2, body.y + 14), (body.x - 6, body.y + 6), (body.x - 4, body.y - 6)], 4)
        pygame.draw.circle(surf, shell, (body.x - 4, body.y - 8), 4)
        for lx in (body.x + 8, body.right - 10):
            pygame.draw.circle(surf, shell2, (lx, body.bottom - 3), 5)
        hx, hy = body.right - 2, body.y - 2
        for ex in (hx - 2, hx - 12):
            pygame.draw.polygon(surf, head, [(ex - 5, hy - 8), (ex + 2, hy - 8), (ex + 1, hy + 6), (ex - 6, hy + 1)])
            pygame.draw.polygon(surf, (250, 220, 200), [(ex - 3, hy - 4), (ex + 1, hy - 4), (ex + 1, hy + 2), (ex - 4, hy - 1)])
        pygame.draw.circle(surf, head, (hx, hy), 15)
        pygame.draw.circle(surf, (20, 20, 20), (hx - 5, hy - 5), 3)
    elif shape == "rabbit":
        body = pygame.Rect(0, 0, 38, 32); body.midbottom = (cx, fy)
        pygame.draw.ellipse(surf, shell, body)
        pygame.draw.ellipse(surf, light, (body.x + 4, body.y + 4, body.w - 14, 6))
        pygame.draw.circle(surf, shell2, (body.x + 3, body.y + 12), 5)
        for lx in (body.x + 8, body.right - 9):
            pygame.draw.circle(surf, shell2, (lx, body.bottom - 3), 5)
        hx, hy = body.right - 4, body.y - 2
        for ex in (hx - 2, hx - 11):
            pygame.draw.ellipse(surf, head, (ex - 4, hy - 22, 8, 22))
            pygame.draw.ellipse(surf, (250, 220, 210), (ex - 3, hy - 20, 4, 14))
        pygame.draw.circle(surf, head, (hx, hy), 14)
        pygame.draw.circle(surf, (20, 20, 20), (hx - 5, hy - 5), 3)
    else:  # turtle
        shell_r = pygame.Rect(0, 0, 46, 36); shell_r.midbottom = (cx + 2, fy - 2)
        pygame.draw.circle(surf, shell2, (shell_r.x + 8, shell_r.bottom - 4), 5)
        pygame.draw.circle(surf, shell2, (shell_r.right - 8, shell_r.bottom - 4), 6)
        pygame.draw.circle(surf, shell2, (shell_r.x + 3, shell_r.bottom - 2), 4)
        pygame.draw.circle(surf, shell2, (shell_r.right - 3, shell_r.bottom - 2), 5)
        pygame.draw.ellipse(surf, shell, shell_r)
        pygame.draw.ellipse(surf, light, (shell_r.x + 7, shell_r.y + 4, shell_r.w - 22, 8))
        hd = pygame.Rect(0, 0, 24, 20); hd.midleft = (shell_r.right - 6, shell_r.centery + 2)
        pygame.draw.circle(surf, head, (hd.right - 2, hd.centery), 12)
        pygame.draw.circle(surf, (20, 20, 20), (hd.right - 6, hd.centery - 4), 2)
        pygame.draw.circle(surf, tuple(min(255, c + 40) for c in head), (hd.right - 9, hd.centery - 7), 3)


class Player:
    def __init__(self):
        self.rect = pygame.Rect(PLAYER_X, GROUND_Y - PLAYER_H, PLAYER_W, PLAYER_H)
        self.vy = 0
        self.on_ground = True
        self.double_used = False
        self.crouching = False
        self.skin = "green"

    def update(self, jump_requested, double_requested, crouch, ground_y):
        was_grounded = self.on_ground
        orig_bottom = self.rect.bottom
        self.crouching = bool(crouch and was_grounded)
        self.rect.height = CROUCH_H if self.crouching else PLAYER_H
        # Changing height alters the top, not the feet; keep the feet where they
        # were while grounded so the height change doesn't lift the player off
        # the ground (which caused a crouch<->stand flicker).
        if was_grounded:
            self.rect.bottom = orig_bottom

        prev_bottom = self.rect.bottom
        if jump_requested and was_grounded:
            self.vy = JUMP_V
            self.on_ground = False
        elif double_requested and not self.on_ground and not self.double_used:
            self.vy = JUMP_V * 0.9
            self.double_used = True
        self.vy += GRAVITY
        self.rect.y += int(self.vy)
        if self.rect.bottom >= ground_y and prev_bottom <= ground_y + 1:
            self.rect.bottom = ground_y
            self.vy = 0
            self.on_ground = True
            self.double_used = False
        else:
            self.on_ground = False

    def draw(self, surf):
        sprite = get_sprite(self.skin)
        if sprite is not None:
            if self.crouching:
                tw, th = self.rect.width + 20, CROUCH_H + 14
            else:
                tw, th = self.rect.width + 12, self.rect.height + 10
            img = pygame.transform.smoothscale(sprite, (int(tw), int(th)))
            surf.blit(img, (self.rect.centerx - int(tw) // 2, self.rect.bottom - int(th)))
            return
        sk = SKINS.get(self.skin, SKINS["green"])
        draw_animal(surf, self.rect.centerx, self.rect.bottom, sk, self.crouching)


class Obstacle:
    def __init__(self, x, speed, height=OB_H, hit_w=HIT_W, hit_h=None):
        self.x = x
        self.speed = speed
        self.body = pygame.Rect(x, GROUND_Y - height, OB_W, height)
        hh = hit_h if hit_h is not None else height
        self.hit = pygame.Rect(x + (OB_W - hit_w) // 2, GROUND_Y - hh, hit_w, hh)

    def update(self):
        self.x -= self.speed
        self.body.x = self.x
        self.hit.x = self.x + (OB_W - HIT_W) // 2

    @property
    def rect(self):
        return self.hit

    def draw(self, surf):
        pygame.draw.rect(surf, (210, 150, 80), self.body)
        # 渐变：左侧亮、右侧暗
        for k in range(OB_W):
            t = k / OB_W
            c = (int(210 + (170 - 210) * t), int(150 + (110 - 150) * t), int(80 + (60 - 80) * t))
            pygame.draw.line(surf, c, (self.body.x + k, self.body.y), (self.body.x + k, self.body.bottom))
        pygame.draw.rect(surf, (120, 78, 40), self.body, 2)   # 描边
        pygame.draw.rect(surf, (250, 230, 150), (self.body.x + 3, self.body.y, OB_W - 6, 6))
        # 底部装饰：小花 + 草叶
        _gx = self.body.x + OB_W - 4
        pygame.draw.line(surf, (95, 150, 80), (_gx, GROUND_Y), (_gx - 3, GROUND_Y - 14), 3)
        pygame.draw.line(surf, (95, 150, 80), (_gx - 1, GROUND_Y - 6), (_gx - 8, GROUND_Y - 12), 2)
        _fx, _fy = _gx - 3, GROUND_Y - 18
        for _a in range(5):
            import math as _math
            _ang = _a * 2 * _math.pi / 5
            pygame.draw.circle(surf, (235, 170, 200), (int(_fx + 4 * _math.cos(_ang)), int(_fy + 4 * _math.sin(_ang))), 3)
        pygame.draw.circle(surf, (250, 225, 120), (_fx, _fy), 3)


class DuckObstacle:
    def __init__(self, x, speed, top_y=None, height=WALL_H):
        self.x = x
        self.speed = speed
        self.height = height
        if top_y is None:
            top_y = GROUND_Y - GAP_BOTTOM - WALL_H
        self.rect = pygame.Rect(x, top_y, WALL_W, height)

    def update(self):
        self.x -= self.speed
        self.rect.x = self.x

    def draw(self, surf):
        pygame.draw.rect(surf, (90, 140, 200), self.rect)
        pygame.draw.rect(surf, (56, 92, 140), self.rect, 2)   # 描边
        for i in range(1, 4):
            y = self.rect.y + i * (self.height // 4)
            pygame.draw.rect(surf, (120, 160, 215), (self.rect.x + 3, y, WALL_W - 6, 4))
        # 绿色枝条爬墙（装饰，不改变碰撞）
        vx = self.rect.right - 6
        pygame.draw.lines(surf, (95, 160, 90), False,
                          [(vx, self.rect.bottom), (vx - 5, self.rect.bottom - 18), (vx + 2, self.rect.bottom - 36),
                           (vx - 3, self.rect.bottom - 54), (vx + 1, self.rect.centery)], 3)
        for _ly in (self.rect.bottom - 24, self.rect.bottom - 42):
            pygame.draw.circle(surf, (120, 190, 110), (vx + 4, _ly), 3)
            pygame.draw.circle(surf, (120, 190, 110), (vx - 8, _ly - 6), 3)


class PlatformBump:
    """An obstacle on top of the platform bridge: only hits a player ON the bridge."""

    def __init__(self, x, speed, top_y):
        self.x = x
        self.speed = speed
        self.rect = pygame.Rect(x, top_y - BUMP_H, BUMP_W, BUMP_H)

    def update(self):
        self.x -= self.speed
        self.rect.x = self.x

    def draw(self, surf):
        pygame.draw.rect(surf, (200, 80, 60), self.rect)


class TripleBump:
    """Three connected red blocks on the platform, near its end."""

    def __init__(self, x, speed, top_y):
        self.x = x
        self.speed = speed
        self.rect = pygame.Rect(x, top_y - BUMP_H, BUMP_W * 3, BUMP_H)

    def update(self):
        self.x -= self.speed
        self.rect.x = self.x

    def draw(self, surf):
        for i in range(3):
            pygame.draw.rect(surf, (200, 80, 60),
                             (self.rect.x + i * BUMP_W, self.rect.y, BUMP_W, self.rect.height))
        # thin darker separators: three blocks clearly visible yet connected (no gap)
        for i in range(1, 3):
            pygame.draw.rect(surf, (155, 58, 42),
                             (self.rect.x + i * BUMP_W - 1, self.rect.y, 2, self.rect.height))


class Platform:
    """A long one-way bridge you can ride; you fall when it ends."""

    def __init__(self, x, speed, top_y):
        self.x = x
        self.speed = speed
        self.top_y = top_y
        self.rect = pygame.Rect(x, top_y, PLAT_W, PLAT_H)

    def update(self):
        self.x -= self.speed
        self.rect.x = self.x

    def draw(self, surf):
        pygame.draw.rect(surf, (150, 120, 90), self.rect)
        pygame.draw.rect(surf, (100, 82, 62), (self.rect.x, self.rect.y + PLAT_H - 5, PLAT_W, 5))


class Flag:
    """Mario-style goal flag: flat base, thin silver pole, triangle flag on top.
    Touching any part wins; then the triangle slides down the pole (the pole
    stays) and off screen, ~1.5s, before the clear screen."""
    POLE_H = int(HEIGHT * 2 / 3)
    BASE_W, BASE_H = 70, 8
    POLE_W = 5
    FLAG_W, FLAG_H = 46, 28

    def __init__(self, x, speed):
        self.x = x
        self.speed = speed
        self.slide = 0.0
        self.rect = pygame.Rect(x, GROUND_Y - self.POLE_H, self.BASE_W, self.POLE_H + self.BASE_H)

    def update(self):
        # Only scroll while the flag is still standing; once it's won (slide > 0)
        # the pole and base stay put and just the triangle slides down.
        if self.slide <= 0:
            self.x -= self.speed
            self.rect.x = self.x
        if self.slide > 0:
            self.slide += 6

    def draw(self, surf):
        cx = self.x + self.BASE_W // 2
        top = GROUND_Y - self.POLE_H
        pygame.draw.rect(surf, (60, 50, 40), (self.x, GROUND_Y - self.BASE_H, self.BASE_W, self.BASE_H))
        pygame.draw.rect(surf, (225, 228, 245), (cx - self.POLE_W // 2, top, self.POLE_W, self.POLE_H))
        tri_top = top + self.slide
        pygame.draw.polygon(surf, (230, 70, 70), [
            (cx, tri_top), (cx, tri_top + self.FLAG_H),
            (cx - self.FLAG_W, tri_top + self.FLAG_H // 2),
        ])


class GestureFeeder(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.raw = "idle"
        self.stable = "idle"
        self.running = True
        self._candidate = "none"
        self._count = 0
        self.camera_ok = True   # False when the camera can't open / stops delivering frames

    def run(self):
        try:
            import cv2
            # Windows 下 DirectShow 打开摄像头更稳；其他平台用默认后端。
            backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else 0
            cap = cv2.VideoCapture(0, backend)
            if not cap.isOpened():
                self.camera_ok = False
                print("GestureFeeder: camera open failed", flush=True)
                return
            self.camera_ok = True
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            tracker = HandTracker(num_hands=2)
            read_fails = 0
            while self.running:
                ok, frame = cap.read()
                if not ok:
                    read_fails += 1
                    if read_fails > 60:      # ~1s of no frames: treat as camera lost
                        self.camera_ok = False
                    continue
                read_fails = 0
                self.camera_ok = True
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                hands = tracker.process(rgb)
                g = self._state_from(hands)
                self.raw = g
                if g == self._candidate:
                    self._count += 1
                    if self._count >= DEBOUNCE_FRAMES:
                        self.stable = g
                else:
                    self._candidate = g
                    self._count = 1
            tracker.close()
            cap.release()
        except Exception as e:  # noqa: BLE001
            self.camera_ok = False
            print(f"GestureFeeder error: {e}", flush=True)

    @staticmethod
    def _state_from(hands):
        """idle: fist / no hand. open: single open upright (jump).
        crouch: BOTH hands in fists. two_palms: both open (double jump).
        two_fingers: 2 fingers up (pause). one_finger: 1 finger up (resume)."""
        if len(hands) >= 2:
            opens = [h for h in hands if h["gesture"] == "open"]
            fists = [h for h in hands if h["gesture"] == "fist"]
            if len(opens) >= 2:
                return "two_palms"
            if len(fists) >= 2:
                return "crouch"
        if hands:
            h0 = hands[0]
            if h0["count"] == 2:
                return "two_fingers"
            if h0["count"] == 1:
                return "one_finger"
            if h0["gesture"] == "open":
                return "open"
        return "idle"

    def stop(self):
        self.running = False


def draw_background(surf, scroll):
    # 天空渐变（上深下略亮）
    top, bot = (24, 28, 38), (44, 52, 70)
    for yy in range(0, GROUND_Y):
        t = yy / max(1, GROUND_Y)
        col = (int(top[0] + (bot[0] - top[0]) * t),
               int(top[1] + (bot[1] - top[1]) * t),
               int(top[2] + (bot[2] - top[2]) * t))
        pygame.draw.line(surf, col, (0, yy), (WIDTH, yy))
    for i in range(-1, WIDTH // 120 + 2):
        bx = i * 120 - (int(scroll * 0.3) % 120)
        pygame.draw.polygon(surf, HILL, [(bx, GROUND_Y), (bx + 60, GROUND_Y - 70), (bx + 120, GROUND_Y)])
        pygame.draw.polygon(surf, HILL2, [(bx + 60, GROUND_Y), (bx + 110, GROUND_Y - 46), (bx + 160, GROUND_Y)])
    for i in range(-1, WIDTH // 180 + 2):
        cx = i * 180 - (int(scroll * 0.15) % 180)
        pygame.draw.ellipse(surf, (52, 60, 74), (cx, 60, 90, 26))
        pygame.draw.ellipse(surf, (52, 60, 74), (cx + 30, 48, 70, 22))
    pygame.draw.rect(surf, GROUND, (0, GROUND_Y, WIDTH, HEIGHT - GROUND_Y))
    for i in range(-1, WIDTH // 60 + 2):
        gx = i * 60 - (int(scroll) % 60)
        pygame.draw.rect(surf, GROUND_DASH, (gx, GROUND_Y + 40, 26, 6))


def spawn_particles(parts, x, y, color, n=8, spread=3, up=1):
    for _ in range(n):
        parts.append([x + random.uniform(-8, 8), y + random.uniform(-3, 3),
                      random.uniform(-spread, spread), random.uniform(-up - 1, 0),
                      random.randint(10, 22), color])


def update_particles(parts):
    for p in parts:
        p[0] += p[2]
        p[1] += p[3]
        p[3] += 0.25
        p[4] -= 1
    parts[:] = [p for p in parts if p[4] > 0]


def draw_particles(surf, parts):
    for p in parts:
        r = max(1, int(3 * p[4] / 22 + 1))
        pygame.draw.circle(surf, p[5], (int(p[0]), int(p[1])), r)


def run_game(max_frames=None):
    pygame.init()
    # 默认全屏（SCALED 自动把 640x480 逻辑画面缩放到屏幕）；失败回退窗口
    try:
        pygame.display.set_mode((WIDTH, HEIGHT), pygame.SCALED | pygame.FULLSCREEN)
        pygame.event.set_grab(True)
        _fullscreen_start = True
    except Exception:
        pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.event.set_grab(True)
        _fullscreen_start = False
    screen = pygame.display.get_surface()
    if not HEADLESS:
        pygame.event.set_grab(True)
    clock = pygame.time.Clock()
    font = load_font(32)
    big_font = load_font(58)
    hint_font = load_font(20)

    # ---- sound effects ----
    sfx = {}
    try:
        pygame.mixer.init()
        _sdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
        for _n in ("jump", "double_jump", "crouch", "pause", "resume", "win", "die", "hurt"):
            _p = os.path.join(_sdir, _n + ".wav")
            if os.path.exists(_p):
                sfx[_n] = pygame.mixer.Sound(_p)
                # crouch is a low bass "thud": keep it quieter than the rest
                sfx[_n].set_volume(0.3 if _n == "crouch" else 0.7)
    except Exception:
        sfx = {}

    def play_sound(name):
        if name in sfx:
            sfx[name].play()

    # ---- background music (gentle loop, kept quiet) ----
    try:
        _bgm_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds", "bgm.wav")
        if os.path.exists(_bgm_path):
            pygame.mixer.music.load(_bgm_path)
            pygame.mixer.music.set_volume(0.6)
            pygame.mixer.music.play(-1)      # loop forever
    except Exception:
        pass

    state = "play" if HEADLESS else "start"

    # -------- 存档 / 模式 / 难度 --------
    save = load_save()
    active_slot = save["active"]
    _slot = get_slot(active_slot)
    mode = _slot["mode"] if _slot["mode"] in MODES else "level"
    diff = _slot["diff"] if _slot["diff"] in DIFFS else "normal"
    dconf = DIFFS[diff]
    fullscreen = _fullscreen_start
    skin = load_save()["skin"]
    points = get_points()

    player = Player()
    player.skin = skin
    obstacles = []
    platforms = []
    particles = []
    scroll = 0.0
    since_spawn = 0
    score = 0
    best = _slot["best"]
    jump_armed = True
    double_armed = True
    paused = False
    pause_armed = True
    resume_armed = True
    crouching = False
    crouch_seen = 0
    stand_seen = 0
    crouch_armed = True
    platform_left = 2
    pattern_i = 0
    riding_platform = False
    flags = []
    level_done = False
    winning = False
    win_timer = 0
    lives = dconf["lives"]
    max_lives = dconf["lives"]
    hit_timer = 0        # brief invulnerable/pass-through window after a hit
    hit_flash = 0        # red flash frames after a hit
    timelimit = 60 * FPS if mode == "timed" else None
    timed_left = timelimit

    feeder = None
    if not HEADLESS:
        feeder = GestureFeeder()
        feeder.start()

    frames = 0
    running = True
    # 键盘回退（无摄像头 / 调试时用）：↑ 跳或二段跳，↓ 切换蹲，空格也能跳
    kb_double = False
    kb_crouch = False

    start_rect = pygame.Rect(WIDTH // 2 - 140, 300, 280, 44)
    restart_rect = pygame.Rect(90, 300, 200, 44)
    quit_rect = pygame.Rect(WIDTH - 300, 300, 200, 44)
    # -------- 菜单（多级）-------
    menu_screen = "main"   # main / save / diff / mode / shop
    selected_slot = None
    # 皮肤收藏（当前拥有的，用于商城显示）
    owned_set = set(load_save()["owned"])
    main_btns = {}
    _mb = [("save", "存档"), ("diff", "难度"), ("mode", "模式"), ("shop", "商城")]
    for i, (k, _l) in enumerate(_mb):
        main_btns[k] = pygame.Rect(WIDTH // 2 - 90, 114 + i * 58, 180, 50)
    start_btn_rect = pygame.Rect(WIDTH // 2 - 90, 346, 180, 52)
    # 存档子界面：10 个空位(2x5) + 存档/读取/删除/返回
    slot_rects10 = [pygame.Rect(60 + (i % 5) * 112, 110 + (i // 5) * 74, 100, 56) for i in range(10)]
    save_btn_rect = pygame.Rect(150, 300, 104, 46)
    load_btn_rect = pygame.Rect(266, 300, 104, 46)
    del_btn_rect = pygame.Rect(382, 300, 104, 46)
    back_rect = pygame.Rect(WIDTH // 2 - 50, 424, 100, 42)
    # 商城：5 个皮肤行(靠左) + 预览 + 购买键
    shop_btn_rects = {}
    for i, sk in enumerate(SKIN_ORDER):
        shop_btn_rects[sk] = pygame.Rect(24, 110 + i * 54, 300, 46)
    preview_rect = pygame.Rect(350, 110, 266, 260)
    buy_btn_rect = pygame.Rect(410, 340, 150, 52)
    preview_skin = None
    # 难度 / 模式 子界面按钮
    mode_btns = {}
    for i, m in enumerate(MODE_ORDER):
        mode_btns[m] = pygame.Rect(WIDTH // 2 - 90, 130 + i * 66, 180, 50)
    diff_btns = {}
    for i, dch in enumerate(DIFF_ORDER):
        diff_btns[dch] = pygame.Rect(WIDTH // 2 - 90, 130 + i * 66, 180, 50)

    def reset():
        nonlocal player, obstacles, platforms, scroll, since_spawn, score
        nonlocal jump_armed, double_armed, paused, pause_armed, resume_armed
        nonlocal crouching, crouch_seen, stand_seen, crouch_armed, platform_left
        nonlocal pattern_i, riding_platform
        nonlocal flags, level_done, winning, win_timer
        nonlocal lives, hit_timer, hit_flash, timed_left, max_lives, particles
        player = Player()
        player.skin = skin
        obstacles = []
        platforms = []
        particles = []
        flags = []
        scroll = 0.0
        since_spawn = 0
        score = 0
        jump_armed = True
        double_armed = True
        paused = False
        pause_armed = True
        resume_armed = True
        crouching = False
        crouch_seen = 0
        stand_seen = 0
        crouch_armed = True
        platform_left = 2
        pattern_i = 0
        riding_platform = False
        level_done = False
        winning = False
        win_timer = 0
        lives = dconf["lives"]
        hit_timer = 0
        hit_flash = 0
        timed_left = timelimit
        max_lives = dconf["lives"]

    def spawn_platform(spd):
        # Spawn at the screen edge so the bridge appears promptly.
        top = GROUND_Y - PLAT_TOP_OFF
        platforms.append(Platform(WIDTH, spd, top))
        # Red bumps: further from the left end, wide spacing, fewer of them.
        for bx in (WIDTH + 400, WIDTH + 900):
            obstacles.append(PlatformBump(bx, spd, top))
        # A triple-connected red obstacle just before the platform ends.
        obstacles.append(TripleBump(WIDTH + PLAT_W - 320, spd, top))
        for bx in (WIDTH + 170, WIDTH + 420):
            obstacles.append(Obstacle(bx, spd, OB_H_HALF, hit_w=HIT_W, hit_h=OB_H_HALF - 4))
        # A duck wall just below the platform: shorter so it stays under the platform (no crossing).
        plat_bottom = top + PLAT_H
        duck_h = (GROUND_Y - GAP_BOTTOM) - plat_bottom
        obstacles.append(DuckObstacle(WIDTH + 700, spd, top_y=plat_bottom, height=duck_h))

    def current_ground(prev_bottom, next_bottom):
        # Swept landing: land on a platform if the player's bottom crosses its
        # top this frame (prev_bottom above it, next_bottom at/below it). This
        # avoids tunneling on fast double-jumps.
        g = GROUND_Y
        if player.vy >= 0:
            for p in platforms:
                if p.rect.left <= player.rect.centerx <= p.rect.right:
                    if prev_bottom <= p.top_y + 1 and next_bottom >= p.top_y:
                        if p.top_y < g:
                            g = p.top_y
        return g

    while running:
        keys = pygame.key.get_pressed()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_r:
                    reset()
                    state = "play"
                elif ev.key in (pygame.K_SPACE, pygame.K_RETURN) and state == "start":
                    reset()
                    state = "play"
                elif ev.key in (pygame.K_SPACE, pygame.K_RETURN) and state in ("over", "win"):
                    reset()
                    state = "play"
                elif ev.key == pygame.K_DOWN and state == "play" and not paused:
                    kb_crouch = True
                elif ev.key == pygame.K_UP and state == "play" and not paused and not player.on_ground:
                    kb_double = True
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                mx, my = ev.pos
                if paused:
                    paused = False
                elif state == "start":
                    if menu_screen == "main":
                        if main_btns["save"].collidepoint(mx, my):
                            menu_screen = "save"
                        elif main_btns["diff"].collidepoint(mx, my):
                            menu_screen = "diff"
                        elif main_btns["mode"].collidepoint(mx, my):
                            menu_screen = "mode"
                        elif main_btns["shop"].collidepoint(mx, my):
                            menu_screen = "shop"
                        elif start_btn_rect.collidepoint(mx, my):
                            reset()
                            state = "play"
                    elif menu_screen == "save":
                        for i in range(10):
                            if slot_rects10[i].collidepoint(mx, my):
                                selected_slot = str(i + 1)
                        if save_btn_rect.collidepoint(mx, my):
                            tgt = selected_slot if selected_slot else next_empty_slot()
                            save_to_slot(tgt, mode, diff, best)
                            active_slot = tgt
                            selected_slot = tgt
                        elif load_btn_rect.collidepoint(mx, my) and selected_slot:
                            _s = get_slot(selected_slot)
                            mode = _s["mode"] if _s["mode"] in MODES else "level"
                            diff = _s["diff"] if _s["diff"] in DIFFS else "normal"
                            dconf = DIFFS[diff]
                            best = _s["best"]
                            active_slot = selected_slot
                            timelimit = 60 * FPS if mode == "timed" else None
                            menu_screen = "main"
                        elif del_btn_rect.collidepoint(mx, my) and selected_slot:
                            delete_slot(selected_slot)
                            selected_slot = None
                        elif back_rect.collidepoint(mx, my):
                            menu_screen = "main"
                    elif menu_screen == "shop":
                        pts = get_points()
                        for sk in SKIN_ORDER:
                            if shop_btn_rects[sk].collidepoint(mx, my):
                                preview_skin = sk     # 任何皮肤点击都出预览
                        if buy_btn_rect.collidepoint(mx, my) and preview_skin:
                            if preview_skin in owned_set:
                                set_skin(preview_skin)      # 已拥有→使用
                                skin = preview_skin
                                preview_skin = None
                            elif pts >= SKINS[preview_skin]["price"]:
                                own_skin(preview_skin)
                                add_points(-SKINS[preview_skin]["price"])
                                set_skin(preview_skin)
                                skin = preview_skin
                                owned_set.add(preview_skin)
                                preview_skin = None
                                points = get_points()   # 刷新本地积分
                        if back_rect.collidepoint(mx, my):
                            points = get_points()
                            skin = load_save()["skin"]
                            menu_screen = "main"
                    elif menu_screen == "diff":
                        for dch in DIFF_ORDER:
                            if diff_btns[dch].collidepoint(mx, my):
                                diff = dch
                                dconf = DIFFS[diff]
                                best = get_slot(active_slot)["best"]
                        if back_rect.collidepoint(mx, my):
                            menu_screen = "main"
                    elif menu_screen == "mode":
                        for m in MODE_ORDER:
                            if mode_btns[m].collidepoint(mx, my):
                                mode = m
                                timelimit = 60 * FPS if mode == "timed" else None
                                best = get_slot(active_slot)["best"]
                        if back_rect.collidepoint(mx, my):
                            menu_screen = "main"
                elif state in ("over", "win") and restart_rect.collidepoint(mx, my):
                    reset()
                    state = "play"
                elif state in ("over", "win") and quit_rect.collidepoint(mx, my):
                    state = "start"
                    menu_screen = "main"

        if keys[pygame.K_r] and state in ("over", "win"):
            reset()
            state = "play"
        if keys[pygame.K_ESCAPE]:
            running = False

        if state == "play":
            gesture = feeder.stable if feeder else "idle"
            if hit_timer > 0:
                hit_timer -= 1
            if hit_flash > 0:
                hit_flash -= 1
            update_particles(particles)

            if not paused:
                if gesture == "two_fingers" and pause_armed:
                    paused = True
                    pause_armed = False
                    play_sound("pause")
                elif gesture != "two_fingers":
                    pause_armed = True
            else:
                if gesture == "one_finger" and resume_armed:
                    paused = False
                    resume_armed = False
                    play_sound("resume")
                elif gesture != "one_finger":
                    resume_armed = True

            if not paused:
                if winning:
                    for f in flags:
                        f.update()
                    win_timer += 1
                    if win_timer > 90:
                        state = "win"
                        best = max(best, save_to_slot(active_slot, mode, diff, score))
                        points = add_points(score)
                else:
                    keyboard_jump = keys[pygame.K_SPACE] or keys[pygame.K_UP]
                    open_now = gesture == "open"
                    two_now = gesture == "two_palms"

                    if kb_crouch:
                        crouching = not crouching
                        kb_crouch = False
                        play_sound("crouch")

                    # Crouch toggles once per double-fist press: sensitive (2 frames),
                    # and only re-arms after an 8-frame release so flicker can't flip it.
                    if gesture == "crouch":
                        crouch_seen += 1
                        stand_seen = 0
                    else:
                        stand_seen += 1
                        crouch_seen = 0
                    if crouch_seen >= 2 and crouch_armed:
                        crouching = not crouching
                        crouch_seen = 0
                        crouch_armed = False
                        play_sound("crouch")
                    if stand_seen >= 8:
                        crouch_armed = True

                    jump_requested = keyboard_jump
                    double_requested = kb_double
                    kb_double = False
                    if open_now and jump_armed:
                        jump_requested = True
                        jump_armed = False
                    if not open_now:
                        jump_armed = True
                    if two_now and double_armed:
                        double_requested = True
                        double_armed = False
                    if not two_now:
                        double_armed = True

                    if jump_requested and player.on_ground:
                        play_sound("jump")
                        spawn_particles(particles, player.rect.centerx, player.rect.bottom, (200, 205, 220), n=7, spread=2.6, up=1)
                    elif double_requested and not player.on_ground and not player.double_used:
                        play_sound("double_jump")
                        spawn_particles(particles, player.rect.centerx, player.rect.bottom, (210, 190, 240), n=8, spread=3, up=1)

                    prev_bottom = player.rect.bottom
                    prev_top = player.rect.top
                    next_bottom = prev_bottom + int(player.vy + GRAVITY)
                    ground_y = current_ground(prev_bottom, next_bottom)
                    player.update(jump_requested, double_requested, crouching, ground_y)

                    # Solid platform: swept bump-head if the player rises through
                    # its bottom (no pass-through, no death). Landing is above.
                    if player.vy < 0:
                        for p in platforms:
                            if p.rect.left <= player.rect.centerx <= p.rect.right:
                                if prev_top >= p.rect.bottom - 1 and player.rect.top <= p.rect.bottom:
                                    player.vy = 0
                                    player.rect.top = p.rect.bottom

                    scroll += dconf["speed"]
                    since_spawn += 1
                    if not riding_platform and not level_done and since_spawn >= dconf["interval"]:
                        since_spawn = 0
                        spd = dconf["speed"]
                        if mode == "level":
                            kind = PATTERN[pattern_i % len(PATTERN)]
                            pattern_i += 1
                        else:
                            kind = random.choice(["pillar", "duck", "pillar", "duck", "pillar"])
                        if kind == "pillar":
                            obstacles.append(Obstacle(WIDTH + OB_W, spd))
                        elif kind == "duck":
                            obstacles.append(DuckObstacle(WIDTH + WALL_W, spd))
                        elif kind == "platform":
                            riding_platform = True
                            spawn_platform(spd)
                        elif kind == "flag":
                            flags.append(Flag(WIDTH, spd))
                            level_done = True

                    # 限时模式倒计时
                    if mode == "timed":
                        timed_left -= 1
                        if timed_left <= 0 and state == "play":
                            state = "win"
                            play_sound("win")
                            best = max(best, save_to_slot(active_slot, mode, diff, score))
                            points = add_points(score)

                    for ob in obstacles[:]:
                        ob.update()
                        if ob.rect.right < 0:
                            obstacles.remove(ob)
                            score += 1
                            if score > best:
                                best = score
                        elif player.rect.colliderect(ob.rect):
                            if hit_timer <= 0:
                                lives -= 1
                                hit_timer = 90      # ~1.5s pass-through so one obstacle can't drain all
                                hit_flash = 18      # red flash feedback
                                play_sound("hurt")
                                spawn_particles(particles, player.rect.centerx, player.rect.centery, (240, 92, 66), n=12, spread=4.5, up=2)
                                if lives <= 0:
                                    state = "over"
                                    play_sound("die")
                                    best = max(best, save_to_slot(active_slot, mode, diff, score))
                                    points = add_points(score)
                                    break
                            # else: brief invulnerable window, just pass through this obstacle
                    for p in platforms[:]:
                        p.update()
                        if p.rect.right < 0:
                            platforms.remove(p)
                            if not platforms:
                                riding_platform = False
                    for f in flags[:]:
                        f.update()
                        if player.rect.colliderect(f.rect):
                            winning = True
                            win_timer = 0
                            f.slide = 1
                            play_sound("win")

        # ---- render ----
        if not HEADLESS:
            draw_background(screen, int(scroll))

            if state == "start":
                screen.blit(big_font.render("AI 手势跳跃", True, (240, 240, 240)),
                            (WIDTH // 2 - 130, 26))
                # 当前信息：分几行放左边
                _inf = [(f"模式：{MODES[mode]['label']}", (120, 195, 130)),
                        (f"难度：{DIFFS[diff]['label']}", (150, 210, 235)),
                        (f"最佳：{best}", (240, 200, 120)),
                        (f"积分：{points}", (240, 200, 120))]
                for li, (txt, col) in enumerate(_inf):
                    screen.blit(hint_font.render(txt, True, col), (14, 84 + li * 22))

                if menu_screen == "main":
                    cols = {"save": (150, 120, 200), "diff": (120, 195, 130),
                            "mode": (90, 150, 200), "shop": (205, 150, 80)}
                    labels = {"save": "存档", "diff": "难度", "mode": "模式", "shop": "商城"}
                    for k, r in main_btns.items():
                        c = cols[k]
                        pygame.draw.rect(screen, c, r, border_radius=12)
                        pygame.draw.rect(screen, tuple(min(255, x + 40) for x in c), r, 2, border_radius=12)
                        t = font.render(labels[k], True, (240, 245, 250))
                        screen.blit(t, (r.x + (r.w - t.get_width()) // 2, r.y + (r.h - t.get_height()) // 2 + 2))
                    pygame.draw.rect(screen, (90, 150, 200), start_btn_rect, border_radius=12)
                    pygame.draw.rect(screen, (150, 210, 235), start_btn_rect, 2, border_radius=12)
                    t = font.render("开始游戏", True, (240, 245, 250))
                    screen.blit(t, (start_btn_rect.x + (start_btn_rect.w - t.get_width()) // 2, start_btn_rect.y + 8))

                elif menu_screen == "save":
                    for i in range(10):
                        r = slot_rects10[i]
                        s = get_slot(str(i + 1))
                        sel = (selected_slot == str(i + 1))
                        used = (s.get("best", 0) > 0 or s["mode"] != "level" or s["diff"] != "normal")
                        pygame.draw.rect(screen, (150, 120, 200) if sel else (46, 56, 74), r, border_radius=8)
                        pygame.draw.rect(screen, (200, 170, 235) if sel else (72, 88, 110), r, 2, border_radius=8)
                        t = font.render(str(i + 1), True, (238, 243, 248))
                        screen.blit(t, (r.x + 8, r.y + 4))
                        if used:
                            it = hint_font.render(f"{MODES[s['mode']]['label']}·{DIFFS[s['diff']]['label']}", True, (190, 205, 225))
                            screen.blit(it, (r.x + 4, r.y + 26))
                            bt = hint_font.render(f"{s['best']}分", True, (240, 200, 120))
                            screen.blit(bt, (r.x + 4, r.y + 42))
                    for rect, label, col in [(save_btn_rect, "存档", (120, 195, 130)),
                                             (load_btn_rect, "读取", (90, 150, 200)),
                                             (del_btn_rect, "删除", (205, 90, 80)),
                                             (back_rect, "返回", (120, 120, 130))]:
                        pygame.draw.rect(screen, col, rect, border_radius=8)
                        pygame.draw.rect(screen, tuple(min(255, x + 40) for x in col), rect, 2, border_radius=8)
                        t = font.render(label, True, (240, 245, 250))
                        screen.blit(t, (rect.x + (rect.w - t.get_width()) // 2, rect.y + (rect.h - t.get_height()) // 2 + 2))

                elif menu_screen == "shop":
                    pts = get_points()
                    screen.blit(font.render(f"积分 {pts}", True, (240, 200, 120)), (24, 40))
                    for sk in SKIN_ORDER:
                        r = shop_btn_rects[sk]
                        conf = SKINS[sk]
                        owned = sk in owned_set
                        selected = (skin == sk)
                        pygame.draw.rect(screen, (90, 150, 200) if selected else (46, 56, 74), r, border_radius=10)
                        pygame.draw.rect(screen, (150, 210, 235) if selected else (72, 88, 110), r, 2, border_radius=10)
                        pygame.draw.ellipse(screen, conf["shell"], (r.x + 10, r.y + 12, 24, 24))
                        pygame.draw.ellipse(screen, conf["shell2"], (r.x + 14, r.y + 16, 16, 16))
                        t = font.render(conf["label"], True, (238, 243, 248))
                        screen.blit(t, (r.x + 44, r.y + (r.h - t.get_height()) // 2))
                        if owned:
                            st = hint_font.render("已拥有" if not selected else "使用中", True, (150, 230, 170))
                        else:
                            st = hint_font.render(f"{conf['price']} 积分", True, (240, 200, 120))
                        screen.blit(st, (r.x + 210, r.y + (r.h - st.get_height()) // 2))
                    # 右侧预览 + 购买键（选中的未拥有皮肤）
                    if preview_skin:
                        conf = SKINS[preview_skin]
                        pygame.draw.rect(screen, (40, 50, 66), preview_rect, border_radius=14)
                        pygame.draw.rect(screen, (90, 110, 135), preview_rect, 2, border_radius=14)
                        pvx, pvy = preview_rect.centerx, preview_rect.bottom - 20
                        psprite = get_sprite(preview_skin)
                        if psprite is not None:
                            img = pygame.transform.smoothscale(psprite, (92, 86))
                            screen.blit(img, (pvx - 46, pvy - 86))
                        else:
                            draw_animal(screen, pvx, pvy, conf, False)
                        _t = font.render(conf["label"], True, (238, 243, 248))
                        screen.blit(_t, (preview_rect.centerx - _t.get_width() // 2, preview_rect.y + 14))
                        owned = preview_skin in owned_set
                        cur_using = (skin == preview_skin)
                        if owned:
                            can = not cur_using
                            bc = (120, 195, 130) if can else (120, 120, 130)
                            label = "使用" if can else "使用中"
                        else:
                            can = pts >= conf["price"]
                            bc = (120, 195, 130) if can else (100, 100, 100)
                            label = "购买" if can else "积分不足"
                        pygame.draw.rect(screen, bc, buy_btn_rect, border_radius=10)
                        pygame.draw.rect(screen, tuple(min(255, x + 30) for x in bc), buy_btn_rect, 2, border_radius=10)
                        bt = font.render(label, True, (240, 245, 250))
                        screen.blit(bt, (buy_btn_rect.x + (buy_btn_rect.w - bt.get_width()) // 2,
                                        buy_btn_rect.y + (buy_btn_rect.h - bt.get_height()) // 2 + 2))
                    pygame.draw.rect(screen, (120, 120, 130), back_rect, border_radius=8)
                    pygame.draw.rect(screen, (150, 150, 165), back_rect, 2, border_radius=8)
                    t = font.render("返回", True, (240, 245, 250))
                    screen.blit(t, (back_rect.x + (back_rect.w - t.get_width()) // 2, back_rect.y + 8))

                elif menu_screen in ("mode", "diff"):
                    title = "选择模式" if menu_screen == "mode" else "选择难度"
                    screen.blit(font.render(title, True, (200, 210, 230)), (WIDTH // 2 - 70, 66))
                    order = MODE_ORDER if menu_screen == "mode" else DIFF_ORDER
                    btns = mode_btns if menu_screen == "mode" else diff_btns
                    conf = MODES if menu_screen == "mode" else DIFFS
                    cur = mode if menu_screen == "mode" else diff
                    for key in order:
                        r = btns[key]
                        sel = (key == cur)
                        pygame.draw.rect(screen, (120, 195, 130) if sel else (46, 56, 74), r, border_radius=12)
                        pygame.draw.rect(screen, (165, 225, 175) if sel else (72, 88, 110), r, 2, border_radius=12)
                        t = font.render(conf[key]["label"], True, (238, 243, 248))
                        screen.blit(t, (r.x + (r.w - t.get_width()) // 2, r.y + (r.h - t.get_height()) // 2 + 2))
                    pygame.draw.rect(screen, (120, 120, 130), back_rect, border_radius=8)
                    pygame.draw.rect(screen, (150, 150, 165), back_rect, 2, border_radius=8)
                    t = font.render("返回", True, (240, 245, 250))
                    screen.blit(t, (back_rect.x + (back_rect.w - t.get_width()) // 2, back_rect.y + 8))

                if feeder is not None and not feeder.camera_ok:
                    warn = hint_font.render("⚠ 未检测到摄像头画面，请检查摄像头", True, (255, 110, 90))
                    wx = (WIDTH - warn.get_width()) // 2
                    bar = pygame.Surface((warn.get_width() + 20, 28), pygame.SRCALPHA)
                    bar.fill((40, 20, 20, 190))
                    screen.blit(bar, (wx - 10, HEIGHT - 46))
                    screen.blit(warn, (wx, HEIGHT - 42))
            else:
                for ob in obstacles:
                    ob.draw(screen)
                for p in platforms:
                    p.draw(screen)
                for f in flags:
                    f.draw(screen)
                player.draw(screen)
                draw_particles(screen, particles)

                if state == "over":
                    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                    overlay.fill((0, 0, 0, 130))
                    screen.blit(overlay, (0, 0))
                    screen.blit(big_font.render("游戏结束", True, (240, 120, 120)),
                                (WIDTH // 2 - 120, 150))
                    screen.blit(font.render(f"得分 {score}   最高 {best}", True, (240, 240, 240)),
                                (WIDTH // 2 - 110, 240))
                    screen.blit(font.render("重来", True, (160, 220, 255)),
                                (restart_rect.x + 70, restart_rect.y + 8))
                    screen.blit(font.render("返回", True, (255, 190, 130)),
                                (quit_rect.x + 76, quit_rect.y + 8))
                elif paused:
                    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                    overlay.fill((0, 0, 0, 140))
                    screen.blit(overlay, (0, 0))
                    screen.blit(big_font.render("暂停中", True, (240, 240, 240)),
                                (WIDTH // 2 - 80, 190))
                    screen.blit(font.render("伸 1 根手指 或 点击屏幕 继续", True, (200, 220, 255)),
                                (WIDTH // 2 - 190, 270))
                elif state == "win":
                    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                    overlay.fill((0, 0, 0, 150))
                    screen.blit(overlay, (0, 0))
                    screen.blit(big_font.render("过关!", True, (150, 230, 150)),
                                (WIDTH // 2 - 90, 150))
                    screen.blit(font.render(f"得分 {score}   最高 {best}", True, (240, 240, 240)),
                                (WIDTH // 2 - 110, 240))
                    screen.blit(font.render("重来", True, (160, 220, 255)),
                                (restart_rect.x + 70, restart_rect.y + 8))
                    screen.blit(font.render("返回", True, (255, 190, 130)),
                                (quit_rect.x + 76, quit_rect.y + 8))
                else:
                    g = feeder.stable if feeder else "idle"
                    screen.blit(font.render(f"得分 {score}   最高 {best}", True, (240, 240, 240)),
                                (10, 10))
                    mode_txt = f"{MODES[mode]['label']} · {DIFFS[diff]['label']}"
                    if mode == "timed":
                        mode_txt += f"    时间 {max(0, timed_left // FPS)}s"
                    screen.blit(hint_font.render(mode_txt, True, (170, 180, 200)), (10, 42))
                    screen.blit(hint_font.render(
                        f"手势 {g}   抬=跳 双拳=蹲 双掌=二段 2指=暂停 1指=继续",
                        True, (170, 180, 200)), (10, 64))
                    # 5 hearts (top-right): remaining lives filled, lost ones dim
                    for i in range(max_lives):
                        cx = WIDTH - 22 - i * 22
                        cy = 16
                        col = (232, 72, 72) if i < lives else (95, 105, 125)
                        pygame.draw.circle(screen, col, (cx - 4, cy - 2), 5)
                        pygame.draw.circle(screen, col, (cx + 4, cy - 2), 5)
                        pygame.draw.polygon(screen, col,
                                             [(cx - 8, cy + 1), (cx + 8, cy + 1), (cx, cy + 11)])
                    # red flash when hit
                    if hit_flash > 0:
                        flash = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                        flash.fill((220, 40, 40, int(130 * hit_flash / 18)))
                        screen.blit(flash, (0, 0))
                    if feeder is not None and not feeder.camera_ok:
                        warn = hint_font.render("⚠ 未检测到摄像头画面，请检查摄像头", True, (255, 110, 90))
                        wx = (WIDTH - warn.get_width()) // 2
                        bar = pygame.Surface((warn.get_width() + 20, 28), pygame.SRCALPHA)
                        bar.fill((40, 20, 20, 190))
                        screen.blit(bar, (wx - 10, HEIGHT - 46))
                        screen.blit(warn, (wx, HEIGHT - 42))

            pygame.display.flip()

        frames += 1
        if max_frames is not None and frames >= max_frames:
            running = False
        clock.tick(FPS)

    if feeder is not None:
        feeder.stop()
    pygame.quit()
    if HEADLESS:
        print(f"HEADLESS_DONE frames={frames} state={state} score={score}", flush=True)


def main():
    max_frames = None
    if HEADLESS:
        idx = sys.argv.index("--headless-frames")
        max_frames = int(sys.argv[idx + 1])
    run_game(max_frames)


if __name__ == "__main__":
    main()
