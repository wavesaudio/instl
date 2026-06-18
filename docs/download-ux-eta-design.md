# Design: Reliable download progress + ETA UX (instl ↔ Waves Central)

Status: **Draft for review** · Author: (drafted with Claude) · Date: 2026-06-17
Branch context: `instl-modernization` (instl), integration branch `download-enhancements`; consumer = Waves Central.

This doc covers the four agreed workstreams:

1. **Smoothed throughput / live ETA**
2. **Post-download phase honesty** (no more "stuck at 99%")
3. **Byte-based unified progress** (one byte-true bar across download + install)
4. **Harden the data contract** (structured `DOWNLOAD_EVENT` primary; regex legacy-only)

It is grounded in the current code on both sides. File:line references are to the
state of the repos on the date above.

---

## 1. Current state (what actually happens today)

### 1.1 The pipeline

`plan → emit pybatch .py → run it`. The UX is driven entirely by what the running
script logs to the `--log` buffer file, which Central tails via `chokidar` (100 ms
poll) — `Central …/shell/processes/shellInstlProcess.tsx:81-86`.

Three lifecycle stages:

- **Preparing** — resolve install graph, fetch info-map, mark need-download, compute
  denominators `__NUM_FILES_TO_DOWNLOAD__` / `__NUM_BYTES_TO_DOWNLOAD__`
  (`pyinstl/instlInstanceSync_url.py:303-305`; query `svnTree/svnTable.py:1001-1013`),
  then emit `session_state="downloading"` with `filesPlanned`/`bytesPlanned`
  (`pybatch/info_mapBatchCommands.py:617-688`).
- **Downloading** — curl (`--parallel --progress-bar`); instl parses curl's progress
  line ~1/s and re-emits a normalized text line plus structured events
  (`pybatch/subprocessBatchCommands.py:862-907`).
- **Post-download** — checksum-verify (`pybatch/info_mapBatchCommands.py:358-490`),
  chown/chmod, copy/`Unwtar` (`pybatch/wtarBatchCommands.py:171-293`), permissions,
  pre/post actions (`pyinstl/client/_actions.py:16-48`), rewrite `require.yaml`.

### 1.2 Two parallel data channels to Central

- **Legacy text** — `Progress N of M; Downloaded 45 of 24469 files, Downloaded 512M of 19.79G, Speed 10.5M`
  parsed by regex (`Central …/progress/shellInstlProcessProgressHandler.tsx:40-41`).
- **Structured** — `DOWNLOAD_EVENT {json}` envelopes: `sessionState`, `fileState`,
  `retryDecision`, `capability`, `sessionSummary` (`pyinstl/downloadEvents.py`;
  consumer `Central …/progress/downloadEventParser.tsx`, `downloadEventTypes.tsx`).
  Gated by `capability.centralUxEnabled` (kill switch) + cohort.

### 1.3 Root causes of unreliable UX

**A. ETA & live speed are blank during the whole download.**
`computeEta` reads throughput and received-bytes *only* from the final summary:

```
throughput = input.summary?.summary?.observedThroughputBytesPerSecond   // downloadMetaLine.tsx:67
received   = input.summary?.summary?.totals?.bytesReceived              // :69
```

`sessionSummary` is emitted once, at session end (`pyinstl/downloadObservability.py:300-316`,
`end_session`). `session_state` events carry `filesPlanned`/`bytesPlanned` but **no
`bytesReceived` and no throughput** (`pyinstl/downloadEvents.py:240-265`). So until the
download is over there is nothing for `computeEta` to use → no ETA, no live speed in the
structured UX. The cumulative bytes/speed exist *inside the curl loop*
(`subprocessBatchCommands.py:895-906`) but are only written to the legacy text line, not
to the structured channel.

**B. ETA only models the download, never the install tail.**
Every post-download command has `own_progress_count = 1` regardless of work
(`pybatch/baseClasses.py:257-261`); an `Unwtar` of a 10 GB archive counts the same as
verifying one tiny file (`pybatch/wtarBatchCommands.py:174`). Central hard-caps the bar
at 99 % (`shellInstlProcessProgressHandler.tsx:234`) to hide the end-of-download dead
zone, but the ETA still decays to ~0 while unpack/copy run for minutes → the classic
"stuck at 99 %".

