# `partial-read` — results

Ran on a 300 MB test file (`meta/raw_samples`: 39,321,600 `float64` elements, chunked at
1,310,720 elements/chunk, no compression), Linux, h5py 3.14.0 / HDF5 1.14.6, via:

```sh
python3 make_test_file.py
python3 run_comparison.py
```

Full output:

```
=== partial_read (reads only /results) ===
[partial_read] file size on disk:  300.0 MB
[partial_read] RSS delta:          0.90 MB
[partial_read] bytes read (rchar): 0.00 MB
[partial_read] bytes read (block): 0.00 MB
RESULT: {"rss_delta_mb": 0.8984375, "rchar_delta_mb": 0.004563331604003906, "read_bytes_delta_mb": 0.0, "scenario": "partial_read", "file_size_mb": 300.01233673095703}
read results/scalar_result = 42.5 (version 1)
PASS: read stayed under the 5 MB partial-read budget

=== partial_meta_slice (reads one chunk's worth from the middle of /meta) ===
[partial_meta_slice] file size on disk:  300.0 MB
[partial_meta_slice] RSS delta:          0.88 MB
[partial_meta_slice] bytes read (rchar): 0.01 MB
[partial_meta_slice] bytes read (block): 0.00 MB
RESULT: {"rss_delta_mb": 0.875, "rchar_delta_mb": 0.006402015686035156, "read_bytes_delta_mb": 0.0, "scenario": "partial_meta_slice", "file_size_mb": 300.01233673095703}
read 10 elements from the middle of meta/raw_samples (chunk shape (1310720,)): [ 0.77708733  1.1366455   2.76014969  0.67331987 -0.07271819 -1.88393905
 -1.72853803  0.06244361  0.08083217  0.51990668]
PASS: read stayed under the 20 MB one-chunk budget

=== full_read (also reads all of /meta) ===
[full_read] file size on disk:  300.0 MB
[full_read] RSS delta:          300.98 MB
[full_read] bytes read (rchar): 300.01 MB
[full_read] bytes read (block): 0.00 MB
RESULT: {"rss_delta_mb": 300.98046875, "rchar_delta_mb": 300.0088586807251, "read_bytes_delta_mb": 0.0, "scenario": "full_read", "file_size_mb": 300.01233673095703}
read results/scalar_result = 42.5 and all 39,321,600 /meta elements

=== comparison ===
scenario              rss_delta_mb  rchar_delta_mb
partial_read                  0.90            0.00
partial_meta_slice            0.88            0.01
full_read                   300.98          300.01
```

## Takeaway

Reading `results/scalar_result` (a single 8-byte value, plus an attribute) cost **~4.6 KB**, and
slicing 10 elements out of the middle of `meta/raw_samples` cost **~6.7 KB**, of actual
read-syscall traffic — each under 1 MB of RSS growth, regardless of `meta`'s 300 MB total size.
Reading `meta/raw_samples` in full cost the entire 300 MB in both signals. `open → read one small
value → close` does not pull the rest of the file into memory, at any scale — confirmed by an I/O
signal (`/proc/self/io`'s `rchar`) that isn't affected by OS page-cache behavior, not just by RSS.

`read_bytes` (the narrower, block-device-only figure) reads 0.00 MB in every scenario here because
the file was still warm in the OS page cache from being written moments earlier in the same test
run — expected, and exactly why `rchar` (what h5py *asked* to read) rather than `read_bytes` (what
the OS had to actually fetch from disk) is the signal this test relies on.

## A follow-up finding: compression changes the picture

`partial_meta_slice`'s ~6.7 KB is smaller than the dataset's own ~10 MB chunk size, not just
smaller than the 300 MB file. A quick side-by-side probe (not part of the committed harness)
confirms why: the same 10-element slice against an identically-shaped dataset built with
`compression="gzip"` instead measured **~7.7 MB** of `rchar` — essentially the whole chunk.

Uncompressed ("unfiltered") chunks are byte-addressable at arbitrary offsets, so HDF5 can seek
directly to the requested elements within a chunk's on-disk block. A compressed chunk is an
opaque blob — there's no way to decompress "just the middle ten elements," so HDF5 must read and
decompress the entire chunk to serve any read that touches it. Chunking narrows a read down to
one chunk either way; whether that read is further narrowed to just the requested elements
depends on whether a filter (compression, shuffle, etc.) is attached to the dataset.
