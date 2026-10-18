"""Shared benchmark harness for the fused key builder.

Design rules (learned the hard way - see README "Methodology"):

  * A/A null control first: two byte-identical copies of the same tree are
    timed against each other to establish the noise floor. Any reported
    speedup must sit far outside it, otherwise it is not a result.
  * Interleaved rounds: the two arms alternate inside one round, and the
    per-round ratio is summarised by the median. Absolute timings drift with
    machine load; ratios mostly do not.
  * Per-arm iteration counts: an arm that is 5x faster would otherwise be
    dominated by timer overhead, so each arm is calibrated to roughly the same
    total wall time.
  * Deterministic secondary metrics (call counts, not clocks) are reported
    alongside timings, so conclusions do not rest on the clock alone.

Arms are resolved by ``arm_path`` so the same scripts work in the development
layout (``<lab>/upstream`` next to ``<lab>/work``) and in a plain clone, where
the reference implementation has to be fetched separately.
"""

from __future__ import annotations

import gc
import importlib
import json
import os
import statistics
import sys
import time
from typing import Callable

HERE = os.path.dirname(os.path.abspath(__file__))       # <repo>/bench
REPO = os.path.dirname(HERE)                            # <repo>

# Where the reference (pristine) implementation may live. Only explicit
# locations are searched: guessing a sibling directory would let a copy of this
# repository silently pick up somebody else's checkout, and a differential test
# that compares a tree with itself always passes.
REFERENCE_ENV = "NATSORT_UPSTREAM"
REFERENCE_CANDIDATES = (
    os.path.join(HERE, ".upstream"),                     # pip install --target
    os.path.join(REPO, "upstream"),                      # vendored copy
)


def arm_path(name: str) -> str:
    """
    Resolve an arm name to a directory containing a ``natsort`` package.

    Parameters
    ----------
    name : str
        ``"self"`` (this repository) or ``"upstream"`` (pristine reference).

    Returns
    -------
    str
        Absolute path to the directory that holds the ``natsort`` package.

    Raises
    ------
    SystemExit
        If the reference implementation cannot be found, with the command that
        downloads it.

    """
    if name in {"self", "work", "."}:
        return REPO
    if name != "upstream":
        raise SystemExit(f"unknown arm {name!r}; use 'self' or 'upstream'")

    env = os.environ.get(REFERENCE_ENV)
    candidates = (env,) if env else REFERENCE_CANDIDATES
    for candidate in candidates:
        if candidate and os.path.isdir(os.path.join(candidate, "natsort")):
            return candidate
    raise SystemExit(
        "reference implementation not found.\n"
        "Fetch it first, then re-run:\n"
        "    pip install --no-deps --target bench/.upstream natsort==8.4.0\n"
        f"or point ${REFERENCE_ENV} at a directory containing natsort/."
    )


def load_arm(name: str) -> object:
    """Import ``natsort`` from the named arm in a fresh module state."""
    path = arm_path(name)
    for name_ in [m for m in sys.modules if m == "natsort" or m.startswith("natsort.")]:
        del sys.modules[name_]
    sys.path.insert(0, path)
    try:
        mod = importlib.import_module("natsort")
    finally:
        sys.path.remove(path)
    got = os.path.dirname(os.path.dirname(os.path.abspath(mod.__file__)))
    assert os.path.samefile(got, path), f"imported {got}, expected {path}"
    return mod


# --------------------------------------------------------------------------
# Datasets. Deliberately not degenerate: a corpus of identical strings or of
# pure words measures the splitter, not the numeric conversion.
# --------------------------------------------------------------------------

def dataset(name: str, n: int = 2000) -> list[str]:
    import random
    import string

    rnd = random.Random(20261018)
    if name == "version":            # version strings, mixed int segments
        return [
            f"pkg-{rnd.randint(0, 40)}.{rnd.randint(0, 30)}.{rnd.randint(0, 99)}"
            for _ in range(n)
        ]
    if name == "filenames":          # realistic filenames: text+numeric mix
        out = []
        for _ in range(n):
            body = "".join(
                rnd.choice(string.ascii_lowercase)
                if rnd.random() < 0.7
                else str(rnd.randint(0, 9999))
                for _ in range(rnd.randint(4, 10))
            )
            out.append(f"{body}_{rnd.randint(0, 999)}.txt")
        return out
    if name == "words":              # no digits at all: splitter-only workload
        return [
            "".join(rnd.choice(string.ascii_lowercase) for _ in range(12))
            for _ in range(n)
        ]
    if name == "numbers":            # pure integers as strings
        return [str(rnd.randint(0, 10**rnd.randint(1, 12))) for _ in range(n)]
    if name == "floats":             # floats, exercises the float path
        return [f"{rnd.uniform(-1e6, 1e6):.6g}" for _ in range(n)]
    if name == "unicode":            # unicode digits + accents (NFD matters)
        return [
            f"第{rnd.randint(0, 500)}章_café_{rnd.randint(0, 99)}.md" for _ in range(n)
        ]
    if name == "longpath":           # long strings with many components
        out = []
        for _ in range(max(1, n // 10)):
            out.append(
                "/".join(
                    f"dir{rnd.randint(0, 99)}/file{rnd.randint(0, 999)}_v{rnd.randint(0, 9)}"
                    for _ in range(6)
                )
            )
        return out
    raise KeyError(name)


DATASETS = ["version", "filenames", "words", "numbers", "floats", "unicode", "longpath"]


def configs(ns):
    """Algorithm presets used across the benchmarks."""
    return [
        ("INT", ns.DEFAULT),
        ("REAL", ns.REAL),
        ("IGNORECASE", ns.IGNORECASE),
        ("NUMAFTER", ns.NUMAFTER),
    ]


def calibrate(fn: Callable[[], object], target: float = 0.025) -> int:
    """Return an iteration count whose runtime is close to *target* seconds."""
    n = 1
    while True:
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        dt = time.perf_counter() - t0
        if dt >= target or n >= 1 << 20:
            return max(1, int(n * target / max(dt, 1e-9)))
        n = max(n * 2, int(n * target / max(dt, 1e-9)) + 1)


def timed(fn: Callable[[], object], iters: int, repeat: int = 5) -> float:
    """Best-of-N mean-per-call time. Best-of-N resists GC/OS jitter spikes."""
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        for _ in range(iters):
            fn()
        dt = (time.perf_counter() - t0) / iters
        best = min(best, dt)
    return best


def interleaved(
    a: Callable[[], object],
    b: Callable[[], object],
    iters_a: int,
    iters_b: int,
    rounds: int = 9,
) -> dict:
    """Alternate A and B across rounds; summarise per-round ratios."""
    ratios, ta_all, tb_all = [], [], []
    for i in range(rounds):
        if i % 2 == 0:
            ta = timed(a, iters_a, repeat=1)
            tb = timed(b, iters_b, repeat=1)
        else:  # reverse order to cancel position effects
            tb = timed(b, iters_b, repeat=1)
            ta = timed(a, iters_a, repeat=1)
        ratios.append(ta / tb)
        ta_all.append(ta)
        tb_all.append(tb)
    return {
        "ratio_median": statistics.median(ratios),
        "ratio_min": min(ratios),
        "ratio_max": max(ratios),
        "a_median": statistics.median(ta_all),
        "b_median": statistics.median(tb_all),
        "rounds": rounds,
    }


def dump(path: str, obj: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def quiet_gc() -> None:
    gc.collect()
    gc.freeze()  # keep benchmark allocations out of the collector's way
