import argparse
import os
import random
import sys
import time

from .config import Config
from .keymap import unsupported_chars
from .machine import AutoTyper
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
    而编辑器收到的是回车键，两边就此错位。"""
    with open(path, "r", encoding="utf-8") as f:
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
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
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
        verbose=args.verbose,
    )
    if args.preset not in PRESETS:
        print(f"ERROR: unknown preset '{args.preset}'. "
              f"Available: {', '.join(preset_names())} "
              f"(or --preset list for details)")
        return 1
    overridden = apply_preset(cfg, args.preset)
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

    rng = random.Random(args.seed)
    typer = AutoTyper(cfg, source, rng=rng)

    mode = "LIVE" if not cfg.dry_run else "DRY-RUN"
    print(f"mode={mode} chars={len(source)} speed={cfg.speed_multiplier}x "
          f"kill_hotkey={cfg.kill_hotkey.upper()}")
    print(f"source: {source_desc}")
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
        print(f"{k}: {v}")
    return 0 if not summary.get("killed") else 130


if __name__ == "__main__":
    sys.exit(main())
