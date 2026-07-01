# Download Enhancements POC — Change Defense

**Audience:** Shai Shasag (instl author) · Vitaly (Central maintainer)
**Branches:** instl `instl-modernization` (base `afef589a`) · Central `feature/V17.0.10---POC-Download-Enhancements` (base `1a2291c4`, off `main`)
**Date:** 2026-06

## How to read this / honesty statement

Every change below is listed with: **what** changed, **why** it's an improvement, **why it's safe** (nothing necessary was removed/broken), **macOS/Windows** correctness, and **verification status**.

Verification truth-in-advertising:
- **macOS:** verified live (full Central install end-to-end) and via the unit/characterization suites.
- **Windows:** **reasoned from code, not yet run.** Where a Windows behavior is only argued from the source, it says so. A Windows smoke-test checklist is in §E — nothing here claims "tested on Windows."

Scope completeness (verified against git history):
- **instl:** covers the **entire** POC from the first commit `95709186` "Resuming Dowload" (2026-05-18) — master contains no `download*` modules, so the whole feature is on-branch and captured — plus the modernization refactor.
- **Central:** covers the **entire** POC from the first commit `4502a25`/`c2919ec` (2026-05-27/28) through HEAD — all ~20 POC commits and ~50 files, audited subsystem-by-subsystem against the pre-POC baseline `6e67472f`. (An earlier draft of this doc only covered the last 4 commits; this version is complete.)

I also **proactively concede** a short list of real caveats in §D. None is a known break; they are the honest edges, raised so they don't get "found."

---

## TL;DR safety matrix

| Area | Default | Changes existing behavior? | Fails safe? | Windows verdict (from code) |
|---|---|---|---|---|
| Verify perf (sidecar removal) | n/a | Yes — drops dead per-file writes | n/a | Safe — same syscalls, fewer |
| Parallel verify + log throttle | parallel **off** | Counter identical; logs throttled | Yes (serial fallback) | Safe |
| curl resilience (retries/offline/http2/continue-at) | on (flag-gated bits) | Yes — more retries, auto-resume leftover `.part` | Yes | Safe; needs curl ≥7.71 on Win |
| Resume sidecars + temp→promote | resume **off** | Only when resume on | Yes (writes swallowed) | Safe by construction (same-volume) |
| Control channel (pause/resume) | inert w/o Central | No, unless Central drives stdin | Yes (best-effort) | **Safe — blocking stdin read, no `select()`** |
| Retry matrix + failure class | **ON** | **Yes — redownload is now per-file bounded-retry** | Yes (bounded, gate preserved) | Safe |
| Adaptive concurrency | **off** | No (provably inert) | Yes | Safe |
| Cohort | control | No (telemetry label only) | Yes | Safe |
| Structured events | telemetry **on** | Additive log lines only | Yes (all swallowed) | Safe |
| Modernization (decomp/hygiene/accessors) | n/a | Behavior-identical (+3 bug fixes) | n/a | Safe; nothing Win dropped |
| Central event ingestion | — | **Additive, front-gated**; legacy regex intact | Yes (parse fails → null) | CRLF handled; **split-line drop untested** |
| Central control channel (stdin) | inert w/o Central | New `sendCommand` — **all 7 implementors updated** | Yes (best-effort) | Safe (LF + instl `.strip()`) |
| Central offline detect + hold | hold gated on capability | Legacy keeps fail-on-offline | Yes | Safe; **no max-hold ceiling** |
| Central failure-recovery | UX-gated (**fixed**) | Msg-level additive; dialog buttons now UX-gated + retryable-aware | Legacy → legacy footer | Locale-dependent string match |
| Central dialog + shared controls | UI fallback when state "none" | Shared ProgressBar additive (non-regressing) | — | `toLocaleString` cosmetic only |

---

# Part A — instl (for Shai)

## A1. Verify perf: stop writing per-file resume sidecars in the checksum pass *(this session)*

- **What:** `CheckDownloadFolderChecksum.__call__` no longer writes a resume sidecar (VERIFYING / VERIFIED / ALREADY_VALID) per file.
- **Why:** Timing instrumentation localized **337.8s of a 343.8s verify loop (98%)** to `_save_resume_sidecar` — each verified file did a JSON read-back + atomic fsync write, ~2 calls/file (~49k filesystem ops over 24k files). Live verify dropped **~4m49s → ~12s** (~24×); residual is just SHA-1 hashing.
- **Why it's safe (the crux):** the verify-time `transfer_state` is **written but never read**. The only consumer, `resume_decision_for_download_item` (`downloadState.py:774-823`), reads only `record.source` (etag/last-modified/signed-url) and on-disk **partial-temp existence** — confirmed line-by-line, no read of `record.transfer.state` anywhere. Recovery after an interrupted verify is driven by `mark_need_download` → `need_to_download_file` (on-disk checksum/size truth, `misc_utils.py:366`), independent of any sidecar. Bad/missing files **still** get a sidecar via the retry path (`_emit_retry_decision` → `_save_resume_sidecar_with_retry_count`).
- **macOS/Windows:** identical on both — this only removes I/O. No platform surface.
- **Verified:** live macOS install (12s); 4 tests updated to the corrected contract; full `pyinstl`+`pybatch` suites green (394 passed).

