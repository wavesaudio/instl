# Download event contract (instl → Waves Central)

Status: **Authoritative contract** · Last updated: 2026-07-30

This document is the contract of record for the structured download-telemetry
channel that instl emits and Waves Central consumes.

**Source of truth:** the emitters in `pyinstl/downloadEvents.py` and the enums in
`pyinstl/downloadState.py` / `pyinstl/downloadFailures.py`. The consumer types
live in Central `…/shell/progress/downloadEventTypes.tsx`. When code and this doc
disagree, the code wins — fix the doc. On the instl side
`pyinstl/test/test_downloadEventsContract.py` pins this contract.

---

## 1. Transport

Each event is one log line at INFO level:

```
DOWNLOAD_EVENT {compact-json-with-sorted-keys}
```

* The literal prefix `DOWNLOAD_EVENT` (`DOWNLOAD_EVENT_LOG_PREFIX`) lets Central
  cheaply find structured events without parsing every line.
* JSON keys are sorted; values are compact. Central tolerates the production log
  prefix `<timestamp> | <LEVEL> | ` before the token (see `downloadEventParser`).
* The channel runs **alongside** the legacy free-text progress lines, not instead
  of them (see §6). Old Central builds and the `instl-V9`/`V10` engines only have
  the legacy lines.

The whole channel is gated by a process-level kill switch
(`set_telemetry_enabled`, driven by the `DOWNLOAD_TELEMETRY_ENABLED` rollout
flag). When off, no lines are emitted.

---

## 2. Envelope (every event)

| key | type | notes |
|---|---|---|
| `event` | string | one of the §3 event types |
| `schemaVersion` | int | currently **1**; see §5 |
| `sessionId` | string | opaque per-invocation id (`__INVOCATION_RANDOM_ID__`), `"unknown"` if absent |
| `timestamp` | string | ISO-8601 UTC, seconds resolution, `Z` suffix; computed at format time |

**Privacy:** a fixed denylist (`_DISALLOWED_EVENT_FIELDS`) is dropped before
serialization — `url`, `URL`, `urlRedacted`, `headers`, `cookie`, `cookies`,
`authorization`, `Authorization`, `policy`, `signature`, `Signed-URL`,
`signedUrl`, `tempPath`, `finalPath`, `localPath`, `downloadPath`. Matching is
exact-key, not case-insensitive. Hosts may pass as bare host strings; full
URLs/paths must not.

---

## 3. Event types and fields

`event` values: `download.session_state`, `download.file_state`,
`download.retry_decision`, `download.capability`, `download.session_summary`.

### 3.1 `download.session_state`

Session lifecycle transitions, plus in-flight download progress ticks.

| key | type | notes |
|---|---|---|
| `state` | string | a §4.1 session state |
| `previousState` | string\|null | optional prior state |
| `filesPlanned` | int\|null | total files this session |
| `bytesPlanned` | int\|null | total bytes this session |
| `concurrencyPlanned` | int\|null | planned parallel transfers |
| `actionId` | string\|null | install action id |
| `repositoryMajorVersion` | int\|null | |
| `repositoryRevision` | int\|null | |
| `reason` | string\|null | short literal (e.g. `download_started`, `checksum_verify`) |

**Optional live-progress fields** — present *only* on in-flight
`downloading` progress ticks, absent on lifecycle transitions:

| key | type | notes |
|---|---|---|
| `bytesReceived` | int | cumulative, monotonic |
| `filesCompleted` | int | cumulative, monotonic |
| `observedThroughputBytesPerSecond` | int | EMA-smoothed (α≈0.2), bytes/sec |

Central uses these for the live ETA and meta line (`downloadMetaLine.tsx`); it
falls back to `download.session_summary` totals when they are absent.

**Phase transitions emitted:** `verifying_downloads` before the
checksum pass, `copying` at copy start, `completed` after the require-file write.
Central maps these to the "Verifying" / "Installing" / terminal UX states.

**Backend-hold session states (offline-hold / stall / reconcile) — gated on
`DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD`:** the bulk-download engine
(`CurlTransfer` in `pyinstl/downloadTransfer.py`) now recovers from connectivity loss itself and,
*only* when the driving client declared the backend-hold capability (see §3.6),
narrates that recovery with additional `session_state` transitions:

