"""validate.py — batch validation across seeds + kill-switch path test."""
import os
import random
import threading

from .config import Config
from .machine import AutoTyper
from .main import DEMO_SOURCE


def batch():
    rows = []
    for seed in (1, 2, 3, 4, 5):
        cfg = Config(
            speed_multiplier=200.0, countdown_seconds=0,
            line_end_think_prob=0.10,
            pause_short_ln_mu=-3.0, pause_short_clip=(0.003, 0.02),
            edit_min_gap_s=0.0, p_edit_previous=0.03,
            p_rewrite_chunk=0.05,
            log_file=os.devnull,
        )
        t = AutoTyper(cfg, DEMO_SOURCE, rng=random.Random(seed))
        t.sched.threshold = 8.0  # human-scale active seconds -> long pause
        s = t.run()
        ok = (s["final_matches_source"]
              and s["source_consumed"] == len(DEMO_SOURCE))
        print(f"seed={seed} invariant={ok} errors={s['errors']} "
              f"bursts={s['bursts']} shortP={s['short_pauses']} "
              f"longP={s['long_pauses']} edits={s['edits']} "
              f"rewrites={s['rewrites']}")
        assert ok, "INVARIANT VIOLATION"
        rows.append(s)
    errs = [r["errors"] for r in rows]
    bursts = [r["bursts"] for r in rows]
    edits = [r["edits"] for r in rows]
    rewrites = [r["rewrites"] for r in rows]
    assert sum(errs) > 0 and sum(bursts) > 0
    assert sum(edits) > 0 and sum(rewrites) > 0
    print(f"BATCH PASS: typos {min(errs)}-{max(errs)}, bursts {min(bursts)}"
          f"-{max(bursts)}, edits {min(edits)}-{max(edits)}, "
          f"rewrites {min(rewrites)}-{max(rewrites)} across seeds")


def kill_switch():
    cfg = Config(speed_multiplier=100.0, log_file=os.devnull)  # slow enough to interrupt
    from .executor import Killer

    k = Killer()
    t = AutoTyper(cfg, DEMO_SOURCE * 20, rng=random.Random(9), killer=k)
    th = threading.Timer(1.5, k.set)
    th.start()
    s = t.run()
    th.join()
    n = len(DEMO_SOURCE) * 20
    print(f"kill_switch: killed={s['killed']} consumed={s['source_consumed']}"
          f"/{n}")
    assert s["killed"] and s["source_consumed"] < n
    print("KILL-SWITCH PATH OK")


if __name__ == "__main__":
    batch()
    kill_switch()
    print("ALL VALIDATION PASSED")
