# Wire-scan HDF5 schema: current layout, annotated, plus a compatible extension

Structure only — names of every group/attribute/dataset, no values — verified fresh against
`~/save/slac-wire/hdf/OTF_WS28144_20260716_124144.h5` via `h5py.visititems()` (not from memory of
an earlier dump). Repeating patterns (`{profile}` = `x`/`y`/`u`, `{detector}` = `PMT29150`/`PMT756`/
`PMT820`/`TMITLOSS`, `{bpm}` = one of the 16 saved BPMs) are shown once with a placeholder rather
than listed 50+ times over — every placeholder actually repeats identically in the real file.

Every claim below traces to code already read directly in this conversation:
`slac_measurements/wires/analysis/results.py`'s `save_to_h5()`, `.../collection/results.py`'s
`_save_metadata()`/`_save_raw_data()`, `.../analysis/analysis.py`'s `analyze()`/`_fit_profile()`/
`_get_rms_sizes()`, and `.../tmit_loss.py`'s `TMITLoss.measure()`.

## Part 1 — current schema, annotated

Role legend: **RAW** input data · **FIT-IN** windowed data actually fit · **FIT-OUT** fit output ·
**RESULT** the final answer · **CONFIG** read by the fit/selection code · **CONTEXT** descriptive
only, not read by any fit/selection code traced this session.

```
/rms_sizes                                                    [dataset]  RESULT
    [x_rms, y_rms] = fit_result[x/y].detectors[rms_detector].sigma. rms_detector can be any
    fitted detector -- a PMT-type detector (PMT29150/756/820) or the BPM-derived TMITLOSS
    aggregate -- and the choice matters materially: in this file PMT29150 (the recorded
    rms_detector) gives a degenerate x-plane result (amplitude=0.0, sigma=5774.26), while
    TMITLOSS would have given a physically plausible one (sigma=135.05) -- see the comparison
    in slacwire-pv-trace.md.

/collection_result/
    metadata/                                                 [group]
        @active_profiles                                      [attr]     CONFIG
            which profiles (x/y/u) were scanned at all -- determines which fit_result/profiles
            subgroups exist below.
        @area                                                 [attr]     CONTEXT
        @beampath                                              [attr]     CONFIG
            resolves TMITLOSS's BPM set (which beampath areas get included) and EDEF-vs-BSA
            buffer routing; not read by the Gaussian fit itself.
        @buffer_number                                         [attr]     CONTEXT
            (identifies which EDEF slot's HST PVs were read; not used in fit math itself)
        @default_detector                                      [attr]     CONFIG
            fallback for rms_detector when not explicitly overridden.
        @install_angle                                         [attr]     CONFIG
            stage<->beam coordinate conversion in _fit_profile() -- the fitted "mean" depends
            on this.
        @rms_detector                                          [attr]     CONFIG
            directly determines which detector's sigma becomes /rms_sizes.
        @timestamp                                             [attr]     CONTEXT
        @wire_name                                             [attr]     CONTEXT
        detectors                                               [dataset]  CONFIG
            full list of detector names fit against every profile.
        scan_ranges/                                            [group]    CONTEXT
            @x_start, @x_end, @y_start, @y_end, @u_start, @u_end [attrs]
            (not read by _peak_window()/_fit_profile() -- the actual fit window is computed
            dynamically from the data, not from these)
    raw_data/                                                 [group]
        BPM{bpm}/                                              [group]    RAW
            x, y                                                [datasets]
            (feeds analysis/profiles/{x,y}/detectors/... only if a BPM ever appears as a
            fitted "detector" -- it doesn't in this file; these 16 BPMs are jitter-correction/
            profile-adjacent x/y reads, never routed into fit_result)
        PMT29150, PMT756, PMT820                                [datasets]  RAW
            feed analysis/profiles/{profile}/detectors/{same name}/values.
        TMITLOSS                                                [dataset]  RAW (derived)
            NOT a PV read -- TMITLoss.measure()'s (mean_upstream - mean_downstream) * 100
            across many BPMs (see Part 2, item 1). Treated exactly like a raw detector signal
            from here on: feeds analysis/profiles/*/detectors/TMITLOSS same as the PMTs.
        WS28144                                                 [dataset]  RAW
            the wire position buffer -- becomes the x-axis for every fit, in raw stage
            coordinates (install_angle conversion happens later, in analysis).

/analysis/
    profiles/{profile}/                                       [group]
        positions                                               [dataset]  FIT-IN
            windowed wire-position values for this profile (from raw_data/WS28144).
        profile_indices                                         [dataset]  FIT-IN
            which raw_data sample indices belong to this profile's scan window.
        detectors/{detector}/
            values                                              [dataset]  FIT-IN
                the detector signal actually handed to _fit_profile() for this profile.
            @label, @units                                      [attrs]    CONTEXT
    fit_result/{profile}/{detector}/                            [group]
        @amplitude                                              [attr]     FIT-OUT
            fit-quality diagnostic; amplitude=0.0 flags a degenerate fit (as found for
            PMT29150's x-plane in this exact file) -- not read by _get_rms_sizes() itself.
        @mean                                                   [attr]     FIT-OUT
            fitted centroid, converted back to stage coordinates; not used by rms_sizes.
        @sigma                                                  [attr]     FIT-OUT / RESULT input
            this is what _get_rms_sizes() reads for whichever detector is rms_detector.
        @offset                                                 [attr]     FIT-OUT
            fit shape parameter; diagnostic only.
        curve                                                   [dataset]  FIT-OUT (QA only)
            the fitted curve evaluated at `positions`, below -- for plotting/QA; nothing
            downstream reads it.
        positions                                               [dataset]  FIT-OUT (QA only)
            the (windowed) x-values `curve` was evaluated at.
```

