"""Shared constants, test-file layout, and a lightweight memory/IO probe for
the /results vs /meta partial-read test harness.

Every script in this directory works against the same on-disk layout so
make_test_file.py, run_partial_read.py, run_partial_meta_slice.py,
run_full_read.py, and run_comparison.py all agree on what "results" and
"meta" contain.
"""

import json
import os
import pathlib

import psutil

TEST_DIR = pathlib.Path(__file__).parent
DEFAULT_FILE_PATH = TEST_DIR / "test_data.h5"

RESULTS_GROUP = "results"
META_GROUP = "meta"

RESULTS_ATTRS = {
    "version": 1,
    "created_by": "h5py-testing/partial-read",
    "description": "Small analysis summary -- the thing a real reader actually wants.",
}
RESULTS_SCALAR_NAME = "scalar_result"
RESULTS_SUMMARY_NAME = "summary"
RESULTS_SUMMARY_LEN = 100
RESULTS_LABELS_NAME = "labels"
RESULTS_LABELS_LEN = 10

META_DATASET_NAME = "raw_samples"
META_DTYPE = "float64"
DEFAULT_META_SIZE_MB = 300
META_WRITE_CHUNK_MB = 10
META_SLICE_LEN = 10

# How much read-syscall traffic is acceptable for a read that's only
# supposed to touch /results. Generous relative to /results' own size (a
# few KB of attrs/datasets plus HDF5 object-header/B-tree overhead) but
# tiny next to DEFAULT_META_SIZE_MB, so a regression that actually pulls
# /meta in trips it immediately.
PARTIAL_READ_BUDGET_MB = 5

# Upper bound for a slice that's supposed to touch only a small part of
# the one chunk it falls in. Because the dataset is unfiltered
# (uncompressed), HDF5 can read just the requested byte range directly
# rather than pulling the whole chunk into its cache -- measured well
# under 1 MB in practice (see run_partial_meta_slice.py's docstring). This
# budget is set to a full chunk's worth (META_WRITE_CHUNK_MB) as a
# generous fallback in case that optimization doesn't apply in some HDF5
# version, while still catching a real full-dataset read (which would be
# ~DEFAULT_META_SIZE_MB, far larger).
META_SLICE_BUDGET_MB = 2 * META_WRITE_CHUNK_MB

_PROCESS = psutil.Process()


def _read_proc_io():
    """(rchar, read_bytes) for this process, or (None, None) if unavailable.

    rchar counts bytes passed to read()/pread() regardless of whether they
    were served from the page cache -- what we actually want here, since
    the question is whether h5py *asked* to read /meta, not whether the OS
    had to hit disk to satisfy it. read_bytes is the narrower,
    block-device-only figure. /proc/self/io is Linux-only; callers must
    tolerate None on other platforms.
    """
    try:
        with open("/proc/self/io") as f:
            fields = dict(line.split(": ") for line in f.read().splitlines())
        return int(fields["rchar"]), int(fields["read_bytes"])
    except FileNotFoundError:
        return None, None


def _mb(num_bytes):
    return None if num_bytes is None else num_bytes / (1024 * 1024)


class Snapshot:
    """Point-in-time process RSS and cumulative read-syscall byte counts."""

    def __init__(self):
        self.rss_bytes = _PROCESS.memory_info().rss
        self.rchar_bytes, self.read_bytes = _read_proc_io()

    def delta_mb(self, before):
        def _delta(after_val, before_val):
            return None if after_val is None or before_val is None else _mb(after_val - before_val)

        return {
            "rss_delta_mb": _mb(self.rss_bytes - before.rss_bytes),
            "rchar_delta_mb": _delta(self.rchar_bytes, before.rchar_bytes),
            "read_bytes_delta_mb": _delta(self.read_bytes, before.read_bytes),
        }


def report(scenario, path, before, after):
    """Print a human-readable block plus a machine-parseable RESULT: JSON line."""
    file_size_mb = os.path.getsize(path) / (1024 * 1024)
    delta = after.delta_mb(before)
    delta["scenario"] = scenario
    delta["file_size_mb"] = file_size_mb

    print(f"[{scenario}] file size on disk:  {file_size_mb:.1f} MB")
    print(f"[{scenario}] RSS delta:          {delta['rss_delta_mb']:.2f} MB")
    if delta["rchar_delta_mb"] is not None:
        print(f"[{scenario}] bytes read (rchar): {delta['rchar_delta_mb']:.2f} MB")
        print(f"[{scenario}] bytes read (block): {delta['read_bytes_delta_mb']:.2f} MB")
    else:
        print(f"[{scenario}] /proc/self/io unavailable on this platform -- I/O byte counts skipped")
    print(f"RESULT: {json.dumps(delta)}")
    return delta
