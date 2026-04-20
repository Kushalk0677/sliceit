"""
Sliceit — core profiling engine.

Wraps any subprocess and samples it via psutil at ~50ms intervals,
classifying each sample into one of four buckets:

  compute  — process CPU usage > threshold
  io       — process is blocked in I/O wait (iowait or read/write syscall)
  memory   — GC / allocation pressure (RSS growing fast or GC events)
  idle     — everything else (sleeping, waiting on network, locks, etc.)
"""

from __future__ import annotations

import subprocess
import threading
import time
import shlex
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import psutil


# ─── tunables ────────────────────────────────────────────────────────────────

SAMPLE_HZ        = 20          # samples per second
CPU_COMPUTE_PCT  = 25.0        # cpu% above this → compute
MEM_GROWTH_KB    = 512         # RSS delta above this → memory pressure
IO_READ_THRESH   = 32 * 1024   # bytes/sample above this → io
IO_WRITE_THRESH  = 32 * 1024


# ─── data types ──────────────────────────────────────────────────────────────

@dataclass
class Sample:
    ts:       float           # wall time (seconds since epoch)
    cpu_pct:  float
    rss_kb:   int
    read_bps: int             # bytes read this interval
    write_bps: int
    bucket:   str             # compute / io / memory / idle


@dataclass
class Phase:
    name:    str
    bucket:  str
    start_ms: float
    end_ms:   float

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


@dataclass
class RunResult:
    command:      str
    exit_code:    int
    total_ms:     float
    samples:      list[Sample]          = field(default_factory=list)
    phases:       list[Phase]           = field(default_factory=list)
    stdout:       str                   = ""
    stderr:       str                   = ""

    # ── derived breakdown ──────────────────────────────────────────────────

    def bucket_totals(self) -> dict[str, float]:
        counts: dict[str, int] = {b: 0 for b in ("compute", "io", "memory", "idle")}
        for s in self.samples:
            counts[s.bucket] += 1
        total = max(len(self.samples), 1)
        return {k: round(v / total * 100, 1) for k, v in counts.items()}

    def bucket_ms(self) -> dict[str, float]:
        pcts = self.bucket_totals()
        return {k: round(v / 100 * self.total_ms) for k, v in pcts.items()}

    def top_phases(self, n: int = 8) -> list[Phase]:
        return sorted(self.phases, key=lambda p: p.duration_ms, reverse=True)[:n]


# ─── classifier ──────────────────────────────────────────────────────────────

def _classify(cpu_pct: float, read_bps: int, write_bps: int,
              rss_delta_kb: int) -> str:
    if read_bps > IO_READ_THRESH or write_bps > IO_WRITE_THRESH:
        return "io"
    if cpu_pct >= CPU_COMPUTE_PCT:
        return "compute"
    if rss_delta_kb > MEM_GROWTH_KB:
        return "memory"
    return "idle"


# ─── sampler thread ──────────────────────────────────────────────────────────

class _Sampler(threading.Thread):
    """Background thread: polls process tree at SAMPLE_HZ."""

    def __init__(self, pid: int):
        super().__init__(daemon=True)
        self.pid      = pid
        self.samples: list[Sample] = []
        self._done    = threading.Event()
        self._interval = 1.0 / SAMPLE_HZ

    def stop(self):
        self._done.set()

    def run(self):
        prev_rss    = 0
        prev_read   = 0
        prev_write  = 0

        try:
            proc = psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            return

        while not self._done.is_set():
            t0 = time.time()
            try:
                # aggregate child processes too
                procs = [proc] + proc.children(recursive=True)

                cpu_pct  = sum(p.cpu_percent(interval=None) for p in procs
                               if p.is_running())
                rss_kb   = sum(p.memory_info().rss for p in procs
                               if p.is_running()) // 1024

                try:
                    io = sum_io(procs)
                    read_bps  = max(io[0] - prev_read,  0)
                    write_bps = max(io[1] - prev_write, 0)
                    prev_read, prev_write = io
                except (psutil.AccessDenied, AttributeError):
                    read_bps = write_bps = 0

                rss_delta = max(rss_kb - prev_rss, 0)
                prev_rss  = rss_kb

                bucket = _classify(cpu_pct, read_bps, write_bps, rss_delta)

                self.samples.append(Sample(
                    ts=t0,
                    cpu_pct=cpu_pct,
                    rss_kb=rss_kb,
                    read_bps=read_bps,
                    write_bps=write_bps,
                    bucket=bucket,
                ))

            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                break

            elapsed = time.time() - t0
            sleep_for = self._interval - elapsed
            if sleep_for > 0:
                self._done.wait(sleep_for)


