import random
import time
from typing import Any, Dict

from .config import Config
from .buffer import Buffer
from .delays import DelayModel
from .typos import TypoEngine
from .executor import Executor, Logger, Killer


class Pipeline:
    def __init__(self, source):
        self.src = source
        self.i = 0
        self.consumed = 0

    def next(self):
        if self.i >= len(self.src):
            return None
        c = self.src[self.i]
        self.i += 1
        self.consumed += 1
        return c

    def peek(self):
        return self.src[self.i] if self.i < len(self.src) else None

    def consume_peek(self):
        return self.next()


class LongPauseScheduler:
    def __init__(self, delays: DelayModel):
        self.delays = delays
        self.threshold = delays.sample_pareto_threshold()
        self.active = 0.0

    def add(self, seconds):
        self.active += seconds

    def should_fire(self):
        return self.active >= self.threshold

    def reset(self):
        self.threshold = self.delays.sample_pareto_threshold()
        self.active = 0.0


class AutoTyper:
    STATES = ("TYPING", "BACKSPACE_BURST", "PAUSE_SHORT", "PAUSE_LONG",
              "EDIT_PREVIOUS", "REWRITE_CHUNK", "REVIEW")

    # rng 默认必须是 random.Random 实例（与 delays.py / typos.py 同理）：写
    # `rng=random` 会被推成 ModuleType，与全部 `rng=random.Random(n)` 调用冲突。
    #
    # mode/targets 是多模式扩展点（见 modes.py）。默认 None 时退化成 1.x 行为：
    # 单个 source 字符串 + 缓冲区自校验，`run()` 逻辑与重构前逐字相同。
    def __init__(self, cfg: Config, source: str, rng: random.Random = random.Random(),
                 buffer=None, executor=None, logger=None, killer=None,
                 delays=None, scheduler=None, mode=None, targets=None):
        self.cfg = cfg
        self.rng = rng
        self.source = source
        self.pipeline = Pipeline(source)
        self.mode = mode
        self.targets = targets
        self.buffer = buffer if buffer is not None else Buffer("")
        self.kill = killer if killer is not None else Killer()
        self.logger = logger if logger is not None else Logger(cfg)
        self.delays = delays if delays is not None else DelayModel(cfg, rng)
        self.executor = executor if executor is not None else Executor(
            cfg, self.delays, self.logger, self.kill)
        self.sched = scheduler if scheduler is not None else LongPauseScheduler(self.delays)
        self.typos = TypoEngine(cfg, rng)
        self.last_sent = ""
        self.err_typed = ""
        self.err_intended = ""
        self.err_detect_in = -1
        self.last_edit_time = -1e18
        self.finished = False
        self.started_at = None
        self.chars_since_progress = 0
        self._pause_ticks = 0
        # 长暂停剩余墙钟秒数（0 表示当前不在长暂停里）；界面用它显示倒计时。
        self.pause_long_left = 0.0
        self.cur_state = "TYPING"
        # 交替打字配额：>0 表示本次 _drive 最多再打多少字符（打满就存盘切文件），
        # 0 = 不限（顺序/单文档路径，行为与 1.x 逐字相同）。
        self._slice_budget = 0
        self._slice_typed = 0
        # 标注成 dict[str, Any]：字面量全是非负 int，类型检查器会推成
        # dict[str, int]，于是 run() 里 `summary["elapsed_s"] = round(...)`
        # （float）、`summary["final_matches_source"] = ...`（bool）全被拒。
        # stats 本身确实是异构计数器表，Any 才是准确描述。
        self.stats: Dict[str, Any] = {
            "chars": 0, "source_consumed": 0, "errors": 0,
            "corrections": 0, "bursts": 0, "short_pauses": 0,
            "long_pauses": 0, "edits": 0, "rewrites": 0,
            "reviews": 0, "pause_count": 0}
        self.handlers = {
            "TYPING": self._h_typing,
            "BACKSPACE_BURST": self._h_burst,
            "PAUSE_SHORT": self._h_pause_short,
            "PAUSE_LONG": self._h_pause_long,
            "EDIT_PREVIOUS": self._h_edit_previous,
            "REWRITE_CHUNK": self._h_rewrite_chunk,
            "REVIEW": self._h_review,
        }

    def run(self):
        # 多目标模式（VSCode 等）走文件循环；单目标（默认）走原来的单文档路径，
        # 两者共用下面这一个 _drive()，因此状态机行为完全一致。
        if self.mode is not None and getattr(self.mode, "multi_target", False):
            return self._run_multi()
        return self._run_single()

    def _slice_expired(self):
        """交替打字配额是否已用尽（0 = 不限，永不触发）。

        顺序/单文档路径下 _slice_budget 恒为 0，因此本方法恒返回 False，
        行为与 1.x 逐字相同；只有 _run_interleaved 会在切文件前设好配额。
        """
        return self._slice_budget > 0 and self._slice_typed >= self._slice_budget

    def _drive(self):
        """跑完当前 target 的打字状态机（单文档与多模式共用）。"""
        state = "TYPING"
        try:
            while (not self.kill.killed() and not self.finished
                   and not self._slice_expired()):
                if self.kill.paused():
                    self._wait_while_paused()
                    continue
                self.cur_state = state
                state = self.handlers[state]() or "TYPING"
        except KeyboardInterrupt:
            self.kill.set()
        finally:
            self._flush_correction()

    def _run_single(self):
        """1.x 原始路径：单文档 + 缓冲区自校验。逐字保持原行为。"""
        self.executor.start()
        self.executor.check_window()
        self.started_at = time.time()
        try:
            self._drive()
        finally:
            self.executor.stop()
        elapsed = time.time() - self.started_at
        summary = dict(self.stats)
        summary["source_consumed"] = self.pipeline.consumed
        summary["elapsed_s"] = round(elapsed, 1)
        summary["final_matches_source"] = self.buffer.text == self.source
        summary["killed"] = self.kill.killed()
        # 收尾标记：让 report 能确认这一段是「跑完了」而不是被强杀在半路，
        # 从而不会把残缺的一段当成完整样本去对照概率。
        try:
            self.logger.mark_end(summary)
        except Exception:
            pass
        return summary

    def _run_multi(self):
        """多目标模式：对每个 Target 重置 buffer/pipeline 后各跑一遍状态机。

        与单文档路径的关键差异：
        - 每个文件开始前重置 buffer / pipeline / finished / 长暂停调度器，
          否则第二个文件会带着第一个文件的疲劳与光标位置跑，必然出错；
        - 逐文件调用 mode.before_type() / mode.after_type()，由模式负责定位
          编辑器与校验；
        - summary 里的 final_matches_source 只有在 mode.verify_trustworthy()
          为真时才可信，否则置 None 并在 per_file 里给出逐文件结论。
        """
        # 本方法只在 run() 判定 mode 非空且 multi_target 时调用，但检查器
        # 无法推断这一点；先取局部变量，既收窄了类型也少写 4 次 self.mode。
        mode = self.mode
        assert mode is not None, "_run_multi 只应在 mode 已设置时调用"
        targets = self.targets or []
        self.executor.start()
        self.executor.check_window()
        self.started_at = time.time()
        self._total_chars = 0

        # file_switch_chars > 0 且真的有多文件时走交替推进；否则顺序执行
        # （顺序是 1.x 以来的原始行为，也是默认路径）。
        if self.cfg.file_switch_chars > 0 and len(targets) > 1:
            per_file = self._run_interleaved(mode, targets)
        else:
            per_file = self._run_sequential(mode, targets)
        try:
            self.executor.stop()
        except Exception:
            pass
        return self._summarise(mode, targets, per_file)

    def _run_sequential(self, mode, targets):
        """一个文件彻底打完再切下一个（顺序执行）。"""
        per_file = []
        total_chars = 0
        for idx, target in enumerate(targets, 1):
            if self.kill.killed():
                break
            self._reset_for_target()
            self.source = target.content
            self.pipeline = Pipeline(target.content)
            self.logger.log("FILE", "start",
                            f"{idx}/{len(targets)} {target.path}", 0)
            self._notify_progress(idx - 1, len(targets), target)
            try:
                mode.before_type(target, self)
            except Exception as exc:
                self.logger.log("FILE", "acquire_failed",
                                 f"{target.path}: {exc!r}", 0)
                per_file.append({"path": target.path, "ok": False,
                                 "detail": f"定位失败: {exc}"})
                continue
            self._drive()
            result = self._finish_one(mode, target)
            total_chars += self.stats["chars"]
            per_file.append({"path": target.path,
                             "ok": result.get("ok"),
                             "detail": result.get("detail", ""),
                             "chars": self.stats["chars"]})
        self._total_chars = total_chars
        return per_file

    def _notify_progress(self, done, total, target):
        """推一次逐文件进度给 GUI（失败不能影响打字流程）。"""
        if self.cfg.progress_hook:
            try:
                self.cfg.progress_hook(done, total, target)
            except Exception:
                pass

    def _finish_one(self, mode, target):
        """收尾一个文件：调模式的 after_type，异常按失败记录。"""
        try:
            return mode.after_type(target, self) or {}
        except Exception as exc:
            return {"ok": False, "detail": f"校验失败: {exc}"}

    def _summarise(self, mode, targets, per_file):
        """顺序与交替两种调度共用的收尾：组装 summary 并写日志尾标。"""
        # started_at 在 run() 进入调度前必然已赋值；这里兜底仅为满足类型检查。
        elapsed = time.time() - (self.started_at or time.time())
        summary = dict(self.stats)
        summary["chars"] = self._total_chars
        summary["files"] = len(targets)
        summary["files_ok"] = sum(1 for f in per_file if f["ok"] is True)
        # 未校验（ok=None）与失败（ok=False）必须分开报，否则会误导排查方向
        summary["files_unverified"] = sum(1 for f in per_file
                                          if f["ok"] is None)
        summary["per_file"] = per_file
        summary["elapsed_s"] = round(elapsed, 1)
        summary["killed"] = self.kill.killed()
        # 内存缓冲区在多目标模式下不能代表真实文档（编辑器会改写、且每个文件
        # 都会重置），所以不能报 final_matches_source——由 per_file 给出结论。
        summary["final_matches_source"] = (
            None if not mode.verify_trustworthy()
            else self.buffer.text == self.source)
        summary["verify_trustworthy"] = mode.verify_trustworthy()
        try:
            self.logger.mark_end(summary)
        except Exception:
            pass
        return summary

    def _drive_limited(self, budget):
        """限量驱动状态机：本文件最多打 budget 个字符就停（切文件用）。"""
        self._slice_budget = budget
        self._slice_typed = 0
        try:
            self._drive()
        finally:
            self._slice_budget = 0
            self._slice_typed = 0

    def _save_only(self, mode, target):
        """切文件前的轻量存盘（不做完整校验）；异常不影响主流程。

        顺序路径不会调用它——那里 after_type 已经负责存盘 + 回读校验。
        """
        saver = getattr(mode, "save_only", None)
        if saver is None:
            return
        try:
            saver(target, self)
        except Exception as exc:
            self.logger.log("FILE", "save_failed",
                            f"{target.path}: {exc!r}", 0)

    def _run_interleaved(self, mode, targets):
        """多文件交替：每个文件打满 file_switch_chars 就存盘切到下一个。

        每个文件一个常驻槽（缓冲区 + 管道 + 已打字符进度），切回来时原样
        恢复，因此每个文件都从上次停下的位置继续打，直到全部完成。切文件
        之间插入 switch_pause_s 的随机停顿（人尺度），像真人同时在改几个
        文件。一轮里所有文件都没有任何进展（理论上不该发生）则退出防死循环。
        """
        budget = max(1, int(self.cfg.file_switch_chars))
        # 每文件常驻状态：buf 缓冲区、pipe 管道、done 是否打完。管道与缓冲区
        # 都跨轮保留，切回来时原样恢复，因此无需假设"缓冲区长度 == 管道位置"。
        slots = []
        for t in targets:
            slots.append({"target": t, "buf": Buffer(""),
                          "pipe": Pipeline(t.content), "done": False,
                          "result": None})
        total = len(slots)
        completed = 0
        total_chars = 0
        self._total_chars = 0
        try:
            while completed < total and not self.kill.killed():
                progressed = False
                for slot in slots:
                    if self.kill.killed():
                        break
                    if slot["done"]:
                        continue
                    target = slot["target"]
                    # 恢复该文件的缓冲区与管道（不重建，接着上次打）
                    self.buffer = slot["buf"]
                    self.pipeline = slot["pipe"]
                    self.source = target.content
                    self.finished = False
                    self.err_typed = ""
                    self.err_intended = ""
                    self.err_detect_in = -1
                    self.pause_long_left = 0.0
                    self.sched.reset()
                    self.logger.log("FILE", "start",
                                    f"interleave {target.path}", 0)
                    self._notify_progress(completed, total, target)
                    try:
                        mode.before_type(target, self)
                    except Exception as exc:
                        self.logger.log("FILE", "acquire_failed",
                                        f"{target.path}: {exc!r}", 0)
                        slot["result"] = {"ok": False,
                                          "detail": f"定位失败: {exc}"}
                        slot["done"] = True
                        completed += 1
                        continue
                    before_chars = self.stats["chars"]
                    self._drive_limited(budget)
                    typed = self.stats["chars"] - before_chars
                    total_chars += typed
                    progressed = progressed or typed > 0
                    # 打完的判定：finished（管道取空时置位）或管道已耗尽。
                    # 后者兜底"文件长度恰为配额整数倍"的边界——最后一个字符
                    # 打完即触顶，_h_typing 来不及取到 None 就退出了循环。
                    if self.finished or self.pipeline.peek() is None:
                        self.finished = True
                        slot["result"] = self._finish_one(mode, target)
                        slot["done"] = True
                        completed += 1
                    else:
                        # 没打完：存盘 + 随机停顿，等下一轮回来接着打
                        self._save_only(mode, target)
                        if self.cfg.switch_pause_s:
                            self._sleep(
                                self.rng.uniform(*self.cfg.switch_pause_s),
                                active=False)
                if not progressed:
                    break      # 一轮毫无进展：防死循环
        finally:
            self._total_chars = total_chars
        # 汇总 per_file（含未完成的），保持与顺序路径一致的字段
        per_file = []
        for slot in slots:
            res = slot["result"] or {}
            per_file.append({"path": slot["target"].path,
                             "ok": res.get("ok"),
                             "detail": res.get("detail", ""),
                             "chars": len(slot["buf"].text)})
        return per_file

    def _reset_for_target(self):
        """切换到下一个文件前清干净跨文件状态。"""
        self.buffer = Buffer("")
        self.finished = False
        self.last_sent = ""
        self.err_typed = ""
        self.err_intended = ""
        self.err_detect_in = -1
        self.pause_long_left = 0.0
        # 疲劳/预热是"一个人连续打字"的属性；换文件等于换了一次会话，
        # 但同一轮任务里的累积节奏保留——所以只重置长暂停调度器。
        self.sched.reset()
        for k in self.stats:
            self.stats[k] = 0

    def _progress(self):
        pct = 100.0 * self.pipeline.i / max(1, len(self.source))
        if not self.cfg.verbose:
            print(f"\r[{pct:5.1f}%] chars={self.stats['chars']} "
                  f"errors={self.stats['errors']} edits={self.stats['edits']} "
                  f"rewrites={self.stats['rewrites']}", end="", flush=True)

    def _wait_while_paused(self):
        """前台窗口失焦（或用户点了暂停）后停在这里，直到恢复或收到停止请求。

        只在不打字的时候被调用——`check_window` 仅在行尾与启动时触发，
        所以停顿点永远落在"文档与缓冲区一致"的安全位置上。
        """
        self._pause_ticks = 0
        started = time.time()
        while self.kill.paused() and not self.kill.killed():
            time.sleep(0.05)
            if self._pause_ticks % 10 == 0:
                self._progress()          # 暂停时也要让界面/控制台刷新
            self._pause_ticks += 1
        if self.kill.killed():
            return
        self.stats["pause_count"] += 1
        self.logger.log("PAUSE", "resume", f"after={time.time()-started:.1f}s", 0)
        self._progress()

    def _sleep(self, seconds, active=True, chunk=0.25):
        deadline = time.time() + seconds
        total = 0.0
        # 只在"较长"的停顿里响应暂停：短到一次击键间隔的 sleep 让它自然走完，
        # 免得状态机在半个动作中间被冻住。
        honor_pause = seconds >= 0.5
        while True:
            if self.kill.killed():
                self.delays.note_pause(total)
                return False
            if honor_pause and self.kill.paused():
                self.delays.note_pause(total)
                self._wait_while_paused()
                if self.kill.killed():
                    return False
                total = 0.0                      # 恢复后重新计时这段停顿
                deadline = time.time() + seconds
                continue
            now = time.time()
            if now >= deadline:
                break
            dt = min(chunk, deadline - now)
            time.sleep(dt)
            total += dt
            if self.pause_long_left > 0:
                self.pause_long_left = max(0.0, self.pause_long_left - dt)
            if active:
                human_dt = dt * self.cfg.speed_multiplier
                self.sched.add(human_dt)
                self.delays.add_active(human_dt)
        self.delays.note_pause(total)
        return True

    def _send(self, ch, urgent=False, mandatory=False):
        # 兜住"暂停/停止请求恰好落在本轮循环中间"的竞态。
        #
        # mandatory=False（正常打字）：还没打过这个字符，直接不发是安全的——
        #   缓冲区与文档保持一致，被停止后目标文档不多内容。
        # mandatory=True（重打刚删掉的片段）：那些字符已经从文档里删掉了，
        #   只存在于内存里，**必须**补完，否则文档会缺字。此时不再响应暂停/停止。
        if not mandatory:
            if self.kill.killed():
                return
            if self.kill.paused():
                self._wait_while_paused()
                if self.kill.killed():
                    return
        d = self.delays.sample(self.last_sent, ch)
        hold = self.cfg.urgent_hold if urgent else None
        self.executor.type_char(ch, d * 1000.0, hold=hold)
        self.buffer.type_char(ch)
        self.last_sent = ch
        self.stats["chars"] += 1
        self._slice_typed += 1
        if urgent:
            return  # 已请求停止：不再制造拟人延时，尽快补完
        self._sleep(d, active=True)

    def _retype(self, chars, allow_typos=True):
        """重打一段刚被删掉的文本。

        一旦按下删除键，这段文本就只存在于内存里了：必须打完，否则目标
        文档会缺字。若中途收到停止请求，则改用 urgent 节奏尽快补完——
        停止的延迟被限制在这一个片段之内，而不会留下半截内容。
        allow_typos=False 用于"纠正错误后重打正确内容"，此时不该再犯新错。
        """
        for ch in chars:
            urgent = self.kill.killed()
            if allow_typos:
                self._emit_intended(ch, allow_transpose=False, urgent=urgent,
                                    mandatory=True)
            else:
                self._send(ch, urgent=urgent, mandatory=True)

    def _return_to_end(self):
        """光标回到文末。已请求停止时不再移动（没人接着打字，省掉几百次方向键）。"""
        if self.kill.killed():
            return
        self._navigate_to(len(self.buffer.text))

    def _emit_intended(self, ch, allow_transpose=True, urgent=False,
                       mandatory=False):
        if self.err_detect_in >= 0:
            if ch == "\n" or self.err_detect_in == 0:
                self._flush_correction()
            else:
                self.err_detect_in -= 1
                self._send(ch, urgent=urgent, mandatory=mandatory)
                self.err_typed += ch
                self.err_intended += ch
                return
        nxt = self.pipeline.peek() if allow_transpose else None
        err = self.typos.roll(ch, next_char=nxt,
                              tempo_factor=self.delays.tempo_factor)
        if err is None:
            self._send(ch, urgent=urgent, mandatory=mandatory)
            return
        self.stats["errors"] += 1
        self.logger.log("TYPING", "typo", err["kind"], 0)
        if err["kind"] == "transposition":
            # 顺序对调：先打后一个源字符，再打当前字符；两个源字符都要消费掉
            self.pipeline.consume_peek()
            self._send(err["emit_first"], urgent=urgent, mandatory=mandatory)
            self._send(err["emit_second"], urgent=urgent, mandatory=mandatory)
            self.err_typed = err["emit_first"] + err["emit_second"]
            self.err_intended = err["emit_second"] + err["emit_first"]
        else:
            for pc in err["emit"]:
                self._send(pc, urgent=urgent, mandatory=mandatory)
            self.err_typed = err["emit"]
            self.err_intended = ch
        self.err_detect_in = err["detect_after"]

    def _flush_correction(self):
        if self.err_detect_in < 0:
            return
        self.stats["corrections"] += 1
        n = len(self.err_typed)
        self.logger.log("TYPING", "corr", f"n={n}", 0)
        for _ in range(n):
            self.executor.backspace()
            self.buffer.backspace()
            if not self.kill.killed():
                self._sleep(self.delays.backspace_delay(), active=True)
        self._retype(self.err_intended, allow_typos=False)
        self.err_typed = ""
        self.err_intended = ""
        self.err_detect_in = -1

    def _h_typing(self):
        while not self.kill.killed() and not self._slice_expired():
            ch = self.pipeline.next()
            if ch is None:
                self._flush_correction()
                self.finished = True
                return "TYPING"
            self._emit_intended(ch)
            if ch == "\n":
                think = self.delays.line_end_think()
                if think > 0:
                    self.logger.log("TYPING", "think", "", think * 1000)
                    self._sleep(think, active=True)
            if self.err_detect_in >= 0:
                continue
            self.chars_since_progress += 1
            if self.chars_since_progress >= 25:
                self.chars_since_progress = 0
                self._progress()
            peek = self.pipeline.peek()
            if self.sched.should_fire() and peek in (" ", "\n", None):
                self.logger.log("SCHED", "long_pause_due",
                                f"active={self.sched.active:.0f}s", 0)
                return "PAUSE_LONG"
            boundary = peek in ("\n", None)
            if boundary and not self.executor.check_window():
                # 焦点已经不在目标窗口：继续打下去就是往别的窗口里灌字
                self.logger.log("TYPING", "focus_lost", "", 0)
                return "TYPING"
            if not boundary:
                r = self.rng.random()
                if r < self.cfg.p_backspace_burst:
                    return "BACKSPACE_BURST"
                if r < self.cfg.p_backspace_burst + self.cfg.p_pause_short:
                    return "PAUSE_SHORT"
            else:
                now = time.time()
                gap_ok = (now - self.last_edit_time) >= self.cfg.edit_min_gap_s
                probs = []
                if gap_ok:
                    probs.append(("EDIT_PREVIOUS", self.cfg.p_edit_previous))
                probs.append(("REWRITE_CHUNK", self.cfg.p_rewrite_chunk))
                probs.append(("REVIEW", self.cfg.p_review))
                p_short = (self.cfg.p_pause_short_sentence
                           if ch in self.cfg.sentence_end_chars
                           else self.cfg.p_pause_short)
                probs.append(("PAUSE_SHORT", p_short))
                r = self.rng.random()
                acc = 0.0
                for st, p in probs:
                    acc += p
                    if r < acc:
                        if st == "EDIT_PREVIOUS":
                            self.last_edit_time = now
                        return st
        return "TYPING"

    def _h_burst(self):
        self.logger.log("BACKSPACE_BURST", "enter", "", 0)
        buf = self.buffer
        li = buf.current_line()
        cap = buf.cursor - buf.line_start(li)
        n = min(self.rng.randint(*self.cfg.backspace_n_range), cap)
        if n < 2:
            return "TYPING"   # 什么也没删，不计数（否则指标虚高）
        if self.kill.killed():
            return "TYPING"   # 还没动过文档，直接放弃
        self.stats["bursts"] += 1
        deleted = buf.seg(buf.cursor - n, buf.cursor)
        # 删除与重打必须成对完成，中途不再检查 kill（否则会漏字）
        for _ in range(n):
            self.executor.backspace()
            buf.backspace()
            self._sleep(self.delays.backspace_delay(), active=True)
        self._retype(deleted)
        self._flush_correction()
        self.logger.log("BACKSPACE_BURST", "exit", f"n={n}", 0)
        return "TYPING"

    def _h_pause_short(self):
        d = self.delays.pause_short()
        self.stats["short_pauses"] += 1
        self.logger.log("PAUSE_SHORT", "sleep", f"{d:.2f}s", d * 1000)
        self._sleep(d, active=True)
        return "TYPING"

    def _h_pause_long(self):
        d = self.delays.long_pause()
        self.stats["long_pauses"] += 1
        self.logger.log("PAUSE_LONG", "sleep", f"{d:.0f}s", d * 1000)
        # d is human-scale seconds; scale to wall time like every other delay.
        # 记录剩余时间，供界面显示"长暂停中，剩 N 分钟"。
        self.pause_long_left = d / self.cfg.speed_multiplier
        self._sleep(d / self.cfg.speed_multiplier, active=False,
                    chunk=self.cfg.long_sleep_chunk)
        self.pause_long_left = 0.0
        if self.kill.killed():
            return "TYPING"
        self.delays.reset_fatigue()
        self.delays.note_pause(d)
        # 找回位置的动作必须是"左 N 再右 N"的对称位移。若 N 超过已打字符数，
        # 真实编辑器会先被文档头夹住、再往右冲过头，光标就与缓冲区错位了。
        left = min(self.rng.randint(*self.cfg.resume_left_range),
                   self.buffer.cursor)
        if left > 0:
            self.executor.nav_left(left)
            if self.kill.killed():
                return "TYPING"     # 已经要求停止，没必要再走回去
            reorient_pause = self.rng.uniform(0.3, 1.2)
            self._sleep(reorient_pause / self.cfg.speed_multiplier,
                        active=False)
            self.executor.nav_right(left)
        self.logger.log("PAUSE_LONG", "resume_ritual", f"left={left}", 0)
        reorient = self.rng.uniform(*self.cfg.resume_reorient_range)
        self._sleep(reorient / self.cfg.speed_multiplier, active=True)
        # Clear the active-time window only when the pause fully completes,
        # so the next long-pause interval starts from zero.
        self.sched.reset()
        return "TYPING"

    def _navigate_to(self, pos):
        """Move the caret to absolute buffer position `pos` using ONLY
        arrow keys. Vertical moves first (sticky-column semantics are
        mirrored by the buffer), then a horizontal correction step."""
        buf = self.buffer
        tl, tc = buf.line_col_of(pos)
        cl, _ = buf.line_col()
        if tl < cl:
            up = cl - tl
            self.executor.nav_up(up)
            buf.apply_up(up)
        elif tl > cl:
            down = tl - cl
            self.executor.nav_down(down)
            buf.apply_down(down)
        _, cc = buf.line_col()
        if tc > cc:
            self.executor.nav_right(tc - cc)
            buf.move_right(tc - cc)
        elif tc < cc:
            self.executor.nav_left(cc - tc)
            buf.move_left(cc - tc)
        # 不要用 assert：python -O 会把它整行删掉，而这是光标不错位的唯一守卫。
        # 一旦错位，EDIT_PREVIOUS / REWRITE_CHUNK 就会在错误位置删除文本。
        if buf.cursor != pos:
            self.logger.log("NAV", "desync", f"{buf.cursor}!={pos}", 0)
            raise RuntimeError(f"navigation desync: {buf.cursor} != {pos}")

    def _retype_span(self, a, b):
        """选区删掉 [a,b) 再原样重打。返回 False 表示这段没被改动
        （导航未完成就被要求停止，或者删掉的内容与预期不符）。"""
        buf = self.buffer
        expected = buf.seg(a, b)
        self._navigate_to(a)
        if self.kill.killed():
            return False     # 还没删任何东西，此刻放弃是安全的
        self.executor.select_shift_right(b - a)
        removed = buf.delete_forward(b - a)
        if removed != expected:
            self.logger.log("EDIT_PREVIOUS", "delete_mismatch", repr(removed), 0)
            return False
        self._retype(expected)
        self._flush_correction()
        ok = buf.seg(a, a + len(expected)) == expected
        if not ok:
            self.logger.log("EDIT_PREVIOUS", "retype_mismatch", repr(expected), 0)
        return ok

    def _h_edit_previous(self):
        buf = self.buffer
        cur_line = buf.current_line()
        lo_n, hi_n = self.cfg.edit_lookback_range
        lo = max(0, cur_line - hi_n)
        hi = cur_line - lo_n
        if hi <= lo:
            return "TYPING"
        candidates = list(range(lo, hi))
        weights = [1.0 / (cur_line - i) for i in candidates]
        target = self.rng.choices(candidates, weights=weights, k=1)[0]
        words = buf.words_on_line(target)
        if not words:
            return "TYPING"
        a, b, wtext = self.rng.choice(words)
        kinds, ws = zip(*self.cfg.edit_op_weights)
        op = self.rng.choices(kinds, weights=ws, k=1)[0]
        self.stats["edits"] += 1
        self.logger.log("EDIT_PREVIOUS", "start", f"{op} '{wtext}' line={target}", 0)
        line_end = buf.line_end_excl_newline(target)
        if op == "replace_word":
            self._retype_span(a, b)
        elif op == "retype_clause":
            b2 = min(b + self.rng.randint(3, 10), line_end)
            self._retype_span(a, b2)
        else:
            b2 = min(a + self.rng.randint(2, 5), line_end)
            if self._retype_span(a, b2):
                c2 = min(b2 + self.rng.randint(2, 5), line_end)
                self._retype_span(b2, c2)
        self._return_to_end()
        rp = self.rng.uniform(*self.cfg.edit_return_pause)
        self._sleep(rp / self.cfg.speed_multiplier, active=True)
        self.logger.log("EDIT_PREVIOUS", "exit", "", rp * 1000)
        return "TYPING"

    def _h_review(self):
        """回读遍数：用纯方向键回扫一眼刚写的内容，只读不改。

        这是整个状态机里唯一不修改文本的状态——只移动光标，因此
        `buffer.text == source` 这条不变式完全不受影响。真实的人写完
        一行会瞄一眼，而模型此前只会"写"、从不"回头看"。
        """
        back = self.rng.randint(*self.cfg.review_back_range)
        if self.buffer.cursor <= 1:
            return "TYPING"
        back = min(back, self.buffer.cursor)
        self.stats["reviews"] += 1
        self.logger.log("REVIEW", "start", f"back={back}", 0)
        self._navigate_to(self.buffer.cursor - back)
        if self.kill.killed():
            return "TYPING"
        self._sleep(self.rng.uniform(0.25, 0.9), active=True)
        if self.kill.killed():
            return "TYPING"
        # 轻微的视线移动：往左再看一两下，所以中途最左位置会略窄于 back
        back2 = self.rng.randint(1, 3)
        self._navigate_to(max(0, self.buffer.cursor - back2))
        self._sleep(self.rng.uniform(0.15, 0.5), active=True)
        self._return_to_end()
        if self.kill.killed():
            return "TYPING"
        self._sleep(self.rng.uniform(0.1, 0.35), active=True)
        self.logger.log("REVIEW", "exit", "", 0)
        return "TYPING"

    def _h_rewrite_chunk(self):
        buf = self.buffer
        complete = buf.complete_line_count()
        k = min(self.rng.randint(*self.cfg.rewrite_lines_range), complete)
        if k < 1:
            return "TYPING"
        starts = buf._line_starts()
        partial_start = starts[-1]
        chunk_start = starts[-1 - k]
        chunk_text = buf.text[chunk_start:partial_start]
        if not chunk_text.endswith("\n"):
            return "TYPING"
        self.logger.log("REWRITE_CHUNK", "start", f"k={k} len={len(chunk_text)}", 0)
        self._navigate_to(chunk_start)
        if self.kill.killed():
            return "TYPING"    # 还没删任何东西，直接放弃
        self.stats["rewrites"] += 1
        self.executor.select_shift_down(k)
        removed = buf.delete_forward(len(chunk_text))
        if removed != chunk_text:
            self.logger.log("REWRITE_CHUNK", "delete_mismatch", "", 0)
            self._return_to_end()
            return "TYPING"
        self._retype(chunk_text)
        self._flush_correction()
        ok = buf.text[chunk_start:chunk_start + len(chunk_text)] == chunk_text
        if not ok:
            self.logger.log("REWRITE_CHUNK", "retype_mismatch", "", 0)
        self._return_to_end()
        self.logger.log("REWRITE_CHUNK", "exit", f"ok={ok}", 0)
        return "TYPING"
