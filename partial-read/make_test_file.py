"""Creates a test HDF5 file with a small "results" group (a handful of
attributes and small datasets -- what a real reader wants) and a much
larger "meta" group (one big 1-D dataset, standing in for raw per-sample
data a results reader has no reason to touch), so run_partial_read.py has
something concrete to check: does reading a results value pull the whole
file into memory?
"""

import argparse
import os

import h5py
import numpy as np

import common


def make_test_file(path, meta_size_mb, seed=0):
    rng = np.random.default_rng(seed)
    itemsize = np.dtype(common.META_DTYPE).itemsize
    n_meta_elements = int(meta_size_mb * 1024 * 1024 / itemsize)
    chunk_elements = max(1, int(common.META_WRITE_CHUNK_MB * 1024 * 1024 / itemsize))

    with h5py.File(path, "w") as f:
        results = f.create_group(common.RESULTS_GROUP)
        for name, value in common.RESULTS_ATTRS.items():
            results.attrs[name] = value
        results.create_dataset(common.RESULTS_SCALAR_NAME, data=42.5)
        results.create_dataset(
            common.RESULTS_SUMMARY_NAME, data=rng.normal(size=common.RESULTS_SUMMARY_LEN)
        )
        results.create_dataset(
            common.RESULTS_LABELS_NAME,
            data=[f"channel_{i}" for i in range(common.RESULTS_LABELS_LEN)],
        )

        meta = f.create_group(common.META_GROUP)
        dset = meta.create_dataset(
            common.META_DATASET_NAME,
            shape=(n_meta_elements,),
            dtype=common.META_DTYPE,
            chunks=(min(chunk_elements, n_meta_elements),),
        )
        # Filled in chunks so *generating* the file doesn't itself need the
        # whole array resident at once -- keeps this script's own memory
        # use independent of --meta-size-mb.
        for start in range(0, n_meta_elements, chunk_elements):
            end = min(start + chunk_elements, n_meta_elements)
            dset[start:end] = rng.normal(size=end - start)

    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(common.DEFAULT_FILE_PATH))
    parser.add_argument("--meta-size-mb", type=float, default=common.DEFAULT_META_SIZE_MB)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    make_test_file(args.path, args.meta_size_mb, args.seed)
    actual_mb = os.path.getsize(args.path) / (1024 * 1024)
    print(f"wrote {args.path} ({actual_mb:.1f} MB on disk; /meta target was {args.meta_size_mb} MB)")


if __name__ == "__main__":
    main()
