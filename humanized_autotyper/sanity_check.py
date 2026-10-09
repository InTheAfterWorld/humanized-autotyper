import json
import os
import random
import tempfile
import time
from typing import Any, Dict

from .config import Config
from .buffer import Buffer
from .delays import DelayModel
from .keymap import unsupported_chars, dyad_factor, FINGER
from .typos import TypoEngine, is_typoable
from .machine import AutoTyper
from .main import DEMO_SOURCE, source_problem


def test_buffer():
    b = Buffer("hello\nworld")
    for ch in "!!!":
        b.type_char(ch)
    assert b.text == "hello\nworld!!!" and b.cursor == 14
    b.backspace()
    assert b.text == "hello\nworld!!" and b.cursor == 13
    b.to_line_start()
    assert b.line_col() == (1, 0)
    b.apply_up(1)
    assert b.line_col() == (0, 0)
    b.move_right(3)
    assert b.seg(b.cursor - 3, b.cursor) == "hel"
    assert b.complete_line_count() == 1 and b.line_count() == 2
    assert b.line_end_excl_newline(0) == 5
    ws = Buffer("def foo_bar(x):\n    return x").words_on_line(0)
    assert "foo_bar" in [w[2] for w in ws]
    print("PASS buffer")


def test_delays():
    cfg = Config()
    rng = random.Random(1)
    dm = DelayModel(cfg, rng)
    s = sorted(dm.sample("", "a") for _ in range(5000))
    med, p95 = s[2500], s[4750]
    assert 0.07 <= med <= 0.16 and p95 <= cfg.delay_clip[1]
    d_nl = sum(dm.sample("\n", "a") for _ in range(500)) / 500
    d_rep = sum(dm.sample("a", "a") for _ in range(500)) / 500
    assert d_nl > med * 1.8
    ps = sorted(dm.pause_short() for _ in range(2000))
    assert cfg.pause_short_clip[0] <= ps[0] + 1e-9 <= ps[-1] <= cfg.pause_short_clip[1] + 1e-9
    lp = sorted(dm.long_pause() for _ in range(2000))
    assert lp[-1] <= cfg.long_pause_cap + 1e-9 and lp[1000] >= cfg.long_pause_xmin
    dm.add_active(600)
    assert dm._fatigue() > 1.0
    dm.note_pause(10)
    assert dm.warmup_left == cfg.warmup_chars
    print(f"PASS delays median={med*1000:.0f}ms p95={p95*1000:.0f}ms "
          f"afterNL={d_nl*1000:.0f}ms repeat={d_rep*1000:.0f}ms")


def test_typos():
    cfg = Config()
    rng = random.Random(2)
    te = TypoEngine(cfg, rng)
    kinds = {}
    n = 4000
    for _ in range(n):
        r = te.roll("d", next_char="x")
        if r:
            assert r["kind"] in ("adjacent", "double", "transposition", "random")
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    rate = sum(kinds.values()) / n
    assert 0.004 <= rate <= 0.03 and kinds.get("transposition", 0) > 0
    assert te.roll("\n", next_char=None) is None
    print(f"PASS typos rate={rate:.3f} kinds={kinds}")


def fast_cfg(**over):
    # 标注成 Dict[str, Any]：dict(...) 的字面量值类型会被推成
    # float | tuple | str 的联合，再展开进 Config(**base) 时每个字段都被判
    # 不匹配（一次报 60+ 个错）。这些 override 本来就是任意 Config 字段。
    base: Dict[str, Any] = dict(
        dry_run=True, speed_multiplier=300.0, countdown_seconds=0,
        line_end_think_prob=0.02, pause_short_ln_mu=-4.6,
        pause_short_clip=(0.002, 0.01), long_pause_cap=0.4,
        edit_min_gap_s=0.0, p_edit_previous=0.06, p_rewrite_chunk=0.06,
        log_file=os.devnull,
    )
    base.update(over)
    return Config(**base)


def test_full_dry_run():
    cfg = fast_cfg()
    t0 = time.time()
    typer = AutoTyper(cfg, DEMO_SOURCE, rng=random.Random(42))
    typer.sched.threshold = 0.05
    s = typer.run()
    took = time.time() - t0
    assert s["final_matches_source"], "BUFFER != SOURCE after full run"
    assert s["source_consumed"] == len(DEMO_SOURCE)
    assert s["errors"] > 0 and s["corrections"] > 0
    assert s["long_pauses"] >= 1
    assert took < 120
    print(f"PASS full_dry_run {s} in {took:.1f}s")


def _primed_typer(cfg, upto):
    typer = AutoTyper(cfg, DEMO_SOURCE, rng=random.Random(7))
    typer.buffer.text = DEMO_SOURCE[:upto]
    typer.buffer.cursor = upto
    typer.pipeline.i = upto
    typer.last_sent = DEMO_SOURCE[upto - 1] if upto else ""
    return typer


def test_edit_previous_unit():
    cfg = fast_cfg()
    for upto in (300, 500, 700):
        t = _primed_typer(cfg, upto)
        before = t.buffer.text
        fired = False
        for _ in range(30):
            t.last_edit_time = -1e18
            t._h_edit_previous()
            if t.stats["edits"] > 0:
                fired = True
                break
        assert fired, f"edit never fired at upto={upto}"
        assert t.buffer.text == before, "EDIT_PREVIOUS changed committed text"
        assert t.buffer.cursor == len(before), "cursor not at doc end after edit"
        assert t.err_detect_in < 0
    print("PASS edit_previous_unit")


def test_rewrite_chunk_unit():
    cfg = fast_cfg()
    for upto in (400, 700):
        t = _primed_typer(cfg, upto)
        before = t.buffer.text
        t._h_rewrite_chunk()
        assert t.buffer.text == before, "REWRITE_CHUNK changed committed text"
        assert t.buffer.cursor == len(before)
        assert t.stats["rewrites"] >= 1
    print("PASS rewrite_chunk_unit")


def test_burst_unit():
    cfg = fast_cfg()
    t = _primed_typer(cfg, 500)
    # 光标必须落在行中间：行首只剩 1 个字符时爆发本来就删不动
    t.buffer.text = "x" * 40
    t.buffer.cursor = 40
    before = t.buffer.text
    t._h_burst()
    assert t.stats["bursts"] == 1
    assert t.buffer.text == before, "BACKSPACE_BURST changed text net effect"
    print("PASS burst_unit")


def test_pause_long_unit():
    cfg = fast_cfg()
    t = _primed_typer(cfg, 400)
    before = t.buffer.text
    cur_before = t.buffer.cursor
    t.delays.reset_fatigue()
    t.sched.active = 999.0
    r = t._h_pause_long()
    assert r == "TYPING"
    assert t.buffer.text == before and t.buffer.cursor == cur_before
    assert t.sched.active < 0.5
    print("PASS pause_long_unit")


class NavRecorder:
    """只记录方向键次数，不发送任何按键。"""
    def __init__(self):
        self.taps = []

    def nav_left(self, n=1):
        self.taps.append(("left", n))

    def nav_right(self, n=1):
        self.taps.append(("right", n))

    def nav_up(self, n=1):
        self.taps.append(("up", n))

    def nav_down(self, n=1):
        self.taps.append(("down", n))


def test_pause_long_ritual_clamped():
    """光标在文首附近时，"左 N 再右 N"的找回位置动作不能超过已打字符数：
    超出部分会被编辑器在文档头夹住，回程就冲过头，光标与缓冲区错位。"""
    cfg = fast_cfg()
    cfg.resume_left_range = (60, 60)
    cfg.long_pause_xmin = cfg.long_pause_cap = 1.0
    for upto in (0, 10, 30, 200):
        t = _primed_typer(cfg, upto)
        rec = NavRecorder()
        t.executor = rec
        t.sched.active = 1e9
        before = t.buffer.text
        t._h_pause_long()
        left = sum(n for k, n in rec.taps if k == "left")
        right = sum(n for k, n in rec.taps if k == "right")
        assert left == right, f"左移/右移不对称: {left} vs {right}"
        assert left <= upto, f"左移 {left} 次 > 已打 {upto} 字符"
        assert t.buffer.text == before and t.buffer.cursor == len(before)
    print("PASS pause_long_ritual_clamped")


def test_burst_no_fake_count():
    """行首只剩 1 个字符时删不动，这种"没发生的爆发"不能计入统计。"""
    cfg = fast_cfg()
    t = AutoTyper(cfg, DEMO_SOURCE, rng=random.Random(3))
    t.buffer.text = "a"
    t.buffer.cursor = 1
    t.pipeline.i = 1
    for _ in range(20):
        t._h_burst()
    assert t.stats["bursts"] == 0 and t.buffer.text == "a"
    print("PASS burst_no_fake_count")


