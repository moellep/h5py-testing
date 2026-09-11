# `partial-read` — does reading a small `/results` value pull the whole file into memory?

Checks a specific claim about `h5py`/HDF5's lazy-access model: a file with a small `results`
group (a handful of attributes and small datasets) and a much larger `meta` group (one big
dataset) should let a reader open the file, read a value out of `results`, and close it again
while touching only a small, roughly constant amount of memory and disk I/O — never anywhere
close to the size of `meta`.

## Files

- **`common.py`** — shared file layout (group/dataset names, sizes) and a small memory/IO probe
  (`Snapshot`, `report()`) used by every scenario script.
- **`make_test_file.py`** — builds `test_data.h5`: `results/` gets a scalar, a 100-element summary
  array, a 10-element string array, and a few attributes; `meta/raw_samples` gets one big 1-D
  `float64` dataset (`--meta-size-mb`, default 300 MB), written in chunks so generating the file
  doesn't itself need the whole array resident at once.
- **`run_partial_read.py`** — the scenario under test: open the file, read
  `results/scalar_result` and one attribute, close it. Asserts the read stayed under a small
  budget (`common.PARTIAL_READ_BUDGET_MB`, default 5 MB) of read-syscall traffic.
- **`run_partial_meta_slice.py`** — a second partial-read scenario: slice 10 elements out of the
  *middle* of `meta/raw_samples` instead. Demonstrates chunking specifically — the dataset is
  stored as independent fixed-size chunks (`make_test_file.py`'s `chunks=` argument), so this only
  requires the one chunk the slice falls in, not the whole dataset. See its docstring for a further
  nuance: because the chunk is unfiltered (no compression), HDF5 reads only the requested bytes
  out of that chunk rather than the whole chunk.
- **`run_full_read.py`** — control scenario: also reads all of `meta/raw_samples` into memory, for
  contrast. Confirms the probe actually detects a real full-file read (i.e. the partial-read
  results aren't cheap just because nothing here would ever show a difference).
- **`run_comparison.py`** — runs all three scenarios as separate processes (clean RSS/IO numbers,
  no cross-contamination from one scenario's page cache/allocator state leaking into another's
  measurement) and prints a side-by-side table.

## How it's measured

Two independent signals, both taken as before/after deltas around the read:

- **RSS** (`psutil.Process().memory_info().rss`) — the process's actual resident memory.
- **`rchar`** from `/proc/self/io` (Linux-only) — cumulative bytes passed to `read()`/`pread()`,
  counted *regardless of whether they were served from the page cache*. This is the more
  reliable signal: RSS can be muddied by allocator behavior, and a `read_bytes` figure (bytes
  that actually hit the block device) would look artificially small once the OS has cached the
  file from a previous run. `rchar` answers the actual question — did h5py *ask* to read
  `meta`? — independent of caching.

## Running it

```sh
python3 make_test_file.py                # writes test_data.h5 (~300 MB by default)
python3 run_comparison.py                # runs all three scenarios, prints the comparison
# or individually:
python3 run_partial_read.py              # asserts it stayed under the partial-read budget
python3 run_partial_meta_slice.py        # asserts the /meta slice stayed under the one-chunk budget
python3 run_full_read.py                 # control: reads everything
```

`test_data.h5` is generated, not committed (see repo `.gitignore`) — regenerate it before running
the scenarios. `--meta-size-mb` controls how large the contrast is; the default of 300 MB is
already dramatic enough that the two scenarios can't be confused by measurement noise.

## Result

From a real run of `run_comparison.py` against the default 300 MB file:

| scenario             | RSS delta (MB) | bytes read via `rchar` (MB) |
|----------------------|---------------:|-----------------------------:|
| `partial_read`       |           0.90 |                         0.005 |
| `partial_meta_slice` |           0.88 |                         0.006 |
| `full_read`          |         300.98 |                        300.01 |

Reading one value out of `results`, or slicing 10 elements out of the middle of `meta`, each cost
under 10 KB of actual I/O and under 1 MB of RSS growth — independent of `meta`'s total size.
Reading all of `meta` cost the full 300 MB in both signals. See
[`../docs/partial-read/SUMMARY.md`](../docs/partial-read/SUMMARY.md) for the full run output.

This matches how HDF5's file format is designed to be used: object headers, attributes, and
group/dataset metadata live in small, independently-addressable records (B-tree/heap structures
in the file's superblock region), and the library's default POSIX driver does targeted
`pread()`s against them rather than mapping or reading the file as a whole. Nothing about opening
a file or resolving `results/scalar_result` requires touching `meta` at all — and the same holds
for slicing into `meta` itself, thanks to chunking: the dataset is broken into independent
fixed-size blocks (`chunks=` in `make_test_file.py`), so a slice only requires the one chunk it
falls in, not the whole dataset.

**Caveat, worth knowing:** `partial_meta_slice`'s ~6 KB is smaller than the ~10 MB chunk it reads
from, because that chunk is *unfiltered* (no compression) — HDF5 can address arbitrary byte
ranges within an uncompressed chunk directly. Rerunning the same slice against a
`compression="gzip"` copy of the same layout measured ~7-8 MB read instead — the entire chunk,
because compressed bytes aren't randomly addressable; decompression requires the whole block.
Chunking always narrows a read down to one chunk; whether it narrows further to just the
requested elements depends on whether that chunk has a filter attached.
