"""presets.py — 「人设」预设，GUI 与 CLI 共用。

所有值都是 Config 的真实单位（秒/概率小数），
apply_preset(cfg, name) 直接把值写进 Config 实例。
"""
from .config import Config

# 名字 -> {字段: 值}；只覆盖列出的字段，其余保持默认/滑块当前值。
PRESETS = {
    "标准": {},
    "高效型程序员": {
        "delay_mu": 0.08,            # 中位敲键间隔 80ms
        "delay_ln_sigma": 0.30,      # 节奏更稳
        "p_typo": 0.005,
        "p_burst_enter": 0.06,
        "fatigue_rate": 0.002,
        "p_backspace_burst": 0.004,
        "p_pause_short": 0.004,
        "p_edit_previous": 0.002,
        "p_rewrite_chunk": 0.003,
    },
    "手生普通人": {
        "delay_mu": 0.18,            # 中位 180ms，明显偏慢
        "delay_ln_sigma": 0.75,      # 忽快忽慢
        "p_typo": 0.025,
        "typo_autocorr_window": 14,  # 更容易连错
        "p_burst_enter": 0.025,
        "fatigue_rate": 0.010,
        "p_backspace_burst": 0.016,
        "p_pause_short": 0.020,
        "pause_short_clip": (0.8, 12.0),
        "p_edit_previous": 0.008,
        "edit_min_gap_s": 40.0,
        "p_rewrite_chunk": 0.010,
    },
}


def preset_names():
    return list(PRESETS.keys())


def apply_preset(cfg: Config, name: str) -> int:
    """把预设写入 cfg。返回实际覆盖的字段数；未知名字抛 KeyError。"""
    values = PRESETS[name]
    n = 0
    for k, v in values.items():
        assert hasattr(cfg, k), f"unknown config field: {k}"
        setattr(cfg, k, v)
        n += 1
    return n


def describe(name: str) -> str:
    """给 CLI 打印用的单行描述。"""
    v = PRESETS[name]
    if not v:
        return "config 默认参数"
    mu_ms = v.get("delay_mu", 0.11) * 1000
    typo_pct = v.get("p_typo", 0.012) * 100
    return f"中位间隔~{mu_ms:.0f}ms  错字率{typo_pct:.1f}%  " \
           f"(共覆盖 {len(v)} 项)"