## Part 2 — a compatible extension

Purely additive: new groups/attrs/datasets only. Nothing existing is renamed, moved, or removed,
so `load_from_h5()` and every other current reader keep working unmodified. Four additions, each
tied to a gap found and discussed earlier in this conversation:

### 1. `TMITLOSS`'s raw inputs

```
/collection_result/
    raw_data/
        tmitloss_bpms/{bpm_name}                                [dataset]  NEW
            one (n_measurements,) array per BPM TMITLoss._get_bpm_data() actually reads --
            every BPM across all of this scan's beampath's areas (13 areas for CU_SXR: GUN,
            L0, DL1, L1, BC1, L2, BC2, L3, CLTS, BSYS, LTUS, UNDS, DMPS) -- a larger, different
            set than the 16 BPMs already saved under raw_data/BPM{bpm}/x,y.
    metadata/
        @tmitloss_upstream_bpms                                 [attr]     NEW
        @tmitloss_downstream_bpms                                [attr]     NEW
            string lists -- beam_profile_device.metadata.tmitloss.upstream/.downstream
            *as used at this scan time*, not left as a live re-lookup (same archival-safety
            reasoning as item 3).
```
Together these make `TMITLOSS`'s `(mean_upstream - mean_downstream) * 100` computation fully
reproducible from the archive alone.

### 2. Scan config capture

```
/collection_result/metadata/
    @fitting_method                                             [attr]     NEW
        currently computed ("gaussian" by default) but never written -- confirmed absent from
        MeasurementMetadata's schema.
    @jitter_correction                                          [attr]     NEW
    @jitter_rms                                                 [attr]     NEW (nullable)
        both already real fields on WireMeasurementAnalysisResult that save_to_h5() simply
        never writes.
```
`charge_normalization`/`charge_toroid` are deliberately **not** included yet: traced this session
and confirmed they don't currently reach `slac_measurements` at all —
`WireBeamProfileMeasurement.measure()` doesn't accept them, so `slacwire`'s call site would raise
`TypeError` as currently written. Worth adding once that's actually wired up, not before.

### 3. MAD-X/device-name -> PV mapping

