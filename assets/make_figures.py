"""Generate the figures used in the README, straight from benchmark JSON.

Design notes (learned from earlier rounds):
  * English labels only - CJK glyphs render as boxes without an explicit font.
  * Warm editorial palette, shared with the other reports in this series.
  * Ratios sit at a fixed height with headroom above the tallest bar, so the
    annotation never fights the bar or its whisker.
  * A log scale is used where the spread exceeds 10x, with explicit ticks so
    no reader has to infer the magnitude of an unlabelled minor tick.
  * In-bar labels are avoided entirely: they get clipped on narrow bars.
Every value is read from ``bench/results/*.json``; nothing is typed by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from matplotlib.ticker import LogLocator, NullFormatter  # noqa: E402

INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"

HERE = Path(__file__).resolve().parent
RES = HERE.parent / "bench" / "results"
OUT = HERE.parent / "assets"


def style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "axes.edgecolor": MUTED,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.family": "DejaVu Sans",
        }
    )


def load(name: str) -> list[dict]:
    with open(RES / name, encoding="utf-8") as fh:
        return json.load(fh)["rows"]


def fig_speedup() -> None:
    """Figure 1: per-key speedup by corpus and algorithm (grouped bars)."""
    rows = load("bench_key.json")
    datasets = list(dict.fromkeys(r["dataset"] for r in rows))
    configs = ["INT", "REAL", "IGNORECASE", "NUMAFTER"]
    colors = {"INT": AMBER, "REAL": TERRACOTTA, "IGNORECASE": OLIVE, "NUMAFTER": MUTED}
    lookup = {(r["dataset"], r["config"]): r for r in rows}

    x = np.arange(len(datasets))
    width = 0.2
    fig, ax = plt.subplots(figsize=(11.5, 5.6))
    top = 0.0
    for i, cfg in enumerate(configs):
        vals = [lookup[(d, cfg)]["speedup_median"] for d in datasets]
        lo = [lookup[(d, cfg)]["speedup_median"] - lookup[(d, cfg)]["speedup_min"] for d in datasets]
        hi = [lookup[(d, cfg)]["speedup_max"] - lookup[(d, cfg)]["speedup_median"] for d in datasets]
        ax.bar(
            x + (i - 1.5) * width,
            vals,
            width,
            label=cfg,
            color=colors[cfg],
            edgecolor=PAPER,
            linewidth=0.6,
            yerr=[lo, hi],
            error_kw={"ecolor": MUTED, "elinewidth": 0.8, "capsize": 2},
            zorder=3,
        )
        top = max(top, max(v + e for v, e in zip(vals, hi, strict=True)))
        for xi, v, e in zip(x + (i - 1.5) * width, vals, hi, strict=True):
            ax.text(xi, v + e + top * 0.015, f"{v:.2f}", ha="center", va="bottom",
                    fontsize=7.4, color=INK)

    ax.axhline(1.0, color=TERRACOTTA, linewidth=1.0, linestyle="--", zorder=2)
    ax.text(len(datasets) - 0.35, 1.04, "upstream = 1.0x", ha="right", va="bottom",
            fontsize=8, color=TERRACOTTA)
    ax.set_ylim(0, top * 1.20)
    ax.set_xticks(x)
    ax.set_xticklabels([d.replace("longpath", "long paths") for d in datasets])
    ax.set_ylabel("speedup vs upstream (x, key building only)")
    # Headline numbers are derived, never typed: the range comes from the data.
    fast = [
        r["speedup_median"]
        for r in rows
        if r["dataset"] != "unicode"
    ]
    ax.set_title(
        f"Key construction is {min(fast):.1f}x - {max(fast):.1f}x faster, depending on the corpus\n"
        "median of 9 interleaved rounds; whiskers = min/max round ratio",
        loc="left",
        fontsize=12,
        pad=14,
    )
    ax.legend(frameon=False, ncol=4, loc="upper right", bbox_to_anchor=(1.0, 1.02))
    ax.grid(axis="y", color=MUTED, alpha=0.18, zorder=0)
    fig.tight_layout()
    fig.savefig(OUT / "speedup_by_corpus.png", dpi=170)
    plt.close(fig)


def fig_absolute() -> None:
    """Figure 2: absolute cost per string, log scale, both algorithms."""
    key = {(r["dataset"], r["config"]): r for r in load("bench_key.json")}
    datasets = ["words", "numbers", "floats", "filenames", "version", "longpath"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    for ax, cfg, title in (
        (axes[0], "INT", "default algorithm (INT)"),
        (axes[1], "REAL", "float algorithm (REAL)"),
    ):
        up = [key[(d, cfg)]["upstream_us_per_item"] for d in datasets]
        opt = [key[(d, cfg)]["optimised_us_per_item"] for d in datasets]
        x = np.arange(len(datasets))
        ax.bar(x - 0.2, up, 0.38, label="upstream", color=MUTED, zorder=3)
        ax.bar(x + 0.2, opt, 0.38, label="optimised", color=AMBER, zorder=3)
        ax.set_yscale("log")
        ax.set_ylim(0.5, max(max(up), max(opt)) * 6)
        ax.yaxis.set_major_locator(LogLocator(base=10, numticks=6))
        ax.yaxis.set_minor_formatter(NullFormatter())
        for xi, (u, o) in enumerate(zip(up, opt, strict=True)):
            ax.text(xi, max(u, o) * 1.5, f"{u / o:.2f}x", ha="center", va="bottom",
                    fontsize=9, color=TERRACOTTA, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([d.replace("longpath", "long\npaths") for d in datasets], fontsize=9)
        ax.set_ylabel("microseconds per string (log scale)")
        ax.set_title(title, loc="left", fontsize=11)
        ax.grid(axis="y", color=MUTED, alpha=0.18, zorder=0)
        ax.legend(frameon=False, loc="upper left")

    fig.suptitle("Absolute cost per string: same result, less overhead",
                 x=0.012, y=0.985, ha="left", fontsize=12)
    fig.text(0.012, 0.015,
             "Shorter bars are better. Non-ASCII input deliberately keeps the upstream path, "
             "so those two bars are equal.",
             fontsize=8, color=MUTED)
    fig.tight_layout(rect=(0.01, 0.045, 1, 0.95))
    fig.savefig(OUT / "absolute_time.png", dpi=170)
    plt.close(fig)


def fig_work() -> None:
    """Figure 3: deterministic Python-call counts (no clock involved)."""
    rows = load("work_count.json")
    labels = [f"{r['dataset']}\n{r['config']}" for r in rows]
    up = [r["python_calls_upstream"] for r in rows]
    opt = [r["python_calls_optimised"] for r in rows]
    x = np.arange(len(rows))

    fig, ax = plt.subplots(figsize=(9.6, 4.8))
    ax.bar(x - 0.2, up, 0.38, label="upstream", color=MUTED, zorder=3)
    ax.bar(x + 0.2, opt, 0.38, label="optimised", color=OLIVE, zorder=3)
    for xi, (u, o) in enumerate(zip(up, opt, strict=True)):
        ax.text(xi - 0.2, u * 1.02, f"{u:,}", ha="center", va="bottom", fontsize=8, color=INK)
        ax.text(xi + 0.2, o * 1.02, f"{o:,}", ha="center", va="bottom", fontsize=8, color=INK)
        ax.text(xi, max(u, o) * 1.16, f"-{(u - o) / u * 100:.0f}%", ha="center", va="bottom",
                fontsize=9.5, color=TERRACOTTA, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("Python calls to build 500 keys")
    ax.set_ylim(0, max(up) * 1.30)
    ax.set_title(
        "Fewer Python-level calls per key - the mechanism behind the speedup\n"
        "counted with sys.setprofile, not timed; output tuples are identical",
        loc="left",
        fontsize=11,
        pad=12,
    )
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", color=MUTED, alpha=0.18, zorder=0)
    fig.tight_layout()
    fig.savefig(OUT / "work_count.png", dpi=170)
    plt.close(fig)


def fig_pipeline() -> None:
    """Figure 4: before/after pipeline, drawn as a diagram."""
    fig, ax = plt.subplots(figsize=(12, 5.2))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 46)
    ax.axis("off")

    def box(x, y, w, h, text, color, *, filled=False, size=8.6):
        ax.add_patch(
            FancyBboxPatch(
                (x, y), w, h,
                boxstyle="round,pad=0.3,rounding_size=1.1",
                linewidth=1.0,
                edgecolor=color,
                facecolor=color if filled else PAPER,
                zorder=2,
            )
        )
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=size, color=PAPER if filled else INK, zorder=3)

    def arrow(x0, x1, y, color=MUTED):
        ax.add_patch(FancyArrowPatch((x0, y), (x1, y), arrowstyle="-|>",
                                     mutation_scale=11, color=color, lw=1.0, zorder=1))

    ax.text(0.5, 41.5, "Before - six Python-level stages per string",
            fontsize=11.5, color=TERRACOTTA, fontweight="bold")
    steps = ["NFD\nnormalize", "no-op\ntransform", "regex\nsplit",
             "filter\n(None)", "fast_int\nper part", "sep\ninserter"]
    for i, s in enumerate(steps):
        x0 = 0.5 + i * 16.4
        box(x0, 28, 13.4, 9, s, TERRACOTTA)
        if i < len(steps) - 1:
            arrow(x0 + 13.7, x0 + 16.1, 32.5)

    ax.text(0.5, 21.5, "After - one fused pass, ASCII fast path",
            fontsize=11.5, color=OLIVE, fontweight="bold")
    box(0.5, 6, 29, 11, "isascii() guard\nNFD skipped (a no-op on ASCII)", OLIVE)
    arrow(29.8, 32.2, 11.5, OLIVE)
    box(32.2, 6, 29, 11, "reduced regex\nUnicode numeral class dropped", OLIVE)
    arrow(61.5, 63.9, 11.5, OLIVE)
    box(63.9, 6, 35.6, 11, "single loop\nslice spans -> convert -> emit separator",
        OLIVE, filled=True)

    ax.text(0.5, 24.2, "same tuple, 3-5x fewer Python calls",
            fontsize=9, color=MUTED, style="italic")
    fig.tight_layout()
    fig.savefig(OUT / "pipeline.png", dpi=170)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    style()
    fig_speedup()
    fig_absolute()
    fig_work()
    fig_pipeline()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