**C. Speed is instantaneous and unsmoothed.** The legacy line passes curl's raw
per-tick `Speed` through (`subprocessBatchCommands.py:906`); the only smoothed figure
(`observedThroughputBytesPerSecond = total_bytes / wall_seconds`,
`downloadObservability.py:266-273`) is cumulative and end-only.

**D. Legacy regex is a latent outage.** Any reword of the `Progress … of …` line
silently freezes the bar (`shellInstlProcessProgressHandler.tsx:40-41`); phase/detail
labels are hardcoded English patterns (`instlProgressPatternMap.tsx`).

### 1.4 What already exists and works (build on, don't rebuild)

- `DownloadObservability` sampler with cumulative throughput + per-host totals,
  `set_plan`, `record_outcome`, `snapshot()` (`pyinstl/downloadObservability.py`).
- Structured event envelope + emitters, schema-versioned
  (`pyinstl/downloadEvents.py:410-427`).
- Central structured consumer with `downloadStateBus` snapshot store, state-pill
  mapping, and a **weighted multi-phase bar** (`phasesFactors`, must sum to 1.0;
  `shellInstlProcessProgressHandler.tsx:97-106,348-358`).
- The monotonic byte/file high-water accounting across pause/resume
  (`subprocessBatchCommands.py:770-918`).

---

## 2. Goals & non-goals

**Goals**
- A live, stable ETA visible throughout the download.
- A bar that keeps moving (and an ETA that stays meaningful) through verify + install.
- Byte-true progress as the single source of truth, files as a secondary readout.
- Structured channel as the contract of record; regex demoted to old-engine fallback.

**Non-goals**
- No change to curl invocation, resume/retry logic, or the download algorithm.
- No change to the install *semantics* (what gets copied/unpacked).
- No new IPC mechanism — keep using the `--log` buffer + `DOWNLOAD_EVENT` lines.

---

## 3. Proposed data contract changes

All additive. Bump `DOWNLOAD_EVENT_SCHEMA_VERSION`? **No** — additive fields on existing
event types are forward-compatible (Central's parser tolerates unknown fields and
`asKnownDownloadEvent` ignores unknown types). Keep version, document new optional
fields. Central treats every new field as optional with a fallback.

### 3.1 Add live throughput/progress to `session_state` (Workstream 1)

Extend `make_session_state_event` (`pyinstl/downloadEvents.py:240-265`) with optional:

| field | meaning |
|---|---|
| `bytesReceived` | cumulative monotonic bytes this session |
| `filesCompleted` | cumulative monotonic files this session |
| `observedThroughputBytesPerSecond` | smoothed (EMA) throughput, see §4.1 |
| `phase` | one of `download` \| `verify` \| `install` (for the unified bar, §4.3) |
| `phaseBytesPlanned`, `phaseBytesDone` | per-phase byte budget (§4.3) |

Emit a `session_state` **progress tick** from inside the curl loop on a throttle
(≥1 s, on meaningful delta), reusing the cumulative figures already computed at
`subprocessBatchCommands.py:895-906`.

### 3.2 New `phase_state` (or reuse `session_state`) for verify/install (Workstream 2)

Prefer **reusing `session_state`** with the existing state vocabulary already declared
in `downloadEventTypes.tsx` (`verifying_downloads`, `ready_to_copy`, `copying`,
`completed`). Emit transitions around the post-download sections (§4.2) and, where cheap,
periodic ticks carrying `phaseBytesDone/phaseBytesPlanned`.

---

## 4. Workstream detail

### Workstream 1 — Smoothed throughput / live ETA

**instl side**
- Add an EMA throughput accumulator to `CurlWithInternalParallel` (or to the active
  `DownloadObservability`): `ema = α·inst + (1-α)·ema`, α ≈ 0.2, seeded with the first
  cumulative average. Computing instantaneous = Δbytes/Δwall between ticks (we already
  have `cumulative_bytes` and can read a monotonic clock — note `Date`/`monotonic`
  usage already present via `downloadObservability._wall_clock`).
