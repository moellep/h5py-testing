# h5py-testing

Standalone test harnesses for `h5py`/HDF5 behavior questions — things worth checking in isolation
against a small generated test file rather than reasoning about in the abstract.

## Tests

- [`partial-read/`](partial-read/) — checks that opening a file and reading a small value out of a
  `results` group (or slicing a few elements out of a large chunked `meta` dataset) doesn't pull
  the rest of the file into memory. Generates a test file with both, then compares two partial
  reads against a full read using RSS and `/proc/self/io` read-syscall counts.

Each test directory is self-contained (its own `common.py`/test-file generator, its own README)
and can be run independently. See [`docs/`](docs/) for committed reference run output.
