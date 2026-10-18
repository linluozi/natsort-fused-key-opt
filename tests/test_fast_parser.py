"""Tests for the fused ASCII key builder introduced in this fork.

Why these tests exist next to ``bench/diff_test.py``: the differential test
proves the optimised output equals the upstream output, but it would also pass
if the optimisation were silently removed (both arms would then be the slow
path). These tests therefore assert *structure* as well as behaviour:

* the fused parser is selected for the algorithms it claims to support, and not
  selected for the ones it does not;
* the ASCII pattern really is reduced, and its numeric body is unchanged;
* the hot loop is reached, i.e. matches are iterated instead of the string
  being split by the six-stage pipeline;
* non-ASCII input still constructs and uses the original pipeline;
* components keep their exact types (``1`` vs ``1.0`` matters downstream).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from natsort import natsort_keygen, ns, utils


@pytest.mark.parametrize(
    ("alg", "expected"),
    [
        (ns.DEFAULT, True),
        (ns.REAL, True),
        (ns.IGNORECASE, True),
        (ns.NUMAFTER, True),
        (ns.SIGNED | ns.FLOAT | ns.NANLAST, True),
        # Modes the fusion deliberately does not model.
        (ns.PATH, False),
        (ns.GROUPLETTERS, False),
        (ns.LOCALE, False),
        (ns.LOWERCASEFIRST, False),
        (ns.PATH | ns.FLOAT, False),
    ],
)
def test_fast_parser_selection(alg, expected):
    """The fused parser is used exactly for the supported flag sets."""
    assert utils._can_use_fast_parser(alg) is expected


def test_ascii_pattern_drops_unicode_numeral_alternative():
    """The reduced pattern must not contain the Unicode numeral class."""
    full = utils.regex_chooser(ns.DEFAULT)
    reduced = utils._ascii_only_pattern(full)
    assert reduced == r"(\d+)"
    # The upstream pattern carries a class of Unicode numerals that the
    # reduced one drops entirely.
    assert "[²" in full.pattern or "|[" in full.pattern
    assert "[" not in reduced


@pytest.mark.parametrize("alg", [ns.DEFAULT, ns.REAL, ns.SIGNED, ns.NOEXP])
def test_ascii_pattern_keeps_numeric_body(alg):
    """Signed / exponent variants survive the reduction unchanged."""
    full = utils.regex_chooser(alg if alg & ns.FLOAT else alg)
    reduced = utils._ascii_only_pattern(full)
    assert reduced is not None
    body = full.pattern[1 : full.pattern.index("|[")]
    assert reduced == f"({body})"


def test_ascii_pattern_returns_none_for_unexpected_shape():
    """A pattern without the numeral alternative is refused, not mangled."""
    assert utils._ascii_only_pattern(re.compile(r"(\d+)")) is None


@pytest.mark.parametrize("alg", [ns.DEFAULT, ns.REAL, ns.IGNORECASE])
def test_hot_loop_iterates_matches(alg):
    """Bypass detection: the fused path iterates matches, it does not split.

    ``re.Pattern`` is immutable, so this counts C-level calls with the profile
    hook: the fused parser calls ``finditer`` and never ``split``, while the
    upstream pipeline does the opposite.
    """
    calls = {"finditer": 0, "split": 0}

    def prof(frame, event, arg):
        if event == "c_call":
            name = getattr(arg, "__name__", "")
            if name == "finditer":
                calls["finditer"] += 1
            elif name == "split" and "re" in repr(arg):
                calls["split"] += 1

    key = natsort_keygen(alg=alg)
    sys.setprofile(prof)
    try:
        key("file12_v3.txt")
    finally:
        sys.setprofile(None)
    assert calls["finditer"] > 0
    assert calls["split"] == 0


def test_non_ascii_input_uses_original_pipeline(monkeypatch):
    """Non-ASCII strings must fall back to the layered parser, not the loop."""
    calls = {"slow": 0}
    original = utils.parse_string_factory

    def spy(*args, **kwargs):
        func = original(*args, **kwargs)

        def wrapper(x):
            calls["slow"] += 1
            return func(x)

        return wrapper

    monkeypatch.setattr(utils, "parse_string_factory", spy)
    key = natsort_keygen(alg=ns.DEFAULT)
    # ASCII input must not touch the slow parser at all.
    assert key("file10.txt") == ("file", 10, ".txt")
    assert calls["slow"] == 0
    # Non-ASCII input must reach it, and still produce the decomposed form.
    assert key("caf\u00e9_10") == ("cafe\u0301_", 10)
    assert calls["slow"] == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ()),
        ("abc", ("abc",)),
        ("a1", ("a", 1)),
        ("1a", ("", 1, "a")),
        ("a1b2", ("a", 1, "b", 2)),
        ("12", ("", 12)),
        ("-12", ("-", 12)),
        ("1.5", ("", 1, ".", 5)),
        ("1_2", ("", 1, "_", 2)),
        ("a-5.034e2", ("a-", 5, ".", 34, "e", 2)),
        (" 12", (" ", 12)),
        ("12 ", ("", 12, " ")),
    ],
)
def test_fast_parser_component_shapes(value, expected):
    """Shapes that the separator logic must reproduce exactly."""
    assert natsort_keygen(alg=ns.DEFAULT)(value) == expected


def test_component_types_are_preserved():
    """``1`` and ``1.0`` compare equal but must not be interchangeable."""
    assert [type(x) for x in natsort_keygen(alg=ns.DEFAULT)("a12b")] == [str, int, str]
    assert [type(x) for x in natsort_keygen(alg=ns.REAL)("a12b")] == [str, float, str]


@pytest.mark.parametrize("value", ["nan", "NaN", "-inf", "inf", "Infinity"])
def test_nan_inf_values_are_still_numbers(value):
    """The float path must keep ``fast_float``'s word handling."""
    out = natsort_keygen(alg=ns.REAL)(value)
    assert len(out) == 2
    assert out[0] == ""
    assert out[1] in (float("inf"), float("-inf"))