- On each throttled tick (≥1 s), call `emit_session_state(state="downloading",
  bytes_received=cumulative_bytes, files_completed=downloaded_files,
  observed_throughput_bytes_per_second=ema, …)`. Seam: inside the `if match:` block at
  `subprocessBatchCommands.py:875-907`, guarded by a throttle timestamp.
- Keep the legacy text line unchanged for old Central.

**Central side**
- `computeEta` (`downloadMetaLine.tsx:66-76`): prefer live `sessionState` fields, fall
  back to `summary`:
  ```
  throughput = sessionState?.observedThroughputBytesPerSecond ?? summary?.…
  received   = sessionState?.bytesReceived               ?? summary?.…?.bytesReceived
  planned    = sessionState?.bytesPlanned                ?? summary?.…?.bytesPlanned
  ```
- Same fallback for the speed string (`downloadMetaLine.tsx:93`).
- Optionally apply a short client-side floor/clamp so a transient stall doesn't spike
  ETA to hours (cap displayed ETA growth rate).

**Result:** ETA + speed are populated from the first tick (~1 s in) and are stable
because the EMA is server-computed and Central uses cumulative received bytes.

### Workstream 2 — Post-download phase honesty

**instl side** — emit `session_state` transitions around the existing sections:
- `verifying_downloads` before `CheckDownloadFolderChecksum`
  (`instlInstanceSync_url.py:343`).
- `ready_to_copy` → `copying` entering `create_copy_instructions`
  (`instlClientCopy.py:69-139`).
- `completed` after `require.yaml` rewrite.
These map to Central's existing visible states (`downloadVisibleState.tsx`) → the pill
shows "Verifying" / "Installing" and the bar switches to a determinate-or-animated mode
instead of freezing at 99 %.

**Optional within-phase progress** (bigger lift, do second):
- Byte-weight verify (we already iterate files with sizes in the checksum pass) and
  `Unwtar`/copy (`own_progress_count ∝ size`, or stream extraction progress). This makes
  the install phase's bar move, not just its label.

**Central side** — ensure the bar renders an animated/indeterminate style for
`verifying`/`installing` when no per-phase byte fraction is present, and a determinate
fraction when `phaseBytesDone/phaseBytesPlanned` arrive. The state→variant mapping
already exists (`downloadVisibleState.tsx:185-203`).

### Workstream 3 — Byte-based unified progress

Use Central's existing `phasesFactors` machinery
(`shellInstlProcessProgressHandler.tsx:97-106,348-358`) but feed it **byte fractions**,
not step counts:
- Define a top-level split, e.g. `download 0.7 / install 0.3` (tunable; could be derived
  from `bytesPlanned` vs an estimated uncompressed footprint — see Risk R3).
- Within the download phase, the bar fraction = `bytesReceived / bytesPlanned` (from
  Workstream 1 fields) rather than `currentStep/currentTotalSteps`.
- Within the install phase, fraction = `phaseBytesDone / phaseBytesPlanned` if available,
  else animated.
- Keep the 99 % cap only as a final guard, not as the primary mechanism to hide the tail.

This removes the file-count jumpiness (smaller-files-first + parallelism) by making the
displayed bar byte-true end to end; file counts remain in the meta line as a readout.

### Workstream 4 — Harden the data contract — ✅ IMPLEMENTED (docs + tests)

- **Document the contract** — ✅ `docs/download-events.md` is now the authoritative
  contract: transport, envelope, all 5 event types + field tables, the full state /
  file-state / failure-class vocabularies, the additive-evolution rule, and a §6 that
  states exactly what each consumer relies on.
- **Contract tests both sides** — ✅ instl `pyinstl/test/test_downloadEventsContract.py`
  pins the documented key sets (subset checks, so additions are allowed but
  removals/renames fail), the schema version, the W1 additive-field invariant, and the
  denylist. Central `…/shell/progress/downloadEventContract.test.tsx` pins the same from
  the consumer side: canonical lines parse into the documented typed fields (incl. W1
  live fields + the ETA-fallback summary fields), additive fields are tolerated, and a
  future `schemaVersion` is rejected.
- **Version discipline** — ✅ documented in `download-events.md` §5 and asserted by the
  instl contract test (`DOWNLOAD_EVENT_SCHEMA_VERSION == 1`); Central gates on
  `schemaVersion <= DOWNLOAD_EVENT_SCHEMA_VERSION` (`downloadEventParser.tsx`).
