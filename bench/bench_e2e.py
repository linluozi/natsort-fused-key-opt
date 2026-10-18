"""
End-to-end benchmark of ``natsorted`` / ``nsorted`` style calls.

This is the number a user actually experiences: the key function is only a
means to that end. 5000-element lists keep the comparison step meaningful
(about 15% of the total), so the speedups here are lower than key-only
measurements - and more honest.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (
    calibrate,
    dump,
    interleaved,
    load_arm,
    quiet_gc,
)

CASES = ["filenames", "version", "words", "numbers", "longpath", "unicode"]


def main() -> int:
    quiet_gc()
    up = load_arm("upstream")
    opt = load_arm("self")
    from harness import dataset

    rows = []
    for ds in CASES:
        data = dataset(ds, 5000)
        for label, alg in [
            ("INT", 0),
            ("REAL", up.ns.REAL),
            ("IGNORECASE", up.ns.IGNORECASE),
        ]:

            def a(d=data, al=alg):
                return up.natsorted(d, alg=al)

            def b(d=data, al=alg):
                return opt.natsorted(d, alg=al)

            assert a() == b(), f"sort order differs for {ds}/{label}"
            ia = calibrate(a)
            ib = calibrate(b)
            r = interleaved(a, b, ia, ib, rounds=9)
            rows.append(
                {
                    "dataset": ds,
                    "config": label,
                    "n_items": len(data),
                    "upstream_ms": r["a_median"] * 1e3,
                    "optimised_ms": r["b_median"] * 1e3,
                    "speedup_median": r["ratio_median"],
                    "speedup_min": r["ratio_min"],
                    "speedup_max": r["ratio_max"],
                }
            )
    dump(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "results", "bench_e2e.json"
        ),
        {"rows": rows},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
