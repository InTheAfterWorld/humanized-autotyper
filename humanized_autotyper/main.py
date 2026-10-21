import argparse
import json
import os
import random
import sys
import time

from .config import Config
from .keymap import unsupported_chars
from .machine import AutoTyper
from .modes import (DEFAULT_EXTS, VSCODE_REQUIRED_SETTINGS, SingleFileMode,
                    VSCodeMode, collect_targets, get_mode, mode_names)
from .presets import PRESETS, apply_preset, describe, preset_names

DEMO_SOURCE = '''def compute_stats(numbers):
    total = 0
    count = 0
    for n in numbers:
        if n < 0:
            continue
        total += n
        count += 1
    mean = total / count if count else 0.0
    return {"total": total, "count": count, "mean": mean}


class Session:
    def __init__(self, name):
        self.name = name
        self.events = []

    def record(self, kind, value):
        self.events.append((kind, value))

    def summary(self):
        kinds = [k for k, _ in self.events]
        return {k: kinds.count(k) for k in set(kinds)}


def main():
    data = [3, 7, -2, 10, 4, 8, -5, 6]
    stats = compute_stats(data)
    session = Session("demo")
    for key, value in stats.items():
        session.record("stat", (key, value))
    print(session.summary())


if __name__ == "__main__":
    main()
'''


