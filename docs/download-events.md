# Download event contract (instl → Waves Central)

Status: **Authoritative contract** · Last updated: 2026-06-17

This document is the contract of record for the structured download-telemetry
channel that instl emits and Waves Central consumes. It is the "harden the
contract" deliverable (Workstream 4) of `download-ux-eta-design.md`.

**Source of truth:** the emitters in `pyinstl/downloadEvents.py` and the enums in
`pyinstl/downloadState.py` / `pyinstl/downloadFailures.py`. The consumer types
live in Central `…/shell/progress/downloadEventTypes.tsx`. When code and this doc
disagree, the code wins — fix the doc. Both the instl contract test
(`pyinstl/test/test_downloadEventsContract.py`) and the Central contract test
(`…/shell/progress/downloadEventContract.test.tsx`) pin this contract.

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

**Privacy (D-014/D-016/NFR-005):** a fixed denylist is dropped before
serialization — `url`, `urlRedacted`, `headers`, `cookie(s)`, `authorization`,
`policy`, `signature`, `signedUrl`, `tempPath`, `finalPath`, `localPath`,
`downloadPath`. Hosts may pass as bare host strings; full URLs/paths must not.

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

**Optional live-progress fields (Workstream 1)** — present *only* on in-flight
`downloading` progress ticks, absent on lifecycle transitions:

| key | type | notes |
|---|---|---|
| `bytesReceived` | int | cumulative, monotonic |
| `filesCompleted` | int | cumulative, monotonic |
| `observedThroughputBytesPerSecond` | int | EMA-smoothed (α≈0.2), bytes/sec |

Central uses these for the live ETA and meta line (`downloadMetaLine.tsx`); it
falls back to `download.session_summary` totals when they are absent.

**Phase transitions emitted (Workstream 2):** `verifying_downloads` before the
checksum pass, `copying` at copy start, `completed` after the require-file write.
Central maps these to the "Verifying" / "Installing" / terminal UX states.

### 3.2 `download.file_state`

Per-file transitions. Keys: `fileId`, `repoPath`, `state` (§4.2),
`previousState`, `expectedSize`, `receivedBytes`, `retryCount`,
`lastFailureClass` (§4.3), `resumed` (bool), `host` (bare host).

### 3.3 `download.retry_decision`

Wrapped form of the legacy `DOWNLOAD_RETRY_DECISION` line. Keys: `fileId`,
`repoPath`, `failureClass` (§4.3), `attempt`, `decision`
(`resume`|`restart`|`fail_terminal`), `delayMs`, `restartRequired`, `reason`,
`receivedBytes`, `concurrency`, `retryAfterSeconds`, `httpStatus`,
`curlExitCode`. The legacy text line is still emitted unchanged (D-016).

### 3.4 `download.capability`

One-shot backend feature snapshot Central uses for UX gating (D-004). Keys:
`resumeEnabled`, `adaptiveConcurrencyEnabled`, `validatedHosts` (bare hosts),
`retryMatrixVersion`, `stateSchemaVersion`, `eventSchemaVersion`, `cohort`,
`featureFlags` (map of bool), `centralUxEnabled`, `telemetryEnabled`,
`retryPolicyEnabled`. **`centralUxEnabled` is the master gate** for the new
structured UX.

### 3.5 `download.session_summary`

The aggregated `session-summary.json` payload lifted onto the channel so Central
need not read the sidecar. Carries `summary` (object): `wallMs`, `filesPlanned`,
`bytesPlanned`, `concurrencyPlanned`, `totals` (incl. `successes`,
`failuresRetryable`, `bytesReceived`), `observedThroughputBytesPerSecond`,
`errorRate`, `retryableErrorRate`, `hosts`.

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
`timeout_during_transfer`, `http_auth_policy`, `http_error`, `disk_write`,
`disk_space`, `permission_denied`, `checksum_mismatch`, `partial_transfer`,
`process_terminated`, `cancelled`, `missing_after_transfer`, `malformed_url`,
`network_send_error`, `network_receive_error`, `unknown_download_error`.

Consumers **must** treat unknown enum values as forward-compatible (D-007): map to
a safe default, don't crash.

---

## 5. Versioning & evolution rules

* **Additive fields do NOT bump `schemaVersion`.** Adding an optional field to an
  existing event (as Workstream 1 did with the live-progress fields) keeps
  `schemaVersion = 1`. Consumers read new fields with a fallback and ignore
  unknown ones.
* **Breaking changes DO bump `schemaVersion`** (renaming/removing/retyping a
  field, changing semantics). Central rejects any event whose `schemaVersion`
  exceeds the version it knows (`downloadEventParser` gates on
  `schemaVersion <= DOWNLOAD_EVENT_SCHEMA_VERSION`) and treats it as "no data".
* **Never remove or rename a field without a version bump.** The contract tests in
  both repos fail if a documented field disappears.
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
  download portion is byte-true (Workstream 3) but is parsed from the legacy
  `Downloaded A of B` line. Driving the bar % entirely from the structured channel
  (so the legacy regex can be demoted to an old-engine fallback) is **future
  work**, tied to the deferred install-phase byte budget (W3 option b). Until then
  the legacy progress line **must** keep being emitted.

---

## 7. Tests pinning this contract

* instl: `pyinstl/test/test_downloadEvents.py` (builder shapes) +
  `pyinstl/test/test_downloadEventsContract.py` (documented key sets, schema
  version, additive-field invariants, denylist).
* Central: `…/shell/progress/downloadEventParser.test.tsx` (parse/forward-compat) +
  `…/shell/progress/downloadEventContract.test.tsx` (canonical lines from this doc
  parse into the documented typed fields, incl. the W1 live fields).
