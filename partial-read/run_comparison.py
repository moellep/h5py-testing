"""Runs run_partial_read.py, run_partial_meta_slice.py, and
run_full_read.py as separate processes against the same test file and
prints a side-by-side comparison -- proof that reading a value from
/results, or slicing one chunk out of /meta, both cost a small, roughly
constant amount of memory/IO no matter how large /meta is, while reading
all of /meta actually costs proportionally to its size.

Separate processes (not all three scenarios in one interpreter) so each
one's RSS and /proc/self/io numbers reflect only its own access pattern,
not whatever an earlier scenario already paged in or read.
"""

import argparse
import json
import subprocess
import sys

import common


def run_scenario(script, path):
    result = subprocess.run(
        [sys.executable, script, "--path", path],
        capture_output=True,
        text=True,
        check=True,
        cwd=common.TEST_DIR,
    )
    print(result.stdout, end="")
    for line in result.stdout.splitlines():
        if line.startswith("RESULT: "):
            return json.loads(line[len("RESULT: ") :])
    raise RuntimeError(f"{script} printed no RESULT: line")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(common.DEFAULT_FILE_PATH))
    args = parser.parse_args()

    print("=== partial_read (reads only /results) ===")
    partial = run_scenario("run_partial_read.py", args.path)
    print("\n=== partial_meta_slice (reads one chunk's worth from the middle of /meta) ===")
    meta_slice = run_scenario("run_partial_meta_slice.py", args.path)
    print("\n=== full_read (also reads all of /meta) ===")
    full = run_scenario("run_full_read.py", args.path)

    print("\n=== comparison ===")
    print(f"{'scenario':<20}{'rss_delta_mb':>14}{'rchar_delta_mb':>16}")
    for row in (partial, meta_slice, full):
        rchar = row["rchar_delta_mb"]
        rchar_str = f"{rchar:.2f}" if rchar is not None else "n/a"
        print(f"{row['scenario']:<20}{row['rss_delta_mb']:>14.2f}{rchar_str:>16}")


if __name__ == "__main__":
    main()
