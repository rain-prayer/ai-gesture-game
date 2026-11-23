"""Generate simple game SFX WAV files (pure stdlib, no network, no numpy).

Run once:  python tools/gen_sounds.py
Creates game/sounds/*.wav : jump, double_jump, crouch, pause, resume, win, die, hurt, bgm
"""
import math
import os
import struct
import wave

SR = 22050
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game", "sounds")


def _write_wav(name, samples):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples)
        w.writeframes(frames)
    print("wrote", path)


def _tone(freq, dur, vol=0.5, shape="sine", rise=0.0):
    n = max(1, int(SR * dur))
    start, end = freq, freq * (1 + rise)
    out = []
    for i in range(n):
        t = i / SR
        f = start + (end - start) * (i / n)
        ph = 2 * math.pi * f * t
        if shape == "sine":
            v = math.sin(ph)
        elif shape == "square":
            v = 1.0 if math.sin(ph) >= 0 else -1.0
        else:  # triangle
            v = 2 * math.asin(math.sin(ph)) / math.pi
        env = min(1.0, i / (0.005 * SR)) * math.exp(-3.2 * i / n)
        out.append(v * vol * env)
    return out


def _silence(dur):
    return [0.0] * max(0, int(SR * dur))


def _seq(*parts):
    out = []
    for p in parts:
        out.extend(p)
    return out


def main():
    _write_wav("jump", _tone(300, 0.11, rise=0.9))                 # 上升"啾"
    _write_wav("double_jump", _tone(430, 0.14, rise=1.1))          # 更高上升
    _write_wav("crouch", _tone(130, 0.09, vol=0.6, shape="square", rise=-0.4))  # 低闷"墩"
    _write_wav("pause", _tone(600, 0.08))
    _write_wav("resume", _tone(820, 0.09))
    _write_wav("win", _seq(_tone(523, 0.11), _tone(659, 0.11),
                           _tone(784, 0.15), _tone(1046, 0.26)))   # C-E-G-C 上行
    _write_wav("die", _tone(420, 0.32, rise=-0.72))                # 下行失重
    _write_wav("hurt", _tone(280, 0.10, vol=0.5, rise=-0.5))       # 掉心短促"受伤"
    _write_wav("bgm", _bgm())                                      # 轻柔背景音乐循环


def _pluck(freq, dur, vol=0.18):
    n = max(1, int(SR * dur))
    out = []
    for i in range(n):
        t = i / SR
        v = math.sin(2 * math.pi * freq * t)
        env = min(1.0, i / (0.004 * SR)) * math.exp(-4.5 * i / n)
        out.append(v * vol * env)
    return out


def _pad(freq, dur, vol=0.15):
    n = max(1, int(SR * dur))
    out = []
    for i in range(n):
        t = i / SR
        v = (math.sin(2 * math.pi * freq * t) + 0.5 * math.sin(2 * math.pi * freq * 2 * t)) / 1.5
        env = min(1.0, i / (0.02 * SR)) * (0.6 + 0.4 * math.sin(math.pi * i / n))
        out.append(v * vol * env)
    return out


def _mix(*signals):
    L = max(len(s) for s in signals)
    out = [0.0] * L
    for s in signals:
        for i, v in enumerate(s):
            out[i] += v
    return out


def _bgm():
    """Gentle 4-chord lo-fi loop: soft bass + arpeggio. Quiet, not busy."""
    chords = [  # (bass, r1, r3, r5)
        (130.81, 261.63, 329.63, 392.00),   # C
        (110.00, 220.00, 261.63, 329.63),   # Am
        (87.31, 174.61, 220.00, 261.63),    # F
        (98.00, 196.00, 246.94, 293.66),    # G
    ]
    dur = 1.8
    note_len = 0.55
    out = []
    for (bass, r1, r3, r5) in chords:
        bass = _pad(bass, dur, 0.14)
        arp = [0.0] * int(SR * dur)
        for note, off in zip((r1, r3, r5), (0, int(SR * 0.55), int(SR * 1.10))):
            pl = _pluck(note, 0.5, 0.17)
            for i, v in enumerate(pl):
                if off + i < len(arp):
                    arp[off + i] += v
        out.extend(_mix(bass, arp))
    return out


if __name__ == "__main__":
    main()