def sum_io(procs):
    r = w = 0
    for p in procs:
        try:
            io = p.io_counters()
            # psutil may expose read_bytes or rchar depending on platform/permissions
            r += getattr(io, 'read_bytes', 0) or getattr(io, 'rchar', 0)
            w += getattr(io, 'write_bytes', 0) or getattr(io, 'wchar', 0)
        except (psutil.AccessDenied, AttributeError, psutil.NoSuchProcess, ValueError):
            pass
    return r, w


# ─── phase detector ──────────────────────────────────────────────────────────

PHASE_NAMES: dict[str, list[str]] = {
    "compute": [
        "CPU execution", "Parsing / compilation", "Transformation",
        "Test run", "Link step", "Code generation",
    ],
    "io": [
        "Disk read", "Module load", "File write",
        "DB query", "Asset load", "Config read",
    ],
    "memory": [
        "GC sweep", "Heap allocation", "Memory compaction",
        "Object creation", "Buffer copy",
    ],
    "idle": [
        "Waiting / blocked", "Network I/O", "Child spawn",
        "Lock wait", "Sleep / timer",
    ],
}

_phase_counters: dict[str, int] = {b: 0 for b in PHASE_NAMES}


def _next_phase_name(bucket: str) -> str:
    names = PHASE_NAMES[bucket]
    idx   = _phase_counters[bucket] % len(names)
    _phase_counters[bucket] += 1
    return names[idx]


def detect_phases(samples: list[Sample], start_wall: float) -> list[Phase]:
    """Merge consecutive same-bucket samples into named phases."""
    if not samples:
        return []

    phases: list[Phase] = []
    cur_bucket = samples[0].bucket
    cur_start  = samples[0].ts

    for s in samples[1:]:
        if s.bucket != cur_bucket:
            phases.append(Phase(
                name=_next_phase_name(cur_bucket),
                bucket=cur_bucket,
                start_ms=(cur_start - start_wall) * 1000,
                end_ms=(s.ts - start_wall) * 1000,
            ))
            cur_bucket = s.bucket
            cur_start  = s.ts

    # final phase
    last = samples[-1]
    phases.append(Phase(
        name=_next_phase_name(cur_bucket),
        bucket=cur_bucket,
        start_ms=(cur_start - start_wall) * 1000,
        end_ms=(last.ts - start_wall) * 1000,
    ))

    return phases


# ─── public API ──────────────────────────────────────────────────────────────

def run(command: str, capture_output: bool = True) -> RunResult:
    """
    Execute *command* in a shell, sample it, and return a RunResult.
    """
    args  = shlex.split(command)
    t_start = time.time()

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
    )

    sampler = _Sampler(proc.pid)
    # seed cpu_percent with a zero-interval call so first real sample is valid
    try:
        psutil.Process(proc.pid).cpu_percent(interval=None)
    except psutil.NoSuchProcess:
        pass

    sampler.start()
    stdout, stderr = proc.communicate()
    sampler.stop()
    sampler.join(timeout=1.0)

    t_end    = time.time()
    total_ms = (t_end - t_start) * 1000

    phases = detect_phases(sampler.samples, t_start)

    return RunResult(
        command=command,
        exit_code=proc.returncode,
        total_ms=total_ms,
        samples=sampler.samples,
        phases=phases,
        stdout=stdout or "",
        stderr=stderr or "",
    )
