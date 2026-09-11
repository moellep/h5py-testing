"""A third partial-read scenario, distinct from both of the others: slice a
handful of elements out of the *middle* of the large /meta dataset,
instead of reading /results (run_partial_read.py) or all of /meta
(run_full_read.py).

Demonstrates that chunking is what makes a partial read of a large
dataset cheap: /meta/raw_samples is stored as independent fixed-size
chunks (see make_test_file.py's chunks= argument), so slicing a few
elements only requires locating the one chunk that slice falls in, not
the whole dataset.

It goes further than that, though: measured I/O here is a few KB, not a
whole ~10 MB chunk. Because this dataset has no compression filter, HDF5
can read exactly the requested byte range directly out of the chunk's
on-disk block, rather than reading the whole chunk into its cache to
extract a few elements. That optimization only works because the chunk's
bytes are addressable at arbitrary offsets; a *compressed* chunk doesn't
have that property (you must decompress the whole block to get anything
out of it), so the same slice against a `compression="gzip"` dataset
measures ~7-8 MB read -- the entire chunk. Chunking narrows a read down
to one chunk either way; whether that read is itself further narrowed to
just the requested elements depends on whether the chunk is filtered.
"""

import argparse

import h5py

import common


def read_meta_slice(path, slice_len):
    with h5py.File(path, "r") as f:
        dset = f[common.META_GROUP][common.META_DATASET_NAME]
        start = dset.shape[0] // 2
        values = dset[start : start + slice_len]
        chunk_shape = dset.chunks
    return values, chunk_shape


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(common.DEFAULT_FILE_PATH))
    parser.add_argument("--slice-len", type=int, default=common.META_SLICE_LEN)
    args = parser.parse_args()

    before = common.Snapshot()
    values, chunk_shape = read_meta_slice(args.path, args.slice_len)
    after = common.Snapshot()

    delta = common.report("partial_meta_slice", args.path, before, after)
    print(
        f"read {args.slice_len} elements from the middle of "
        f"{common.META_GROUP}/{common.META_DATASET_NAME} (chunk shape {chunk_shape}): {values}"
    )

    if delta["rchar_delta_mb"] is not None:
        assert delta["rchar_delta_mb"] < common.META_SLICE_BUDGET_MB, (
            f"read {delta['rchar_delta_mb']:.2f} MB to fetch {args.slice_len} elements -- "
            f"expected under {common.META_SLICE_BUDGET_MB} MB (about one chunk); "
            "more of /meta may have been pulled in than just the containing chunk"
        )
        print(f"PASS: read stayed under the {common.META_SLICE_BUDGET_MB} MB one-chunk budget")


if __name__ == "__main__":
    main()
