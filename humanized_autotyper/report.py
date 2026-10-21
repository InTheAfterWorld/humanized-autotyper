"""report.py — audit observed behaviour against configured probabilities.

Run a dry-run first to export an event CSV, then:

    autotyper-report out.csv            # audit every run found in the file
    autotyper-report out.csv --run 2    # audit only the 2nd run
    autotyper-report out.csv --list     # just list the runs

Reads the event log written by Logger (ts,run_id,state,event,detail,delay_ms)
and prints observed vs. expected frequencies for the key humanization knobs.

Why runs are split
------------------
The log is opened in append mode, so one file accumulates many runs.  Pooling
them mixes populations recorded under different settings -- a `--speed 30`
smoke run (median ~4ms) next to a real 1.0x run (median ~115ms) drags the
pooled median to ~67ms and inflates CV from ~0.46 to ~1.00, which reads as
"unstable rhythm" when nothing changed.  Each run now writes `RUN,start` (with
a config snapshot) and `RUN,end` rows, so this module splits on those and
compares each segment against the config that actually produced it.
"""
import argparse
import csv
import json
import statistics
import sys
from collections import Counter

from .config import Config


def load(path):
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for line in reader:
            rows.append(line)
    return rows


def _cfg_from_snapshot(detail):
    """Rebuild the Config a run actually used, from its RUN,start detail."""
    try:
        snap = json.loads(detail)
    except (TypeError, ValueError):
        return None
    if not isinstance(snap, dict):
        return None
    kwargs = {}
    for k, v in snap.items():
        # tuples round-trip as JSON lists; Config consumers unpack them
        # (`lo, hi = cfg.delay_clip`), so restore tuples for the known ones.
        if isinstance(v, list):
            v = tuple(tuple(x) if isinstance(x, list) else x for x in v)
        kwargs[k] = v
    try:
        return Config(**kwargs)
    except TypeError:
        return None


def split_runs(rows):
    """Group rows into runs.  Returns a list of dicts.

    Each dict: {"index", "run_id", "rows", "cfg", "summary", "closed"}.
    `cfg` is None when the log predates run markers (or the snapshot failed to
    parse); callers fall back to Config() and say so in the output.

    Anchoring rule: a new run starts at a `RUN,start` marker.  The run_id column
    is only a *secondary* signal -- if a run_id change is seen while no marker
    opened the current run (legacy file, or a header/column mismatch from a
    crashed writer), the change is ignored rather than splitting the run apart.
    """
    runs = []
    cur = None

    def open_run(rid):
        run = {"index": len(runs) + 1, "run_id": rid or "", "rows": [],
               "cfg": None, "summary": None, "closed": False}
        runs.append(run)
        return run

    for r in rows:
        # 防御：日志可能被截断/串写，或表头与数据列数不一致（DictReader 会把
        # 多余列塞进 None 键、缺失列留 None）。取不到 state 就当普通行处理，
        # 不能在这里 KeyError 崩掉——report 的作用恰恰是诊断坏日志。
        state = r.get("state") or ""
        event = r.get("event") or ""
        rid = r.get("run_id") or ""
        if state == "RUN":
            if event == "start":
                cur = open_run(rid)
                cur["cfg"] = _cfg_from_snapshot(r.get("detail"))
                continue
            if event == "end":
                if cur is not None:
                    cur["closed"] = True
                    try:
                        cur["summary"] = json.loads(r.get("detail") or "")
                    except (TypeError, ValueError):
                        cur["summary"] = None
                continue
            continue                      # unknown RUN event: ignore
        if cur is None:
            # Rows before any marker (legacy log) form one implicit run.
            cur = open_run("")
        elif not cur["run_id"] and rid:
            cur["run_id"] = rid
        cur["rows"].append(r)

    for run in runs:
        if not run["run_id"]:
            run["run_id"] = "(unsegmented)"
    return [run for run in runs if run["rows"]]


def _fmt_horizon_seconds(seconds):
    """Sub-minute ranges are used by tests/tuning; don't round them to 0min."""
    if abs(seconds) < 60:
        return f"{seconds:g}s"
    return f"{seconds / 60:.0f}min"


