# From button click to `.h5`: full call chain and PV trace

Traced end to end against a real example file: `~/save/slac-wire/hdf/OTF_WS28144_20260716_124144.h5`
(wire `WS28144`, area `L3`, buffer number `5`, scan mode `otf`). Every code reference below was read
directly from `~/src/slaclab/slacwire`, `~/src/slaclab/slac-measurements`, `~/src/slaclab/slac-devices`,
and `~/src/moellep/slac-timing` — not inferred from memory. PV name prefixes (`WIRE:LI28:144`,
`PMT:LI29:150`, `PMT:LTUH:756`, `PMT:LTUH:820`, `BPMS:LI27:201`, ...) were resolved via `slac_db`'s
per-area YAML device tables, which happen to ship as bundled package data in this environment — that
resolution is a database lookup, not a computable naming formula (see the "PV name resolution" note
at the end).

## 1. Button click (PyDM GUI)

`slacwire/ws_gui.py`, `WireScanSuiteGUI.start_scan_callback()` — wired to `self.ui.startButton.clicked`
(`init_ui()`, line 164). It:

- Disables the button, sets `self.suite.save = True` (this is what makes the eventual `save_to_h5()`
  call actually happen).
- Spins up a `WireScanSuiteThread` (a `QThread`, so the Qt event loop stays responsive) that calls
  `self.suite.run_single(wire=wire_name, scan_mode="otf", jitter_correction=..., charge_normalization=...)`
  — `scan_mode="otf"` is hardcoded here, matching the `OTF_` filename prefix.

`update_parameters()` separately binds live-display widgets to the wire's control PVs for the UI itself
(not scan-critical), e.g. `WIRE:LI28:144:MOTR.RBV` (position readback), `WIRE:LI28:144:SCANSTAT`.

## 2. `WireScanSuite.run_single()` (`slacwire/suite/_run.py:80`)

Resolves the wire device, reads its per-wire config (`get_wire_config()` — local config, not EPICS),
then calls:

```python
self._run_device_scan(
    device=device,
    method="otf",
    scan_fn=lambda dev, **kw: self._measure(dev, scan_mode="otf", ...),
    rms_detector=rms_detector,
    file_prefix="OTF",
)
```

## 3. `_run_device_scan()` (`_run.py:159+`)

Builds `run_stamp = scan_started.strftime("%Y%m%d_%H%M%S")` (the timestamp in the filename), then
calls `data = scan_fn(device, rms_detector=selected_detector)` — this is step 4.

## 4. `_measure()` → `WireBeamProfileMeasurement.measure()` (`slac_measurements/wires/scan.py:25`)

The real orchestrator. Two distinct sub-steps:

### 4a. Collection — `create_wire_collection(scan_mode="otf", ...)` picks
`OTFWireMeasurementCollection` (`slac_measurements/wires/collection/otf.py`), then
`collection.measure()` runs `BaseWireMeasurementCollection.measure()`
(`slac_measurements/wires/collection/base.py:53`): reserve a buffer → run the physical scan →
read all HST buffer PVs → release the buffer (`finally:`). Returns the raw
`WireMeasurementCollectionResult`.

**Reserve the buffer** (`EventDefinition._reserve()`, `slac_timing/event_definition.py:45`,
`_PREFIX = "EDEF:SYS0"`):

```
put   IOC:IN20:EV01:EDEFNAME        <- reservation request ("SLAC Tools")
get   EDEF:SYS0:1:NAME ... EDEF:SYS0:11:NAME   <- polled until one matches the request
put   EDEF:SYS0:5:USERNAME          <- claims slot 5 once found
```

Then `_configure()`:

```
put   EDEF:SYS0:5:AVGCNT   = 1
put   EDEF:SYS0:5:MEASCNT  = 1453
put   EDEF:SYS0:5:BEAMCODE = 2        (CU_SXR, per metadata.beampath)
```

**Run the physical scan** (`OTFWireMeasurementCollection._run_collection_scan()`):

```
put/get  WIRE:LI28:144:MOTR_INIT, :MOTR_INIT_STS   <- initialize_otf_with_retry()
put      EDEF:SYS0:5:CTRL = 1                       <- buffer.start()
get      EDEF:SYS0:5:CNT, EDEF:SYS0:5:CNTMAX         <- polled every 0.1s in buffer.is_complete()
get      WIRE:LI28:144:MOTR.RBV                      <- logged every ~1s while waiting
```

This phase is bound by real beam/motor physics, not PV latency — the code's own timeout is
`max(n_points/beam_rate * 1.25, n_points/beam_rate + 10)`, ~15-22s for `n_measurements=1453` @ ~120 Hz.

**Read the buffer** (`_get_data_from_buffer()`, `base.py:214` — sequential, no threading):

```
WIRE:LI28:144:POSNHST5          (position_buffer — h5 key "WS28144")
PMT:LI29:150:QDCRAWHST5         (qdcraw_buffer   — h5 key "PMT29150")
PMT:LTUH:756:QDCRAWHST5         (h5 key "PMT756")
PMT:LTUH:820:QDCRAWHST5         (h5 key "PMT820")
BPMS:LI27:201:XHST5, :YHST5     (bpm_buffer      — h5 key "BPM27201")
... (15 more BPMs, same pattern: BPMS:LI27:301, BPMS:LI27:401, ... BPMS:LI28:901)
BPMS:<every area BPM>:TMITHST5  (aggregated into h5 key "TMITLOSS" -- no single PV; see note below)
```

