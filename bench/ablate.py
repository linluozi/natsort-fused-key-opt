"""
Ablation: which part of the fusion actually pays?

Benchmarks variants of the key builder so each mechanism is attributed instead
of asserted:

  upstream   six-stage pipeline
  V1         fused loop, but NFD still applied to every string
  V2         fused loop, NFD skipped, full (Unicode) numeric pattern
  V3         fused loop, NFD skipped, reduced ASCII pattern
  shipped    the code in ``natsort/utils.py``

V1..V3 differ by exactly one mechanism, so the deltas between *adjacent*
variants - not the totals - say what each mechanism is worth.

All variants are wrapped in the same ``natsort_key`` dispatch (the ``partial``
that ``natsort_keygen`` returns), so every arm pays identical per-call
dispatch overhead. Without that, a bare closure would look faster than any
real key function simply because it skips the type checks that
``natsort_keygen`` must perform.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from functools import partial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (
    calibrate,
    dataset,
    dump,
    interleaved,
    load_arm,
    quiet_gc,
)

opt = load_arm("self")
up = load_arm("upstream")

NS = opt.ns


def build_variant(*, skip_nfd: bool, reduced_pattern: bool, alg: int = 0):
    """Build a string parser with the named mechanisms on or off."""
    numeric = opt.utils.regex_chooser(alg)
    pattern = (
        re.compile(opt.utils._ascii_only_pattern(numeric))
        if reduced_pattern
        else numeric
    )
    convert = float if alg & NS.FLOAT else int
    sep = ""
    normalize = unicodedata.normalize

    def parser(x: str) -> tuple:
        s = x if skip_nfd else normalize("NFD", x)
        out: list = []
        prev = False
        last = 0
        found = False
        for match in pattern.finditer(s):
            found = True
            start = match.start()
            if start > last:
                out.append(s[last:start])
                prev = False
            text = match.group()
            try:
                value = convert(text)
            except ValueError:
                out.append(text)
                prev = False
            else:
                if prev or not out:
                    out.append(sep)
                out.append(value)
                prev = True
            last = match.end()
        if not found:
            return (s,) if s else ()
        if last < len(s):
            out.append(s[last:])
        return tuple(out)

    # Same dispatch as a real key: type checks, bytes/None/number branches.
    return partial(
        opt.utils.natsort_key,
        key=None,
        string_func=parser,
        bytes_func=opt.utils.parse_bytes_factory(alg),
        num_func=opt.utils.parse_number_or_none_factory(alg, sep, sep),
    )


def main() -> int:
    quiet_gc()
    data = dataset("filenames", 2000)
    ref = up.natsort_keygen()
    variants = {
        "V1_nfd_kept_full_regex": build_variant(skip_nfd=False, reduced_pattern=False),
        "V2_nfd_skipped_full_regex": build_variant(
            skip_nfd=True, reduced_pattern=False
        ),
        "V3_nfd_skipped_reduced_regex": build_variant(
            skip_nfd=True, reduced_pattern=True
        ),
        "shipped": opt.natsort_keygen(),
    }
    for name, fn in variants.items():
        mismatches = sum(1 for s in data if fn(s) != ref(s))
        assert mismatches == 0, f"{name}: {mismatches} mismatches"

    arms = {"upstream": ref, **variants}
    keys = list(arms)
    pairs = {}
    for i, left in enumerate(keys):
        for right in keys[i + 1 :]:
            a = lambda f=arms[left], d=data: [f(s) for s in d]  # noqa: E731
            b = lambda f=arms[right], d=data: [f(s) for s in d]  # noqa: E731
            ia, ib = calibrate(a), calibrate(b)
            r = interleaved(a, b, ia, ib, rounds=7)
            pairs[f"{left}__vs__{right}"] = {
                "left_us": r["a_median"] / len(data) * 1e6,
                "right_us": r["b_median"] / len(data) * 1e6,
                "left_over_right": r["ratio_median"],
            }
    dump(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "results", "ablation.json"
        ),
        {"dataset": "filenames", "n": len(data), "pairs": pairs},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
