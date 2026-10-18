"""
Differential equivalence: optimised natsort vs pristine upstream.

Every string is keyed by both implementations under every algorithm flag
combination that natsort accepts, and the tuples are compared element by
element (including element *types*, because ``1 == 1.0`` in Python but the two
would not compare identically against a string component downstream).

The corpus deliberately contains the cases that broke earlier iterations:
ASCII floats with exponents, ``nan``/``inf`` spellings, unicode digits
(fullwidth digits, ``"٣"``, ``"²"``), combining accents, NUL bytes, empty strings,
lone signs, whitespace, underscores, path-like strings, bytes and numbers.

A poisoned control (``--poison``) deliberately breaks one rule of the fused
parser and asserts the harness notices. Without that step a green run proves
nothing.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # <repo>/bench
sys.path.insert(0, str(HERE))

from harness import arm_path  # noqa: E402


def load(tree: str):
    """Import natsort from the named arm with a clean module cache."""
    path = Path(arm_path(tree))
    for name in [
        m for m in list(sys.modules) if m == "natsort" or m.startswith("natsort.")
    ]:
        del sys.modules[name]
    sys.path.insert(0, str(path))
    try:
        import natsort

        assert Path(natsort.__file__).resolve().parent == (path / "natsort").resolve()
        return natsort
    finally:
        sys.path.remove(str(path))


def corpus() -> list:
    """Build the differential corpus: hand-picked edge cases + generated ones."""
    fixed = [
        "",
        "0",
        "1",
        "-1",
        "+1",
        "007",
        "3.14",
        "-3.14",
        ".5",
        "+.5",
        "5.",
        "1e5",
        "1E-5",
        "-1.5e+3",
        "1e",
        "e5",
        "--1",
        "+-1",
        "-",
        "+",
        ".",
        "..",
        "...",
        "1.2.3",
        "nan",
        "NaN",
        "inf",
        "INF",
        "-inf",
        "+inf",
        "Infinity",
        "infinity",
        "xnan",
        "nanx",
        "a1nan2",
        "1_2",
        "_12",
        "12_",
        " 12",
        "12 ",
        "  7 ",
        "\t9",
        "9\n",
        "a",
        "A",
        "abc",
        "ABC",
        "aBc",
        "a1",
        "1a",
        "a1b2c3",
        "12abc34def56",
        "abc123",
        "123abc",
        "file10.txt",
        "file2.txt",
        "File10.TXT",
        "img_0012_v3.png",
        "v1.2.10",
        "v1.2.9",
        "1.10",
        "1.9",
        "0.0.0",
        "2026-10-18",
        "10/2/2026",
        "1,000",
        "1,000,000",
        "3,14",
        "a-5.034e2",
        "１２３",
        "٣",
        "²",
        "Ⅻ",
        "½",
        "⅓",
        "四",
        "零",
        "〇",
        "café",
        "cafe\u0301",
        "Å",
        "A\u030a",
        "ǅ",
        "ß",
        "İ",
        "ı",
        "第1章",
        "第10章",
        "第2章",
        "测试_001_终版.docx",
        "\x00",
        "a\x00b",
        "1\x002",
        "\u00a012",
        "12\u00a0",
        "a/b/c10",
        "a/b/c2",
        "./dir2/file10.txt",
        "../dir10/f2",
        "~$file1",
        "-file2",
        "+file3",
        "  -12  ",
        "\U0001d7d8\U0001d7d9",  # math digits
        "\u0661\u0662",  # arabic-indic
        "\u06f1\u06f2",  # extended arabic-indic
        "١٢٣abc",
        "abc١٢٣",
    ]
    generated = []
    alphabet = "aA0 1.-+eE_\t\u00e9\u00b2\u0661"
    generated.extend(
        "".join(combo)
        for length in (1, 2, 3)
        for combo in itertools.product(alphabet, repeat=length)
    )
    words = ["nan", "inf", "5", "10", "1.5", "-3", "v", ".", "_", " "]
    generated.extend(a + b for a, b in itertools.product(words, repeat=2))
    return fixed + generated


def flags(ns) -> list[tuple[str, int]]:
    """All interesting algorithm combinations (not the full 2**14 power set)."""
    return [
        ("DEFAULT", 0),
        ("FLOAT", ns.FLOAT),
        ("SIGNED", ns.SIGNED),
        ("FLOAT|SIGNED", ns.FLOAT | ns.SIGNED),
        ("FLOAT|NOEXP", ns.FLOAT | ns.NOEXP),
        ("FLOAT|SIGNED|NOEXP", ns.FLOAT | ns.SIGNED | ns.NOEXP),
        ("IGNORECASE", ns.IGNORECASE),
        ("IGNORECASE|FLOAT", ns.IGNORECASE | ns.FLOAT),
        ("NUMAFTER", ns.NUMAFTER),
        ("NUMAFTER|FLOAT", ns.NUMAFTER | ns.FLOAT),
        ("NANLAST", ns.FLOAT | ns.NANLAST),
        ("LOWERCASEFIRST", ns.LOWERCASEFIRST),
        ("LOWERCASEFIRST|IGNORECASE", ns.LOWERCASEFIRST | ns.IGNORECASE),
        ("COMPATIBILITYNORMALIZE", ns.COMPATIBILITYNORMALIZE),
        ("REAL", ns.REAL),
        # flag combinations that must keep the layered path
        ("GROUPLETTERS", ns.GROUPLETTERS),
        ("PATH", ns.PATH),
        ("PATH|FLOAT", ns.PATH | ns.FLOAT),
        ("LOCALE", ns.LOCALE),
    ]


SHOW = 5  # how many mismatches to print, enough to diagnose without flooding


def compare(up, opt, items) -> tuple[int, int]:
    """Compare both implementations over every item and flag set."""
    total = bad = 0
    for fname, alg in flags(up.ns):
        ku = up.natsort_keygen(alg=alg)
        ko = opt.natsort_keygen(alg=alg)
        for item in items:
            try:
                a = ku(item)
                a_err = None
            except Exception as exc:  # noqa: BLE001
                a, a_err = None, f"{type(exc).__name__}: {exc}"
            try:
                b = ko(item)
                b_err = None
            except Exception as exc:  # noqa: BLE001
                b, b_err = None, f"{type(exc).__name__}: {exc}"
            total += 1
            if a_err or b_err:
                if a_err != b_err:
                    bad += 1
                    if bad <= SHOW:
                        print(f"  EXC DIFF [{fname}] {item!r}: {a_err} != {b_err}")
                continue
            # Value *and* type must match: 1 == 1.0 would hide a mismatch that
            # changes how a component compares against strings downstream.
            if a != b or _shape(a) != _shape(b):
                bad += 1
                if bad <= SHOW:
                    print(f"  DIFF [{fname}] {item!r}: {a!r} != {b!r}")
    return total, bad


def _shape(obj) -> str:
    """Type/shape signature so 1 == 1.0 cannot hide a mismatch."""
    if isinstance(obj, tuple):
        return "(" + ",".join(_shape(x) for x in obj) + ")"
    return type(obj).__name__


def main() -> int:
    poison = "--poison" in sys.argv
    up = load("upstream")
    opt = load("self")
    # Guard against the failure that makes this test worthless: if both arms
    # resolve to the same directory, every comparison compares a tree with
    # itself and always passes.
    if Path(up.__file__).resolve() == Path(opt.__file__).resolve():
        msg = "both arms resolved to the same package; set NATSORT_UPSTREAM"
        raise SystemExit(msg)
    if poison:
        # Break exactly one documented invariant: drop the separator that must
        # precede a leading numeric component. If the harness cannot see this,
        # a green run means nothing.
        utils = sys.modules["natsort.utils"]
        original = utils.fast_string_parser_factory

        def broken(alg, sep, numeric_regex, fallback):
            f = original(alg, sep, numeric_regex, fallback)

            def wrapper(x):
                out = f(x)
                if out and out[0] == sep:
                    return out[1:]
                return out

            return wrapper

        utils.fast_string_parser_factory = broken

    items = corpus()
    # Strings, bytes, numbers and nested sequences all go through the key.
    extra = [b"123", b"", 12, 3.5, None, ["a1", "b2"], ("x10",), Path("dir9/f10.txt")]
    total, bad = compare(up, opt, items)
    t2, b2 = compare(up, opt, extra)
    print(f"strings: {total} comparisons, {bad} mismatches")
    print(f"mixed:   {t2} comparisons, {b2} mismatches")
    ok = bad == 0 and b2 == 0
    if poison:
        verdict = (
            "harness detected the injected bug"
            if not ok
            else "HARNESS IS BLIND - the poison was not detected"
        )
        print("POISON RESULT:", verdict)
        return 0 if not ok else 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
