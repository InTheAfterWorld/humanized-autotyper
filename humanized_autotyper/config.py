import math
from dataclasses import dataclass


def _ln(x):
    return math.log(x)


@dataclass
class Config:
    dry_run: bool = True
    speed_multiplier: float = 1.0
    countdown_seconds: int = 5
    kill_hotkey: str = "f10"
    expected_window_title: str = ""
    log_file: str = "autotyper_log.csv"
    # 启动时清空日志（--fresh）。默认 False = 追加，历史运行会留在同一个文件里，
    # 但每次运行都会写 RUN 标记行，report 能据此切分（见 report.py::split_runs）。
    fresh_log: bool = False
    verbose: bool = False

    p_typo: float = 0.012
    typo_weights: tuple = (
        ("adjacent", 0.60),
        ("double", 0.20),
        ("transposition", 0.15),
        ("random", 0.05),
    )
    typo_detect_probs: tuple = (0.65, 0.25, 0.10)
    typo_autocorr_boost: float = 2.0
    typo_autocorr_window: int = 10
    # 错误率与局部速度耦合：tempo_factor（当前字符"越快越小"的因子）在突发段
    # 约 0.55、同指卡顿约 1.35。实测约 34% 的字符落在快段，乘数均值 ≈1.18，
    # 所以实际错误率约为 p_typo × 1.18（默认 ≈1.4%）——略高于耦合前，是因为
    # 快打段本来就该更容易出错。想回到 1.2% 就把 p_typo 调到 0.010。
    typo_speed_exponent: float = 1.2

    p_burst_enter: float = 0.05
    burst_len_range: tuple = (5, 20)
    burst_speed_factor: float = 0.55

    p_backspace_burst: float = 0.008
    backspace_n_range: tuple = (2, 12)
    backspace_delay_mu: float = 0.090
    backspace_delay_sigma: float = 0.030

    p_pause_short: float = 0.008
    p_pause_short_sentence: float = 0.06
    sentence_end_chars: str = ".:;)}"
    pause_short_ln_mu: float = _ln(2.5)
    pause_short_ln_sigma: float = 0.9
    pause_short_clip: tuple = (0.8, 10.0)
    line_end_think_prob: float = 0.35
    line_end_think_range: tuple = (0.3, 1.5)

    p_edit_previous: float = 0.004
    edit_min_gap_s: float = 90.0
    edit_lookback_range: tuple = (5, 40)
    edit_op_weights: tuple = (
        ("replace_word", 0.35),
        ("retype_clause", 0.40),
        ("fake_delete_insert", 0.25),
    )
    edit_return_pause: tuple = (0.8, 3.0)

    p_rewrite_chunk: float = 0.006
    rewrite_lines_range: tuple = (1, 3)

    # 回读遍数：写完一行后偶尔用纯方向键回扫一眼刚写的内容（只读，不改文本）
    p_review: float = 0.02
    review_back_range: tuple = (5, 25)

    delay_mu: float = 0.11
    delay_ln_sigma: float = 0.42
    delay_clip: tuple = (0.04, 0.40)
    factor_after_newline: float = 2.5
    factor_after_sentence: float = 1.8
    factor_shift: float = 1.4
    factor_space: float = 0.9
    factor_repeat: float = 0.85
    # 二元节奏（同指代价）：相邻两键的手指关系决定速度。真正的打字速度
    # 主要取决于此——同指连击要等手指抬起落下（最慢），双手交替最快。
    dyad_same_finger: float = 1.35
    dyad_alt_hand: float = 0.85
    word_gap_mu: float = 0.06
    word_gap_sigma: float = 0.02

    fatigue_rate: float = 0.005
    fatigue_cap: float = 1.25
    warmup_min_pause: float = 5.0
    warmup_chars: int = 10
    warmup_factor: float = 1.6

    hold_mu: float = 0.075
    hold_sigma: float = 0.020
    # 收到停止请求后，"补完已删除片段"用的按键保持时间（不再引入拟人延时）
    urgent_hold: float = 0.008
    nav_delay_mu: float = 0.070
    nav_delay_sigma: float = 0.020

    long_pause_xmin: float = 240.0
    long_pause_alpha: float = 1.4
    long_pause_cap: float = 2100.0
    long_sleep_chunk: float = 2.0
    resume_left_range: tuple = (0, 60)
    resume_reorient_range: tuple = (0.5, 2.0)