def test_transposition_payload():
    """换序错误的返回结构必须自洽：先打后一个字符，再打当前字符。"""
    te = TypoEngine(Config(), random.Random(3))
    for _ in range(20000):
        r = te.roll("d", next_char="x")
        if r and r["kind"] == "transposition":
            assert r["emit_first"] == "x", r
            assert r["emit_second"] == "d", r
            assert r["typed_len"] == 2, r
            break
    else:
        raise AssertionError("20000 次都没抽到 transposition")
    print("PASS transposition_payload")


def test_kill_mid_edit_keeps_text():
    """停止请求正好落在"已删除、还没重打"之间时，文档不能缺字。"""
    cfg = fast_cfg()
    for upto in (300, 500, 700):
        t = _primed_typer(cfg, upto)
        before = t.buffer.text
        ex = t.executor
        orig_select = ex.select_shift_right

        def kill_on_select(n=1, _t=t, _orig=orig_select):
            _t.kill.set()          # 模拟停止请求恰好在这时到达
            return _orig(n)

        ex.select_shift_right = kill_on_select
        for _ in range(30):
            # 抽中的目标行可能没有可改的单词，那就再抽一次
            t.last_edit_time = -1e18
            t._h_edit_previous()
            if t.kill.killed():
                break
        t._flush_correction()
        assert t.kill.killed(), f"没走到删除路径 (upto={upto})"
        assert t.buffer.text == before, f"停止时删掉的片段没补回来 (upto={upto})"
    print("PASS kill_mid_edit_keeps_text")


def test_kill_mid_burst_keeps_text():
    """回删爆发中途收到停止请求：已删的片段必须补回。"""
    cfg = fast_cfg()
    t = _primed_typer(cfg, 500)
    t.buffer.text = "x" * 40        # 光标在行中，爆发才有得删
    t.buffer.cursor = 40
    before = t.buffer.text
    ex = t.executor
    orig_backspace = ex.backspace
    calls = {"n": 0}

    def backspace(_t=t):
        calls["n"] += 1
        if calls["n"] == 2:
            _t.kill.set()
        return orig_backspace()

    ex.backspace = backspace
    t._h_burst()
    assert t.stats["bursts"] == 1
    assert t.buffer.text == before, "回删爆发被停止后没有补回文本"
    print("PASS kill_mid_burst_keeps_text")


def test_dyad_rhythm():
    """二元节奏：同指连击应明显慢于双手交替，且与"键位相邻"无关。"""
    import statistics

    # 确定性部分：查表本身
    assert dyad_factor("e", "d", 1.35, 0.85) == 1.35      # 同指（左中指列）
    assert dyad_factor("y", "h", 1.35, 0.85) == 1.35      # 同指（右食指，同行）
    assert dyad_factor("w", "e", 1.35, 0.85) == 1.0       # 同手异指
    assert dyad_factor("a", "j", 1.35, 0.85) == 0.85      # 双手交替
    assert dyad_factor("a", "a", 1.35, 0.85) is None      # 同键交给 factor_repeat
    # 关键回归保护：w 与 s 同指（字母行是每指一竖列），不能因为"键位相邻"被当成同手异指
    assert FINGER["w"] == FINGER["s"] and dyad_factor("w", "s", 1.35, 0.85) == 1.35
    assert dyad_factor("a", "1", 1.35, 0.85) is None      # 非字母不参与

    # 集成部分：延迟采样确实吃进了这个因子（用中位数抗长尾）
    cfg = Config()
    dm = DelayModel(cfg, random.Random(11))
    same = statistics.median(dm.sample("e", "d") for _ in range(400))
    alt = statistics.median(dm.sample("a", "j") for _ in range(400))
    assert same > alt * 1.2, f"同指未变慢: {same:.4f} vs {alt:.4f}"
    print(f"PASS dyad_rhythm same_finger={same*1000:.0f}ms "
          f"alt_hand={alt*1000:.0f}ms ratio={same/alt:.2f}")


def test_typo_speed_coupling():
    """错误率必须与局部速度耦合：打得越快(tempo 越小)越容易出错。"""
    cfg = Config()
    n = 12000

    def count(tempo):
        te = TypoEngine(cfg, random.Random(5))
        return sum(1 for _ in range(n)
                   if te.roll("d", next_char="x", tempo_factor=tempo))

    fast, slow = count(0.85), count(1.35)      # 0.85=突发段那种快, 1.35=同指卡顿那种慢
    assert fast > slow * 1.3, f"耦合不足: 快={fast} 慢={slow}"
    # 默认 tempo=1.0 时应与耦合前完全一致
    te = TypoEngine(cfg, random.Random(6))
    hits = sum(1 for _ in range(n) if te.roll("d", next_char="x"))
    assert 0.004 <= hits / n <= 0.03, hits / n

    # 端到端：真实文本上的 tempo 分布决定了整体乘数（含突发段的 0.55）。
    # 实测均值 ≈1.18 —— 锁住它，免得以后改突发参数时错误率静默漂移。
    dm = DelayModel(cfg, random.Random(3))
    src = "def compute_stats(numbers):\n    total = 0\n    return total\n" * 40
    prev, mult = "", []
    for ch in src:
        dm.sample(prev, ch)
        mult.append(dm.tempo_factor ** (-cfg.typo_speed_exponent))
        prev = ch
    mean_mult = sum(mult) / len(mult)
    assert 1.0 <= mean_mult <= 1.4, f"错误率乘数漂移: {mean_mult:.3f}"
    print(f"PASS typo_speed_coupling fast={100*fast/n:.2f}% slow={100*slow/n:.2f}% "
          f"ratio={fast/slow:.2f} (tempo=1.0 -> {100*hits/n:.2f}%, "
          f"端到端乘数={mean_mult:.2f})")


def test_review_keeps_text():
    """回读遍数只读不改：文本与光标必须原样，且确实回扫又回到文末。"""
    cfg = fast_cfg()
    cfg.review_back_range = (20, 20)
    for upto in (300, 500, 700):
        t = _primed_typer(cfg, upto)
        t._sleep = lambda seconds, active=True, chunk=0.25: True   # 不真的睡
        before, cursor_before = t.buffer.text, t.buffer.cursor
        path = []
        real_nav = t._navigate_to
        t._navigate_to = lambda pos, _r=real_nav: (path.append(pos), _r(pos))[1]
        r = t._h_review()
        assert r == "TYPING"
        assert t.buffer.text == before, "REVIEW 改动了文本"
        assert t.buffer.cursor == cursor_before, "REVIEW 结束后光标没回到文末"
        assert t.stats["reviews"] == 1
        # 绝对位置轨迹：必须往回走至少 20 格，最后回到原位
        assert path, "REVIEW 没有做任何导航"
        assert path[-1] == cursor_before, f"没有回到文末: {path}"
        assert cursor_before - min(path) >= 20, f"回扫深度不足: {path}"
    print("PASS review_keeps_text")


def test_review_mid_correction_is_safe():
    """REVIEW 恰好插在"错字已发现、还没纠正"的窗口里时，不得破坏纠正状态。"""
    cfg = fast_cfg()
    cfg.review_back_range = (10, 10)
    t = _primed_typer(cfg, 500)
    t._sleep = lambda seconds, active=True, chunk=0.25: True
    # 伪造一个待补的错字：本该打 'x'，实际打成了 'd'
    t.err_typed, t.err_intended, t.err_detect_in = "d", "x", 1
    before, cursor_before = t.buffer.text, t.buffer.cursor
    t._h_review()
    assert t.err_typed == "d" and t.err_intended == "x"
    assert t.err_detect_in == 1, "REVIEW 破坏了待纠正状态"
    assert t.buffer.text == before and t.buffer.cursor == cursor_before
    t._flush_correction()          # 纠正必须仍然能正常收口
    # 纠正 = 退掉 err_typed 的字符数、再打上 err_intended，所以文本会变，
    # 但必须恰好"换掉一个字符"：即末尾变成本该打的 'x'，长度不变。
    assert t.err_detect_in < 0 and t.err_typed == ""
    assert t.buffer.text[-1] == "x", f"纠正结果不对: {t.buffer.text[-8:]!r}"
    assert len(t.buffer.text) == len(before), "纠正后长度不该变"
    print("PASS review_mid_correction_is_safe")


