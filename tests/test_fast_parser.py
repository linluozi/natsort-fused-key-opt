# ruff: noqa: CPY001  (this project ships no per-file copyright headers)
"""Tests for the fused ASCII key builder introduced in this fork.

Why these tests exist next to ``bench/diff_test.py``: the differential test
proves the optimised output equals the upstream output, but it would also pass
if the optimisation were silently removed (both arms would then be the slow
path). These tests therefore assert *structure* as well as behaviour: that the
fused parser is selected for the algorithms it claims to support, that the
ASCII pattern really is reduced, that the hot loop is reached, and that
non-ASCII input still lands on the original pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from natsort import natsort_keygen, ns, utils

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


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
def test_fast_parser_selection(alg: int, *, expected: bool) -> None:
    """The fused parser is used exactly for the supported flag sets."""
    assert utils._can_use_fast_parser(alg) is expected  # noqa: SLF001


def test_ascii_pattern_drops_unicode_numeral_alternative() -> None:
    """The reduced pattern must not contain the Unicode numeral class."""
    full = utils.regex_chooser(ns.DEFAULT)
    reduced = utils._ascii_only_pattern(full)  # noqa: SLF001
    assert reduced == r"(\d+)"
    # The upstream pattern carries a class of Unicode numerals that the
    # reduced one drops entirely.
    assert "|[" in full.pattern
    assert "[" not in reduced


@pytest.mark.parametrize("alg", [ns.DEFAULT, ns.REAL, ns.SIGNED, ns.NOEXP])
def test_ascii_pattern_keeps_numeric_body(alg: int) -> None:
    """Signed and exponent variants survive the reduction unchanged."""
    full = utils.regex_chooser(alg)
    reduced = utils._ascii_only_pattern(full)  # noqa: SLF001
    assert reduced is not None
    body = full.pattern[1 : full.pattern.index("|[")]
    assert reduced == f"({body})"


def test_ascii_pattern_returns_none_for_unexpected_shape() -> None:
    """A pattern without the numeral alternative is refused, not mangled."""
    import re

    assert utils._ascii_only_pattern(re.compile(r"(\d+)")) is None  # noqa: SLF001


@pytest.mark.parametrize("alg", [ns.DEFAULT, ns.REAL, ns.IGNORECASE])
def test_hot_loop_iterates_matches(alg: int) -> None:
    """
    Bypass detection: the fused path iterates matches, it does not split.

    ``re.Pattern`` is immutable, so C-level calls are counted with the profile
    hook: the fused parser calls ``finditer`` and never ``split``, while the
    upstream pipeline does the opposite.
    """
    calls = {"finditer": 0, "split": 0}

    def prof(_frame: object, event: str, arg: object) -> None:
        if event == "c_call":
            name = getattr(arg, "__name__", "")
            if name == "finditer":
                calls["finditer"] += 1
            elif name == "split":
                calls["split"] += 1

    key = natsort_keygen(alg=alg)
    sys.setprofile(prof)
    try:
        key("file12_v3.txt")
    finally:
        sys.setprofile(None)
    assert calls["finditer"] > 0
    assert calls["split"] == 0


def test_non_ascii_input_uses_original_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-ASCII strings must fall back to the layered parser, not the loop."""
    calls = {"slow": 0}
    original = utils.parse_string_factory

    def spy(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - forwards a factory
        func = original(*args, **kwargs)

        def wrapper(x: str) -> Any:  # noqa: ANN401 - the key is a typed union
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
def test_fast_parser_component_shapes(value: str, expected: tuple[Any, ...]) -> None:
    """Shapes that the separator logic must reproduce exactly."""
    assert natsort_keygen(alg=ns.DEFAULT)(value) == expected


def test_component_types_are_preserved() -> None:
    """``1`` and ``1.0`` compare equal but must not be interchangeable."""
    int_types = [type(x) for x in natsort_keygen(alg=ns.DEFAULT)("a12b")]
    real_types = [type(x) for x in natsort_keygen(alg=ns.REAL)("a12b")]
    assert int_types == [str, int, str]
    assert real_types == [str, float, str]


@pytest.mark.parametrize("value", ["nan", "NaN", "-inf", "inf", "Infinity"])
def test_nan_inf_values_are_still_numbers(value: str) -> None:
    """The float path must keep ``fast_float``'s word handling."""
    out = natsort_keygen(alg=ns.REAL)(value)
    assert len(out) == 2
    assert out[0] == ""
    assert out[1] in (float("inf"), float("-inf"))


def test_nan_inf_words_inside_a_string() -> None:
    """A nan/inf word between numbers is converted, as upstream does."""
    assert natsort_keygen(alg=ns.REAL)("a1nan2") == (
        "a",
        1.0,
        "",
        float("-inf"),
        "",
        2.0,
    )


def test_nanlast_sentinel() -> None:
    """NaN maps to +inf under NANLAST and to -inf otherwise."""
    assert natsort_keygen(alg=ns.REAL)("nan")[1] == float("-inf")
    assert natsort_keygen(alg=ns.REAL | ns.NANLAST)("nan")[1] == float("inf")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("\u00b2", ("", 2)),  # superscript two: a digit in Unicode
        ("\u0661\u0662", ("", 12)),  # arabic-indic digits: decimal digits
        ("\U0001d7d8", ("", 0)),  # mathematical double-struck zero
        # Numerals that are not decimal digits are left as text by upstream,
        # and the fused parser must not change that either.
        ("\u00bd", ("\u00bd",)),
        ("\u216b", ("\u216b",)),
    ],
)
def test_unicode_numerals_are_resolved_like_upstream(
    value: str,
    expected: tuple[Any, ...],
) -> None:
    """Unicode numerals keep resolving through the original pipeline."""
    assert natsort_keygen(alg=ns.DEFAULT)(value) == expected


