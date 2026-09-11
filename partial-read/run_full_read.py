"""Control scenario: also read the entire /meta dataset into memory, for
contrast against run_partial_read.py. Confirms the harness's memory/IO
probe actually detects a real full-file read, rather than the
partial-read scenario merely looking cheap because nothing would show a
difference either way.
"""

import argparse

import h5py

import common


def read_everything(path):
    with h5py.File(path, "r") as f:
        results = f[common.RESULTS_GROUP]
        value = results[common.RESULTS_SCALAR_NAME][()]
        meta = f[common.META_GROUP][common.META_DATASET_NAME][:]
    return value, meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(common.DEFAULT_FILE_PATH))
    args = parser.parse_args()

    before = common.Snapshot()
    value, meta = read_everything(args.path)
    after = common.Snapshot()

    common.report("full_read", args.path, before, after)
    print(f"read {common.RESULTS_GROUP}/{common.RESULTS_SCALAR_NAME} = {value} and all {meta.shape[0]:,} /meta elements")


if __name__ == "__main__":
    main()