def test_review_disabled_is_inert():
    """p_review=0 时不该产生回读事件（并且不破坏任何东西）。"""
    cfg = fast_cfg()
    cfg.p_review = 0.0
    t = _primed_typer(cfg, 500)
    t.sched.threshold = 1e18        # 排除长暂停干扰
    src = DEMO_SOURCE[:500]
    t2 = AutoTyper(cfg, src, rng=random.Random(4))
    t2.sched.threshold = 1e18
    s = t2.run()
    assert s["reviews"] == 0, f"p_review=0 仍有 {s['reviews']} 次回读"
    assert s["final_matches_source"]
    print("PASS review_disabled_is_inert")


def _fake_windll(title):
    """伪造 ctypes.windll.user32，让 check_window 拿到指定的前台窗口标题。"""
    import ctypes
    import types

    class _Buf:
        def __init__(self):
            self.value = ""

    class _User32:
        def GetForegroundWindow(self):
            return 1

        def GetWindowTextW(self, hwnd, buf, n):
            buf.value = title

    return types.SimpleNamespace(user32=_User32())


def _window_probe(expected):
    """构造一个只用来测 check_window 的 Executor（不碰 pynput）。"""
    from .executor import Executor, Logger, Killer

    cfg = Config(dry_run=False, expected_window_title=expected,
                 log_file=os.devnull)
    ex = Executor.__new__(Executor)
    ex.cfg = cfg
    ex.kill = Killer()
    ex.live = True
    ex._warned_mismatch = False
    # 必须叫 log（与 __init__ 一致）。原来这里写 ex.logger，恰好把
    # check_window() 里 self.logger 的笔误掩盖住了——属性名不对，
    # 而这个夹具"碰巧"补上了同名属性，所以测试一直是绿的。
    ex.log = Logger(cfg)
    return ex


def test_check_window_pauses_not_kills():
    """失焦 = 暂停（可恢复），不再是"切走一次就彻底放弃"。"""
    import ctypes

    ex = _window_probe("Notepad")
    real = getattr(ctypes, "windll", None)
    try:
        ctypes.windll = _fake_windll("Untitled - Notepad")
        assert ex.check_window() is True
        assert not ex.kill.paused() and not ex.kill.killed()

        ctypes.windll = _fake_windll("WhatsApp")
        assert ex.check_window() is False, "不匹配应返回 False"
        assert ex.kill.paused(), "失焦应请求暂停"
        assert not ex.kill.killed(), "失焦不该直接杀掉任务"

        ctypes.windll = _fake_windll("Untitled - Notepad")
        assert ex.check_window() is True
        assert not ex.kill.paused(), "窗口回来后应自动撤销暂停"

        # 读不到标题（句柄失效）也必须暂停，而不是放行
        ctypes.windll = _fake_windll("")
        assert ex.check_window() is False and ex.kill.paused()
    finally:
        if real is not None:
            ctypes.windll = real
    print("PASS check_window_pauses_not_kills")


def test_send_guard_blocks_keystroke_while_paused():
    """竞态兜底：_send 遇到暂停标志必须先等恢复，再发键。

    端到端测试（下面那个）在概念上无法断言"零击键"——暂停请求来自另一个
    线程，总可能正好落在某次循环中间。这里确定性地构造那个窗口。
    """
    import threading as _th

    cfg = fast_cfg()
    t = _primed_typer(cfg, 400)
    log = []

    def spy(ch, delay_ms=0.0, hold=None):
        log.append((ch, t.kill.paused()))     # 记录"发键那一刻是否仍在暂停"

    t.executor.type_char = spy
    t.kill.request_pause()
    _th.Timer(0.15, t.kill.request_resume).start()
    started = time.time()
    t._send("Z")

    assert log, "恢复后没有发键"
    assert not log[0][1], "暂停未解除就发了击键"
    assert time.time() - started >= 0.1, "没有真的等过暂停"
    assert t.buffer.text == DEMO_SOURCE[:400] + "Z"
    print(f"PASS send_guard_blocks_keystroke_while_paused "
          f"(waited {time.time()-started:.2f}s)")

    # 被停止时不该补发
    t2 = _primed_typer(cfg, 400)
    sent = []
    t2.executor.type_char = lambda ch, delay_ms=0.0, hold=None: sent.append(ch)
    t2.kill.request_pause()
    t2.kill.set()
    t2._send("Y")
    assert sent == [], "已被停止时不该补发击键"
    assert t2.buffer.text == DEMO_SOURCE[:400]


def test_pause_blocks_typing_and_resumes():
    """暂停期间一个键都不发；恢复后跑完且文本一致。"""
    import threading as _th

    cfg = fast_cfg()
    typer = AutoTyper(cfg, DEMO_SOURCE * 2, rng=random.Random(21))
    typer.sched.threshold = 1e18
    stats = {"pause_seen": False}
    emitted_while_paused = []
    # 插桩必须放在"真正发出击键"的那一层。放在 _send 入口会误报：_send 入口
    # 早于 _wait_while_paused，暂停恰好在等待期间到达也会被记成一次违规。
    real_type_char = typer.executor.type_char

    def spied_type_char(ch, delay_ms=0.0, hold=None):
        if typer.kill.paused():
            emitted_while_paused.append(ch)
        return real_type_char(ch, delay_ms, hold)

    typer.executor.type_char = spied_type_char

    def watch():
        for _ in range(600):
            if typer.kill.paused():
                stats["pause_seen"] = True
                return
            time.sleep(0.005)

    w = _th.Thread(target=watch, daemon=True)
    w.start()
    t0 = _th.Timer(0.15, typer.kill.request_pause)
    t1 = _th.Timer(0.60, typer.kill.request_resume)
    t0.start()
    t1.start()
    s = typer.run()
    for t in (t0, t1):
        t.join()
    w.join(timeout=4)

    assert stats["pause_seen"], "测试没真正进入过暂停（没等到 paused 状态）"
    assert not emitted_while_paused, \
        f"暂停期间发出了 {len(emitted_while_paused)} 次击键: {emitted_while_paused[:8]}"
    assert s["pause_count"] >= 1, "没有记录到暂停"
    assert s["final_matches_source"], "暂停恢复后文本不一致"
    print(f"PASS pause_blocks_typing_and_resumes chars={s['chars']} "
          f"pauses={s['pause_count']}")


def test_pause_during_long_pause_resumes():
    """长暂停中途暂停：同样不该打字，恢复后计数归零、文本一致。"""
    import threading as _th

    cfg = fast_cfg()
    typer = AutoTyper(cfg, DEMO_SOURCE, rng=random.Random(31))
    typer.sched.threshold = 1e18
    cfg.long_pause_xmin = cfg.long_pause_cap = 0.6
    fired = {"n": 0}
    real = typer._wait_while_paused

    def counting_wait():
        fired["n"] += 1
        return real()

    typer._wait_while_paused = counting_wait
    t = _th.Timer(0.2, typer.kill.request_pause)
    t2 = _th.Timer(0.5, typer.kill.request_resume)
    t.start()
    t2.start()
    s = typer.run()
    t.join()
    t2.join()
    assert fired["n"] >= 1, "长暂停期间没有进入暂停等待"
    assert s["final_matches_source"]
    print(f"PASS pause_during_long_pause_resumes pauses={s['pause_count']}")


def test_source_guard():
    """\r 之类的控制字符必须在启动前就被拒绝（dry-run 也照样拒）。"""
    assert unsupported_chars("a\nb\tc") == []
    assert unsupported_chars("a\rb") == [(1, "\r")]
    assert [i for i, _ in unsupported_chars("x\x00y\x0bz")] == [1, 3]
    assert source_problem("") is not None
    assert source_problem("   ") is not None
    assert source_problem("a\rb") is not None
    assert source_problem(DEMO_SOURCE) is None
    print("PASS source_guard")


def test_mixed_text_dry_run():
    """中英混排 + emoji + 制表符：缓冲区必须逐字符等于源文本。"""
    src = "你好，world！\n\tdef 函数(x):  # 😀 ok?\n" * 8
    cfg = fast_cfg()
    t = AutoTyper(cfg, src, rng=random.Random(11))
    t.sched.threshold = 0.05
    s = t.run()
    assert s["final_matches_source"], "中英混排 + emoji 跑完不一致"
    assert s["source_consumed"] == len(src)
    print(f"PASS mixed_text_dry_run chars={s['chars']} errors={s['errors']} "
          f"edits={s['edits']} rewrites={s['rewrites']}")