## A2. Parallel verify hashing + throttled per-file logging

- **What:** verify hashes via `ThreadPoolExecutor` (gated `DOWNLOAD_PARALLEL_VERIFY`, **default off**, serial fallback on any pool error); per-file progress **log lines** throttled to ~4/sec while the **progress counter still advances every file** (Central's "of N" stays exact).
- **Why:** per-file log emission, not the hashing, was a large fraction of the old verify cost; parallel hashing removes the rest. Workers are read-only (no `config_vars`/progress-stack mutation), preserving serial semantics.
- **Why it's safe:** default-off keeps the serial path; the fallback "best-effort parallelism must never break a sync" is explicit. Counter semantics unchanged.
- **macOS/Windows:** `ThreadPoolExecutor` and `hashlib` behave identically; no platform surface.
- **Verified:** `test_parallelVerify.py` (serial==parallel outcome equality, pool-failure fallback, single-item serial).

## A3. curl resilience: retries, offline grace, HTTP/2, auto-resume, ordering

- **What (in `curlHelper.py`):** `CURL_RETRIES` default **2→5**; add `retry-connrefused` + `retry-max-time` (90s); `retry-all-errors` (gated `CURL_RETRY_ALL_ERRORS`, needs curl ≥7.71); `http2` (gated `DOWNLOAD_CURL_HTTP2`); every fresh transfer writes `continue-at = -` (auto-resume a leftover `.part`); `url_sorter` now **largest-first** (better parallel makespan); exit-33 restart-from-zero fallback config wired but only generated when resume entries exist.
- **Why:** survive a brief network outage instead of failing on a single connect-timeout; multiplex over HTTP/2; resume rather than re-fetch; shorter wall-clock via makespan ordering.
- **Why it's safe:** with resume off (default) there are no per-transfer resume sections and no exit-33 fallback files; the original single-batch config path is preserved. Header values are quoted via curl **config-file** escaping (`\`→`\\`, `"`→`\"`) and CR/LF in headers is rejected.
- **macOS/Windows:** **the "shlex is POSIX-only" concern does not apply** — args go into a curl *config file*, not a shell command line, so there is no shell quoting. Windows `fix_path` / `GetShortPathName` (8.3 shortname) handling is **untouched** and the new `output_path` routes through it. **Windows caveat:** the bundled Windows curl must be **≥7.71** for `retry-all-errors` (else set `CURL_RETRY_ALL_ERRORS=no`) and HTTP/2-capable for `http2` (else it silently falls back to 1.1).
- **Verified:** macOS live (download 3m17s clean). **`continue-at = -` and the Windows curl version are the headline Windows smoke-test items.**

## A4. Resume sidecars + temp→promote model (`downloadState.py`)

- **What:** downloads land in a content-addressed temp `<final>.instl-<file_id>.part`; after checksum verify, `promote_verified_temp_file` does `os.replace(temp, final)`. Per-file JSON sidecars (under `bookkeeping/download-state/`) capture source metadata + received bytes for byte-range resume. Gated `DOWNLOAD_RESUME_ENABLED` (**default off**).
- **Why:** enables true resume of an interrupted transfer and an atomic temp→final swap (no half-written final files).
- **Why it's safe:** resume default-off → `resume_decision` returns early, behavior unchanged. All sidecar writes are best-effort (`update_session_state` swallows everything). Atomic writes use a same-directory temp + fsync (OSError swallowed) + `os.replace`.
- **macOS/Windows:** `os.replace` is the **correct** choice over `os.rename` (it atomically replaces an existing destination on Windows; `os.rename` would fail). The temp is a **sibling of the final file by construction**, so promotion is **always same-volume** — no Windows cross-device `os.replace` failure. **Honest edge:** `promote_temp_file` has no *explicit* same-volume guard, so a future caller passing a cross-drive temp path would hit a hard `[WinError 17]`; not reachable today. Also, replacing a destination that another process holds **open** (AV scanner / app being updated) can fail on Windows — a pre-existing reality, now exercised per-file by the temp→promote model.
- **Verified:** macOS; Windows needs the resume-interrupt-and-promote path exercised (§E).

## A5. Control channel: pause / resume / try_now (`downloadControlChannel.py`)

- **What:** a daemon thread reads one-line JSON commands from instl's **stdin**; flips in-process `threading.Event` flags the URL loop and retry-sleeper poll between files. In-flight curl is never killed mid-chunk.
- **Why:** lets Central pause/resume a running download and "try now" during a backoff — without OS signals.
- **Why it's safe:** start is fully guarded (exceptions swallowed at debug); with no Central writing stdin, the stream hits EOF and the thread exits — behavior identical to before. Pause is cooperative (default state "running").
- **macOS/Windows — the one everyone worries about, and it's a NON-ISSUE:** there is **no `select()`/`poll()`/`fcntl`/`msvcrt`** anywhere — the reader is a blocking `for line in sys.stdin`, which is correct on Windows (the broken-on-Windows `select()`-on-a-pipe pattern is *absent*). Pause delivery is a polled `threading.Event`, not a signal. The module docstring explicitly chose stdin-JSON *because* signaling is awkward on Windows. Minor: stdin can be more buffered on Windows, so a pause may arrive slightly later — it never deadlocks or crashes.
- **Verified:** macOS reasoning + code; Windows pause/resume/try_now is a §E item.

## A6. Retry matrix + failure classification — **DEFAULT ON (disclosed)**

- **What:** `downloadFailures.py` normalizes curl/HTTP/Python errors into a `DownloadFailureClass` taxonomy; `downloadRetry.py` maps each to RESUME/RESTART/FAIL_TERMINAL with bounded exponential backoff + jitter. Gated `DOWNLOAD_RETRY_POLICY_ENABLED` (**default `yes`**).
- **Why:** robustness — transient redownload errors recover instead of failing the install.
- **Honest behavior change (do not call this "additive"):** the base `re_download_bad_files` was **single-pass and aborted the whole pass on the first exception**. The new default path gives **each** bad file its own bounded retry (≤5 by class) and **continues past a terminal failure on one file**. Net: a transient error that used to fail a sync now retries; a hard failure on file A no longer blocks B, C. It adds backoff latency on flaky networks.
- **Why it's still safe:** retries are bounded (≤5); the final `raise_on_bad_checksum` gate is **preserved**, so a genuinely failed sync still fails; the kill switch `DOWNLOAD_RETRY_POLICY_ENABLED=no` cleanly restores base-like single-pass behavior; retry-decision logs are privacy-scrubbed (no URL/cookie). `requests` is an optional import, **guarded** (`requests = None` fallback), so the client-only frozen build is unaffected.
- **macOS/Windows:** pure-Python logic (time/random/datetime, all cross-platform, tz-aware). **Minor Windows fidelity note:** `_classify_os_error` keys off numeric `errno`; some Windows failures surface as `WinError` and may classify as `unknown` (terminal) rather than e.g. `disk_space` — it **fails safe** (won't wrongly retry a disk-full), only telemetry fidelity is affected.
- **Verified:** unit tests for classification/backoff/decision; Windows = §E (force a transient redownload failure).

## A7. Adaptive concurrency (`downloadConcurrency.py`) — default off, provably inert

- **What:** between-session controller that *could* tune `PARALLEL_SYNC` from the prior run's summary. Gated `DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED` (**default `no`**).
- **Why:** future throughput tuning.
- **Why it's safe:** with the flag off it returns `DISABLED`, and the call-site leaves `PARALLEL_SYNC` **untouched** (always pre-set to 50 in defaults). The whole call is wrapped "controller must never break sync." Confirmed inert at default config.
- **macOS/Windows:** no `os`/path/clock/random calls — pure arithmetic. No platform surface.

## A8. Rollout cohort (`downloadCohort.py`) — observe-only

- **What:** normalizes a `DOWNLOAD_COHORT` label and **downgrades** it if its required flags are off (so telemetry can't claim a disabled capability). Default `control`.
- **Why:** honest phased-rollout telemetry.
- **Why it's safe:** nothing in the download path branches on the cohort — it's a label on a telemetry event. Fully fail-safe (unknown → `control`).
- **macOS/Windows:** pure string/dict logic; no platform surface.

## A9. Structured events (`downloadEvents.py`)

- **What:** single source of truth for the `DOWNLOAD_EVENT {json}` line contract Central consumes (session/file/retry/capability/summary). Emitted via the stdlib logger at INFO. Kill switch `DOWNLOAD_TELEMETRY_ENABLED` (default on).
- **Why:** gives Central a typed channel instead of scraping free-text.
- **Why it's safe:** runs **alongside** the legacy free-text progress (does not replace it); `emit_event` swallows all format/log errors; a privacy denylist drops auth/URL/local-path keys even if a caller forgets to redact; timestamps are UTC ISO. Kill switch suppresses all of it and the sync still completes.
- **macOS/Windows:** no filesystem/OS assumptions; JSON is deterministic (`sort_keys`). One thing the consumer must tolerate: Windows text-mode logging can introduce `\r` — Central handles it (see B1).

## A10. Modernization — god-object decomposition (admin/, client/, gui/)

- **What:** `instlAdmin`→`pyinstl/admin/`, `instlClient`→`pyinstl/client/`, `instlGui`→`pyinstl/gui/` packages.
- **Why:** the god-objects (1000–1600+ lines) were the stated top refactoring pain point.
- **Why it's safe — behavior-identical:** old modules kept as **backward-compat shims** that re-export from the new packages; dispatch and sibling mixins import through the shims (no dangling imports, AST-verified). **All 21 admin `do_*` methods present** (exact set match); GUI moved verbatim (zero line-multiset diff). Platform-specific code survived intact: per-OS manifest handling (`!index_Win`), Chmod exec-bit logic, the Redis upload daemon, the Tk root + all three GUI tabs.
- **macOS/Windows:** Windows branches preserved (token counts of `Win`/`Chmod`/`win` match old↔new exactly). Admin/GUI are source-only and excluded from the frozen client build, so this can't affect the shipped client anyway.

## A11. Modernization — hygiene (+ 3 latent bug fixes)

- **What:** dead-code removal, unused-import pruning, narrowing `except: pass` to logged/typed excepts — across pybatch, configVar/aYaml, utils, db/svnTree, pyinstl-core.
- **Why it's safe:** every dead-code removal verified unreachable (`if False:`, no-op wrappers, post-`return` code, a duplicate `def quoteme_raw_string`); every narrowed except **still swallows** (now logs) — no control-flow change. **No Windows import was removed** (`grep` for removed `win32*/winreg/pywin32` across all hygiene commits is empty).
- **Disclosed improvements riding along (not byte-identical):** (1) `log.wanging`→`log.warning` (a branch that used to raise `AttributeError`); (2) `get_disk_free_space` now imports `win32file` **inside** the existing `'Win'` guard — a **Windows-only fix** for a prior `NameError`; (3) `Unwzip` now `MakeDir(target)` not `.parent` (platform-agnostic). All are fixes on already-broken paths; Windows posture is **unchanged or better**.

## A12. Modernization — config_vars containment

- **What:** new `configVar/accessors.py` typed accessors + `(cv=None)` injection seams.
- **Why it's safe:** accessors are **literal transcriptions** of the old idioms (`.str()`, `.list()`, `bool()`, `.Path()`); no default, coercion, truthiness, or key changed. OS identity returns the **identical** string on Windows (`"Win"`). No caller passes `cv`, so the global singleton path is unchanged. Migration is incremental but consistent (remaining direct reads resolve identically).
- **macOS/Windows:** no semantic change on either.

## A13. Modernization — `pipes`→`shlex` (py3.13 compat)

- **What:** one 2-line change in `utils/dockutil.py`.
- **Why it's safe:** `pipes.quote` was a CPython alias of `shlex.quote` — byte-identical output. `dockutil` imports `pwd` (Unix-only) at module top, so it **cannot even import on Windows** — the change is vacuous there and POSIX-appropriate on macOS.

## A14. Tests + docs

- **What:** characterization golden suites (pybatch repr→eval serialization, `$()` resolution, client graph/copy reprs); test-rot repairs; ARCHITECTURE/HLD/LLD/REFACTORING + download docs.
- **Why it's safe:** test-repair surfaced **3 real pre-existing bug fixes** (re-add `import abc` in `curlHelper` — module was un-importable at base; `Unwzip` MakeDir; exit-code tuple normalization), each covered by tests. Skipped tests are Mac-only/privilege/GUI/outdated-API — **no Windows-functionality test was skipped or deleted** to green the gate.
- **Windows gap (a coverage weakness, not a regression):** the copy-golden suite forces `__CURRENT_OS__=Win` but pins **POSIX-slash** reprs — there's no golden for Windows backslash paths or `%VAR%` native-var rewriting. Recommend adding Windows-target goldens.

---

# Part B — Central (for Vitaly)

> Covers the full Central POC (~20 commits, ~50 files) across five subsystems, audited against pre-POC baseline `6e67472f`. The two load-bearing safety facts, established by tracing the code:
> 1. **Engine selection:** the live `run-process` path runs only the **latest** engine; legacy V9/V10 installs never reach the new code. On **Windows**, online installs run elevated and so use the line-oriented **buffer-file** output path (not raw stdout) — which incidentally mitigates the chunk-split risk below.
> 2. **Everything new is additive with a legacy fallback or a kill switch** — with two honest exceptions called out in B5/B6 (and §D).

## B1. Structured event ingestion (parser, types, handler, state bus)

- **Files:** `downloadEventTypes.tsx` (new, mirrors instl `downloadEvents.py`), `downloadEventParser.tsx` (new), `downloadEventContract.test.tsx` (new), `shellInstlProcessProgressHandler.tsx` (modified), `downloadStateBus.tsx` (new), `shellInstlProcess.tsx`/`shellInstl.tsx` (modified).
- **What/why:** instl's `DOWNLOAD_EVENT {json}` lines are parsed into typed snapshots on a module-singleton `downloadStateBus` that the dialog reads — giving live ETA, a byte-true monotonic bar, and phase honesty instead of regex-scraping prose.
- **Why it's safe (backward-compat, traced):** **strictly additive and front-gated.** `handleProgress` checks `lineHasDownloadEventPrefix`; if false (every line a legacy engine emits), control falls through to the **unchanged** legacy regexes (`CURL_WRITE_OUT_REGEX`/`PROGRESS_REGEX`/`END_OF_PHASE_REGEX`/restart/action-phase). The download bar **falls back to file-count** when byte totals are absent; `applyStructuredPhaseProgress` is inert when `phaseBytesPlanned<=0` (explicit "old engine" test). The parser is fail-closed (every failure → `null`, never throws). `shellInstl.digestError` attaches the backend snapshot to errors **only** when a real file-state/retry event exists, so legacy error parsing is untouched.
- **macOS/Windows:** CRLF is handled (each line is `.trim()`ed, stripping a trailing `\r`; the JSON payload is trimmed before parse). **Honest gap (untested):** there is **no line buffering** — a `DOWNLOAD_EVENT` line split across two reads is parsed in halves, both fail, and the event is **silently dropped** (degrades gracefully: legacy text bar still advances). This affects (R1) the **modern-macOS** live-stdout path unconditionally and (R2) the **buffer-file** path on *both* OSes if a file read lands mid-write. Because Windows online installs use the buffer-file path, the headline "Windows chunk-split" fear is **largely mitigated** on Windows, but R2 remains. Fix is a small trailing-line accumulator + split-line tests.
- **Minor:** `downloadStateBus` is a process-global singleton relying on serial installs + a per-session `reset()` (called at `executeProcess`); fine today. Parser coerces a non-numeric `schemaVersion` to 1 (forward-compat papercut, not a legacy break).

## B2. Central→instl control channel (pause / resume / try_now over stdin)

- **Files:** `externalProcess/types.tsx` (interface), `electronMainLiveProcess.tsx` / `electronRendererLiveProcess.tsx`, `externalProcess/behaviours/common.tsx` + `types.tsx` (IPC channel), the two `__mocks__`, the windows-device test mock, and `downloadControlBus.tsx` (new renderer shim).
- **What/why:** the dialog's pause/resume/try-now requests hop renderer→main→`innerProcess.stdin.write("${json}\n")` into instl's stdin reader.
- **Why it's safe:** the new `sendCommand(json)` method was added to the `ILiveProcess` interface as a **required** member — and **all 7 construction sites (both real implementations + 3 mocks + the inline test mock) are updated**, with `tsc --noEmit` returning **0 errors** project-wide. (Required-not-optional is the *safer* choice here: the compiler enforces that no implementor is missed, rather than leaving a silent runtime `undefined`.) The stdin write is best-effort — guarded by `stdin && stdin.writable`, wrapped in try/catch, logs-and-drops on failure. The `downloadControlBus` shim is a no-op when no handler is registered, and the handler is cleared in a `finally` so a dead process can't receive commands.
- **macOS/Windows:** writing a single `\n` (LF) is correct — verified on the instl side that the reader does a blocking `for line in stdin` then `.strip()`s each line, so a bare LF terminates and any stray `\r` is removed. No Windows-specific stdin hazard.
- **Test gap:** the `tryNow → "try_now"` command-string mapping (the snake_case instl expects) lives in `shellInstlProcess.sendControl` and is **untested** — a typo would silently no-op on the instl side.

## B3. Offline detection + offline-hold install

- **Files:** `network/onlineDetector.tsx` (new), `baseCentralProductProcess.tsx` (modified).
- **What/why:** `onlineDetector` combines `navigator.onLine`/window events with a retry-pattern heuristic (3 consecutive network-class retry events ⇒ synthetic offline). `baseCentralProductProcess` now **holds** (early-returns from the fail-after-8s `noNetwork` path) instead of failing, when a pausable download is active.
- **Why it's safe (legacy protection, traced):** the hold is gated on `isOfflineHoldActive()` → `isCentralDownloadUxEnabled(getLastCapabilityEvent())`, which returns **false** when the capability event is `null` (legacy engines never emit it) **and** is **double-gated** (a latest engine must also explicitly send `centralUxEnabled:true`, the rollout kill switch). The bus is `reset()` per session so capability can't leak into a later legacy run. **Legacy engines keep the old fail-on-offline behavior.** `onlineDetector` guards `navigator`/`window` absence and defaults to *online* (won't crash or false-trip offline in a headless context).
- **macOS/Windows:** `navigator.onLine` has identical Chromium semantics on both; the retry heuristic is event-driven, OS-agnostic.
- ✅ **Fixed (was: no max-hold ceiling).** When the hold is active it now arms a **30-minute ceiling**; if the connection never returns, the install fails like before instead of hanging forever. The ceiling is cleared on reconnect and on process settle (no stale timer fires post-completion), and both hold-entry and ceiling-exceeded are logged. Legacy engines remain unaffected (hold is capability-gated off). Verified by `tsc` + review; the wiring itself has no unit test (no `BaseCentralProductProcess` harness exists) — covered by the Part E offline-hold smoke tests.

## B4. Failure classification + recovery actions

- **Files:** `downloadErrorParser.tsx` (modified, 74→319 lines), `downloadFailureCategory.tsx` (new), `downloadRecoveryActions.tsx` (new), `failureRecoveryActions.tsx` (new), `errorParsers.test.tsx`.
- **What/why:** an opaque download error becomes a 14-class taxonomy with class-specific, ordered recovery buttons (retry / repair-cache / restart / etc.), preferring instl's own structured `retry_decision.failureClass` over brittle stderr text.
- **Why it's safe (message level — solid):** **additive, not replacing.** The four legacy `errorType` buckets produce the **same** messages as baseline when no backend/UX signal is present (verified by retained tests); classification is stamped **only when a message is produced**, so `unknown`/`cancelled` fall through to the legacy Copy-error/OK footer; parser **ordering is unchanged**; and **all baseline non-download error-parser tests still pass** (MajorStage/Pipe/ShowStoppers/UserAction/WindowsLockingProcess/Offline). The inline-message kill switch (`isCentralUxEnabled`, default false) is correctly plumbed.
- **Two weaknesses found here — now FIXED (see §D-7/8):**
  - ✅ **The dialog recovery buttons are now gated on the UX rollout flag.** `getFailureRecoveryActions` returns `null` unless `CENTRAL_DOWNLOAD_UX_ENABLED_PROP_NAME === true`, so a legacy engine (flag absent) falls back to the legacy Copy-error/OK footer. Regression-tested.
  - ✅ **"Try again" is now suppressed on `retryable:false` failures** (e.g. terminal TLS) — the action map drops `tryAgain` when not retryable. Regression-tested.
- **macOS/Windows:** the curl/instl **string-prose** patterns are **English-locale-dependent** (pre-existing, but the POC widens the surface 4→13 patterns); the **curl-exit-code** patterns (`curl error code: NN`) are locale-independent and robust. No multiline/`^$` anchors → line-ending-safe. One Windows note: a curl-23 "write error" now routes to a permission-fixer button that does little on Windows.

## B5. Progress dialog + shared controls + i18n + telemetry

- **Files:** `progress.tsx`, `_progress.scss`, `complete.css`; `downloadControls.tsx`, `downloadMetaLine.tsx`, `downloadVisibleState.tsx`, deleted `downloadStatePill.tsx`; **shared** `progressBar.tsx` + `common.tsx`; `translation.tsx`/`en_us.tsx`/`types.tsx`; `centralServiceStatistics.tsx`.
- **What/why:** phase-honest title, two-tier meta line, byte-true monotonic bar, inline pause/resume/cancel, a tinted ProgressBar variant, 24 new i18n keys.
- **Why it's safe:**
  - **Shared components do NOT regress.** `progressBar.tsx` adds an **optional** `variant?` prop — when absent the className is byte-identical to baseline; the two non-download call sites (splash, guided tour) pass no variant and a test explicitly locks "no variant ⇒ no `state-*` class". `common.tsx` only **adds** `parseDownloadSizeToBytes` (no existing export touched).
  - **Clean legacy fallback:** when there's no structured session (`visibleState==="none"`), the title is not overridden, the bar is untinted, and the whole meta-line/controls area does not render — the old UI is preserved. Deleting the pill left **zero** dangling references; its label function moved into `downloadVisibleState.tsx`.
- **Honest caveat (see §D):** the new UI is gated on **parseable live progress**, not on a capability event, and **`canPauseResume` defaults true** — so a legacy engine whose curl output parses will synthesize a "downloading" session and show the meta line + Pause/Cancel. This rests on the assumption that **old instl tolerates unknown stdin control commands** (it should — instl logs "unknown cmd" and ignores — but worth confirming for V9/V10).
- **macOS/Windows:** bytes/speed/ETA use `.toFixed()` (locale-independent `.` decimal); only the file **count** uses `toLocaleString()`, which is **display-only and never parsed back** — a cosmetic separator difference on non-English Windows, no round-trip bug. No file paths rendered in the meta line.
- **i18n/telemetry/artifact:** 24 `PROGRESS_DOWNLOAD_ENHANCEMENT__*` keys added consistently across types/translation/en_us (no build break; English-only, consistent with repo). The statistics change is **abort-log attachment** (gzip Central.log on user-abort), **not** download-click telemetry (so if click-telemetry was expected, it's absent). `complete.css` (+14k lines) is a **generated build artifact** committed alongside its SCSS source — pre-existing repo convention, but it bloats the diff.

## B6. Tests

Substantial jest coverage added and green (`tsc --noEmit` clean): `downloadEventParser` (19), `downloadEventContract` (6, pins the cross-repo contract + additive-field tolerance), `downloadStateBus`, `downloadControlBus` (5), `onlineDetector` (5), `downloadFailureCategory`, `downloadRecoveryActions`, `failureRecoveryActions`, `errorParsers` (legacy parsers + new, regression-guarded), `downloadVisibleState` (11), `downloadMetaLine` (8), `downloadControls` (7), `progressBar` (variant + no-variant lock), `shellInstlProcessProgressHandler` (incl. byte-bar, phase-byte tail, **explicit old-engine inertness**, retained legacy paths). **Notable gaps to disclose:** no split-line/CRLF ingestion test; no offline-hold wiring test; no "legacy engine shows generic footer (not new buttons)" test; no `retryable:false`→no-"Try again" test; command-string mapping untested.

---

# Part C — Cross-platform (Windows) summary

**Safe by design (the landmines that were *avoided*):**
- Control channel uses **blocking stdin reads, not `select()`** → Windows-correct.
- Pause/resume is a polled `threading.Event`, **not OS signals** (no SIGSTOP/SIGCONT).
- curl args go into a **config file**, not a shell line → the `shlex`-is-POSIX concern doesn't apply; Windows 8.3 shortname path handling untouched.
- temp→final promotion uses `os.replace` (atomic-replace on Windows) on a **same-volume** temp by construction.
- `requests` import is guarded → client-only frozen build unaffected.
- Modernization dropped **no** Windows import / admin subcommand / platform branch; added a Windows-only `win32file` fix.
- Central: the new `sendCommand` is implemented/stubbed in **all 7** `ILiveProcess` sites (`tsc` clean); stdin write is a single `\n` that instl's `.strip()`ing reader handles; **Windows online installs use the line-oriented buffer-file path**, so the worst-case raw-stdout chunk-split is a macOS concern, not Windows.
- Central: shared `ProgressBar` change is an **optional** prop (non-download call sites byte-identical, test-locked); offline-hold and the inline-message recovery tokens are **capability-gated off** for legacy engines.

**Real Windows items to confirm (none known-broken):**
1. Bundled Windows curl **≥7.71** (for `retry-all-errors`) and HTTP/2-capable — else set the gates off.
2. `continue-at = -` resume-append behavior on a Windows re-run after interruption.
3. `os.replace` over a destination held open by AV / the app being updated (pre-existing Windows reality, now per-file).
4. Central CRLF is handled; the open item is a **split-line `DOWNLOAD_EVENT`** via the buffer-file mid-write race (R2) — confirm events still populate on a large Windows install.
5. Central locale: file-count `toLocaleString()` on non-English Windows is cosmetic only (never parsed back) — confirm it reads sanely.

---

# Part D — Proactive concessions (raise these first)

These are the honest edges. None is a known break; raising them first is what keeps credibility. The first three are the ones I'd lead with.

**instl (Shai):**
1. **Retry policy is ON by default and *does* change redownload behavior** (single-pass/abort → per-file bounded retry that survives terminal failures). Defensible as robustness; kill switch (`DOWNLOAD_RETRY_POLICY_ENABLED=no`) restores base; final fail-gate preserved. *Not* "additive."
2. **`continue-at = -` on all fresh transfers** is the one default-on download behavior change on both OSes (safe because temp names are content-addressed).
3. **`promote_temp_file` has no explicit same-volume guard** — safe as wired (temp is a sibling of the final), but a future cross-drive caller would hard-fail on Windows.
4. **Windows characterization goldens missing** in instl (POSIX-slash only) — coverage gap, not a regression.
5. Pre-existing `verbatim=source_url==['url']` (always-False) bug is **carried over unchanged** (not introduced, not fixed here).
6. Windows `errno`-vs-`WinError` gap in failure classification → some Windows errors classify as `unknown` (fails safe; telemetry fidelity only).

**Central (Vitaly) — FIXED this pass (present as "found and fixed"):**
7. ✅ **Dialog recovery buttons now gated on the Central UX rollout flag.** `getFailureRecoveryActions` returns `null` unless `error.object[CENTRAL_DOWNLOAD_UX_ENABLED_PROP_NAME] === true` — so a legacy engine (flag absent) or rollout-off engine (flag false) falls back to the legacy Copy-error/OK footer. Regression-tested (flag absent/false ⇒ null; flag true ⇒ buttons).
8. ✅ **"Try again" no longer shows on non-retryable failures.** `mapClassToActions` now drops `tryAgain` when `classification.retryable` is false (e.g. terminal TLS → `["cancel"]`; disk-space → `["openDrive","cancel"]`), keeping `cancel` always. Regression-tested.
9. ✅ **Offline-hold now has a max-hold ceiling.** When the hold is active it arms a 30-minute ceiling (`OFFLINE_HOLD_CEILING_MS`); if the connection never returns it fails like before instead of hanging forever. Cleared on reconnect and on process settle (so no stale timer fires post-completion), and logs on hold-entry + ceiling-exceeded. Legacy engines still unaffected (hold is capability-gated off). *(Verified by `tsc` + review; unit test deferred — see #12.)*

*All Central jest suites green after the fixes: 166/166 across 12 suites, incl. the legacy error-parser regression tests; `tsc --noEmit` clean.*

**Central (Vitaly) — remaining (disclosed, not fixed):**
10. **`canPauseResume()` defaults `true`** + the new UI is gated on *parseable live progress*, not a capability event — so a legacy engine whose curl output parses shows Pause/Resume/Cancel. Safe **iff** old instl ignores unknown stdin commands (it should — logs "unknown cmd"); confirm for V9/V10. Recommend gating controls on capability. *(Left as-is: lower risk, and gating it touches the live-progress synthesis path.)*
11. **Line-buffering gap (untested):** a `DOWNLOAD_EVENT` line split across reads is silently dropped — R1 on the macOS live-stdout path, R2 via the buffer-file mid-write race on **both** OSes. Windows online installs use the buffer-file path, so the headline "Windows chunk-split" is mostly mitigated, but R2 remains. Fix: trailing-line accumulator + split-line/CRLF tests.
12. **Remaining test gaps:** offline-hold wiring (no `BaseCentralProductProcess` harness exists — heavy to add without flakiness; covered by the Part E offline-hold positive/negative smoke tests); the `tryNow→"try_now"` command-string mapping; split-line/CRLF ingestion. *(The UX-gate and `retryable` gaps from the earlier draft are now closed with tests.)*
13. `complete.css` (+14k generated lines) is committed (pre-existing convention) — bloats the diff; confirm intent to ship compiled CSS.

---

# Part E — Windows smoke-test checklist (to convert "reasoned" → "verified")

**instl (CLI, on Windows):**
- [ ] Normal sync with `DOWNLOAD_RESUME_ENABLED` off — confirm identical curl behavior + new event lines; sync completes.
- [ ] Pause/resume/try_now via stdin JSON mid-download — confirm `.part` growth halts/resumes and backoff is cut short.
- [ ] Interrupt mid-download, re-run — confirm `continue-at` resume + checksum pass + `os.replace` promotion (no `[WinError 17]`/`[WinError 32]`).
- [ ] Brief network drop — confirm `retry-connrefused`/`retry-max-time` ride through (no single connect-timeout fail).
- [ ] Promotion over an existing (re-install) and an AV-locked destination — characterize behavior.
- [ ] Confirm bundled curl version ≥7.71 / HTTP/2, or gates off.
- [ ] Force a transient redownload failure — confirm bounded retry then success/terminal-raise.

**Central (on Windows):**
- [ ] Latest-engine full install — title tracks phases, bar monotonic, ETA + meta line correct (GB/MB, thousands-separated counts).
- [ ] CRLF / split-line integrity — `DOWNLOAD_EVENT` lines from the Windows engine populate the dialog on a large/fast install (R2 buffer-file race).
- [ ] Pause/Resume/Try-now from the dialog actually reach the Windows instl process (instl log shows the state change); Cancel works in every phase.
- [ ] **Offline-hold positive:** latest engine + `centralUxEnabled:true`, drop the NIC mid-download → install **holds** (no fail dialog), reconnect → resumes/completes.
- [ ] **Offline-hold negative (legacy regression):** route to a **V9/V10** engine, drop the NIC → install **still fails after ~8s** as before (capability `null`).
- [ ] **Legacy footer:** force a checksum/network failure on a legacy engine → confirm the **old generic error footer**, *not* the new recovery buttons (this currently fails per §D-7 — it's the verification that proves the fix).
- [ ] **Terminal TLS:** force a `retryable:false` failure → confirm no misleading "Try again" (per §D-8).
- [ ] Confirm a legacy engine does **not** abort when the offline auto-pause path sends pause/try-now on stdin (per §D-10).
- [ ] Shared-component non-regression: splash + guided-tour ProgressBars visually unchanged.

---

*Prepared from a per-subsystem code audit of both branches against their base commits. macOS behavior verified live; Windows assurances are code-reasoned and pending the §E checklist.*