def read_source(path):
    """读入源文本。\r\n 与单独的 \r 一律归一成 \n——否则缓冲区里记的是 \r，
    而编辑器收到的是回车键，两边就此错位。

    用 utf-8-sig 顺带剥掉 UTF-8 BOM：BOM 会变成内容首字符 U+FEFF，而它
    打不出来（见 modes.py::VSCodeMode._make_target 的说明）。
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


def source_problem(source):
    """返回拒绝启动的理由，没有问题则返回 None。"""
    if not source.strip():
        return "source text is empty (nothing to type)."
    bad = unsupported_chars(source)
    if bad:
        shown = ", ".join(f"{i}:{ch!r}" for i, ch in bad[:5])
        more = "" if len(bad) <= 5 else f" (+{len(bad) - 5} more)"
        return (f"source contains {len(bad)} character(s) that cannot be typed "
                f"reliably: {shown}{more}")
    return None


def parse_args(argv):
    p = argparse.ArgumentParser(description="Humanized autotyper")
    p.add_argument("--file", help="path of source text to type (utf-8)")
    p.add_argument("--live", action="store_true",
                   help="send real keystrokes (default: dry-run)")
    p.add_argument("--speed", type=float, default=1.0,
                   help=">1 faster, <1 slower")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--preset", default="标准", metavar="NAME",
                   help=f"behaviour preset, one of: {', '.join(preset_names())}"
                        " (default: 标准)")
    p.add_argument("--window", default="",
                   help="expected foreground window title substring (live only)")
    p.add_argument("--log", default="autotyper_log.csv")
    p.add_argument("--fresh", action="store_true",
                   help="truncate the log file instead of appending to it "
                        "(the log accumulates runs otherwise; report can split "
                        "them, but --fresh keeps the file single-run)")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--long-horizon", action="store_true",
                   help="simulate long work sessions with real rests "
                        "(work 60-120 min, rest 5-30 min; replaces the "
                        "Pareto long-pause schedule)")
    p.add_argument("--mode", default="notepad", metavar="NAME",
                   help=f"typing mode, one of: {', '.join(mode_names())} "
                        "(default: notepad; --mode list for details)")
    p.add_argument("--src-dir", default=".",
                   help="vscode mode: source directory to enumerate")
    p.add_argument("--ext", default=",".join(DEFAULT_EXTS), metavar="LIST",
                   help="vscode mode: comma-separated extensions to include")
    p.add_argument("--max-files", type=int, default=0,
                   help="vscode mode: only process the first N files (0 = all)")
    return p.parse_args(argv)


def _build_mode(args):
    """按 --mode 构造模式实例。多目标模式在这里枚举 + preflight。

    返回 (mode, targets)：
    - 多目标模式（vscode）：返回 (mode, targets 列表)
    - 单文档路径（notepad）：返回 (None, None)，此时 source 还没读，
      由 main() 读完 source 后再构造 SingleFileMode。

    早先这里返回 SingleFileMode(None) 当占位，那是个类型谎言：source 是
    str，传 None 既不合法也毫无意义（该对象马上就要被 main() 覆盖掉）。
    """
    if args.mode == "vscode":
        exts = [e.strip() for e in args.ext.split(",") if e.strip()]
        mode = VSCodeMode(args.src_dir, exts=exts, max_files=args.max_files)
        try:
            targets = collect_targets(mode)
        except ValueError as exc:
            print("ERROR: 无法启动 VSCode 模式：")
            for line in str(exc).splitlines():
                print(f"  - {line}")
            print("\n提示：把下面的配置加进 VSCode 的 settings.json 后重试：")
            for k, (v, why) in VSCODE_REQUIRED_SETTINGS.items():
                print(f'  "{k}": {json.dumps(v)},   # 否则{why}')
            raise SystemExit(1)
        return mode, targets
    return None, None


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.mode in ("list", "?"):
        print("available modes:")
        for name in mode_names():
            cls = get_mode(name)
            print(f"  {name:10s} {getattr(cls, 'label', '')}")
        return 0
    if args.mode not in mode_names():
        print(f"ERROR: unknown mode '{args.mode}'. "
              f"Available: {', '.join(mode_names())} "
              f"(or --mode list for details)")
        return 1
    if args.preset in ("list", "?"):
        print("available presets:")
        for name in preset_names():
            print(f"  {name:10s} {describe(name)}")
        return 0
    if args.window and not args.live:
        # check_window() 在 dry-run 下直接返回 True，--window 会变成空承诺；
        # README 把它写成"必须传"，所以这里明确拒绝而不是静默忽略。
        print("ERROR: --window only applies to --live; without it window "
              "validation would be silently skipped.")
        return 1
    cfg = Config(
        dry_run=not args.live,
        speed_multiplier=max(0.05, args.speed),
        expected_window_title=args.window,
        log_file=args.log,
        fresh_log=args.fresh,
        long_horizon=args.long_horizon,
        verbose=args.verbose,
    )
    if args.preset not in PRESETS:
        print(f"ERROR: unknown preset '{args.preset}'. "
              f"Available: {', '.join(preset_names())} "
              f"(or --preset list for details)")
        return 1
    overridden = apply_preset(cfg, args.preset)

    # 多目标模式自己枚举文件，不走单文档的 source 读取 / 字符集校验
    typer_mode, targets = _build_mode(args)

    if targets is None:
        source = DEMO_SOURCE
        source_desc = "built-in demo"
        if args.file:
            source = read_source(args.file)
            source_desc = args.file
        else:
            # default: read ./source.txt in the current working directory
            default_txt = "source.txt"
            if os.path.exists(default_txt):
                source = read_source(default_txt)
                source_desc = default_txt
        problem = source_problem(source)
        if problem:
            print(f"ERROR: {problem}")
            return 1
        typer_mode = SingleFileMode(source, source_desc)
    else:
        source = ""
        source_desc = f"{args.src_dir} ({args.ext})"

    rng = random.Random(args.seed)
    if targets is None:
        typer = AutoTyper(cfg, source, rng=rng, mode=typer_mode)
    else:
        # 多目标模式：source 由每个 Target 各自提供，这里传空串占位
        typer = AutoTyper(cfg, "", rng=rng, mode=typer_mode, targets=targets)

    run_mode = "LIVE" if not cfg.dry_run else "DRY-RUN"
    n_desc = f"{len(targets)} file(s)" if targets is not None else \
        f"chars={len(source)}"
    print(f"mode={run_mode} type_mode={args.mode} {n_desc} "
          f"speed={cfg.speed_multiplier}x "
          f"kill_hotkey={cfg.kill_hotkey.upper()}")
    print(f"source: {source_desc}")
    if cfg.long_horizon:
        ws, br = cfg.work_session_range, cfg.break_range
        print(f"long-horizon: work {ws[0] / 60:.0f}-{ws[1] / 60:.0f} min, "
              f"rest {br[0] / 60:.0f}-{br[1] / 60:.0f} min")
    # typer_mode 在两条分支里都已被赋成具体模式（notepad 在上面构造，
    # vscode 由 _build_mode 返回），这里统一提示各自的风险。
    if typer.mode is not None:
        for w in typer.mode.editor_warnings():
            print(f"WARNING: {w}")
    print(f"preset: {args.preset} ({describe(args.preset)}, "
          f"{overridden} fields)")
    if not cfg.dry_run:
        # 倒计时期间就装上键盘监听，F10 随时能中止
        typer.executor.start()
        try:
            for i in range(cfg.countdown_seconds, 0, -1):
                if typer.kill.killed():
                    break
                print(f"starting in {i}... "
                      f"({cfg.kill_hotkey.upper()} to abort)", flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            typer.kill.set()
            print("aborted.")

    try:
        summary = typer.run()
    finally:
        typer.executor.stop()
        typer.logger.close()
    print()
    print("=== summary ===")
    for k, v in summary.items():
        if k == "per_file":
            # 逐文件结论单独列：多文件场景下 bool 汇总没有排查价值
            print(f"per_file ({len(v)}):")
            for f in v:
                ok = f.get("ok")
                # 三态：True 通过 / False 失败 / None 未校验
                mark = "OK  " if ok is True else ("SKIP" if ok is None
                                                 else "FAIL")
                print(f"  [{mark}] {f.get('path')}  {f.get('detail', '')}")
            continue
        print(f"{k}: {v}")
    return 0 if not summary.get("killed") else 130


if __name__ == "__main__":
    sys.exit(main())