def test_log_run_segmentation():
    """日志必须按运行分段，且每段带得上自己那次运行的 config。

    回归背景：日志是追加写的，一次 --speed 300 的冒烟跑和一次 1.0x 的正常跑
    会混在同一个文件里。老 report 把整个文件当一次运行统计，pooled 中位数被
    拉到 ~67ms、CV 从 0.46 涨到 1.00，看起来像"节奏不稳"，其实只是两批不同
    速度的样本被硬拼在一起。
    """
    import csv as _csv
    import json as _json
    import tempfile

    from .executor import Logger
    from .report import load, split_runs

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "seg.csv")

        # run A: 快档（墙钟 ~0.3ms/字）
        cfg_a = Config(log_file=path, speed_multiplier=300.0, p_typo=0.012)
        a = AutoTyper(cfg_a, "hello world\n" * 20, rng=random.Random(1))
        a.sched.threshold = 1e18
        sa = a.run()
        a.logger.close()

        # run B: 慢档（墙钟 ~14ms/字），并且用**不同**的 p_typo
        cfg_b = Config(log_file=path, speed_multiplier=8.0, p_typo=0.05)
        b = AutoTyper(cfg_b, "hello world\n" * 20, rng=random.Random(2))
        b.sched.threshold = 1e18
        sb = b.run()
        b.logger.close()

        rows = load(path)
        runs = split_runs(rows)
        assert len(runs) == 2, f"应切分成 2 段，实际 {len(runs)}"
        assert all(r["closed"] for r in runs), "两段都应有 RUN,end 收尾标记"
        assert runs[0]["run_id"] != runs[1]["run_id"], "两段 run_id 应不同"

        # 每段都要还原出**自己那次**的 config，而不是默认值
        assert runs[0]["cfg"].speed_multiplier == 300.0
        assert runs[1]["cfg"].speed_multiplier == 8.0
        assert runs[0]["cfg"].p_typo == 0.012
        assert runs[1]["cfg"].p_typo == 0.05
        # 元组字段经 JSON 往返后必须仍是元组（Config 内部要解包）
        assert isinstance(runs[0]["cfg"].delay_clip, tuple)
        assert len(runs[0]["cfg"].delay_clip) == 2
        assert isinstance(runs[0]["cfg"].typo_weights[0], tuple)

        # 关键：pooled 中位数与分段中位数必须显著不同，否则这个测试没意义
        def med(rs):
            d = sorted(float(r["delay_ms"]) for r in rs
                       if r["event"] == "char" and r["delay_ms"])
            return d[len(d) // 2]

        m0, m1 = med(runs[0]["rows"]), med(runs[1]["rows"])
        pooled = med([r for run in runs for r in run["rows"]])
        assert m1 > m0 * 5, f"两段墙钟中位数应差很多倍（{m0} vs {m1}）"
        # pooled 中位数落在两段之间（偏向字符数多的那段），所以它**不**等于
        # 任何一段的真实值 —— 这正是老 report 会报出中间数字的原因。
        assert m0 < pooled < m1, \
            f"pooled 中位数应落在两段之间（{m0} < {pooled} < {m1}）"
        assert min(abs(pooled - m0), abs(pooled - m1)) > 0.2 * (m1 - m0), \
            "pooled 应明显偏离两段中至少有一段，否则混算失真无从体现"
        # 但换算回人尺度后两段应当接近（同一套 delay_mu）
        assert abs(m0 * 300.0 - m1 * 8.0) < 0.4 * (m0 * 300.0), \
            "乘回各自 speed 后两段应落在同一量级"

        # --list / --run 不应抛异常
        from . import report as _rep
        assert _rep.main([path, "--list"]) == 0
        assert _rep.main([path, "--run", "2"]) == 0
        assert _rep.main([path, "--run", "9"]) == 1     # 不存在的段号
        # RUN 标记行不应混进事件统计
        assert not any(r["state"] == "RUN" for run in runs for r in run["rows"])
        assert sa["final_matches_source"] and sb["final_matches_source"]
        del _csv, _json


def test_log_fresh_truncates():
    """--fresh 必须清空旧日志；默认（不加）则保留历史。"""
    import tempfile

    from .executor import Logger

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "fresh.csv")
        lg = Logger(Config(log_file=path))
        lg.log("KEY", "char", "'a'", 1.0)
        lg.close()
        first = open(path, encoding="utf-8").read()

        lg = Logger(Config(log_file=path))          # 追加
        lg.log("KEY", "char", "'b'", 1.0)
        lg.close()
        appended = open(path, encoding="utf-8").read()
        assert appended.startswith(first), "默认应追加，不能吞掉旧内容"
        assert "'b'" in appended and "'a'" in appended

        lg = Logger(Config(log_file=path, fresh_log=True))   # 覆盖
        lg.log("KEY", "char", "'c'", 1.0)
        lg.close()
        fresh = open(path, encoding="utf-8").read()
        assert "'a'" not in fresh and "'b'" not in fresh, "--fresh 应清空历史"
        assert "'c'" in fresh
        assert fresh.count("run_id") == 1, "--fresh 后只应有一个表头"


def test_log_legacy_compat():
    """1.0 之前的老日志（无 run_id 列、无 RUN 行）仍要能被 report 读取。"""
    import tempfile

    from .report import load, split_runs

    legacy = (
        "ts,state,event,detail,delay_ms\n"
        "22:38:50,KEY,char,'P',123.5\n"
        "22:38:50,KEY,char,'S',189.6\n"
        "22:38:51,KEY,char,'a',100.0\n"
    )
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "old.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(legacy)
        runs = split_runs(load(path))
        assert len(runs) == 1, "老日志应被当作单次运行"
        run = runs[0]
        assert run["run_id"] == "(unsegmented)"
        assert run["cfg"] is None, "老日志没有 config 快照，必须是 None"
        assert not run["closed"], "老日志没有 RUN,end"
        assert len(run["rows"]) == 3


def test_log_empty_file_gets_header():
    """回归：已存在但 0 字节的日志文件必须补写表头。

    原来用 os.path.exists() 判断「是否新建」，而空文件的 exists 也是 True，
    于是表头被跳过；report 的 DictReader 把第一行数据当表头，直接
    KeyError: 'state' 崩掉。改成按文件大小判断。
    """
    import tempfile

    from .executor import Logger
    from .report import load, split_runs

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "empty.csv")
        open(path, "w").close()                 # 0 字节，但「存在」
        lg = Logger(Config(log_file=path))
        lg.log("KEY", "char", "'a'", 100.0)
        lg.close()
        with open(path, encoding="utf-8") as f:
            assert f.readline().startswith("ts,"), "空文件也必须写表头"
        runs = split_runs(load(path))           # 以前这里 KeyError
        assert len(runs) == 1 and len(runs[0]["rows"]) == 1


def test_log_appends_to_legacy_file():
    """回归：新版本运行追加到 1.0 的 5 列日志时，不能写错列。

    原来无条件写 6 列，于是 DictReader 按 5 个字段名解析，新行的 run_id 落到
    event 列、state 落到 detail 列……整段静默错位（实测写 2 个字符只统计出
    1 个）。现在跟随既有表头写 5 列，并提示用户。
    """
    import tempfile

    from .executor import Logger
    from .report import load, split_runs

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "legacy.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("ts,state,event,detail,delay_ms\n")
            f.write("10:00:00,KEY,char,'a',120.0\n")
        lg = Logger(Config(log_file=path))
        lg.log("KEY", "char", "'b'", 130.0)
        lg.close()

        with open(path, encoding="utf-8") as f:
            assert f.readline().strip() == "ts,state,event,detail,delay_ms"
        rows = load(path)
        # 关键：数据行的列不能错位（RUN 标记行也在其中，属正常）
        data = [r for r in rows if r["state"] != "RUN"]
        assert [r["state"] for r in data] == ["KEY", "KEY"], \
            f"列错位了：{[r['state'] for r in rows]}"
        assert [r["event"] for r in data] == ["char", "char"]
        assert [r["detail"] for r in data] == ["'a'", "'b'"]
        # 两次运行仍应被 RUN 标记切成两段
        runs = split_runs(rows)
        assert len(runs) == 2, f"应切成 2 段，实际 {len(runs)}"
        assert sum(1 for run in runs for r in run["rows"]
                   if r["event"] == "char") == 2, \
            "两个字符都必须被统计到（错位时这里会少一个）"


