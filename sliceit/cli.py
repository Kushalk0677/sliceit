"""
Sliceit CLI entry point.

Usage:
    sliceit run -- <command> [args...]
    sliceit run --quiet -- <command> [args...]
    sliceit run --repeat 3 -- <command> [args...]
    sliceit run --no-capture -- <command> [args...]

Examples:
    sliceit run -- npm test
    sliceit run -- python train.py
    sliceit run -- cargo build
    sliceit run -- pytest tests/
    sliceit run --repeat 3 -- make build
"""

from __future__ import annotations

import sys
import argparse

from rich.console import Console
from rich.text import Text

from .core import run as profile_run
from .display import render, render_compact, make_spinner, console


# ─── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sliceit",
        description="End-to-end latency breakdown for any command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.strip(),
    )

    sub = p.add_subparsers(dest="subcommand", required=True)

    run_p = sub.add_parser("run", help="Profile a command")
    run_p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="One-line summary instead of full dashboard",
    )
    run_p.add_argument(
        "--repeat", "-n",
        type=int,
        default=1,
        metavar="N",
        help="Run the command N times and show all results",
    )
    run_p.add_argument(
        "--no-capture",
        action="store_true",
        help="Let stdout/stderr pass through to terminal",
    )
    run_p.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to profile (use -- before it to avoid flag conflicts)",
    )

    return p


def _clean_command(parts: list[str]) -> str:
    # strip leading '--' separator if present
    if parts and parts[0] == "--":
        parts = parts[1:]
    if not parts:
        console.print("[red]Error:[/red] no command provided.", highlight=False)
        sys.exit(1)
    return " ".join(parts)


def cmd_run(args: argparse.Namespace) -> None:
    command = _clean_command(list(args.command))
    capture = not args.no_capture

    results = []

    for i in range(args.repeat):
        if args.repeat > 1:
            console.print(
                f"\n[dim]run {i+1} of {args.repeat}[/dim]",
                highlight=False,
            )

        with make_spinner(command):
            result = profile_run(command, capture_output=capture)

        results.append(result)

        if args.quiet:
            render_compact(result)
        else:
            render(result)

    # multi-run summary
    if args.repeat > 1 and not args.quiet:
        _render_multi_summary(results)


def _render_multi_summary(results) -> None:
    from rich.table import Table
    from rich import box

    totals_list = [r.bucket_totals() for r in results]
    durations   = [r.total_ms for r in results]

    avg_dur = sum(durations) / len(durations)
    min_dur = min(durations)
    max_dur = max(durations)

    tbl = Table(
        title="[bold]multi-run summary[/bold]",
        box=box.SIMPLE_HEAD,
        border_style="bright_black",
        show_header=True,
        header_style="dim",
        expand=False,
    )
    tbl.add_column("run",     style="dim",        justify="right")
    tbl.add_column("total",   style="bold white",  justify="right")
    tbl.add_column("compute", style="bright_red",  justify="right")
    tbl.add_column("i/o",     style="bright_green",justify="right")
    tbl.add_column("memory",  style="bright_magenta", justify="right")
    tbl.add_column("idle",    style="bright_black", justify="right")

    from .display import _ms
    for i, (r, t) in enumerate(zip(results, totals_list)):
        tbl.add_row(
            f"#{i+1}",
            _ms(r.total_ms),
            f"{t['compute']:.0f}%",
            f"{t['io']:.0f}%",
            f"{t['memory']:.0f}%",
            f"{t['idle']:.0f}%",
        )

    # averages row
    avg_t = {
        b: sum(t[b] for t in totals_list) / len(totals_list)
        for b in ("compute", "io", "memory", "idle")
    }
    tbl.add_row(
        "[dim]avg[/dim]",
        f"[dim]{_ms(avg_dur)}[/dim]",
        f"[dim]{avg_t['compute']:.0f}%[/dim]",
        f"[dim]{avg_t['io']:.0f}%[/dim]",
        f"[dim]{avg_t['memory']:.0f}%[/dim]",
        f"[dim]{avg_t['idle']:.0f}%[/dim]",
    )

    console.print(tbl)
    console.print(
        f"[dim]  min {_ms(min_dur)}  max {_ms(max_dur)}  "
        f"spread {_ms(max_dur - min_dur)}[/dim]"
    )
    console.print()


# ─── entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()

    # if called with no args, print help
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.subcommand == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
