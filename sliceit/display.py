"""
Sliceit — terminal UI (Rich).

Renders a full breakdown panel: timeline bar, bucket cards,
phase table, and insight callout.
"""

from __future__ import annotations

import math
from typing import Optional

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.padding import Padding
from rich.style import Style

from .core import RunResult, Phase

console = Console()

# ─── palette ─────────────────────────────────────────────────────────────────

BUCKET_STYLE = {
    "compute": ("bright_red",    "red",         "▐", "Compute"),
    "io":      ("bright_green",  "green",       "▐", "I/O    "),
    "memory":  ("bright_magenta","magenta",     "▐", "Memory "),
    "idle":    ("bright_black",  "dim white",   "▐", "Idle   "),
}

BAR_CHARS = " ▏▎▍▌▋▊▉█"
TIMELINE_WIDTH = 60


# ─── helpers ─────────────────────────────────────────────────────────────────

def _pct_bar(pct: float, width: int, color: str) -> Text:
    """Filled block bar, proportional to pct (0‒100)."""
    filled = int(round(pct / 100 * width))
    filled = max(0, min(filled, width))
    t = Text()
    t.append("█" * filled, style=color)
    t.append("░" * (width - filled), style="bright_black")
    return t


def _ms(v: float) -> str:
    if v >= 1000:
        return f"{v/1000:.2f}s"
    return f"{v:.0f}ms"


def _fmt_cmd(cmd: str, maxlen: int = 60) -> str:
    return cmd if len(cmd) <= maxlen else cmd[:maxlen - 1] + "…"


# ─── timeline ────────────────────────────────────────────────────────────────

def _timeline(result: RunResult) -> Text:
    """
    Horizontal timeline bar where each character cell ≈ total_ms/WIDTH.
    """
    width   = TIMELINE_WIDTH
    samples = result.samples
    if not samples:
        return Text("no samples collected", style="dim")

    n = len(samples)
    t = Text()

    for i in range(width):
        lo = int(i / width * n)
        hi = int((i + 1) / width * n)
        hi = max(hi, lo + 1)
        chunk = samples[lo:hi]

        counts: dict[str, int] = {}
        for s in chunk:
            counts[s.bucket] = counts.get(s.bucket, 0) + 1

        dominant = max(counts, key=counts.__getitem__)
        color, _, _, _ = BUCKET_STYLE[dominant]
        t.append("█", style=color)

    return t


# ─── spinner / live ──────────────────────────────────────────────────────────