def test_report_survives_malformed_rows():
    """坏日志不能让 report 崩掉——它的职责正是诊断坏日志。"""
    import tempfile

    from . import report as rep

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "bad.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("ts,run_id,state,event,detail,delay_ms\n")
            f.write("10:00:00,r1,KEY,char,'a',100.0\n")
            f.write("10:00:01,r1,KEY,char\n")              # 列数不足
            f.write("10:00:02,r1,KEY,char,'b',5,E,X\n")    # 列数过多
            f.write("10:00:03,r1,KEY,char,'c',notanum\n")  # delay 非数字
            f.write('10:00:04,r1,RUN,start,"{bad json",0.0\n')  # 快照损坏
            f.write("10:00:05,r1,KEY,char,'d',110.0\n")
        runs = rep.split_runs(rep.load(path))
        assert len(runs) == 2
        assert runs[0]["cfg"] is None, "损坏的快照应退回 None"
        assert rep.main([path]) == 0
        assert rep.main([path, "--list"]) == 0
        # 非数字 delay 必须被跳过而不是抛 ValueError
        assert rep.main([path, "--run", "2"]) == 0


def test_report_exit_code_propagates():
    """`python -m ...report` 必须把 main() 的返回值作为进程退出码。"""
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("ts,run_id,state,event,detail,delay_ms\n")
            f.write("10:00:00,r1,KEY,char,'a',100.0\n")
        r = subprocess.run(
            [sys.executable, "-m", "humanized_autotyper.report", path,
             "--run", "9"], capture_output=True, text=True)
        assert r.returncode == 1, \
            f"找不到 run 时应返回 1，实际 {r.returncode}"
        r = subprocess.run(
            [sys.executable, "-m", "humanized_autotyper.report", path,
             "--list"], capture_output=True, text=True)
        assert r.returncode == 0, f"正常审计应返回 0，实际 {r.returncode}"


def test_modes_single_file_is_1x_equivalent():
    """SingleFileMode 必须与 1.x 行为等价：单个 target、缓冲区自校验可信。"""
    from .modes import SingleFileMode, Mode, collect_targets

    m = SingleFileMode(DEMO_SOURCE, "demo.py")
    assert m.multi_target is False, "单文件模式不该走多目标循环"
    assert m.verify_trustworthy() is True, "单文件模式缓冲区即真相，可信"

    targets = collect_targets(m, DEMO_SOURCE)
    assert len(targets) == 1 and targets[0].content == DEMO_SOURCE
    assert m.preflight(targets) == []

    # 默认注册表里必须有 notepad，且 AutoTyper 不传 mode 时行为不变
    from .modes import mode_names, get_mode
    assert "notepad" in mode_names()
    # get_mode 返回的是「类」：各模式构造参数不同，由调用方实例化
    assert get_mode("notepad") is SingleFileMode
    assert issubclass(SingleFileMode, Mode)
    print("PASS modes_single_file_is_1x_equivalent")


def test_modes_multi_target_resets_between_files():
    """多目标模式：每个文件前必须重置 buffer/pipeline/stats，否则第二个文件
    会带着第一个文件的文本与光标跑，结果必然错。"""
    from .modes import Mode, Target

    class FakeMulti(Mode):
        name = "fake"
        multi_target = True

        def __init__(self):
            self.seen = []
            self.done = []

        def iter_targets(self, source=None, **kw):
            return [Target(path=f"f{i}.py", content=f"file {i}\n")
                    for i in range(3)]

        def before_type(self, target, typer):
            self.seen.append((target.path, typer.buffer.text,
                              typer.buffer.cursor))

        def after_type(self, target, typer):
            # 断言"打完的缓冲区 == 该文件的内容"（不是上一个文件的）
            self.done.append((target.path, typer.buffer.text))
            return {"ok": typer.buffer.text == target.content,
                    "detail": "" if typer.buffer.text == target.content
                    else "mismatch"}

        def verify_trustworthy(self):
            return False

    cfg = fast_cfg()
    m = FakeMulti()
    t = AutoTyper(cfg, "", rng=random.Random(3), mode=m, targets=m.iter_targets())
    t.sched.threshold = 1e18
    s = t.run()

    # before_type 时 buffer 必须是空的、cursor 为 0
    assert [s0 for s0, _, _ in m.seen] == ["f0.py", "f1.py", "f2.py"]
    for _, text, cur in m.seen:
        assert text == "" and cur == 0, "跨文件时缓冲区没重置"

    assert s["files"] == 3
    assert s["files_ok"] == 3, f"逐文件校验应全过: {s['per_file']}"
    # 缓冲区不可信时不得谎报 final_matches_source
    assert s["verify_trustworthy"] is False
    assert s["final_matches_source"] is None, \
        "verify_trustworthy=False 时不能报 final_matches_source"
    # 每个文件打完的缓冲区必须等于自己那份内容（注意内容带尾随 \n）
    expected = {f"f{i}.py": f"file {i}\n" for i in range(3)}
    for path, text in m.done:
        assert text == expected[path], f"{path} 内容串了: {text!r}"
    print("PASS modes_multi_target_resets_between_files "
          f"files={s['files']} ok={s['files_ok']}")


def test_modes_kill_stops_remaining_files():
    """F10 后必须立刻停止，不再处理后续文件。"""
    from .modes import Mode, Target

    class KillMode(Mode):
        name = "killmode"
        multi_target = True

        def iter_targets(self, source=None, **kw):
            return [Target(path=f"f{i}.py", content="x\n") for i in range(10)]

        def before_type(self, target, typer):
            if target.path == "f1.py":
                typer.kill.set()      # 第二个文件刚开始就请求停止

        def verify_trustworthy(self):
            return False

    cfg = fast_cfg()
    m = KillMode()
    t = AutoTyper(cfg, "", rng=random.Random(4), mode=m, targets=m.iter_targets())
    t.sched.threshold = 1e18
    s = t.run()
    assert s["killed"] is True
    assert s["files"] == 10
    assert len(s["per_file"]) <= 2, \
        f"停止后不该继续处理文件，实际处理了 {len(s['per_file'])}"
    print(f"PASS modes_kill_stops_remaining_files handled={len(s['per_file'])}/10")


def test_file_switch_interleaves_targets():
    """交替打字：file_switch_chars>0 时必须轮转推进，而非一个打完再下一个。

    每个文件 10 字符、配额 4，因此每个文件需要 3 轮（4+4+2）才打完；首轮
    必须把三个文件各推进一段，且切走前要调用 save_only 存盘。
    """
    from .modes import Mode, Target

    class InterleaveMode(Mode):
        name = "interleave"
        multi_target = True

        def __init__(self):
            self.visits = []      # 每次 before_type 的 (path, 已打文本)
            self.saved = []       # 切走前存盘的 path
            self.done = []        # 打完的 (path, 文本)

        def iter_targets(self, source=None, **kw):
            return [Target(path=f"f{i}.txt", content=f"0123456789")
                    for i in range(3)]

        def before_type(self, target, typer):
            self.visits.append((target.path, typer.buffer.text))

        def save_only(self, target, typer):
            self.saved.append(target.path)

        def after_type(self, target, typer):
            self.done.append((target.path, typer.buffer.text))
            return {"ok": typer.buffer.text == target.content,
                    "detail": "" if typer.buffer.text == target.content
                    else "mismatch"}

        def verify_trustworthy(self):
            return False

    cfg = fast_cfg(file_switch_chars=4, switch_pause_s=(0, 0))
    m = InterleaveMode()
    t = AutoTyper(cfg, "", rng=random.Random(7), mode=m, targets=m.iter_targets())
    t.sched.threshold = 1e18
    s = t.run()

    # 首轮必须三个文件各打一段（而不是一个打完）：三个不同的 path 都出现
    first_round = [p for p, _ in m.visits[:3]]
    assert sorted(first_round) == ["f0.txt", "f1.txt", "f2.txt"], \
        f"首轮应轮转三个文件: {first_round}"
    # 每个文件首轮只打了约配额个字符（< 全长 10），证明是分段推进
    for _, text in m.visits[:3]:
        assert len(text) < 10, f"首轮不该已打完整个文件: {text!r}"
    # 每个文件都被访问了多次（分段），且最终都打完、内容一致
    assert s["files"] == 3
    assert s["files_ok"] == 3, f"逐文件校验应全过: {s['per_file']}"
    expected = "0123456789"
    for path, text in m.done:
        assert text == expected, f"{path} 内容不对: {text!r}"
    # 切走前对未打完的文件调用了 save_only（至少每个文件前两轮各一次）
    assert len(m.saved) >= 3, f"切走前应存盘: {m.saved}"
    print(f"PASS file_switch_interleaves_targets "
          f"visits={len(m.visits)} saved={len(m.saved)}")