def test_whitespace_is_part_of_a_component() -> None:
    """Leading/trailing whitespace must survive as a separate component."""
    key = natsort_keygen(alg=ns.DEFAULT)
    assert key(" 12") == (" ", 12)
    assert key("12 ") == ("", 12, " ")


def test_decomposition_still_happens_for_non_ascii() -> None:
    """NFD equivalence: precomposed and decomposed forms sort the same."""
    key = natsort_keygen()
    assert key("caf\u00e9") == key("cafe\u0301")


def test_casefolding_applies_before_splitting() -> None:
    """IGNORECASE folds case but must not change the split points."""
    key = natsort_keygen(alg=ns.IGNORECASE)
    assert key("FILE10") == key("file10")


def test_path_mode_still_splits_per_component() -> None:
    """PATH keeps the original pipeline; the fused parser must not intercept."""
    key = natsort_keygen(alg=ns.PATH)
    assert key(Path("dir9/f10.txt")) == key("dir9/f10.txt")
    assert sorted([Path("dir10/f1.txt"), Path("dir9/f10.txt")], key=key) == [
        Path("dir9/f10.txt"),
        Path("dir10/f1.txt"),
    ]


def test_parser_rejects_non_string_directly() -> None:
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
        fused(3.5)  # type: ignore[arg-type]


def test_numbers_never_reach_the_string_parser() -> None:
    """Numbers take the numeric branch in natsort_key, as upstream does."""
    assert natsort_keygen(alg=ns.DEFAULT)(3.5) == ("", 3.5)


def test_numeric_backend_is_whichever_natsort_selected() -> None:
    """
    The fused parser must agree with the backend natsort actually selected.

    ``fastnumbers`` is an optional extra, so asserting that it is absent is
    wrong: when it is installed, ``fast_int``/``fast_float`` come from it and
    the fused parser has to match *those* semantics, not the pure-Python
    stand-ins. This asserts both configurations agree on the spellings where
    the two backends could differ.
    """
    from natsort.compat.fastnumbers import try_float

    fused = natsort_keygen(alg=ns.REAL)
    for text in ("1.5", "-2e3", "12", "nan", "inf"):
        expected = next(try_float(iter([text]), map=True, nan=float("-inf")))
        if isinstance(expected, float) and expected != expected:  # NaN
            expected = float("-inf")
        assert fused(text)[-1] == expected, text