- **Don't delete the legacy line** — ✅ unchanged; still emitted for old Central builds
  and `instl-V9/V10`.

**NOT done (correctly deferred):** "make structured the *primary driver*, demote the
legacy regex to a fallback." Investigation found the **bar percentage is computed solely
from the legacy regex** — `handleDownloadEvent` only updates the bus/state pill/ETA, it
never notifies a progress %. So demoting the regex would *break the bar*. Making the
structured channel drive the bar % is the same work as the deferred W3 option (b)
(structured-driven, byte-true install bar); until that lands the legacy progress line
**must** keep driving the bar. This is documented in `download-events.md` §6.

---

## 5. Rollout & safety

- **Kill switch:** everything new rides behind `capability.centralUxEnabled` + cohort
  (`make_capability_event`, `pyinstl/downloadEvents.py:298-351`) — matches the existing
  POC gating (D-018 kill switch, D-022 re-gate-before-merge). Treatment cohort gets live
  ETA + phase honesty; control keeps today's behavior.
- **Instrumentation must never break sync:** all emits stay best-effort
  (`try/except → log.debug`), mirroring `_emit_download_started`
  (`info_mapBatchCommands.py:617-666`).
- **Back-compat:** legacy text line unchanged; additive event fields; Central fallbacks
  preserve old behavior when fields are absent.

---

## 6. Risks

- **R1 — throttle/IO volume.** Periodic `session_state` ticks add log lines. Mitigate
  with ≥1 s throttle + min-delta gate; reuse the existing 1/s curl cadence.
- **R2 — EMA tuning.** α too high = jittery, too low = laggy after a real speed change.
  Start α≈0.2; expose as a constant; validate against a recorded slow/fast trace.
- **R3 — install-phase byte budget unknown.** `bytesPlanned` is compressed/wtar size,
  not uncompressed footprint. For Workstream 3's `install` fraction, either (a) ship a
  fixed 0.7/0.3 split initially, or (b) sum uncompressed sizes from the info-map if
  available. Start with (a); refine later.
- **R4 — monotonicity across resume.** Live `bytesReceived` must use the existing
  high-water/baseline accounting (`subprocessBatchCommands.py:887-900,917`) so the ETA
  never jumps backward on retry/resume.
- **R5 — dual-driver flicker.** If both legacy regex and structured events update the bar
  (Workstream 4 not yet enforced), they can race. Enforce structured-primary first.

---

## 7. Suggested sequencing

1. **W1 (live ETA)** — ✅ **IMPLEMENTED** (instl-modernization branch). Added optional
   `bytesReceived`/`filesCompleted`/`observedThroughputBytesPerSecond` to
   `make_session_state_event` (`pyinstl/downloadEvents.py`); emit a throttled (≥1 s),
   EMA-smoothed (α=0.2) `session_state="downloading"` tick from the curl loop via
   `CurlWithInternalParallel._maybe_emit_progress_tick`
   (`pybatch/subprocessBatchCommands.py`), with the EMA persisting across pause/resume
   and the per-run sample baseline reset so a paused gap is never counted as slow
   transfer. Central: `ISessionStateEvent` gains the optional fields; `computeEta` and
   the meta-line speed/bytes/files prefer the live tick and fall back to the summary
   (`downloadMetaLine.tsx`). Tests: `test_downloadEvents.py` (field shape),
   `test_subprocessBatchCommands.py` (throttle/EMA + never-raises),
   `downloadMetaLine.test.tsx` (ETA source preference). Still behind the existing
   `centralUxEnabled` + cohort gating.
2. **W2 (phase honesty, labels-only)** — ✅ **IMPLEMENTED** (instl-modernization). Added a
   generic `ReportDownloadState(state, reason)` pybatch command + `_emit_download_state`
   helper (`pybatch/info_mapBatchCommands.py`, telemetry-gated like the started path),
   exported via `pybatch/__init__.py`. Inserted transitions: `verifying_downloads` before
   `CheckDownloadFolderChecksum` (`instlInstanceSync_url.py`), `copying` at copy start and
   `completed` after the require-file rewrite (`instlClientCopy.py`). **No Central change
   needed** — `downloadVisibleState.tsx` already maps `verifying_downloads`→"verifying",
   `copying`→"installing", and `completed`→terminal("none"). Tests in
   `test_downloadPromotion.py` (repr round-trip, emits-transition, never-raises). NOTE:
   this moves the phase *label*; the bar % itself still caps at 99 during verify/install
   until W3 makes it byte-true.