Each read is `retries=3, retry_delay=3.0` — a single flaky PV can add ~9-10s in the tail.

**Release** (`finally:` block, `base.py:87`):

```
put   EDEF:SYS0:5:FREE = 1
```

### 4b. Analysis — `WireMeasurementAnalysis(collection_result=..., fitting_method="gaussian").analyze(...)`

Computes `profiles`, `fit_result`, `rms_sizes` via a Gaussian curve fit
(`slac_measurements/fitting/gaussian.py`) — confirmed numerically to reproduce this file's saved
`fit_result` exactly, given only `/collection_result/raw_data` + `/collection_result/metadata`.
**No PV access at all** — pure numpy/scipy on the arrays already read in 4a. Returns the combined
`WireMeasurementAnalysisResult`.

## 5. Back in `_run_device_scan()`: the write

```python
path = self.outdir / f"{file_prefix}_{device.name}_{run_stamp}.h5"
data.save_to_h5(path)
```

`save_to_h5()` is `WireMeasurementAnalysisResult.save_to_h5()`
(`slac_measurements/wires/analysis/results.py:120`). `path` resolves to exactly
`OTF_WS28144_20260716_124144.h5`. No PVs — file I/O only.

## 6. Back in the GUI thread

`WireScanSuiteThread.run()` retrieves the result via `self.suite.latest_run(wire_name)` and emits
`scan_complete`, which `on_scan_complete()` uses to re-enable the button and update plots — this
happens *after* the file is already written to disk. No new PV access.

## Notes

- **Timing**: the real gap between this file's `run_stamp` (filename, scan start) and
  `metadata.timestamp` (collection finish) is ~44s — longer than the ~15-22s scan-motion estimate
  alone, because that gap also covers phase 4b (the analysis/fit step), which isn't PV-bound but
  does take real wall time.
- **PV name resolution is a database lookup, not a formula.** `slac_devices/reader.py`'s
  `create_wire()`/`create_bpm()`/`create_pmt()` call `slac_db.get_device(area, device_type, name)`,
  which loads `{area}.yaml` from `slac_db/package_data/yaml/` and does a dict lookup keyed by short
  device name (`WS28144`, `BPM27201`, ...) — there's no code-computable short-name -> PV-prefix rule.
  Those YAML files happen to be bundled in this environment, which is why the full chain above could
  be walked concretely; that's not guaranteed to hold in every environment, and a revised device
  database would silently change these mappings.
- **`TMITLOSS` has no single corresponding PV.** `slac_measurements/tmit_loss.py`'s
  `TMITLoss.measure()` reads `:TMITHST5` from every BPM in the beampath and computes a normalized
  upstream/downstream loss ratio across all of them (median-normalize each BPM row, average the
  upstream group, divide the rest by that). The h5's `TMITLOSS` array is this derived quantity, not
  one PV's buffered value.
- The buffer mechanism is EDEF (`EDEF:SYS0:<n>:...`, numbers 1-11), not BSA (`BSA:SYS0:1:<n>:...`,
  numbers 21-64) — determined by `slac_timing.factory.create_buffer()` routing on
  `beampath.startswith("CU_")` vs `"SC_"`; this file's `metadata.beampath = 'CU_SXR'` confirms it
  directly (area `L3`, device names `LI27`/`LI28`/`LI29`/`LTUH` are all copper-linac).
- **BPM x/y and wire-position reads are pure passthroughs**, confirmed directly in
  `slac_devices/{bpm,wire,pmt}.py`: `x_buffer()`/`y_buffer()`/`position_buffer()`/`qdcraw_buffer()`
  are all one-line `return buffer.get(f"{control_name}:{suffix}", **kwargs)` calls, no
  scaling/offset/unit conversion, called with `retries=3, retry_delay=3.0` and no `pad=True` — so
  each raw_data array is exactly what its PV returned (the only possible modification, a
  length-truncation to `n_measurements` inside `Buffer._fetch_single()`, is a no-op when the
  buffer fills completely, as it did here). `TMITLoss._get_bpm_data()` is the one exception: it
  reads with `pad=True` (NaN-fills unreachable BPMs rather than failing), and the wire's own
  `raw_data/WS28144` stays in raw stage coordinates — the `install_angle`-based stage→beam
  transform happens later, only during analysis (`coordinates.stage_to_beam()`).

## PV names + actual returned values

