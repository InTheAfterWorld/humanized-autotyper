import random
import string

from .config import Config
from .keymap import ADJACENT

def is_typoable(ch):
    return ch.isalnum() and ch.isascii() or ch == "_"


class TypoEngine:
    # 同 delays.py：默认必须是 Random 实例而不是 random 模块，否则类型检查器
    # 会把 rng 推成 ModuleType，与所有 `rng=random.Random(n)` 的调用冲突。
    def __init__(self, cfg: Config, rng: random.Random = random.Random()):
        self.cfg = cfg
        self.rng = rng
        self.autocorr_left: float = 0

    def roll(self, cur, next_char=None, tempo_factor=1.0):
        c = self.cfg
        if not is_typoable(cur):
            return None
        p = c.p_typo * (
            c.typo_autocorr_boost if self.autocorr_left > 0 else 1.0
        )
        # 错误率与局部速度耦合：tempo_factor < 1 表示这一刻打得偏快
        # （突发段/词内顺手的片段），此时更容易出错；慢下来则更稳。
        p *= (tempo_factor or 1.0) ** (-c.typo_speed_exponent)
        p = min(1.0, p)
        if self.rng.random() >= p:
            if self.autocorr_left > 0:
                self.autocorr_left -= 1
            return None

        kinds, weights = zip(*c.typo_weights)
        kind = self.rng.choices(kinds, weights=weights, k=1)[0]
        payload = None

        if kind == "adjacent":
            payload = self._adjacent(cur)
        elif kind == "double":
            payload = cur + cur
        elif kind == "transposition":
            if next_char and is_typoable(next_char) and next_char != "\n":
                # (先打的意图, 后打的意图)：实际输出时两者顺序对调
                payload = (cur, next_char)
            else:
                payload = self._adjacent(cur)
                kind = "adjacent"
        else:
            if self.rng.random() < 0.5:
                payload = ""
            else:
                pool = string.ascii_lowercase.replace(cur.lower(), "")
                ch = self.rng.choice(pool)
                payload = ch.upper() if cur.isupper() else ch

        self.autocorr_left = c.typo_autocorr_window
        detect = self.rng.choices([0, 1, 2], weights=c.typo_detect_probs, k=1)[0]

        if kind == "transposition":
            return {
                "kind": kind,
                "emit_first": payload[1],    # 顺序对调：先打后一个字符
                "emit_second": payload[0],
                "typed_len": 2,
                "detect_after": detect,
            }
        return {
            "kind": kind,
            "emit": payload,
            "typed_len": len(payload),
            "detect_after": detect,
        }

    def _adjacent(self, ch):
        base = ch.lower() if ch.isupper() else ch
        opts = ADJACENT.get(base)
        if not opts:
            pool = string.ascii_lowercase.replace(base, "")
            wrong = self.rng.choice(pool)
        else:
            wrong = self.rng.choice(opts)
        return wrong.upper() if ch.isupper() else wrong