| state | reason | when |
|---|---|---|
| `paused` | `offline_no_network` | connectivity probe failed; engine is holding (re-emitted, throttled to `DOWNLOAD_OFFLINE_HOLD_EVENT_INTERVAL_SECONDS`). Raised by the recovery loop after a network-class curl exit, AND by the `.part`-size poller after `DOWNLOAD_STALL_PROBE_SECONDS` of zero byte growth with a failed probe (fast path: a mid-transfer link drop only stalls curl's sockets, so no exit code fires until `speed-time`) |
| `downloading` | `resuming_after_offline` | connectivity returned; curl is re-run (`continue-at` resumes `.part` files). The poller's fast-path hold announces this only when bytes actually grow again — probe success alone keeps the hold visible (a wedged curl gets speed-time-aborted and re-run first). While a poller hold is active, plain flat-byte progress ticks are suppressed so the client's backend-hold flag is not churned |
| `downloading` | `stalled_no_progress` | stall-watchdog backstop: on-disk bytes have not grown for `DOWNLOAD_STALL_WATCHDOG_SECONDS` while curl is alive (suppressed while a poller offline-hold is active) |
| `retrying` | `reconcile_missing_outputs` | curl exited 0 but expected outputs are missing; a reconciliation round re-downloads only the missing entries |

These carry the current on-disk byte progress (`bytesReceived`,
`filesCompleted`, `phaseBytesDone`, `phaseBytesPlanned`) so Central's bar keeps
its position while frozen, and deliberately **no**
`observedThroughputBytesPerSecond` — the hold gap must not be averaged into the
ETA. All are additive (schemaVersion stays 1). Without the capability the
engine still holds/reconciles silently and emits only the legacy log lines.

### 3.2 `download.file_state`

Per-file transitions. Keys: `fileId`, `repoPath`, `state` (§4.2),
`previousState`, `expectedSize`, `receivedBytes`, `retryCount`,
`lastFailureClass` (§4.3), `resumed` (bool), `host` (bare host).

### 3.3 `download.retry_decision`

Wrapped form of the legacy `DOWNLOAD_RETRY_DECISION` line. Keys: `fileId`,
`repoPath`, `failureClass` (§4.3), `attempt`, `decision`
(`resume`|`restart`|`fail_terminal`), `delayMs`, `restartRequired`, `reason`,
`receivedBytes`, `concurrency`, `retryAfterSeconds`, `httpStatus`,
`curlExitCode`. The legacy text line is still emitted unchanged.

**Bulk-download network events — gated on
`DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` (§3.6):** the bulk curl loop, which
previously only wrote a free-text log line on network errors, now also emits
`retry_decision` events with the exact same schema. `fileId`/`repoPath` are
`null` (the failure is the bulk transfer, not one file), `decision` is
`resume` (the loop always retries in place via `continue-at`), and `reason`
distinguishes the two emitters:

* `bulk_curl_network_error` — a network-class curl exit from the bulk run
  (`curlExitCode` carries the code; `failureClass` is derived from it).
* `offline_hold_probe_failed` — one per failed connectivity probe while the
  engine holds offline (`failureClass` is `dns_resolution` or `tcp_connect`,
  both network-class, so Central's ≥3-streak online detector still fires even
  though curl is not being re-run while offline).

### 3.4 `download.capability`

One-shot backend feature snapshot Central uses for UX gating. Keys:
`resumeEnabled`, `validatedHosts` (bare hosts),
`retryMatrixVersion`, `stateSchemaVersion`, `eventSchemaVersion`,
`featureFlags` (map of bool), `centralUxEnabled`, `telemetryEnabled`,
`retryPolicyEnabled`. **`centralUxEnabled` is the master gate** for the new
structured UX.

`featureFlags` now also surfaces the connectivity-loss self-sufficiency gates
(`downloadEvents._REPORTED_FLAGS`): `DOWNLOAD_RECONCILE_MISSING_OUTPUTS`,
`DOWNLOAD_OFFLINE_HOLD_ENABLED`, `DOWNLOAD_CURL_STALL_DETECTION`,
`DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES` (all default **true**) and
`DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` (default **false**), so Central and
telemetry can see which recovery layers are active.

### 3.5 `download.session_summary`

The aggregated `session-summary.json` payload lifted onto the channel so Central
need not read the sidecar. Carries `summary` (object): `wallMs`, `filesPlanned`,
`bytesPlanned`, `concurrencyPlanned`, `totals` (incl. `successes`,
`failuresRetryable`, `bytesReceived`), `observedThroughputBytesPerSecond`,
`errorRate`, `retryableErrorRate`, `hosts`.

### 3.6 The backend-hold capability handshake (`DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD`)

This is a **client→engine** declaration, not an event: a NEW Central injects
`DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD: true` into the download settings of the
generated yaml, declaring that it treats the backend-hold signals above (the
bulk-loop network-class `retry_decision`s and the offline-hold / stall /
reconcile `session_state`s) as **informational** — it never answers them with
a stdin pause, because the engine is already holding and resumes itself.

The shipped default is **`no`**, because an OLD Central's 3-streak online
detector would respond to a burst of network-class `retry_decision`s with a
pause that nothing auto-resumes on Windows (`navigator.onLine` lies there),
deadlocking the engine in `wait_if_paused`. With the flag off, **all** silent
recovery (output reconciliation, offline-hold, stall detection, redownload
budgets) still runs — only the legacy log lines / event stream are produced,
so an old Central sees exactly today's events. The flag is surfaced on
`download.capability.featureFlags` (§3.4). Emitter gate:
`_client_handles_backend_hold()` in `pyinstl/downloadTransfer.py`.

---

## 4. Vocabularies

### 4.1 Session states (`DownloadSessionState`)
`preparing`, `verifying_existing_files`, `downloading`, `retrying`, `paused`,
`verifying_downloads`, `ready_to_copy`, `copying`, `completed`, `failed`,
`cancelled`.

### 4.2 File states (`DownloadFileState`)
`planned`, `already_valid`, `queued`, `downloading`, `paused`, `interrupted`,
`downloaded_unverified`, `verifying`, `verified`, `failed_retryable`,
`failed_terminal`.

### 4.3 Failure classes (`DownloadFailureClass`)
`dns_resolution`, `tcp_connect`, `tls`, `timeout_before_first_byte`,
`timeout_during_transfer`, `http_429`, `http_5xx`, `http_auth_policy`,
`http_4xx`, `http_error`, `disk_write`, `disk_space`, `permission_denied`,
`checksum_mismatch`, `partial_transfer`, `process_terminated`, `cancelled`,
`missing_after_transfer`, `malformed_url`, `network_send_error`,
`network_receive_error`, `unknown_download_error`.

Consumers **must** treat unknown enum values as forward-compatible: map to
a safe default, don't crash.

---

## 5. Versioning & evolution rules

* **Additive fields do NOT bump `schemaVersion`.** Adding an optional field to an
  existing event (as the live-progress fields of §3.1 are) keeps
  `schemaVersion = 1`. Consumers read new fields with a fallback and ignore
  unknown ones.
* **Breaking changes DO bump `schemaVersion`** (renaming/removing/retyping a
  field, changing semantics). Central rejects any event whose `schemaVersion`
  exceeds the version it knows (`downloadEventParser` gates on
  `schemaVersion <= DOWNLOAD_EVENT_SCHEMA_VERSION`) and treats it as "no data".
* **Never remove or rename a field without a version bump.** The instl contract
  test fails if a documented field disappears.
* New `event` types and new enum values are additive: emit freely; consumers must
  ignore unknown ones rather than crash.

---

## 6. What each side relies on (and what is NOT yet structured)

* **State pill / label** (Downloading / Verifying / Installing / Paused / Offline /
  Retrying): driven by `session_state` via `downloadVisibleState.tsx`.
* **Meta line + live ETA** (`downloadMetaLine.tsx`): prefers `session_state` live
  fields (§3.1), falls back to `session_summary`.
* **Pause/resume/retry controls + failure dialogs**: driven by `capability`,
  `retry_decision`, `file_state` via `downloadStateBus`.
* **Progress bar percentage**: **still computed from the legacy text progress
  line**, not from structured events (`shellInstlProcessProgressHandler.tsx`). The
  download portion is byte-true but is parsed from the legacy
  `Downloaded A of B` line. Driving the bar % entirely from the structured channel
  (so the legacy regex can be demoted to an old-engine fallback) is **future
  work**, tied to a deferred install-phase byte budget. Until then
  the legacy progress line **must** keep being emitted.

---

## 7. Tests pinning this contract

* instl: `pyinstl/test/test_downloadEvents.py` (builder shapes) +
  `pyinstl/test/test_downloadEventsContract.py` (documented key sets, schema
  version, additive-field invariants, denylist).
* Central: `…/shell/progress/downloadEventParser.test.tsx` (parse/forward-compat).
  There is no Central-side test that pins this document's canonical lines; the
  instl contract test is the only automated check of the documented key sets.