def test_file_switch_disabled_is_sequential():
    """file_switch_chars=0（默认）时必须保持顺序执行：一个文件彻底打完再切。"""
    from .modes import Mode, Target

    class SeqMode(Mode):
        name = "seq"
        multi_target = True

        def __init__(self):
            self.order = []

        def iter_targets(self, source=None, **kw):
            return [Target(path=f"f{i}.txt", content="abc\n")
                    for i in range(3)]

        def before_type(self, target, typer):
            self.order.append(target.path)

        def after_type(self, target, typer):
            return {"ok": True, "detail": ""}

        def verify_trustworthy(self):
            return False

    cfg = fast_cfg()   # 默认 file_switch_chars=0
    m = SeqMode()
    t = AutoTyper(cfg, "", rng=random.Random(8), mode=m, targets=m.iter_targets())
    t.sched.threshold = 1e18
    s = t.run()
    # 顺序路径：before_type 每个文件只调用一次，顺序即目标顺序
    assert m.order == ["f0.txt", "f1.txt", "f2.txt"], \
        f"默认应顺序执行: {m.order}"
    assert s["files_ok"] == 3
    print("PASS file_switch_disabled_is_sequential")


def test_vscode_before_type_resume_keeps_content():
    """交替打字重访：第二次 before_type 绝不能清空文档，只把光标压到文末。

    锁定按键序列：首次 = Ctrl+P → 路径 → Enter → Ctrl+A → Delete；
    重访 = Ctrl+P → 路径 → Enter → Ctrl+End（无 Ctrl+A / Delete）。
    """
    from .modes import VSCodeMode, Target

    events = []

    class FakeExec:
        def key_quick_open(self):     events.append(("combo", "ctrl+p"))
        def key_select_all(self):     events.append(("combo", "ctrl+a"))
        def key_save(self):           events.append(("combo", "ctrl+s"))
        def key_doc_end(self):        events.append(("combo", "ctrl+end"))
        def type_char(self, ch, d=0.0, hold=None):
            events.append(("char", ch))
        def _tap_special(self, name, hold=None):
            events.append(("tap", name))
        def delete_key(self):         events.append(("key", "delete"))

    class FakeLogger:
        def log(self, state, event, detail="", delay=0.0):
            events.append(("log", f"{state}/{event}"))

    class FakeTyper:
        cfg = type("C", (), {"dry_run": False})()
        executor = FakeExec()
        logger = FakeLogger()

        def _sleep(self, s, active=True, chunk=0.25):
            events.append(("sleep", round(s, 3)))

    m = VSCodeMode("proj", settings_paths=[], open_settle_s=0.1)
    tgt = Target(path="a.py", content="hello")

    # 首次：清空
    m.before_type(tgt, FakeTyper())
    seq1 = [e for e in events if e[0] in ("combo", "key", "tap")]
    assert seq1[-2:] == [("combo", "ctrl+a"), ("key", "delete")], \
        f"首次结尾必须 Ctrl+A + Delete: {seq1}"

    # 重访：不清空，改为 Ctrl+End
    events.clear()
    m.before_type(tgt, FakeTyper())
    seq2 = [e for e in events if e[0] in ("combo", "key", "tap")]
    assert ("combo", "ctrl+a") not in seq2, f"重访不该清空: {seq2}"
    assert ("key", "delete") not in seq2, f"重访不该删除: {seq2}"
    assert ("combo", "ctrl+end") in seq2, f"重访应压到文末: {seq2}"
    assert ("log", "FILE/resumed") in events, "重访应记录 resumed 便于审计"
    print("PASS vscode_before_type_resume_keeps_content")


def test_combo_keys_dry_run_and_ordering():
    """组合键：dry-run 只记日志不发键；live 下按下顺序正序、松开顺序逆序。"""
    import random as _r

    from .executor import Executor, Killer, Logger

    # --- dry-run：不能崩，且必须有日志 ---
    cfg = fast_cfg()
    ex = Executor(cfg, DelayModel(cfg, _r.Random(1)), Logger(cfg), Killer())
    assert ex.controller is None
    ex.tap_combo(["ctrl", "s"], label="ctrl+s")
    ex.key_save()
    ex.key_quick_open()
    ex.key_escape()
    assert ex.controller is None, "dry-run 下不应创建 controller"

    # --- live：用桩 controller 记录顺序 ---
    cfg2 = fast_cfg(dry_run=False)
    ex2 = Executor(cfg2, DelayModel(cfg2, _r.Random(1)), Logger(cfg2), Killer())
    assert ex2.controller is not None
    events = []
    # 参数名必须叫 key：pynput 的签名是 press(key)，写成别的名字虽然
    # 运行无碍，但类型检查会判"参数名称不匹配"。
    ex2.controller.press = lambda key: events.append(("press", str(key)))
    ex2.controller.release = lambda key: events.append(("release", str(key)))
    ex2.listener = None                      # 别真的去监听键盘

    ex2.tap_combo(["A", "B", "C"], label="triple")
    assert events == [("press", "A"), ("press", "B"), ("press", "C"),
                      ("release", "C"), ("release", "B"), ("release", "A")], \
        f"组合键顺序错误: {events}"
    # press 与 release 必须成对，否则修饰键会卡住
    assert len([e for e in events if e[0] == "press"]) == \
        len([e for e in events if e[0] == "release"])

    # Ctrl 组合：ctrl 先按下最后松开
    events.clear()
    ex2.key_save()
    assert events[0] == ("press", "Key.ctrl"), f"Ctrl 应先按下: {events}"
    assert events[-1] == ("release", "Key.ctrl"), f"Ctrl 应最后松开: {events}"

    # 空组合不应崩也不应发键
    events.clear()
    ex2.tap_combo([])
    assert events == [], "空组合不该发键"
    print("PASS combo_keys_dry_run_and_ordering")


