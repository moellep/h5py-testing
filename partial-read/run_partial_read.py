"""The scenario under test: open the file, read one small value out of
/results, close it -- and report how much memory and I/O that actually
cost.

Run as its own process (not imported alongside run_full_read.py in one
interpreter) so its RSS and /proc/self/io numbers reflect only this
script's own access pattern, not whatever another scenario already paged
in or cached first.
"""

import argparse

import h5py

import common


def read_one_result(path):
    with h5py.File(path, "r") as f:
        results = f[common.RESULTS_GROUP]
        value = results[common.RESULTS_SCALAR_NAME][()]
        version = results.attrs["version"]
    return value, version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(common.DEFAULT_FILE_PATH))
    args = parser.parse_args()

    before = common.Snapshot()
    value, version = read_one_result(args.path)
    after = common.Snapshot()

    delta = common.report("partial_read", args.path, before, after)
    print(f"read {common.RESULTS_GROUP}/{common.RESULTS_SCALAR_NAME} = {value} (version {version})")

    if delta["rchar_delta_mb"] is not None:
        assert delta["rchar_delta_mb"] < common.PARTIAL_READ_BUDGET_MB, (
            f"read {delta['rchar_delta_mb']:.2f} MB to fetch one small value -- "
            f"expected under {common.PARTIAL_READ_BUDGET_MB} MB; /meta may have been pulled in"
        )
        print(f"PASS: read stayed under the {common.PARTIAL_READ_BUDGET_MB} MB partial-read budget")


if __name__ == "__main__":
    main()