3. **W4 (contract hardening)** — make structured primary, document + contract test.
4. **W3 (byte-unified bar)** — ✅ **DOWNLOAD PORTION IMPLEMENTED** (Central-only). The
   download branch of `shellInstlProcessProgressHandler.tsx` now interpolates `currentStep`
   across its file-count step span (`downloadStartedStep .. +totalFiles`) by the **byte
   fraction** `bytesReceived/bytesPlanned` (parsed from the same line that already carries
   them; clamped [0,1]; falls back to file count if byte totals are missing). This removes
   the file-count jumpiness — the bar now moves smoothly and monotonically with bytes, in
   both legacy-text and structured modes, entirely within the existing `phasesFactors`
   bands (no call-site change). Tests updated/added in
   `shellInstlProcessProgressHandler.test.tsx` (byte-fraction formula + "advances by bytes
   when file count is unchanged"). **STILL DEFERRED (option b):** the install-phase byte
   budget — a determinate copy/unwtar bar and the download/install 0.7/0.3 `phasesFactors`
   split. That needs instl to emit per-phase byte progress during unwtar/copy
   (`wtarBatchCommands`/`copyBatchCommands`), a larger lift; until then the install tail
   shows the W2 phase label with the bar parked at the end of the download band.

5. **W3 option (b) — install-phase byte budget** — ✅ **VERIFY + COPY/UNWTAR DONE.**
   - *Verify:* instl emits `verifying_downloads` ticks with `phaseBytesDone`/`phaseBytesPlanned`
     from `CheckDownloadFolderChecksum`.
   - *Copy/unwtar:* a gated process-global accumulator (`pybatch/copyPhaseProgress.py`) is
     armed by the `copying` `ReportDownloadState` (its `phase_bytes_planned` is filled from
     `bytes_to_copy` after the copy loop, before serialization); the single copy funnel
     `RsyncClone.copy_file_to_file` and `Unwtar.unwtar_a_file` report their bytes, emitting
     throttled `copying` ticks. No-op outside an armed install copy phase.
   - *Central:* `applyStructuredPhaseProgress` advances the bar from where it stood toward
     99% by the phase fraction (monotonic, gated on `phaseBytesPlanned>0`, composes with the
     legacy path via `max`). State-agnostic, so it consumes both verify and copy ticks with
     no extra code.
   Verified: instl 366 pass; Central jest 44 pass; `tsc --noEmit` clean. **Caveat:** wtar
   byte estimates are approximate (compressed parts vs the `wtar_ratio`-estimated planned),
   so the copy fraction is approximate — fine for a progress bar, but worth live tuning.
   **Still future:** the full *structured-drives-bar* that would let the legacy regex be
   demoted (W4's "structured primary"). And the live licensed install needs the full Waves
   build (Products/Debug + `WavesLicenseEngine.bundle` + login + elevation helper), not
   reproducible from the instl + Central repos alone.

Each step is independently shippable and individually gated.

---

## 8. Test plan

- **instl unit:** event builders carry new fields (extend `test_downloadEvents.py`);
  EMA accumulator math; throttle gate; monotonic `bytesReceived` across simulated
  resume; emits are best-effort (no raise on failure).
- **Contract/round-trip:** instl emit → JSON fixture → assert Central parser
  (`downloadEventParser`/`downloadEventTypes`) reads the new fields with fallbacks.
- **Central unit:** `computeEta` prefers live `sessionState`, falls back to `summary`;
  ETA hidden while frozen; bar fraction byte-true; phase factors sum to 1.0.
- **Manual/e2e:** a real slow-network sync shows: ETA within ~1 s, stable under jitter,
  pill transitions Preparing→Downloading→Verifying→Installing→Done, no 99 % freeze.
