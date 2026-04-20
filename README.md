# Sliceit

**See exactly where your command spends time.**

Sliceit wraps any command and breaks execution into four buckets — **compute**, **I/O**, **memory**, and **idle** — then renders a live terminal dashboard showing the full breakdown.

```
sliceit run -- pytest tests/
sliceit run -- python train.py
sliceit run -- cargo build
sliceit run -- npm test
```

---

## Why

Most developers debug slow commands with intuition. `time ./script.sh` gives you a total. Profilers give you a flame graph you have to learn to read. Neither tells you the obvious thing: *is this slow because of CPU, disk, or just waiting?*

Sliceit answers that in one line.

---

## Demo

```
─────────────────  Sliceit  python experiments/smoke_test.py  ──────────────────
  total  3.45s   samples  54   status  ✓ ok

╭──────────────────────────────────── timeline ──────────────────────────────────╮
│ ████████████████████████░░░░░░░░░░░░░░░░░░░░░███████████░░░░░░░░░░░░░░░░░████  │
│   ▐ Compute  ▐ I/O  ▐ Memory  ▐ Idle                                           │
╰────────────────────────────────────────────────────────────────────────────────╯

╭────────────────╮  ╭────────────────╮  ╭────────────────╮  ╭────────────────╮
│ Compute        │  │ I/O            │  │ Memory         │  │ Idle           │
│ 7.4%  255ms    │  │ 24.1%  832ms   │  │ 3.7%  128ms    │  │ 64.8%  2.24s   │
│ █░░░░░░░░░░░░░ │  │ ███░░░░░░░░░░░ │  │ █░░░░░░░░░░░░░ │  │ █████████░░░░░ │
╰────────────────╯  ╰────────────────╯  ╰────────────────╯  ╰────────────────╯

╭──────────────────────────────── phase breakdown ───────────────────────────────╮
│  Waiting / blocked   Idle     1.44s  ████████████████████████                  │
│  Module load         I/O      440ms  ███████                                   │
│  Lock wait           Idle     435ms  ███████                                   │
│  Disk read           I/O      310ms  █████                                     │
│  Network I/O         Idle     250ms  ████                                      │
│  Parsing / compile   Compute  123ms  ██                                        │
│  CPU execution       Compute   63ms  █                                         │
╰────────────────────────────────────────────────────────────────────────────────╯

╭───────────────────────────────────── insight ──────────────────────────────────╮
│ 65% Idle — process is mostly waiting (locks, sleeps, child processes).          │
│ → Investigate blocking calls, use async I/O, or check if worker processes      │
│   are stalling.                                                                 │
╰────────────────────────────────────────────────────────────────────────────────╯
```

---

## Install

```bash
pip install sliceit
```

**Requirements:** Python 3.9+, works on macOS, Linux, and Windows.

Dependencies (`rich`, `psutil`) are installed automatically.

### Add to PATH

After installing, make sure the `sliceit` command is on your PATH.

**Windows (PowerShell):**
```powershell
$s = python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";" + $s, "User")
```
Restart PowerShell after running.

**macOS / Linux:**
```bash
export PATH="$HOME/.local/bin:$PATH"   # add to ~/.bashrc or ~/.zshrc
```

### No PATH? No problem.

```bash
# macOS / Linux
python -m sliceit run -- <command>

# Windows
python -c "from sliceit.cli import main; main()" run -- <command>
```

---

## Usage

```
sliceit run [options] -- <command>
```

| Flag | Description |
|------|-------------|
| `--repeat N`, `-n N` | Run the command N times and show a comparison table |
| `--quiet`, `-q` | One-line summary instead of full dashboard |
| `--no-capture` | Let the command's stdout/stderr print to your terminal normally |

### Examples

```bash
# Scripts
sliceit run -- python train.py
sliceit run -- node index.js

# Test suites
sliceit run -- pytest tests/
sliceit run -- npm test
sliceit run -- cargo test

# Builds
sliceit run -- cargo build
sliceit run -- make build
sliceit run -- go build ./...

# Run 3 times and compare
sliceit run --repeat 3 -- pytest

# One-liner for CI
sliceit run --quiet -- python script.py

# Pass through stdout
sliceit run --no-capture -- cargo build
```

### Multi-run comparison

```
sliceit run --repeat 3 -- npm test

               multi-run summary
  run   total    compute   i/o   memory   idle
 ──────────────────────────────────────────────
   #1   3,240ms     18%    47%      7%     28%
   #2   3,010ms     22%    40%      9%     24%
   #3   3,290ms     16%    52%     14%     18%
  avg   3,180ms     19%    46%     10%     23%

  min 3,010ms  max 3,290ms  spread 280ms
```

---

## How it works

Sliceit wraps your command in a subprocess and polls it — and all its child processes — at **20Hz** using `psutil`. Each sample is classified into one bucket:

| Bucket | Classification rule |
|--------|---------------------|
| **I/O** | Bytes read or written per interval exceed threshold |
| **Compute** | CPU% above 25% |
| **Memory** | RSS growing faster than 512KB per sample |
| **Idle** | Everything else — locks, sleeps, network wait, spawning |

Consecutive same-bucket samples are merged into named phases. The timeline bar maps each character to ~1/60th of total runtime, colored by dominant bucket.

Sampler overhead: under 1% CPU on the background thread.

---

## Limitations

- **Short commands (<200ms)** collect too few samples for a meaningful breakdown. Use `--repeat` to aggregate.
- **Classification is heuristic** — a process doing both CPU work and disk I/O in the same 50ms window gets assigned the dominant signal. Fine-grained interleaving won't be perfectly separated.
- **Windows I/O counters** may show 0% for some processes depending on permissions.
- **GPU time is not measured.** Compute reflects CPU only — GPU-bound workloads will appear mostly Idle.

---

## Roadmap

- [ ] JSON output (`--json`) for CI integration
- [ ] GPU utilization bucket via `pynvml`
- [ ] Export flamegraph-style HTML report
- [ ] Per-child-process breakdown
- [ ] Config file (`.sliceit.toml`) for custom thresholds

---

## License

MIT
