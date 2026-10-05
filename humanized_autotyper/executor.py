import csv
import json
import os
import sys
import threading
import time
from typing import TYPE_CHECKING

from .config import Config
from .delays import DelayModel
from .keymap import SHIFT_SYMBOLS


class Killer:
    def __init__(self):
        self.event = threading.Event()
        self.pause_event = threading.Event()

    def set(self):
        self.event.set()

    def killed(self):
        return self.event.is_set()

    def request_pause(self):
        """请求暂停（例如前台窗口失焦）。可被 request_resume() 撤销。"""
        self.pause_event.set()

    def request_resume(self):
        self.pause_event.clear()

    def paused(self):
        return self.pause_event.is_set()


_RUN_SEQ = [0]


def _new_run_id():
    """每次运行一个唯一 id。

    光靠秒级时间戳不够：短文本连续跑两次（例如测试、冒烟）会落在同一秒里，
    两段的 run_id 就撞上了。补一个进程内自增序号 + pid 来保证唯一。
    """
    _RUN_SEQ[0] += 1
    return "%s-%d-%d" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid(),
                         _RUN_SEQ[0])


class Logger:
    """事件日志写入器。

    日志默认**追加**到 cfg.log_file。一个文件里可能累积多次运行，所以每次运行
    开头写一行 `RUN,start`（携带 run_id + 完整 config 快照），结尾写一行
    `RUN,end`。report.py 据此把文件切分成若干段，并且用**那次运行真实的
    config** 做 obs-vs-cfg 对照——否则多次运行的延迟/概率会混在一起，
    中位数与 CV 都会被污染（见 README「日志分段」）。

    老日志（1.0 之前，没有 RUN 行）仍可被 report 读取，只是被当作单次运行、
    config 退回默认值，并在输出里明确标注 unsegmented。
    """

    HEADER = ["ts", "run_id", "state", "event", "detail", "delay_ms"]
    # 只快照 report 对照时会用到的字段，避免把 log_file 之类的无关路径也写进去
    SNAPSHOT_FIELDS = (
        "p_typo", "typo_weights", "typo_detect_probs", "typo_autocorr_boost",
        "typo_autocorr_window", "typo_speed_exponent", "p_burst_enter",
        "burst_len_range", "burst_speed_factor", "p_backspace_burst",
        "backspace_n_range", "p_pause_short", "p_pause_short_sentence",
        "pause_short_clip", "long_pause_xmin", "long_pause_alpha",
        "long_pause_cap", "p_edit_previous", "edit_min_gap_s",
        "p_rewrite_chunk", "p_review", "delay_mu", "delay_ln_sigma",
        "delay_clip", "dyad_same_finger", "dyad_alt_hand", "fatigue_rate",
        "fatigue_cap", "warmup_factor", "warmup_chars", "speed_multiplier",
    )

    def __init__(self, cfg: Config, run_id=None):
        self.cfg = cfg
        self.run_id = run_id or _new_run_id()
        # os.devnull 在 Windows 上是 "nul"，os.path.exists 对它返回 True；
        # 追加模式打开它是合法的（写进去被丢弃），所以不需要特殊处理。
        # 注意要判断**大小**而不是 os.path.exists：文件被创建过但是 0 字节时
        # exists 为 True 而内容为空，此时若不写表头，report 的 DictReader 会把
        # 第一行数据当成表头，直接 KeyError 崩掉。
        fresh = getattr(cfg, "fresh_log", False)
        needs_header = fresh
        if not fresh:
            try:
                needs_header = os.path.getsize(cfg.log_file) == 0
            except OSError:
                needs_header = True       # 不存在 / 不可 stat -> 当新建处理
        # 已有文件的表头可能不是本版本的（例如 1.0 的 5 列日志）。若不管不顾地
        # 追加 6 列，DictReader 会按 5 个字段名解析每一行，新行的 run_id 落到
        # event 列、state 落到 detail 列……整段数据静默错位（实测 2 个字符只
        # 统计出 1 个）。所以这里跟随既有表头决定写几列。
        self._legacy_cols = False
        if not needs_header:
            try:
                with open(cfg.log_file, "r", encoding="utf-8",
                          newline="") as rf:
                    head = next(csv.reader(rf), [])
                if head and "run_id" not in head:
                    self._legacy_cols = True
            except (OSError, StopIteration, UnicodeDecodeError):
                self._legacy_cols = False
        self.fh = open(cfg.log_file, "w" if fresh else "a",
                       encoding="utf-8", newline="")
        self.writer = csv.writer(self.fh)
        # 表头只在「文件为空」或「--fresh 覆盖」时写；追加到已有内容时保留原表头，
        # 这样老日志（无 run_id 列）也能继续被 report 兼容读取。
        if needs_header:
            self.writer.writerow(self.HEADER)
        elif self._legacy_cols:
            print("WARNING: %s uses an older column layout (no run_id); "
                  "appending without run_id. Use --fresh or a different "
                  "--log path for per-run segmentation." % cfg.log_file)
        self.started_at = time.time()
        self.log("RUN", "start", self._snapshot_json(), 0.0)

    def _snapshot_json(self):
        snap = {k: getattr(self.cfg, k) for k in self.SNAPSHOT_FIELDS
                if hasattr(self.cfg, k)}
        try:
            return json.dumps(snap, sort_keys=True)
        except (TypeError, ValueError):
            return "{}"

    def log(self, state, event, detail="", delay_ms=0.0):
        if self.cfg.verbose and state != "RUN":
            print(f"[{state}] {event} {detail} {round(delay_ms, 1)}ms")
        if self.fh:
            # ts 保留 HH:MM:SS 以兼容老日志；run_id 列才是可靠的切分依据
            # （秒级时间戳会回绕，无法判断两行是否同属一次运行）。
            ts = time.strftime("%H:%M:%S")
            if self._legacy_cols:
                # 老表头没有 run_id 列：按 5 列写，保持列数与表头一致
                row = [ts, state, event, detail, round(delay_ms, 1)]
            else:
                row = [ts, self.run_id, state, event, detail,
                       round(delay_ms, 1)]
            self.writer.writerow(row)
            self.fh.flush()

    def mark_end(self, summary=None):
        """写 RUN,end 收尾行。summary 存成 JSON，便于 report 显示是否跑完。"""
        if not self.fh:
            return
        detail = ""
        if summary:
            try:
                detail = json.dumps(
                    {k: summary.get(k) for k in
                     ("chars", "source_consumed", "errors", "edits",
                      "rewrites", "final_matches_source", "killed",
                      "elapsed_s")},
                    sort_keys=True, default=str)
            except (TypeError, ValueError):
                detail = ""
        self.log("RUN", "end", detail, 0.0)

    def close(self):
        if self.fh:
            self.fh.close()
            self.fh = None