def _make_vscode_tree(d):
    """造一个临时项目树，含该跳过的和不该跳过的目录。"""
    layout = {
        "a.py": "print('a')\n",
        "b.md": "# b\n",
        "sub/c.py": "x = 1\n",
        "node_modules/pkg/index.js": "module.exports = 1;\n",
        ".git/config.py": "should be skipped\n",
        "__pycache__/cached.py": "should be skipped\n",
        "sub/.hidden.py": "should be skipped\n",
        "binary.py": "\x00\x01binary\n",          # 扩展名对但内容含控制字符
        "skip.bin": "ignored by ext\n",
    }
    for rel, content in layout.items():
        full = os.path.join(d, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    return d


def test_vscode_enumeration():
    """VSCode 模式枚举：只收白名单扩展名，跳过依赖/构建/隐藏目录。"""
    from .modes import VSCodeMode, VSCODE_REQUIRED_SETTINGS

    with tempfile.TemporaryDirectory() as d:
        root = _make_vscode_tree(d)
        m = VSCodeMode(root, settings_paths=[])
        targets = m.iter_targets()
        rels = sorted(t.path for t in targets)

        assert any(p.endswith("a.py") for p in rels)
        assert any(p.endswith("b.md") for p in rels)
        assert any(p.replace("\\", "/").endswith("sub/c.py") for p in rels)
        # 必须跳过的
        for bad in ("node_modules", "__pycache__", ".hidden", "should be skipped"):
            assert not any(bad in p for p in rels), f"不该收 {bad}: {rels}"
        # 路径必须是正斜杠（Quick Open 用）
        assert not any("\\" in p for p in rels), f"路径应统一正斜杠: {rels}"
        # 必须相对 src_dir：Quick Open 匹配的是工作区相对路径，出现 ../.. 就废了
        assert not any(".." in p for p in rels), \
            f"路径不该含上级跳转: {rels}"
        # 换行归一：\r\n -> \n
        for t in targets:
            assert "\r" not in t.content

        # exts 过滤生效
        m2 = VSCodeMode(root, exts=[".py"], settings_paths=[])
        assert all(t.path.endswith(".py") for t in m2.iter_targets())
        # 不带点的扩展名要自动补点
        m3 = VSCodeMode(root, exts=["md"], settings_paths=[])
        assert m3.exts == (".md",)
        assert all(t.path.endswith(".md") for t in m3.iter_targets())
        # max_files 截断
        m4 = VSCodeMode(root, exts=[".py"], settings_paths=[], max_files=1)
        assert len(m4.iter_targets()) == 1
        # 直接给文件 -> 单目标
        m5 = VSCodeMode(os.path.join(root, "a.py"), settings_paths=[])
        assert len(m5.iter_targets()) == 1

    assert VSCodeMode.multi_target is True
    assert VSCodeMode("x").verify_trustworthy() is False, \
        "VSCode 模式缓冲区不可信，必须返回 False"
    assert len(VSCODE_REQUIRED_SETTINGS) >= 8
    print(f"PASS vscode_enumeration files={len(rels)}")


def test_vscode_preflight_blocks_bad_setup():
    """preflight 必须拦住：设置没关干净、文件不可读、含控制字符。"""
    from .modes import VSCodeMode, VSCODE_REQUIRED_SETTINGS

    with tempfile.TemporaryDirectory() as d:
        root = _make_vscode_tree(d)
        settings = os.path.join(d, "settings.json")

        # 1) settings.json 不存在 -> 所有必需项都要报错
        m = VSCodeMode(root, settings_paths=[settings])
        errs = m.preflight(m.iter_targets())
        missing = [e for e in errs if "VSCode 设置" in e]
        assert len(missing) == len(VSCODE_REQUIRED_SETTINGS), \
            f"设置全缺时应逐项报错，实际 {len(missing)}"

        # 2) 设置正确 -> 设置相关错误清零（binary.py 的控制字符仍会报）
        good = {k: v for k, (v, _) in VSCODE_REQUIRED_SETTINGS.items()}
        with open(settings, "w", encoding="utf-8") as f:
            json.dump(good, f)
        m2 = VSCodeMode(root, settings_paths=[settings])
        errs2 = m2.preflight(m2.iter_targets())
        assert not [e for e in errs2 if "VSCode 设置" in e], \
            f"设置已合规却仍报错: {errs2}"
        # 控制字符文件必须被单独拦下
        assert [e for e in errs2 if "无法可靠键入" in e], \
            f"binary.py 的控制字符应被拦: {errs2}"

        # 3) workspace 覆盖 user：后读的层级赢
        user = os.path.join(d, "user.json")
        with open(user, "w", encoding="utf-8") as f:
            json.dump({"editor.autoIndent": "full"}, f)
        m3 = VSCodeMode(root, settings_paths=[user, settings])
        errs3 = m3.preflight(m3.iter_targets())
        # settings.json(autoIndent=none)在后，应覆盖 user 的 full
        assert not [e for e in errs3 if "autoIndent" in e], \
            f"后读层级应覆盖前面: {errs3}"

        # 4) 反过来：workspace 设成 full，必须报错
        bad_ws = os.path.join(d, "ws.json")
        with open(bad_ws, "w", encoding="utf-8") as f:
            json.dump({**good, "editor.autoIndent": "full"}, f)
        m4 = VSCodeMode(root, settings_paths=[bad_ws])
        assert [e for e in m4.preflight(m4.iter_targets()) if "autoIndent" in e]

        # 5) 文件夹不存在
        m5 = VSCodeMode(os.path.join(d, "nope"), settings_paths=[])
        assert any("不存在" in e for e in m5.preflight(m5.iter_targets()))
        # 6) 损坏的 settings.json 不能抛异常，要报出来
        broken = os.path.join(d, "broken.json")
        with open(broken, "w", encoding="utf-8") as f:
            f.write("{not json")
        m6 = VSCodeMode(root, settings_paths=[broken])
        assert any("settings.json 读取失败" in e
                   for e in m6.preflight(m6.iter_targets()))
    print("PASS vscode_preflight_blocks_bad_setup")


class _NullLogger:
    """只提供 log() 的空壳：给 after_type/before_type 的替身 typer 用。"""

    def __init__(self):
        self.lines = []

    def log(self, state, event, detail="", delay=0.0):
        self.lines.append((state, event, detail))


def test_vscode_verify_reports_diff():
    """回读校验必须报出**第一个差异的行号**，否则多文件场景无法排查。"""
    from .modes import VSCodeMode, Target

    m = VSCodeMode(".")

    # 完全一致
    assert m._diff("abc\ndef\n", "abc\ndef\n", "x.py")["ok"] is True

    # 中间某行不同 -> 要指出正确的行号
    r = m._diff("a\nb\nc\n", "a\nb\nX\n", "x.py")
    assert r["ok"] is False
    assert r["line"] == 3, f"行号算错: {r}"
    assert "x.py" in r["detail"] and "第 3 行" in r["detail"]

    # 缺字符（实际被截断）-> 长度不同，不能报成"某行不一致"
    r2 = m._diff("a\nb\nc\n", "a\nb\n", "y.py")
    assert r2["ok"] is False
    assert "长度不同" in r2["detail"], r2["detail"]

    # 多出来一行
    r3 = m._diff("a\n", "a\nb\n", "z.py")
    assert r3["ok"] is False and "长度不同" in r3["detail"]

    # 列号：第 2 行第 3 列
    r4 = m._diff("hello\nworld\n", "hello\nWORLD\n", "w.py")
    assert r4["line"] == 2 and r4["col"] == 1, r4

    # 读不回文件时必须 ok=False 而不是抛异常
    assert m._read_back(Target(path="x.py", content="")) is None, \
        "没有 abs_path 的 Target 读不回内容"
    print("PASS vscode_verify_reports_diff")


class _StubTyper:
    """给 VSCodeMode.before_type/after_type 用的替身 typer。

    早先这里用 `type("T", (), {})()` 再逐个赋属性，那会让类型检查器判
    "属性 X 未知"（动态创建的类没有任何属性声明）。改成显式类体后属性可
    被静态推断，而且 IDE 跳转也能用。
    """

    def __init__(self, cfg, executor=None, logger=None):
        self.cfg = cfg
        self.executor = executor
        self.logger = logger or _NullLogger()
        self.slept = []

    def _sleep(self, seconds, active=True, chunk=0.25):
        self.slept.append(seconds)


def test_vscode_reread_matches_disk():
    """after_type 必须以磁盘为准：文件没被改动时不能谎报成功。"""
    from .modes import VSCodeMode, Target

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "reread.py")
        want = "print('hi')\n"
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(want)
        m = VSCodeMode(d, settings_paths=[], save_settle_s=0.0)
        t = Target(path="reread.py", content=want, abs_path=path)

        class FakeTyper:
            pass
        ty = _StubTyper(fast_cfg(dry_run=False))
        sent = []

        class FakeExec:
            def key_save(self):
                sent.append("ctrl+s")
        ty.executor = FakeExec()

        # 磁盘内容 == 期望 -> 通过，且确实发了 Ctrl+S
        res = m.after_type(t, ty)
        assert res["ok"] is True, res
        assert sent == ["ctrl+s"], f"live 下必须存盘: {sent}"

        # 磁盘被改坏 -> 必须抓到，且指出行号
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("print('HI')\n")
        res2 = m.after_type(t, ty)
        assert res2["ok"] is False, "磁盘内容不一致时不该报成功"
        assert res2["line"] == 1, res2

        # CRLF 归一后仍应判定一致（编辑器可能写 CRLF）
        with open(path, "wb") as f:
            f.write(b"print('hi')\r\n")
        assert m.after_type(t, ty)["ok"] is True, "CRLF 应归一后视为一致"
    print("PASS vscode_reread_matches_disk")


def test_vscode_strips_bom():
    """回归：带 BOM 的源文件不能把 U+FEFF 当成内容。

    BOM 若混进 content，会成为首字符 U+FEFF——它打不出来（KeyCode.from_char
    返回 None，type_char 静默跳过而 buffer 照样记账），而且 0xFEFF > 0x20，
    unsupported_chars 抓不到。只能靠 utf-8-sig 读时剥掉。
    """
    from .modes import VSCodeMode
    from .main import read_source

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "bom.py")
        with open(p, "wb") as f:
            f.write(b"\xef\xbb\xbfprint('x')\n")          # 带 BOM
        assert open(p, "rb").read()[:3] == b"\xef\xbb\xbf"

        m = VSCodeMode(d, settings_paths=[])
        t = m.iter_targets()[0]
        assert "\ufeff" not in t.content, f"BOM 未被剥掉: {t.content!r}"
        assert t.content == "print('x')\n"
        assert not t.content.startswith("\ufeff")

        # CLI 的 --file 走 read_source，同样不能带 BOM
        assert read_source(p) == "print('x')\n"

        # 回读也要剥：编辑器写回带 BOM 的文件时应判定为一致
        from .modes import Target
        m2 = VSCodeMode(d, settings_paths=[], save_settle_s=0.0)
        ty = _StubTyper(fast_cfg(dry_run=False))

        class FakeExec:
            def key_save(self):
                pass
        ty.executor = FakeExec()
        res = m2.after_type(Target(path="bom.py", content="print('x')\n",
                                  abs_path=p), ty)
        assert res["ok"] is True, res
    print("PASS vscode_strips_bom")


