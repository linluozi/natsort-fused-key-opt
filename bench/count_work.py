"""
Deterministic work counters: no clocks, only counts.

Clock-based speedups are noisy (see the A/A control). These counters measure
the work the implementation performs, which is stable across runs and makes
the mechanism of the speedup verifiable rather than asserted:

* Python-level function calls per key (generator steps, per-component
  ``fast_int`` calls, ``sep_inserter`` yields, ``unicodedata.normalize``).
* Number of components produced per string (must be identical on both arms).

The counters are collected with ``sys.setprofile``, which reports every
Python call and C call boundary. Only calls into ``natsort`` modules and the
handful of C functions on the hot path are counted, so the numbers are
comparable between arms.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import configs, dataset, dump, load_arm

WATCHED = {
    "unicodedata.normalize",
    "re.Pattern.split",
    "re.Pattern.finditer",
    "_re.Pattern.split",
    "_re.Pattern.finditer",
}


def count_calls(fn, data):
    """Profile *fn* over *data* and return call counts grouped by function."""
    counts: dict[str, int] = {}

    def prof(frame, event, _arg) -> None:
        if event != "call":
            return
        code = frame.f_code
        name = code.co_name
        if "natsort" in code.co_filename:
            key = f"{os.path.basename(code.co_filename)}:{name}"
            counts[key] = counts.get(key, 0) + 1
        elif name in WATCHED:
            counts[name] = counts.get(name, 0) + 1

    sys.setprofile(prof)
    try:
        result = [fn(s) for s in data]
    finally:
        sys.setprofile(None)
    return counts, result


def main() -> int:
    up = load_arm("upstream")
    opt = load_arm("self")
    rows = []
    for ds in ["filenames", "version", "numbers"]:
        data = dataset(ds, 500)
        for label, alg in configs(up.ns)[:2]:
            ku = up.natsort_keygen(alg=alg)
            ko = opt.natsort_keygen(alg=alg)
            cu, ru = count_calls(ku, data)
            co, ro = count_calls(ko, data)
            assert ru == ro, f"component output differs for {ds}/{label}"
            components = sum(len(t) for t in ru)
            row = {
                "dataset": ds,
                "config": label,
                "python_calls_upstream": sum(cu.values()),
                "python_calls_optimised": sum(co.values()),
                "components": components,
                "breakdown_upstream": dict(
                    sorted(cu.items(), key=lambda kv: -kv[1])[:6]
                ),
                "breakdown_optimised": dict(
                    sorted(co.items(), key=lambda kv: -kv[1])[:6]
                ),
            }
            rows.append(row)
    dump(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "results", "work_count.json"
        ),
        {"rows": rows},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