def make_spinner(command: str) -> Live:
    prog = Progress(
        SpinnerColumn(style="bright_cyan"),
        TextColumn("[bold]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
    prog.add_task(f"profiling  [dim]{_fmt_cmd(command)}", total=None)
    return Live(prog, console=console, refresh_per_second=10)


# ─── main render ─────────────────────────────────────────────────────────────

def render(result: RunResult) -> None:
    c = console

    # ── header ────────────────────────────────────────────────────────────
    c.print()
    c.print(Rule(
        Text("  Sliceit ", style="bold bright_cyan") +
        Text(f"  {_fmt_cmd(result.command)}  ", style="dim"),
        style="bright_black",
    ))

    status_color = "green" if result.exit_code == 0 else "red"
    status_text  = "✓ ok" if result.exit_code == 0 else f"✗ exit {result.exit_code}"

    c.print(
        Padding(
            Text.assemble(
                ("  total  ", "dim"),
                (_ms(result.total_ms), "bold white"),
                ("   samples  ", "dim"),
                (str(len(result.samples)), "bold white"),
                ("   status  ", "dim"),
                (status_text, f"bold {status_color}"),
            ),
            (0, 0, 1, 0),
        )
    )

    # ── timeline ──────────────────────────────────────────────────────────
    tl = _timeline(result)
    legend = Text()
    for b, (color, _, blk, label) in BUCKET_STYLE.items():
        legend.append(f"  {blk} ", style=color)
        legend.append(label.strip(), style="dim")

    c.print(Panel(
        Text.assemble(tl, "\n", legend),
        title="[dim]timeline[/dim]",
        border_style="bright_black",
        padding=(0, 1),
    ))

    # ── bucket cards ──────────────────────────────────────────────────────
    totals = result.bucket_totals()
    ms_map = result.bucket_ms()

    cards = []
    for b in ("compute", "io", "memory", "idle"):
        color, dim_color, _, label = BUCKET_STYLE[b]
        pct = totals.get(b, 0.0)
        ms  = ms_map.get(b, 0)

        bar = _pct_bar(pct, 14, color)

        t = Text()
        t.append(f"{label}\n", style=f"bold {color}")
        t.append(f"{pct:.1f}%", style=f"bold white")
        t.append(f"  {_ms(ms)}\n", style="dim")
        t.append_text(bar)

        cards.append(Panel(t, border_style="bright_black", padding=(0, 1)))

    c.print(Columns(cards, equal=True, expand=True))

    # ── phase table ───────────────────────────────────────────────────────
    phases = result.top_phases(8)
    if phases:
        max_dur = max(p.duration_ms for p in phases)

        tbl = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="dim",
            border_style="bright_black",
            expand=True,
            padding=(0, 1),
        )
        tbl.add_column("phase",    style="white",       min_width=20, no_wrap=True)
        tbl.add_column("type",     style="dim",         ratio=2)
        tbl.add_column("duration", style="bold white",  ratio=2, justify="right")
        tbl.add_column("",         ratio=4)

        for p in phases:
            color, _, _, label = BUCKET_STYLE[p.bucket]
            bar_w  = int(p.duration_ms / max(max_dur, 1) * 24)
            bar_w  = max(bar_w, 1)
            bar    = Text("█" * bar_w, style=color)

            tbl.add_row(
                p.name,
                Text(label.strip(), style=f"dim {color}"),
                _ms(p.duration_ms),
                bar,
            )

        c.print(Panel(tbl, title="[dim]phase breakdown[/dim]",
                      border_style="bright_black", padding=(0, 0)))

    # ── insight ───────────────────────────────────────────────────────────
    insight = _make_insight(result)
    if insight:
        c.print(Panel(
            insight,
            title="[dim]insight[/dim]",
            border_style="yellow",
            padding=(0, 1),
        ))

    # ── stderr tail ───────────────────────────────────────────────────────
    if result.exit_code != 0 and result.stderr.strip():
        tail = "\n".join(result.stderr.strip().splitlines()[-6:])
        c.print(Panel(
            Text(tail, style="dim red"),
            title="[dim red]stderr (tail)[/dim red]",
            border_style="red",
            padding=(0, 1),
        ))

    c.print()


# ─── insight generator ───────────────────────────────────────────────────────

def _make_insight(result: RunResult) -> Optional[Text]:
    totals = result.bucket_totals()
    ms_map = result.bucket_ms()

    dominant = max(totals, key=totals.__getitem__)
    pct      = totals[dominant]

    tips = {
        "io": (
            f"[bold bright_green]{pct:.0f}% I/O[/bold bright_green] — "
            "most time blocked on disk or network.\n"
            "[dim]→ Cache dependencies, use in-memory DBs for tests, "
            "or parallelize I/O with asyncio / threads.[/dim]"
        ),
        "compute": (
            f"[bold bright_red]{pct:.0f}% Compute[/bold bright_red] — "
            "CPU-bound execution is the bottleneck.\n"
            "[dim]→ Profile hot loops, consider PyPy/Cython, "
            "or offload to multiprocessing.[/dim]"
        ),
        "memory": (
            f"[bold bright_magenta]{pct:.0f}% Memory pressure[/bold bright_magenta] — "
            "heap allocation or GC is eating time.\n"
            "[dim]→ Use generators/lazy evaluation, "
            "reduce object churn, check for large allocations.[/dim]"
        ),
        "idle": (
            f"[bold bright_black]{pct:.0f}% Idle[/bold bright_black] — "
            "process is mostly waiting (locks, sleeps, child processes).\n"
            "[dim]→ Investigate blocking calls, use async I/O, "
            "or check if worker processes are stalling.[/dim]"
        ),
    }

    from rich.markup import render as rrender
    return rrender(tips.get(dominant, ""))


# ─── compact summary (for --quiet) ───────────────────────────────────────────

def render_compact(result: RunResult) -> None:
    totals = result.bucket_totals()
    c = console

    parts = Text()
    parts.append(_ms(result.total_ms), style="bold white")
    parts.append("  ", style="")

    for b in ("compute", "io", "memory", "idle"):
        color, _, blk, label = BUCKET_STYLE[b]
        pct = totals.get(b, 0.0)
        parts.append(f"{blk} {label.strip()} {pct:.0f}%  ", style=color)

    c.print(parts)
