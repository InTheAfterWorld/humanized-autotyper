"""gui.py — 人性化打字机图形界面。

用 tkinter 实现（Python 自带，无需安装依赖）。所有数值参数都是滑块，
适合非专业用户直接拖动调整：

    py gui.py            # 启动界面
    py gui.py --selftest # 无界面自检（构建控件、收集配置后退出）
"""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .config import Config
from .keymap import unsupported_chars
from .machine import AutoTyper
from .presets import PRESETS, preset_names

# 用户数据（内容 / 设置 / 日志）放当前工作目录：安装后代码位于只读的
# site-packages，不能往里写。从项目根目录启动时路径与重构前一致。
BASE_DIR = os.getcwd()
SOURCE_TXT = os.path.join(BASE_DIR, "source.txt")
SETTINGS_JSON = os.path.join(BASE_DIR, "gui_settings.json")

# --------------------------------------------------------------- 控件清单
# unit: raw=原值, %=百分比(/100), ms=毫秒(/1000), min=分钟(*60)
SLIDERS = {
    "run": [
        ("speed_multiplier", "整体速度倍率", 0.25, 5.0, 0.25, 1.0, "raw", 2),
    ],
    "rhythm": [
        ("delay_mu", "基础敲键间隔", 50, 300, 5, 110, "ms", 0),
        ("delay_ln_sigma", "节奏抖动(越大越随意)", 0.15, 0.9, 0.05, 0.42, "raw", 2),
        ("p_burst_enter", "突发快打概率", 0, 20, 0.5, 5.0, "%", 1),
        ("p_typo", "错字率", 0, 5, 0.1, 1.2, "%", 1),
        ("typo_autocorr_window", "手滑连错窗口(字符)", 0, 25, 1, 10, "raw", 0),
        ("fatigue_rate", "疲劳(每分钟变慢%)", 0, 2, 0.1, 0.5, "%", 1),
    ],
    "pause": [
        ("p_backspace_burst", "回删爆发频率", 0, 3, 0.1, 0.8, "%", 1),
        ("p_pause_short", "短停顿频率", 0, 5, 0.1, 0.8, "%", 1),
        ("pause_clip_hi", "短停顿上限(秒)", 1, 15, 0.5, 10.0, "raw", 1),
        ("long_pause_on", None, None, None, None, None, None, None),
        ("long_pause_xmin", "长暂停最短(分钟)", 2, 30, 1, 4, "min", 0),
        ("long_pause_cap", "长暂停上限(分钟)", 10, 45, 1, 35, "min", 0),
        ("p_edit_previous", "跳回前文重写频率", 0, 2, 0.1, 0.4, "%", 1),
        ("edit_min_gap_s", "两次跳回最少间隔(秒)", 0, 600, 10, 90, "sec", 0),
        ("p_rewrite_chunk", "整段重打频率", 0, 2, 0.1, 0.6, "%", 1),
    ],
}