def _audit(run, cfg, out=print):
    """Print obs-vs-cfg for one run.  `cfg` must already be resolved."""
    rows = run["rows"]
    events = Counter(((r.get("state") or ""), (r.get("event") or ""))
                     for r in rows)
    chars = sum(1 for r in rows if r.get("event") == "char")
    legal = sum(1 for r in rows
                if r.get("event") == "char" and r.get("detail") != "'\\n'")
    errors = events.get(("TYPING", "typo"), 0)
    corrections = events.get(("TYPING", "corr"), 0)
    bursts = events.get(("BACKSPACE_BURST", "enter"), 0)
    pauses = events.get(("PAUSE_SHORT", "sleep"), 0)
    long_pauses = events.get(("PAUSE_LONG", "sleep"), 0)
    rests = events.get(("REST", "sleep"), 0)
    edits = events.get(("EDIT_PREVIOUS", "start"), 0)
    rewrites = events.get(("REWRITE_CHUNK", "start"), 0)
    reviews = events.get(("REVIEW", "start"), 0)

    delays = []
    for r in rows:
        if r.get("event") != "char":
            continue
        raw = r.get("delay_ms")
        if raw in (None, ""):
            continue
        try:                       # 坏日志里可能有非数字（串写/半行）
            delays.append(float(raw))
        except (TypeError, ValueError):
            continue
    delays.sort()

    def line(name, observed, target_frac, n, note=""):
        obs = 100.0 * observed / n if n else 0.0
        out(f"{name:26s} obs {obs:6.2f}%   cfg {target_frac * 100:6.2f}%   {note}")

    out(f"rows        : {len(rows)}")
    out(f"chars       : {chars}  (errors {errors}, corrections {corrections})")
    out()
    line("typo rate", errors, cfg.p_typo, legal,
         f"(boost x{cfg.typo_autocorr_boost} for {cfg.typo_autocorr_window} "
         f"chars after a typo)")
    line("backspace burst", bursts, cfg.p_backspace_burst, chars,
         f"n in {cfg.backspace_n_range}")
    line("short pause (mid-line)", pauses, cfg.p_pause_short, chars)
    if getattr(cfg, "long_horizon", False):
        ws_lo, ws_hi = cfg.work_session_range
        br_lo, br_hi = cfg.break_range
        out(f"{'long-horizon rests':26s} {rests}  (work "
            f"{_fmt_horizon_seconds(ws_lo)}-{_fmt_horizon_seconds(ws_hi)}, "
            f"break {_fmt_horizon_seconds(br_lo)}-"
            f"{_fmt_horizon_seconds(br_hi)})")
    else:
        out(f"{'long pauses':26s} {long_pauses} (Pareto x_min="
            f"{cfg.long_pause_xmin:.0f}s alpha={cfg.long_pause_alpha})")
    out(f"{'edit previous':26s} {edits}  p={cfg.p_edit_previous} at line end")
    out(f"{'rewrite chunk':26s} {rewrites}  p={cfg.p_rewrite_chunk} at line end")
    out(f"{'review pass':26s} {reviews}  p={cfg.p_review} at line end")

    out()
    if delays:
        mid = delays[len(delays) // 2]
        p95 = delays[int(len(delays) * 0.95)]
        mean = statistics.mean(delays)
        cv = statistics.pstdev(delays) / mean if len(delays) > 1 and mean else 0.0
        # delay_ms is already wall-clock: delays.py divides by speed_multiplier
        # before the sample is logged.  Multiply back to get the human-scale
        # delay that config.delay_clip actually bounds.
        speed = cfg.speed_multiplier or 1.0
        out(f"per-char delay_ms: n={len(delays)} min={delays[0]:.1f} "
            f"median={mid:.1f} p95={p95:.1f} max={delays[-1]:.1f} CV={cv:.2f} "
            f"(speed {speed:g}x)")
        out(f"  human-scale (x{speed:g}): median={mid * speed:.1f} "
            f"p95={p95 * speed:.1f}  cfg clip {cfg.delay_clip[0]*1000:.0f}.."
            f"{cfg.delay_clip[1]*1000:.0f}ms  cfg median~{cfg.delay_mu*1000:.0f}ms")
    if errors and not corrections:
        out("\nWARNING: typos happened but no corrections logged — check "
            "the correction path.")


def _run_label(run, total):
    flags = []
    if run["cfg"] is None:
        flags.append("cfg UNKNOWN (falling back to Config() defaults)")
    if not run["closed"]:
        flags.append("no RUN,end (process may have been killed)")
    s = run.get("summary") or {}
    if s.get("killed"):
        flags.append("killed")
    if s and s.get("final_matches_source") is False:
        flags.append("content mismatch")
    suffix = ("  [" + "; ".join(flags) + "]") if flags else ""
    return f"run {run['index']}/{total}  id={run['run_id']}{suffix}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit autotyper CSV event log")
    ap.add_argument("log", help="path to exported CSV event log")
    ap.add_argument("--run", type=int, default=None,
                    help="only audit this run number (default: all runs)")
    ap.add_argument("--list", action="store_true",
                    help="list the runs found in the file and exit")
    args = ap.parse_args(argv)

    rows = load(args.log)
    runs = split_runs(rows)
    if not runs:
        print(f"{args.log}: no usable rows.")
        return 1

    if args.list:
        print(f"{len(runs)} run(s) in {args.log}:")
        for run in runs:
            chars = sum(1 for r in run["rows"] if r.get("event") == "char")
            print(f"  {_run_label(run, len(runs))}  chars={chars}")
        return 0

    if args.run is None:
        selected = runs
    else:
        selected = [r for r in runs if r["index"] == args.run]
        if not selected:
            print(f"ERROR: no run #{args.run} in {args.log} "
                  f"(found {len(runs)} run(s); use --list)")
            return 1

    print(f"{args.log}: {len(runs)} run(s) found, auditing {len(selected)}.")
    if len(runs) > 1:
        print("NOTE: the log accumulates runs, so each is audited separately "
              "against its own config. Use --run N / --list to narrow down.")
    print()

    for i, run in enumerate(selected):
        if i:
            print()
            print("-" * 72)
            print()
        print(_run_label(run, len(runs)))
        _audit(run, run["cfg"] or Config())
    return 0


if __name__ == "__main__":
    # 与 __main__.py / gui.py 保持一致：把 main() 的返回值真正作为进程退出码，
    # 否则 `python -m humanized_autotyper.report --run 9` 明明报错却仍返回 0。
    sys.exit(main())