def test_nan_inf_words_inside_a_string():
    """A nan/inf word between numbers is converted, as upstream does."""
    assert natsort_keygen(alg=ns.REAL)("a1nan2") == ("a", 1.0, "", float("-inf"), "", 2.0)


def test_nanlast_sentinel():
    """NaN maps to +inf under NANLAST and to -inf otherwise."""
    assert natsort_keygen(alg=ns.REAL)("nan")[1] == float("-inf")
    assert natsort_keygen(alg=ns.REAL | ns.NANLAST)("nan")[1] == float("inf")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("\u00b2", ("", 2)),        # superscript two: a digit in Unicode
        ("\u0661\u0662", ("", 12)),  # arabic-indic digits: decimal digits
        ("\U0001d7d8", ("", 0)),    # mathematical double-struck zero
        # Numerals that are not decimal digits are left as text by upstream,
        # and the fused parser must not change that either.
        ("\u00bd", ("\u00bd",)),
        ("\u216b", ("\u216b",)),
    ],
)
def test_unicode_numerals_are_resolved_like_upstream(value, expected):
    """Unicode numerals keep resolving through the original pipeline."""
    assert natsort_keygen(alg=ns.DEFAULT)(value) == expected


def test_whitespace_is_part_of_a_component():
    """Leading/trailing whitespace must survive as a separate component."""
    key = natsort_keygen(alg=ns.DEFAULT)
    assert key(" 12") == (" ", 12)
    assert key("12 ") == ("", 12, " ")


def test_decomposition_still_happens_for_non_ascii():
    """NFD equivalence: precomposed and decomposed forms sort the same."""
    key = natsort_keygen()
    assert key("caf\u00e9") == key("cafe\u0301")


def test_casefolding_applies_before_splitting():
    """IGNORECASE folds case but must not change the split points."""
    key = natsort_keygen(alg=ns.IGNORECASE)
    assert key("FILE10") == key("file10")


def test_path_mode_still_splits_per_component():
    """PATH keeps the original pipeline; the fused parser must not intercept."""
    key = natsort_keygen(alg=ns.PATH)
    assert key(Path("dir9/f10.txt")) == key("dir9/f10.txt")
    # 10 must sort after 9, which only holds if each component is parsed.
    assert sorted([Path("dir10/f1.txt"), Path("dir9/f10.txt")], key=key) == [
        Path("dir9/f10.txt"),
        Path("dir10/f1.txt"),
    ]


def test_parser_rejects_non_string_directly():
    """Called directly, the fused parser raises TypeError like normalize()."""
    numeric_regex = utils.regex_chooser(ns.DEFAULT)
    slow = utils.parse_string_factory(
        ns.DEFAULT,
        "",
        numeric_regex.split,
        utils.input_string_transform_factory(ns.DEFAULT),
        utils.string_component_transform_factory(ns.DEFAULT),
        utils.final_data_transform_factory(ns.DEFAULT, "", ""),
    )
    fused = utils.fast_string_parser_factory(ns.DEFAULT, "", numeric_regex, slow)
    with pytest.raises(TypeError):
        fused(3.5)


def test_numbers_never_reach_the_string_parser():
    """Numbers take the numeric branch in natsort_key, as upstream does."""
    assert natsort_keygen(alg=ns.DEFAULT)(3.5) == ("", 3.5)


def test_no_fastnumbers_import_at_runtime():
    """The optimisation must not change the dependency footprint."""
    import sys

    assert "fastnumbers" not in sys.modules