def _conv(unit):
    return {"raw": lambda v: v, "%": lambda v: v / 100.0,
            "ms": lambda v: v / 1000.0, "min": lambda v: v * 60.0,
            "sec": lambda v: v}[unit]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Humanized Autotyper — 真人化打字机")
        self.minsize(720, 640)
        self.vars = {}          # field -> tk.Variable（滑块原始刻度值）
        self.labels = {}        # field -> 数值标签（程序化改值时要手动刷新）
        self.label_fmt = {}     # field -> 标签格式串
        self.q = queue.Queue()
        # typer 在 _start() 里创建，可能一直是 None（还没开始过）。显式标注成
        # AutoTyper | None，否则类型检查器只会推成 None，_on_close 里的
        # self.typer.kill.set() 就报「kill 不是 None 的已知属性」。
        self.typer: Optional[AutoTyper] = None
        self.running = False
        self._poll_id = None    # after() 句柄，关闭窗口时要取消
        self._cd_id = None
        self._tick_id = None    # 状态栏刷新定时器
        self._run_started = None
        self._src_len = 0
        self.long_on_var = tk.BooleanVar(value=True)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.tab_text = ttk.Frame(nb)
        self.tab_rhythm = ttk.Frame(nb)
        self.tab_pause = ttk.Frame(nb)
        self.tab_run = ttk.Frame(nb)
        for f, label in ((self.tab_text, "📝 内容"),
                         (self.tab_rhythm, "⌨️ 节奏与错误"),
                         (self.tab_pause, "⏸️ 停顿与删改"),
                         (self.tab_run, "▶️ 运行")):
            nb.add(f, text=label)

        self._build_text_tab()
        self._build_sliders(self.tab_rhythm, SLIDERS["rhythm"])
        self._build_sliders(self.tab_pause, SLIDERS["pause"])
        self._build_run_tab()
        self.status = tk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self.status, anchor="w",
                  relief="sunken").pack(fill="x", padx=8, pady=(4, 8))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._load_settings()

    # ---------------------------------------------------------- 内容页
    def _build_text_tab(self):
        bar = ttk.Frame(self.tab_text)
        bar.pack(fill="x", pady=(8, 4))
        ttk.Button(bar, text="从文件导入…", command=self._import_file)\
            .pack(side="left", padx=4)
        ttk.Button(bar, text="保存到 source.txt",
                   command=self._save_source).pack(side="left", padx=4)
        body = ttk.Frame(self.tab_text)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        ysb = ttk.Scrollbar(body, orient="vertical")
        self.txt = tk.Text(body, wrap="word", undo=True,
                           font=("Consolas", 11), height=18,
                           yscrollcommand=ysb.set)
        ysb.config(command=self.txt.yview)
        ysb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        try:
            with open(SOURCE_TXT, "r", encoding="utf-8") as f:
                self.txt.insert("1.0", f.read())
        except OSError:
            pass
        self.txt.bind("<KeyRelease>", lambda e: self._update_char_count())
        self.char_label = ttk.Label(self.tab_text, foreground="#666")
        self.char_label.pack(anchor="e", padx=8, pady=(0, 6))
        self._update_char_count()

    def _update_char_count(self):
        text = self.txt.get("1.0", "end").rstrip("\n")
        lines = text.count("\n") + 1 if text else 0
        self.char_label.config(text=f"{len(text)} 字符 / {lines} 行")

    def _import_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", f.read().replace("\r\n", "\n"))
        self._update_char_count()

    def _save_source(self):
        with open(SOURCE_TXT, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.txt.get("1.0", "end"))
        self.status.set(f"已保存到 {SOURCE_TXT}")

    # ---------------------------------------------------------- 参数页
    def _build_sliders(self, frame, defs):
        for i, (field, label, lo, hi, res, dft, unit, digits) \
                in enumerate(defs):
            if field == "long_pause_on":
                ttk.Checkbutton(
                    frame, variable=self.long_on_var,
                    text="启用长暂停（中途离开电脑几分钟～半小时再回来继续打）"
                ).grid(row=i, column=0, columnspan=2, sticky="w",
                       padx=14, pady=(14, 2))
                continue
            var = tk.DoubleVar(value=dft)
            self.vars[field] = var
            fmt = "{:." + str(digits) + "f}" + (
                "%" if unit == "%" else "ms" if unit == "ms" else "")
            row = ttk.Frame(frame)
            row.grid(row=i, column=0, columnspan=2, sticky="ew",
                     padx=10, pady=4)
            frame.columnconfigure(0, weight=1)
            ttk.Label(row, text=label, width=24).pack(side="left")
            val_lbl = ttk.Label(row, width=10, anchor="e",
                                foreground="#0066cc")
            scale = tk.Scale(row, orient="horizontal", variable=var,
                             from_=lo, to=hi, resolution=res,
                             showvalue=False, length=300,
                             command=lambda v, w=val_lbl, fm=fmt: w.config(
                                 text=fm.format(float(v))))
            scale.pack(side="left", padx=8, fill="x", expand=True)
            val_lbl.pack(side="left")
            val_lbl.config(text=fmt.format(float(var.get())))
            self.labels[field] = val_lbl
            self.label_fmt[field] = fmt

    def _sync_labels(self):
        """载入设置/套用预设是程序化改值，Scale 的 command 不会触发，
        必须手动刷新数值标签，否则界面显示的还是旧数字。"""
        for field, lbl in self.labels.items():
            lbl.config(text=self.label_fmt[field].format(
                float(self.vars[field].get())))

    # ---------------------------------------------------------- 运行页
    def _build_run_tab(self):
        top = ttk.Labelframe(self.tab_run, text="预设人设")
        top.pack(fill="x", padx=10, pady=(10, 6))
        self.preset_var = tk.StringVar(value="标准")
        cb = ttk.Combobox(top, textvariable=self.preset_var, state="readonly",
                          values=preset_names(), width=20)
        cb.pack(side="left", padx=8, pady=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_preset())
        ttk.Label(top, foreground="#666",
                  text="选预设会覆盖滑块值").pack(side="left", padx=8)

        winf = ttk.Labelframe(self.tab_run, text="目标窗口与倒计时")
        winf.pack(fill="x", padx=10, pady=6)
        wrow = ttk.Frame(winf)
        wrow.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(wrow, text="目标窗口标题（可选）").pack(side="left")
        self.window_var = tk.StringVar(value="")
        ttk.Entry(wrow, textvariable=self.window_var, width=26)\
            .pack(side="left", padx=6)
        ttk.Label(winf, foreground="#666",
                  text="填了就先切到该窗口再开始：前台窗口一旦切走会自动暂停，"
                       "切回来继续（只支持 Windows）").pack(anchor="w", padx=8)

        cd = ttk.Frame(winf)
        cd.pack(side="left", padx=8, pady=6)
        ttk.Label(cd, text="开始前等待(秒)").pack(side="left")
        self.cd_var = tk.IntVar(value=5)
        ttk.Spinbox(cd, from_=0, to=30, textvariable=self.cd_var,
                    width=4).pack(side="left", padx=4)

        self.speed_host = ttk.Frame(self.tab_run)
        self.speed_host.pack(fill="x", padx=10)
        self._build_sliders(self.speed_host, SLIDERS["run"])

        act = ttk.Frame(self.tab_run)
        act.pack(fill="x", padx=10, pady=8)
        self.btn_start = ttk.Button(act, text="▶ 开始真实输入",
                                    command=self._start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_pause = ttk.Button(act, text="⏸ 暂停", state="disabled",
                                    command=self._toggle_pause)
        self.btn_pause.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(act, text="■ 停止", state="disabled",
                                   command=self._stop)
        self.btn_stop.pack(side="left", padx=4)
        ttk.Label(self.tab_run, foreground="#b00",
                  text="⚠ 点「开始真实输入」后就是倒计时，请在这几秒内把光标"
                       "点进目标窗口；暂停用 ⏸ 或切走窗口，紧急停止随时按 F10")\
            .pack(padx=12, anchor="w")

        self.progress = ttk.Progressbar(self.tab_run, maximum=100)
        self.progress.pack(fill="x", padx=10, pady=4)

        lf = ttk.Labelframe(self.tab_run, text="输出日志")
        lf.pack(fill="both", expand=True, padx=10, pady=(4, 8))
        self.log = tk.Text(lf, height=9, font=("Consolas", 9),
                           state="disabled")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    # ------------------------------------------------------------ 配置
    def _collect_config(self):
        c = Config(log_file=os.path.join(BASE_DIR, "autotyper_log.csv"),
                   dry_run=False)
        convs = {}
        for defs in SLIDERS.values():
            for (field, _, _, _, _, _, unit, _) in defs:
                if unit:
                    convs[field] = _conv(unit)
        for field, fn in convs.items():
            setattr(c, field, fn(self.vars[field].get()))
        c.pause_short_clip = (0.8, float(self.vars["pause_clip_hi"].get()))
        if not self.long_on_var.get():
            c.long_pause_xmin = c.long_pause_cap = 1e9   # 永不触发
        c.countdown_seconds = self.cd_var.get()
        c.expected_window_title = self.window_var.get().strip()
        return c

    def _apply_preset(self):
        """把共享预设（Config 真实单位）换算成滑块刻度再写入。"""
        # field -> 滑块单位（含 pause_clip_hi 的特殊别名）
        unit_of = {}
        for defs in SLIDERS.values():
            for (field, _, _, _, _, _, unit, _) in defs:
                if unit:
                    unit_of[field] = unit
        inverse = {"%": 100.0, "ms": 1000.0, "min": 1 / 60.0}
        applied = 0
        for field, value in PRESETS[self.preset_var.get()].items():
            if field == "pause_short_clip":     # 元组 -> 只取上限滑块
                if "pause_clip_hi" in self.vars:
                    self.vars["pause_clip_hi"].set(float(value[1]))
                    applied += 1
                continue
            if field not in self.vars:
                continue
            unit = unit_of.get(field, "raw")
            self.vars[field].set(float(value) * inverse.get(unit, 1.0))
            applied += 1
        self.status.set(f"已应用预设「{self.preset_var.get()}」"
                        f"（{applied} 项滑块）")
        self._sync_labels()

    def _save_settings(self):
        data = {k: v.get() for k, v in self.vars.items()}
        data["_preset"] = self.preset_var.get()
        data["_countdown"] = self.cd_var.get()
        data["_long_on"] = self.long_on_var.get()
        data["_window"] = self.window_var.get()
        try:
            with open(SETTINGS_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def _load_settings(self):
        if not os.path.exists(SETTINGS_JSON):
            return
        try:
            with open(SETTINGS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for k, v in data.items():
            if k == "_preset":
                self.preset_var.set(v)
            elif k == "_countdown":
                self.cd_var.set(int(v))
            elif k == "_long_on":
                self.long_on_var.set(bool(v))
            elif k == "_window":
                self.window_var.set(str(v))
            elif k in self.vars:
                self.vars[k].set(float(v))
        self._sync_labels()

    # ------------------------------------------------------------ 运行
    def _log_line(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self):
        src_text = self.txt.get("1.0", "end").rstrip("\n")
        if not src_text.strip():
            messagebox.showerror("没有内容",
                                 "请先在「内容」页填写要输入的文字。")
            return
        bad = unsupported_chars(src_text)
        if bad:
            shown = "，".join(f"{i}:{ch!r}" for i, ch in bad[:5])
            messagebox.showerror(
                "含无法键入的字符",
                f"文本里有 {len(bad)} 个无法可靠输入的控制字符（{shown}）。\n"
                "请先删掉它们，单独的 \\r 请换成换行。")
            return
        import random as _random
        cfg = self._collect_config()
        typer = AutoTyper(cfg, src_text, rng=_random.Random())
        self.typer = typer

        orig_progress = typer._progress

        def patched_progress():
            orig_progress()
            pct = 100.0 * typer.pipeline.i / max(1, len(src_text))
            self.q.put(("pct", pct))

        typer._progress = patched_progress

        self._set_running(True)
        self._run_started = time.time()
        self._src_len = len(src_text)
        self.progress["value"] = 0
        typer.executor.start()          # 倒计时期间 F10 也能中止
        n = self.cd_var.get()
        if n > 0:
            self._countdown(typer, n)
        else:
            self._launch_worker(typer)

    def _countdown(self, typer, n):
        """开始前的等待，给用户切窗口的时间；每一秒都检查停止请求。"""
        if typer.kill.killed():
            typer.executor.stop()
            self._cancel_tick()
            self._set_running(False)
            self.status.set("已取消")
            return
        if n <= 0:
            self._launch_worker(typer)
            return
        self.status.set(f"{n} 秒后开始：请把光标点进目标窗口（F10 可中止）")
        self._cd_id = self.after(
            1000, lambda: self._countdown(typer, n - 1))

    # ------------------------------------------------- 状态栏 / 暂停 / ETA
    STATE_LABELS = {"TYPING": "正在输入", "BACKSPACE_BURST": "回删爆发",
                    "PAUSE_SHORT": "短停顿", "PAUSE_LONG": "长暂停",
                    "EDIT_PREVIOUS": "跳回前文改", "REWRITE_CHUNK": "整段重打",
                    "REVIEW": "回读刚写的"}

    @staticmethod
    def _fmt_left(seconds):
        seconds = max(0.0, seconds)
        if seconds < 60:
            return f"{seconds:.0f} 秒"
        return f"{seconds / 60:.0f} 分钟"

    def _status_now(self):
        """当前状态 + 进度 + ETA。故意不写百分比——进度条已经在显示它了。"""
        t = self.typer
        if t is None:
            return None
        if t.kill.paused():
            return "⏸ 已暂停（等待目标窗口 / 点「▶ 继续」）"
        left = getattr(t, "pause_long_left", 0.0)
        if left > 0:
            return f"长暂停中，剩 {self._fmt_left(left)}"
        label = self.STATE_LABELS.get(getattr(t, "cur_state", "TYPING"),
                                      "正在输入")
        pct = 100.0 * t.pipeline.i / max(1, self._src_len)
        if self._run_started and t.pipeline.i > 0:
            elapsed = time.time() - self._run_started
            # 线性外推：即使有删改，consumed 与总长的比例仍然可用
            eta = elapsed / t.pipeline.i * max(0, self._src_len - t.pipeline.i)
            return f"{label} {pct:.0f}%，约剩 {self._fmt_left(eta)}"
        return f"{label} {pct:.0f}%"

    def _tick(self):
        if not self.running:
            self._tick_id = None
            return
        txt = self._status_now()
        if txt:
            self.status.set(txt)
        self._sync_pause_button()
        self._tick_id = self.after(500, self._tick)

    def _cancel_tick(self):
        if self._tick_id is not None:
            self.after_cancel(self._tick_id)
            self._tick_id = None

    def _sync_pause_button(self):
        if not self.running:
            self.btn_pause.config(state="disabled", text="⏸ 暂停")
            return
        if self.typer is not None and self.typer.kill.paused():
            self.btn_pause.config(state="normal", text="▶ 继续")
        else:
            self.btn_pause.config(state="normal", text="⏸ 暂停")

    def _toggle_pause(self):
        if self.typer is None:
            return
        k = self.typer.kill
        if k.paused():
            k.request_resume()
        else:
            k.request_pause()
        self._sync_pause_button()
        self.status.set(self._status_now() or "已暂停")

    def _launch_worker(self, typer):
        def work():
            try:
                s = typer.run()
                self.q.put(("done", s))
            except Exception:
                # 工作线程里任何异常都不能让界面永远停在"运行中"
                self.q.put(("error", traceback.format_exc()))

        self.status.set("正在输入…")
        threading.Thread(target=work, daemon=True).start()
        self._poll_id = self.after(120, self._poll_queue)
        self._cancel_tick()
        self._tick_id = self.after(500, self._tick)

    def _stop(self):
        if self.typer:
            self.typer.kill.set()
            self.status.set("已请求停止…")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "pct":
                    self.progress["value"] = payload
                    # 状态栏交给 _tick 统一维护（带 ETA / 当前状态），这里不动
                elif kind == "error":
                    self._set_running(False)
                    self._log_line("出错，已停止：")
                    for ln in payload.strip().splitlines()[-4:]:
                        self._log_line("    " + ln)
                    self.status.set("出错了，详见输出日志")
                elif kind == "done":
                    s = payload
                    self._set_running(False)
                    if s["final_matches_source"]:
                        self.progress["value"] = 100
                    for ln in (
                        f"chars={s['chars']} errors={s['errors']} "
                        f"bursts={s['bursts']} edits={s['edits']} "
                        f"rewrites={s['rewrites']} reviews={s['reviews']} "
                        f"pauses={s['pause_count']}",
                        f"内容一致: {s['final_matches_source']}  "
                        f"耗时 {s['elapsed_s']}s"
                        + ("（被停止）" if s["killed"] else ""),
                    ):
                        self._log_line(ln)
                    if s["killed"]:
                        self.status.set("已停止")
                    elif s["final_matches_source"]:
                        self.status.set("完成 ✓ 内容一致")
                    else:
                        self.status.set("结束，但内容与源文本不一致（看日志）")
        except queue.Empty:
            pass
        if self.running:
            self._poll_id = self.after(120, self._poll_queue)

    def _set_running(self, running):
        self.running = running
        st = "disabled" if running else "normal"
        self.btn_start.config(state=st)
        self.btn_stop.config(state="normal" if running else "disabled")
        self._sync_pause_button()

    def _on_close(self):
        for aid in (self._cd_id, self._poll_id, self._tick_id):
            if aid is not None:
                self.after_cancel(aid)
        self._cd_id = self._poll_id = self._tick_id = None
        if self.running:
            if not messagebox.askyesno(
                    "正在运行", "任务尚未结束，确定停止并退出吗？"):
                return
            # running 时 typer 一定已创建（_start 里先建 typer 再置 running），
            # 但显式判空更稳：万一顺序调整，也不会在关闭时崩掉。
            if self.typer is not None:
                self.typer.kill.set()
        self._save_settings()
        self.destroy()


def selftest():
    """无交互自检：构建全部控件、收集配置、校验滑块到配置的映射。

    注意：这里绝不真正启动输入（GUI 已无演练模式），也绝不动当前目录下用户
    真正的 gui_settings.json —— 设置读写全部改走临时文件。
    """
    global SETTINGS_JSON
    import tempfile
    SETTINGS_JSON = os.path.join(tempfile.gettempdir(),
                                "autotyper_selftest_settings.json")
    app = App()
    app.update_idletasks()
    cfg = app._collect_config()
    assert abs(cfg.delay_mu - app.vars["delay_mu"].get() / 1000.0) < 1e-9
    assert abs(cfg.p_typo - app.vars["p_typo"].get() / 100.0) < 1e-9
    assert abs(cfg.p_burst_enter -
               app.vars["p_burst_enter"].get() / 100.0) < 1e-9
    assert abs(cfg.long_pause_xmin -
               app.vars["long_pause_xmin"].get() * 60.0) < 1e-9
    assert cfg.pause_short_clip[1] == app.vars["pause_clip_hi"].get()
    # GUI 只有实机模式：dry_run 必须为 False，否则点按钮只会空跑
    assert app._collect_config().dry_run is False
    # 程序化改滑块值后数值标签要跟着刷新
    app.vars["delay_mu"].set(250.0)
    app.vars["p_typo"].set(4.0)
    app._sync_labels()
    assert app.labels["delay_mu"].cget("text") == "250ms"
    assert app.labels["p_typo"].cget("text") == "4.0%"
    # 关闭长暂停 -> 永不触发
    app.long_on_var.set(False)
    off = app._collect_config()
    assert off.long_pause_cap > 1e8
    app.long_on_var.set(True)
    # 预设映射
    app.preset_var.set("手生普通人")
    app._apply_preset()
    p = app._collect_config()
    assert 0.15 <= p.delay_mu <= 0.20 and p.p_typo > 0.02
    # 设置持久化往返
    app.preset_var.set("高效型程序员")
    app._apply_preset()
    app._save_settings()
    app2 = App()
    assert abs(app2.vars["delay_mu"].get() -
               app.vars["delay_mu"].get()) < 1e-9
    assert app2.cd_var.get() == app.cd_var.get()
    # 载入设置后标签不能停留在默认值
    assert app2.labels["delay_mu"].cget("text") == app2.label_fmt["delay_mu"]\
        .format(app2.vars["delay_mu"].get())
    # 结束回调：正常结束与工作线程抛异常都必须复位界面
    done = {"chars": 10, "errors": 0, "bursts": 0, "edits": 0, "rewrites": 0,
            "reviews": 0, "pause_count": 0,
            "final_matches_source": True, "elapsed_s": 1.0, "killed": False}
    app._set_running(True)
    app.q.put(("done", done))
    app._poll_queue()
    assert not app.running, "结束后界面没有复位"
    assert str(app.btn_start["state"]) == "normal"
    assert "内容一致: True" in app.log.get("1.0", "end")
    app._set_running(True)
    app.q.put(("error", "Traceback (most recent call last):\n  boom"))
    app._poll_queue()
    assert not app.running, "异常后界面没有复位"
    need = dict(done, final_matches_source=False)
    app._set_running(True)
    app.q.put(("done", need))
    app._poll_queue()
    assert "不一致" in app.status.get()
    # 倒计时编排：n>0 只排定时器，n<=0 才真的进工作线程（用假 typer，不发按键）
    class FakeTyper:
        def __init__(self):
            from .executor import Killer
            self.kill = Killer()
            self.ran = False
            self.executor = type("E", (), {"start": lambda s: None,
                                           "stop": lambda s: None})()

        def run(_self):
            _self.ran = True
            return done

    fake = FakeTyper()
    app._countdown(fake, 2)
    assert app._cd_id is not None and not fake.ran
    app.after_cancel(app._cd_id)
    app._cd_id = None
    app._set_running(True)
    app._countdown(fake, 0)
    assert fake.ran, "倒计时结束后没有进入工作线程"
    if app._poll_id is not None:
        app.after_cancel(app._poll_id)
    app.destroy()
    app2.destroy()
    os.remove(SETTINGS_JSON)
    print("GUI SELFTEST PASSED")


def main():
    """命令行入口：`autotyper-gui`（等同 python -m humanized_autotyper.gui）。"""
    if "--selftest" in sys.argv[1:]:
        selftest()
        return 0
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