class Executor:
    # dry-run 下 pynput 不会被 import，所以这些属性只能声明成"可能是 None"。
    # 用 TYPE_CHECKING 下的注解，既不引入运行时依赖，又能让类型检查器知道
    # controller 真的有 press()/release()（之前只在 else 分支赋 None，被推断成
    # 纯 None 类型，于是每一处 .press()/.release() 都报
    # "press/release 不是 None 的已知属性"）。
    if TYPE_CHECKING:
        from pynput.keyboard import Controller, Key, KeyCode, Listener

        controller: "Controller | None"
        listener: "Listener | None"
        _Key: "type[Key] | None"
        _KeyCode: "type[KeyCode] | None"

    def __init__(self, cfg: Config, delays: DelayModel, logger: Logger, killer: Killer):
        self.cfg = cfg
        self.delays = delays
        self.log = logger
        self.kill = killer
        self.live = not cfg.dry_run
        self._started = False
        self._warned_mismatch = False
        # 先给默认值：dry-run 分支不会 import pynput，但属性必须存在，
        # 否则访问 self.controller 会 AttributeError。
        self.controller = None
        self._Key = None
        self._KeyCode = None
        self.listener = None
        if self.live:
            from pynput.keyboard import Controller, Key, Listener, KeyCode

            self._Key = Key
            self._KeyCode = KeyCode
            self.controller = Controller()
            self.listener = Listener(on_press=self._on_press)

    def _on_press(self, key):
        name = getattr(key, "name", "")
        if name == self.cfg.kill_hotkey:
            self.kill.set()

    def start(self):
        # 幂等：CLI 在倒计时前就武装 F10，run() 之后还会再调一次
        if self.live and not self._started and self.listener is not None:
            self._started = True
            self.listener.start()

    def stop(self):
        if self.live and self._started and self.listener is not None:
            self._started = False
            try:
                self.listener.stop()
            except Exception:
                pass

    def check_window(self):
        """校验前台窗口标题。不匹配时**暂停**（而不是中止），匹配后自动恢复。

        语义变更说明：以前这里失败就 kill.set()，等于"切走一次就彻底放弃"。
        但真实的人只是暂停打字、切回来继续，所以现在失焦 = 暂停，
        由 AutoTyper.run() 循环等待恢复；只有取不到窗口标题（非 Windows）
        或压根没配 expected_window_title 时才走拒绝/跳过。
        """
        if not self.live or not self.cfg.expected_window_title:
            return True
        if not sys.platform.startswith("win"):
            self.log.log("WINDOW", "unsupported_platform", sys.platform, 0)
            print("WARNING: --window validation needs Windows; refusing to start "
                  "because the foreground window cannot be verified.")
            self.kill.set()
            return False
        import ctypes

        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value
        except Exception as exc:      # 取不到标题就不该继续打字
            self.log.log("WINDOW", "read_failed", repr(exc), 0)
            title = ""
        ok = self.cfg.expected_window_title.lower() in title.lower()
        if ok:
            self.kill.request_resume()
            self._warned_mismatch = False
            return True
        if not self.kill.killed():
            self.kill.request_pause()
        if not self._warned_mismatch:
            print(f"WARNING: foreground window '{title}' does not match "
                  f"'{self.cfg.expected_window_title}' — pausing.")
            self._warned_mismatch = True
        return False

    def _sleep(self, seconds):
        time.sleep(max(0.0, seconds))

    def type_char(self, ch, delay_ms=0.0, hold=None):
        self.log.log("KEY", "char", repr(ch), delay_ms)
        # live 时这三个必然已由 __init__ 建好；这里显式判空既让类型检查器
        # 能收窄类型，也让"live 却缺 controller"时退化为不发键而不是崩掉。
        if self.controller is None or self._Key is None or self._KeyCode is None:
            return
        hold = self.delays.hold_time() if hold is None else hold
        if ch == "\n":
            self._tap_special("enter", hold)
            return
        shift = False
        base = ch
        # "İ" 这类字符 lower() 会变成两个码位，只能按原字符交给 pynput 直接注入
        if ch.isupper() and len(ch.lower()) == 1:
            base = ch.lower()
            shift = True
        elif ch in SHIFT_SYMBOLS:
            base = SHIFT_SYMBOLS[ch]
            shift = True
        key = self._KeyCode.from_char(base) if base != "" else None
        if key is None:
            return
        if shift:
            self.controller.press(self._Key.shift)
        self.controller.press(key)
        self._sleep(hold)
        self.controller.release(key)
        if shift:
            self.controller.release(self._Key.shift)

    def _tap_special(self, name, hold=None):
        self.log.log("KEY", "tap", name, 0)
        if self.controller is None or self._Key is None:
            return
        key = getattr(self._Key, name)
        self.controller.press(key)
        self._sleep(hold if hold is not None else self.delays.nav_delay())
        self.controller.release(key)

    def backspace(self):
        self._tap_special("backspace")

    def delete_key(self):
        self._tap_special("delete")

    def nav_left(self, n=1):
        for _ in range(n):
            self._tap_special("left")

    def nav_right(self, n=1):
        for _ in range(n):
            self._tap_special("right")

    def nav_up(self, n=1):
        for _ in range(n):
            self._tap_special("up")

    def nav_down(self, n=1):
        for _ in range(n):
            self._tap_special("down")

    def select_shift_down(self, n=1):
        self.log.log("SELECT", "shift+down", f"x{n}", 0)
        if self.controller is None or self._Key is None:
            return
        self.controller.press(self._Key.shift)
        for _ in range(n):
            self.controller.press(self._Key.down)
            self._sleep(self.delays.nav_delay())
            self.controller.release(self._Key.down)
        self.controller.release(self._Key.shift)

    def select_shift_right(self, n=1):
        self.log.log("SELECT", "shift+right", f"x{n}", 0)
        if self.controller is None or self._Key is None:
            return
        self.controller.press(self._Key.shift)
        for _ in range(n):
            self.controller.press(self._Key.right)
            self._sleep(self.delays.nav_delay())
            self.controller.release(self._Key.right)
        self.controller.release(self._Key.shift)
