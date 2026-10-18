"""Interleaved A/B benchmark: pristine upstream vs optimised key builder.

Reported numbers are per-call medians of per-round ratios (see harness.py for
why). The A/A control in ``aa_control.json`` bounds what counts as signal:
anything inside roughly +-10% is noise on this machine.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (  # noqa: E402
    DATASETS,
    calibrate,
    configs,
    dataset,
    dump,
    interleaved,
    load_arm,
    quiet_gc,
    timed,
)

ROUNDS = 9


def main() -> int:
    quiet_gc()
    up = load_arm("upstream")
    opt = load_arm("self")

    rows = []
    for ds in DATASETS:
        data = dataset(ds)
        for label, alg in configs(up.ns):
            fu = up.natsort_keygen(alg=alg)
            fo = opt.natsort_keygen(alg=alg)

            # The exact same workload on both arms: build one key per string.
            def arm_a(f=fu, d=data):
                return [f(s) for s in d]

            def arm_b(f=fo, d=data):
                return [f(s) for s in d]

            ia = calibrate(arm_a)
            ib = calibrate(arm_b)
            r = interleaved(arm_a, arm_b, ia, ib, rounds=ROUNDS)
            per_call_up = r["a_median"] / len(data)
            per_call_opt = r["b_median"] / len(data)
            row = {
                "dataset": ds,
                "config": label,
                "n_items": len(data),
                "upstream_us_per_item": per_call_up * 1e6,
                "optimised_us_per_item": per_call_opt * 1e6,
                "speedup_median": r["ratio_median"],
                "speedup_min": r["ratio_min"],
                "speedup_max": r["ratio_max"],
                "iters_upstream": ia,
                "iters_optimised": ib,
            }
            rows.append(row)
            print(
                f"{ds:10s} {label:10s} {per_call_up*1e6:7.2f} -> {per_call_opt*1e6:6.2f} us  "
                f"{r['ratio_median']:5.2f}x  [{r['ratio_min']:4.2f},{r['ratio_max']:4.2f}]",
                flush=True,
            )

    dump(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "bench_key.json"),
        {"rounds": ROUNDS, "rows": rows},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
