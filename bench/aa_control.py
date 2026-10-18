"""
A/A null control: two byte-identical copies must produce ratio ~1.0.

This is the calibration that decides how large an effect has to be before it is
worth reporting. Run it before believing any A/B number.

Two temporary copies of *this* repository are created, imported as separate
modules, and timed against each other. They are byte-identical, so any ratio
that deviates from 1.0 is measurement noise, not a difference in the code.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (
    DATASETS,
    REPO,
    calibrate,
    configs,
    dataset,
    dump,
    interleaved,
    quiet_gc,
)


def clone(dest: str) -> None:
    """Copy just the package, which is enough to import it."""
    shutil.copytree(
        os.path.join(REPO, "natsort"),
        os.path.join(dest, "natsort"),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def main() -> int:
    quiet_gc()
    tmp = tempfile.mkdtemp(prefix="natsort-aa-")
    arm_a, arm_b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
    try:
        clone(arm_a)
        clone(arm_b)

        sys.path.insert(0, arm_a)
        import natsort as first

        sys.path.remove(arm_a)
        for mod in [
            m for m in sys.modules if m == "natsort" or m.startswith("natsort.")
        ]:
            del sys.modules[mod]
        sys.path.insert(0, arm_b)
        import natsort as second

        sys.path.remove(arm_b)

        rows = []
        for ds in DATASETS:
            data = dataset(ds)
            for label, alg in configs(first.ns):
                fa = first.natsort_keygen(alg=alg)
                fb = second.natsort_keygen(alg=alg)

                def arm_1(f=fa, d=data):
                    return [f(s) for s in d]

                def arm_2(f=fb, d=data):
                    return [f(s) for s in d]

                ia, ib = calibrate(arm_1), calibrate(arm_2)
                r = interleaved(arm_1, arm_2, ia, ib, rounds=7)
                rows.append({"dataset": ds, "config": label, **r})
                print(
                    f"{ds:10s} {label:10s} ratio={r['ratio_median']:.4f} "
                    f"[{r['ratio_min']:.4f},{r['ratio_max']:.4f}]",
                    flush=True,
                )
        ratios = sorted(row["ratio_median"] for row in rows)
        print(
            "AA median",
            round(ratios[len(ratios) // 2], 4),
            "min",
            round(min(ratios), 4),
            "max",
            round(max(ratios), 4),
        )
        dump(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "results", "aa_control.json"
            ),
            {"rows": rows},
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
