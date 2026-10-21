import math
import random

from .config import Config
from .keymap import SHIFT_SYMBOLS, dyad_factor


class DelayModel:
    # rng 必须是 random.Random **实例**，不能是 random 模块本身：模块也提供
    # random()/gauss()/randint()/choices()，但类型不同，写 `rng=random` 会让
    # 类型检查器把参数推成 ModuleType，于是所有 `rng=random.Random(n)` 的调用
    # 都报「Random 不可分配给 ModuleType」。这里默认 random.Random()——它既是
    # 实例、API 又与模块一致，调用方省略 rng 时行为不变（都取全局随机源）。
    def __init__(self, cfg: Config, rng: random.Random = random.Random()):
        self.cfg = cfg
        self.rng = rng
        self.ln_mu = math.log(cfg.delay_mu)
        self.fatigue_minutes = 0.0
        # 这三个是「剩余计数」：warmup_chars 在 GUI 里由滑块 float 换算而来，
        # 赋进来可能是 float，所以显式标注成 float，避免 int/float 混赋值报错。
        self.warmup_left: float = 0.0
        self.burst_left: float = 0
        self.burst_refractory: float = 0
        # 上一次 sample() 的"局部速度因子"：排除了疲劳与预热这类慢变量，
        # 只反映这一刻打得多快（< 1 表示偏快）。TypoEngine 用它把错误率
        # 与局部速度耦合起来——打得越快越容易出错。
        self.tempo_factor = 1.0

    def add_active(self, seconds):
        self.fatigue_minutes += seconds / 60.0

    def note_pause(self, seconds):
        if seconds >= self.cfg.warmup_min_pause:
            self.warmup_left = self.cfg.warmup_chars

    def reset_fatigue(self):
        self.fatigue_minutes = 0.0

    def _fatigue(self):
        f = 1.0 + self.cfg.fatigue_rate * self.fatigue_minutes
        return min(self.cfg.fatigue_cap, f)

    def _warmup(self):
        if self.warmup_left <= 0:
            return 1.0, False
        frac = self.warmup_left / max(1, self.cfg.warmup_chars)
        self.warmup_left -= 1
        return 1.0 + (self.cfg.warmup_factor - 1.0) * frac, True

    def _roll_burst(self, cur):
        c = self.cfg
        if self.burst_left > 0:
            self.burst_left -= 1
            return True
        if self.burst_refractory > 0:
            self.burst_refractory -= 1
            return False
        if cur and cur != "\n" and self.rng.random() < c.p_burst_enter:
            self.burst_left = self.rng.randint(*c.burst_len_range) - 1
            self.burst_refractory = self.burst_left + self.rng.randint(10, 30)
            return True
        return False

    def sample(self, prev, cur):
        c = self.cfg
        sigma = c.delay_ln_sigma
        factor = 1.0

        bursting = self._roll_burst(cur)
        if bursting:
            factor *= c.burst_speed_factor
            sigma *= 0.5

        if prev == "\n":
            factor *= c.factor_after_newline
        elif prev and prev in c.sentence_end_chars:
            factor *= c.factor_after_sentence

        if cur != "\n":
            if cur.isupper() or (not cur.isspace() and cur in SHIFT_SYMBOLS):
                factor *= c.factor_shift
            if cur == " ":
                factor *= c.factor_space
                gap = max(0.0, self.rng.gauss(c.word_gap_mu, c.word_gap_sigma))
            else:
                gap = 0.0
            if cur == prev and cur.isalnum():
                factor *= c.factor_repeat
        else:
            gap = 0.0

        # 二元节奏：相邻两键的手指关系。突发段代表"肌肉记忆自动挡"，此时
        # 手指差异被抹平，所以只保留三成幅度（与上面的 sigma *= 0.5 同源）。
        dyad = dyad_factor(prev, cur, c.dyad_same_finger, c.dyad_alt_hand)
        if dyad is not None:
            factor *= 1.0 + (dyad - 1.0) * (0.3 if bursting else 1.0)

        self.tempo_factor = factor

        d = math.exp(self.rng.gauss(self.ln_mu, sigma)) * factor
        d *= self._fatigue()
        wf, _ = self._warmup()
        d *= wf
        # clamp the human-scale latency first, then map to wall-clock time,
        # so speed_multiplier doesn't get destroyed by the clip bounds.
        d = min(max(d, c.delay_clip[0]), c.delay_clip[1])
        d /= c.speed_multiplier
        if not bursting:
            d += gap / c.speed_multiplier
        return d

    def hold_time(self):
        t = max(0.02, self.rng.gauss(self.cfg.hold_mu, self.cfg.hold_sigma))
        return t / self.cfg.speed_multiplier

    def nav_delay(self):
        t = max(0.02, self.rng.gauss(self.cfg.nav_delay_mu, self.cfg.nav_delay_sigma))
        return t / self.cfg.speed_multiplier

    def backspace_delay(self):
        t = max(
            0.02,
            self.rng.gauss(
                self.cfg.backspace_delay_mu, self.cfg.backspace_delay_sigma
            ),
        )
        return t / self.cfg.speed_multiplier

    def pause_short(self):
        c = self.cfg
        d = math.exp(self.rng.gauss(c.pause_short_ln_mu, c.pause_short_ln_sigma))
        lo, hi = c.pause_short_clip
        return min(max(d, lo), hi) / c.speed_multiplier

    def line_end_think(self):
        c = self.cfg
        if self.rng.random() >= c.line_end_think_prob:
            return 0.0
        lo, hi = c.line_end_think_range
        return self.rng.uniform(lo, hi) / c.speed_multiplier

    def long_pause(self):
        c = self.cfg
        u = max(self.rng.random(), 1e-9)
        d = c.long_pause_xmin * (u ** (-1.0 / c.long_pause_alpha))
        return min(d, c.long_pause_cap)

    def work_session(self):
        """长程模式：下一次休息前要连续工作多少 human-scale 秒。"""
        lo, hi = self.cfg.work_session_range
        if hi < lo:
            lo, hi = hi, lo
        return self.rng.uniform(lo, hi)

    def rest_duration(self):
        """长程模式：这次休息持续多少 human-scale 秒。"""
        lo, hi = self.cfg.break_range
        if hi < lo:
            lo, hi = hi, lo
        return self.rng.uniform(lo, hi)

    def sample_pareto_threshold(self):
        return self.long_pause()