Real values pulled directly from this file's own `/collection_result/raw_data` (h5py summary:
length, first, last, min, max). Everything not saved anywhere in the file is marked `unknown`
(with array length appended when the PV is buffer-shaped, since that length is independently
knowable even when the content isn't).

### 1. Button click (GUI display binding)

| PV | Value |
|---|---|
| `WIRE:LI28:144:MOTR.RBV` | unknown |
| `WIRE:LI28:144:SCANSTAT` | unknown |

### 4a. Reserve the buffer

| PV | Value |
|---|---|
| `IOC:IN20:EV01:EDEFNAME` (put) | `"SLAC Tools"` (the `_BUFFER_NAME` constant) |
| `EDEF:SYS0:1:NAME` ... `:11:NAME` (polled) | unknown, except slot `5` which matches `"SLAC Tools"` |
| `EDEF:SYS0:5:USERNAME` (put) | unknown (OS username of whoever ran the GUI) |
| `EDEF:SYS0:5:AVGCNT` (put) | unknown (likely `1`, `Buffer`'s pydantic default — not persisted in this file) |
| `EDEF:SYS0:5:MEASCNT` (put) | `1453` (matches every raw_data array's length exactly) |
| `EDEF:SYS0:5:BEAMCODE` (put) | `2` (`CU_SXR`, per `metadata.beampath` and `BEAMCODE_MAP`) |

### 4a. Run the physical scan

| PV | Value |
|---|---|
| `WIRE:LI28:144:MOTR_INIT` (put), `:MOTR_INIT_STS` (get) | unknown |
| `EDEF:SYS0:5:CTRL` (put) | unknown (a `1`, but not recorded) |
| `EDEF:SYS0:5:CNT`, `:CNTMAX` (polled repeatedly) | unknown during polling; at completion, `1453` / `1453` (inferred — the scan completed and returned exactly `MEASCNT`-length data with no `BufferSizeError`) |
| `WIRE:LI28:144:MOTR.RBV` (logged ~every 1s) | unknown, not a fixed-length buffer read |

### 4a. Read the buffer — values actually saved in this file

| PV | Value |
|---|---|
| `WIRE:LI28:144:POSNHST5` | array, `len=1453, first=8324.0, last=14616.0, min=8324.0, max=46469.0` |
| `PMT:LI29:150:QDCRAWHST5` | array, `len=1453, first=197.0, last=199.0, min=191.0, max=1006.0` |
| `PMT:LTUH:756:QDCRAWHST5` | array, `len=1453, first=869.0, last=868.0, min=863.0, max=873.0` |
| `PMT:LTUH:820:QDCRAWHST5` | array, `len=1453, first=360.0, last=363.0, min=275.0, max=431.0` |
| `BPMS:LI27:201:XHST5` | array, `len=1453, first=0.3063, last=0.3030, min=0.2608, max=0.4483` |
| `BPMS:LI27:201:YHST5` | array, `len=1453, first=-0.3872, last=-0.3878, min=-0.5175, max=-0.3584` |
| (15 more BPMs, same shape) | unknown, `len=1453` each — not individually pulled above |
| every area BPM's `:TMITHST5` (feeding TMITLOSS; likely a larger/different BPM set than the 16 above) | unknown, `len=1453` each |

`raw_data/TMITLOSS` itself — a *derived* value, not a PV:

| Quantity | Value |
|---|---|
| `(mean_upstream - mean_downstream) * 100` | array, `len=1453, first=-0.1598, last=-0.2203, min=-0.2975, max=10.0746` |

### 4a. Release

| PV | Value |
|---|---|
| `EDEF:SYS0:5:FREE` (put) | unknown (a `1`, but not recorded) |

### 4b/5/6. Analysis, save, GUI completion

No PV access in any of these steps.

## Does `rms_sizes` use `TMITLOSS`? What if it had?

`rms_sizes` only pulls the fit `sigma` for the one detector named by `rms_detector` (defaults to
`metadata.default_detector`) — both are `PMT29150` for this file (`analysis.py`'s `_get_rms_sizes()`:
`x_rms = fit_result["x"].detectors[selected_detector].sigma`, same for `y`). `TMITLOSS` goes through
the exact same fit as every other detector (it's in `metadata.detectors`, and
`/analysis/fit_result/{x,y,u}/TMITLOSS` all exist with their own fitted params) — it's just never
selected for `rms_sizes` in this particular scan.

Comparing the two detectors' actual fit results, both already stored in the file:

| | x_rms | y_rms |
|---|---|---|
| **Actual `rms_sizes`** (`PMT29150`) | `5774.26` | `42.21` |
| **If `TMITLOSS` instead** | `135.05` | `77.63` |
| ratio (TMITLOSS / PMT29150) | `0.023×` (~43× smaller) | `1.84×` (~2× larger) |

The x-plane difference is explained by the fit amplitudes, not noise: `PMT29150`'s x-fit has
`amplitude = 0.0` — a degenerate fit with no real signal to constrain it, so its `5774.26` isn't a
meaningful beam size. `TMITLOSS`'s x-fit has `amplitude = 5.73`, a real signal, making its `135.05`
the more physically plausible x measurement. In y it's the reverse: `PMT29150`'s y-fit has a strong
amplitude (`780.77`) vs. `TMITLOSS`'s weak one (`10.07`), so `PMT29150`'s `42.21` is likely the more
trustworthy y measurement there. Net: for this scan, no single detector gives a trustworthy result
in both planes — `rms_sizes` as actually recorded is a poor x measurement specifically, because of
which detector `rms_detector` happened to be.