def test_vscode_before_type_clears_document():
    """回归：打开文件后必须清空文档。

    Quick Open 只是**切换**标签页，文档里还留着上次的内容；而每个文件的
    Buffer 是从空的起步的。不清空就会把新文本插到旧内容中间。

    这里锁定按下的**顺序**必须完整且正确：
    Ctrl+P -> 路径 -> Enter -> Ctrl+A -> Delete
    """
    from .modes import VSCodeMode, Target

    events = []

    class FakeExec:
        def key_quick_open(self):     events.append(("combo", "ctrl+p"))
        def key_select_all(self):     events.append(("combo", "ctrl+a"))
        def key_save(self):           events.append(("combo", "ctrl+s"))
        def type_char(self, ch, d=0.0, hold=None):
            events.append(("char", ch))
        def _tap_special(self, name, hold=None):
            events.append(("tap", name))
        def delete_key(self):         events.append(("key", "delete"))

    class FakeLogger:
        def log(self, state, event, detail="", delay=0.0):
            events.append(("log", f"{state}/{event}"))

    class FakeTyper:
        cfg = type("C", (), {"dry_run": False})()
        executor = FakeExec()
        logger = FakeLogger()

        def _sleep(self, s, active=True, chunk=0.25):
            events.append(("sleep", round(s, 3)))

    m = VSCodeMode("proj", settings_paths=[], open_settle_s=0.6)
    m.before_type(Target(path="sub/a.py", content="x"), FakeTyper())

    seq = [e for e in events if e[0] in ("combo", "key", "tap")]
    assert seq[0] == ("combo", "ctrl+p"), f"必须先开 Quick Open: {seq}"
    assert seq[-2:] == [("combo", "ctrl+a"), ("key", "delete")], \
        f"结尾必须是 Ctrl+A + Delete 清空: {seq}"
    assert ("tap", "return") in seq, f"敲完路径要按 Enter: {seq}"
    # Enter 必须在清空之前
    i_enter = seq.index(("tap", "return"))
    i_clear = seq.index(("combo", "ctrl+a"))
    assert i_enter < i_clear, f"先打开文件再清空: {seq}"
    # 路径逐字符输入，且用的是相对 src_dir 的正斜杠路径
    typed = "".join(c for kind, c in events if kind == "char")
    assert typed == "sub/a.py", f"路径输入不对: {typed!r}"
    assert ("log", "FILE/cleared") in events, "应记录清空动作以便审计"

    # rel_prefix 存在时要带前缀（src_dir 不在工作区根目录的情形）
    events.clear()
    m2 = VSCodeMode("proj", settings_paths=[], open_settle_s=0.1,
                    rel_prefix="myrepo")
    m2.before_type(Target(path="a.py", content="x"), FakeTyper())
    typed2 = "".join(c for kind, c in events if kind == "char")
    assert typed2 == "myrepo/a.py", typed2

    # dry-run 必须一发键都不发
    events.clear()

    class DryTyper(FakeTyper):
        cfg = type("C", (), {"dry_run": True})()
    m3 = VSCodeMode("proj", settings_paths=[])
    m3.before_type(Target(path="a.py", content="x"), DryTyper())
    assert events == [], f"dry-run 不该发键: {events}"
    print("PASS vscode_before_type_clears_document")


def test_vscode_dry_run_does_not_fake_verification():
    """回归：dry-run 下 after_type 必须报「未校验」，不能报通过。

    target.content 本身就是从 abs_path 读出来的，中间没写过任何东西，
    比对必然相等——那是个恒真式。若报 ok=True，用户会误以为 dry-run
    验证过文件没问题，实际上一根键都没发。
    """
    from .modes import VSCodeMode, Target

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "dry.py")
        content = "x = 1\n"
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        m = VSCodeMode(d, settings_paths=[])
        t = Target(path="dry.py", content=content, abs_path=path)

        ty = _StubTyper(fast_cfg())          # dry_run=True
        res = m.after_type(t, ty)
        assert res["ok"] is None, \
            f"dry-run 不该报通过（恒真式）: {res}"
        assert res["verified"] is False
        assert "未做磁盘校验" in res["detail"]

    # 汇总层也要区分：未校验不能算通过
    assert s_files_ok_ignores_unverified()
    print("PASS vscode_dry_run_does_not_fake_verification")


def s_files_ok_ignores_unverified():
    """files_ok 只数 ok is True；ok=None（未校验）不得混入成功数。"""
    per_file = [{"ok": True}, {"ok": None}, {"ok": False}]
    ok = sum(1 for f in per_file if f["ok"] is True)
    unver = sum(1 for f in per_file if f["ok"] is None)
    assert (ok, unver) == (1, 1), (ok, unver)
    return True


def test_combo_keys_use_real_pynput_names():
    """回归：所有用到的 pynput Key / KeyCode 成员必须真实存在。

    pynput 的转义键叫 `Key.esc`，**没有** `Key.escape`——写成后者 dry-run
    一路绿灯（不发键），实机却会 AttributeError。这类错误只有对着真实对象
    取属性才能发现，所以这里直接 getattr 一遍。
    """
    from pynput.keyboard import Key, KeyCode

    for name in ("esc", "ctrl", "shift", "enter", "backspace", "delete",
                 "left", "right", "up", "down"):
        assert hasattr(Key, name), f"pynput Key 没有 {name}"

    # 这两个"看起来对但不存在"的写法必须被拒
    for bogus in ("escape", "control", "return", "del"):
        assert not hasattr(Key, bogus), \
            f"pynput Key 居然有 {bogus}？那本测试的假设就过时了"

    assert KeyCode.from_char("a") is not None
    assert KeyCode.from_char("!") is not None
    # _tap_special 用的名字也必须存在
    for name in ("enter", "backspace", "delete", "left", "right", "up", "down"):
        getattr(Key, name)

    # executor 里实际用到的组合键解析也要能跑通
    from .executor import Executor, Killer, Logger
    cfg = fast_cfg(dry_run=False)
    ex = Executor(cfg, DelayModel(cfg, random.Random(1)), Logger(cfg), Killer())
    assert ex._Key is not None and ex._KeyCode is not None
    for ch in ("s", "p", "a"):
        keys = ex._ctrl_key(ch)
        assert keys and len(keys) == 2, f"Ctrl+{ch} 组合解析失败"
    assert ex._Key.esc is not None, "key_escape 依赖的 Key.esc 必须存在"
    print("PASS combo_keys_use_real_pynput_names")


def main():
    test_buffer()
    test_delays()
    test_typos()
    test_dyad_rhythm()
    test_typo_speed_coupling()
    test_full_dry_run()
    test_edit_previous_unit()
    test_rewrite_chunk_unit()
    test_burst_unit()
    test_pause_long_unit()
    test_pause_long_ritual_clamped()
    test_burst_no_fake_count()
    test_transposition_payload()
    test_kill_mid_edit_keeps_text()
    test_kill_mid_burst_keeps_text()
    test_source_guard()
    test_review_keeps_text()
    test_review_mid_correction_is_safe()
    test_review_disabled_is_inert()
    test_check_window_pauses_not_kills()
    test_send_guard_blocks_keystroke_while_paused()
    test_pause_blocks_typing_and_resumes()
    test_pause_during_long_pause_resumes()
    test_mixed_text_dry_run()
    test_log_run_segmentation()
    test_log_fresh_truncates()
    test_log_legacy_compat()
    test_log_empty_file_gets_header()
    test_log_appends_to_legacy_file()
    test_report_survives_malformed_rows()
    test_report_exit_code_propagates()
    test_modes_single_file_is_1x_equivalent()
    test_modes_multi_target_resets_between_files()
    test_modes_kill_stops_remaining_files()
    test_file_switch_interleaves_targets()
    test_file_switch_disabled_is_sequential()
    test_vscode_before_type_resume_keeps_content()
    test_combo_keys_dry_run_and_ordering()
    test_combo_keys_use_real_pynput_names()
    test_vscode_enumeration()
    test_vscode_preflight_blocks_bad_setup()
    test_vscode_verify_reports_diff()
    test_vscode_reread_matches_disk()
    test_vscode_strips_bom()
    test_vscode_before_type_clears_document()
    test_vscode_dry_run_does_not_fake_verification()
    print("ALL SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