```
/pv_map/                                                        [group]    NEW
    @WS28144 = "WIRE:LI28:144:POSNHST5"
    @PMT29150 = "PMT:LI29:150:QDCRAWHST5"
    @PMT756 = "PMT:LTUH:756:QDCRAWHST5"
    @PMT820 = "PMT:LTUH:820:QDCRAWHST5"
    @BPM27201:x = "BPMS:LI27:201:XHST5"
    @BPM27201:y = "BPMS:LI27:201:YHST5"
    ... one attr per raw_data entry, including the new tmitloss_bpms/* ones
```
Full PV name, not just the `control_name` prefix — a reader needs no separate knowledge of the
`POSN`/`QDCRAW`/`X`/`Y`/`TMIT` suffix convention to interpret the archive. Closes exactly the gap
the earlier PV-name-inference investigation found: currently only resolvable via a live `slac_db`
YAML lookup, which could silently drift from what was true at scan time.

### 4. `rms_sizes`, computed both ways, each with a confidence factor

```
/rms_sizes_by_method/                                           [group]    NEW
    PMT29150/                                                    [group]
        @x_rms = 5774.26      @x_confidence = 0.0
        @y_rms = 42.21        @y_confidence = 780.77
    TMITLOSS/                                                    [group]
        @x_rms = 135.05       @x_confidence = 5.73
        @y_rms = 77.63        @y_confidence = 10.07
```
`x_rms`/`y_rms` are the same `sigma` values already in `fit_result`, pre-extracted for direct
side-by-side comparison without walking the nested `analysis/fit_result` tree. `x_confidence`/
`y_confidence` are literally the fit `amplitude` for that plane — no new statistic invented, just
an existing number surfaced under the name that matches what it already told us: `amplitude=0.0`
flags a degenerate, untrustworthy fit (`PMT29150`'s x-plane here); a real, nonzero amplitude means
the fit had actual signal to constrain it. At minimum the two detectors this conversation already
compared; naturally generalizes to every detector in `fit_result` later, since the values already
exist there.

### On size: compress `raw_data` (including the new `tmitloss_bpms`)

Item 1's `tmitloss_bpms` arrays (172 BPMs across all 13 `CU_SXR` areas, counted directly from
`slac_db`'s YAML device tables) are the dominant cost of this extension — roughly `1.9 MB` added
uncompressed, versus a few KB to at most ~100 KB for items 2-4 combined, taking the file from
~610 KB to an estimated ~2.5-2.7 MB.

Compression in HDF5 is a per-dataset filter, not a group-level setting, but since
`_save_raw_data()` already loops `for device_name, data in self.raw_data.items():
group.create_dataset(device_name, data=data)`, adding `compression="gzip"` to that one loop (and
the new `tmitloss_bpms` writer) applies it uniformly to the whole raw-data subtree in practice,
independent of `fit_result`/`profiles`/`metadata` elsewhere in the same file — no restructuring
needed. `gzip` (zlib) is h5py's built-in filter, no external plugin required; it does require
chunked rather than contiguous storage, which h5py sets automatically when `compression=` is
passed. A truly separate *file* is also an option (`h5py.ExternalLink`, reading transparently as
one logical tree) if the cold, rarely-re-read raw archive should be split out from a small, fast
"hot" analysis file entirely.

Measured (not assumed) `gzip` level-6 ratios on this file's actual arrays: `PMT29150` 10.01x,
`WS28144` (position) 3.46x, `BPM27201/x` 2.14x, `BPM27201/y` 2.17x, `TMITLOSS` (already-derived,
higher-entropy) only 1.07x. The new `tmitloss_bpms` arrays are raw `:TMIT` reads — architecturally
the same signal category as the measured `:X`/`:Y` BPM data, not the smoother position/PMT
signals — so ~2.1-2.2x is the realistic expectation, not the PMT outlier. Applying that to the
~1.9 MB of new raw data brings it down to roughly ~870-900 KB, for an extended-file total of
roughly ~1.5-1.6 MB (~2.5x the current file) instead of ~2.5-2.7 MB (~4.3x) uncompressed.
