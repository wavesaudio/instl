# instl — High-Level Design (HLD)

This document describes the design of each major subsystem of **instl** at a high level:
its responsibility, the key components it is built from, the public interface it exposes to
the rest of the system, the state it owns and persists, its inbound/outbound dependencies,
and the design notes and constraints that shape it.

It complements `ARCHITECTURE.md` (the cross-cutting view: layering, dependency graph, runtime
flows) and precedes the LLD (line-by-line internals). Read `ARCHITECTURE.md` first for the
big picture; this document zooms into each subsystem one at a time. Contracts and interfaces
are described here — implementation details belong in the LLD.

## Subsystems

1. **CLI & Entry Point** — process boot, command-line parsing, command dispatch, top-level run lifecycle.
2. **Instance Base** — the abstract command-object root (config loading, batch generation, dependency queries) plus the interactive REPL.
3. **Client Commands** — the end-user install/copy/remove/uninstall/report workflow, plus the `doit` runner and the `misc` utility commands.
4. **Sync Backends & Connections** — selecting and driving how a client fetches files from a remote repo; URL/SVN/P4/boto backends and the connection/URL-translation layer.
5. **Download Subsystem** — the curl-based bulk download engine: config-file generation, failure classification, retry/backoff, pause/resume control, resume state, observability, adaptive concurrency, telemetry, and cohorts.
6. **Admin Tooling** — the admin-side command monolith used to build and maintain the deployment repository (SVN maintenance, verification, up2s3/activate, the Redis daemon).
7. **GUI** — the Tk/ttk desktop front-end that builds command lines and spawns instl as a subprocess.
8. **PyBatch Command Objects** — the dual-identity object model (execute + serialize-to-Python-source) for every deployment action, plus the accumulator that renders the batch script.
9. **ConfigVar System** — the scoped, lazily-resolved configuration-variable engine and its `$(NAME)` resolution mini-language and YAML loader.
10. **Data Tables (svnTree + db)** — the SQLite-backed persistence layer: the info-map (svn) table and the index-item tables.
11. **aYaml & Utils** — the foundational augmented-YAML layer and the shared standard-library-style toolkit.

## Component-interaction summary

The **CLI & Entry Point** boots the process, parses options into the **ConfigVar System**, and
constructs exactly one command instance — a subclass of **Instance Base** — for the chosen mode
(client / doit / misc / admin / gui / interactive). Every command instance inherits from Instance
Base, which loads configuration through the ConfigVar System and YAML readers, owns a **PyBatch**
command accumulator, and owns the **Data Tables** (via the DB manager mixin).

A **Client Command** runs a pipeline: read the index YAML into the index-item tables, resolve
inheritance and install status, then (for sync) delegate to a **Sync Backend**, which reads the
remote info-map into the svn table and feeds download URLs into the **Download Subsystem** through
the curl helper. All commands accumulate work as PyBatch objects partitioned into named sections;
PyBatch serializes that tree to an eval-able Python "batch script" that re-imports PyBatch and runs
the same objects later. **Admin Tooling** uses the same Instance Base / PyBatch / Data Tables stack
to build repo artifacts and push them to S3/Redis. The **GUI** does not run commands in-process —
it builds command lines and spawns instl as a subprocess. **aYaml & Utils** and the **ConfigVar
System** sit underneath everything as shared foundations.

---

## 1. CLI & Entry Point

### Responsibility
Boot the instl process and drive a single run end-to-end: normalize stdout/stderr to UTF-8, fix SSL
paths and inject a truststore, parse the command line into config vars, seed the ~40-key initial
variable set (paths, OS identity, IDs, invocation id), dispatch to the correct command-mode handler,
and wrap the whole run in a top-level reporting/lifecycle context manager. This is the single boot
path for both direct CLI invocation and recursive sub-process invocation (e.g. `up2s3`, the
command-list runner, the admin Redis daemon).

### Key components
| Component | Responsibility |
|---|---|
| `instl` (launcher script) | Executable entry; reopens stdout/stderr as UTF-8 then calls `instl_own_main(sys.argv)`. |
| `instl_own_main` | Real entry point; runs inside the reporting context, fixes SSL, parses options, builds `initial_vars`, dispatches by `(mode, is_compiled)`, closes the instance. |
| `InvocationReporter` | Outermost context manager (a `PythonBatchRuntime` subclass) owning top-level logging, the invocation header/footer, run timing, and exception suppression/propagation. |
| `CommandLineOptions` / `OptionToConfigVar` | argparse namespace whose attributes are descriptors that write parsed options straight through into the global config vars. |
| `prepare_args_parser` / `read_command_line_options` | Build the command catalog and per-command argparse parser; parse argv into the namespace; default to interactive mode when no args. |
| `CommandListRunner` / `run_commands_from_file` | Implements `command-list`: read instl command lines from a config file and run them serially or in parallel (via fork), reusing one misc instance. |
| `InstlException` / `InstlFatalException` | Domain exception types caught by the interactive loop and the pybatch exit machinery. |
| Path/env resolvers (`get_path_to_instl_app`, `fix_ssl_paths`, …) | `lru_cache`'d resolution of app/data/exec paths and launch command, branching on frozen vs source and on OS. |

### Public interface
- `instl_own_main(argv) -> None` — the sole boot entry; called by the launcher and re-used as a `multiprocessing.Process` target for `up2s3`.
- `read_command_line_options(namespace, arg_list=None) -> command_names` — used here and by the command-list runner for each sub-command line.
- `CommandLineOptions()` — namespace callers construct before parsing.
- `run_commands_from_file(initial_vars, options)` — invoked when the command is `command-list`.
- Contract with command instances: construct the instance, call `init_from_cmd_line_options(options)`, then `do_command()`, then `close()`.

### Owned state & persistence
Owns no DB tables or on-disk artifacts directly. It writes the invocation header/footer to the
system log file (via logger configuration) and assembles the in-memory `initial_vars` dict that is
handed to the command instance (which then loads it into config vars). `command-list` mode reads
command lines from a config file and forks child processes.

### Dependencies
- **Out:** ConfigVar System (descriptors write through to the global config vars); PyBatch (`PythonBatchRuntime` base); aYaml & Utils (OS detection, paths, logging); Sync Backends/Connections (`inject_truststore`); all command-mode subsystems (client/doit/misc/admin/gui/interactive); the download control channel (lazy, sync commands only).
- **In:** the launcher script; the admin `up2s3` recursive invocation; the command-list runner.

### Design notes & constraints
- Parsing is not idempotent: option attributes are descriptors with import-time-seeded defaults that mutate the **global** config-var singleton in place, so recursive/forked invocations rely on scoped config-var contexts to avoid cross-contamination.
- `admin`/`interactive`/`gui` modes are only permitted when not frozen (not running as a PyInstaller build).
- Top-level exception/exit-code policy is implicit: there is no `try/except` in `instl_own_main`; suppression vs re-raise is owned by the pybatch runtime's `__enter__`/`__exit__`, and the `fail` command's exit code is computed in the misc subsystem. The entry point is intentionally thin; this dispersion of exit-code policy is a known constraint.

---

## 2. Instance Base

### Responsibility
Provide the abstract base class for every instl command object (client, admin, misc, doit, gui) plus
the interactive REPL. It centralizes shared concerns: configuration loading (defaults + user config +
index YAML via tag-dispatching readers), batch-file generation and execution, the DB lifecycle, cache/
sync directory resolution, dependency-graph queries, and require/config serialization.

### Key components
| Component | Responsibility |
|---|---|
| `InstlInstanceBase` | Abstract root for all command objects; holds shared state (batch accumulator, download tool, path searcher) and implements config loading, batch render/run, cache-dir resolution, and dependency queries. |
| `IndexYamlReaderBase` | Mixin combining the DB manager and the config-var YAML reader; wires `!require` / `!index` / OS-specific `!index_*` tags to the index-item table. |
| `check_version_compatibility` | Compares the running instl version against a minimum-version config var. |
| `go_interactive` / `CMDObj` | Entry point and `cmd.Cmd`-based REPL holding one client and one admin instance, exposing `do_*`/`complete_*` commands and readline history. |
| `do_list_imp` / `create_completion_list_imp` | Free functions monkey-patched onto the base class by `go_interactive` to provide listing and tab-completion. |

### Public interface
- `InstlInstanceBase(initial_vars=None)` — subclassed by all five command classes.
- The standard lifecycle the entry point relies on: `init_from_cmd_line_options(options)` → `do_command()` (abstract; implemented by subclasses) → `close()`.
- `read_yaml_file(...)` / `read_defaults_file(...)` — YAML loading used by subclasses and the REPL.
- `write_batch_file(...)` / `run_batch_file()` — render and optionally run the generated batch script.
- `write_config_vars_to_file(...)` / `write_require_file(...)` — YAML serialization used by client/admin.
- Dependency analysis: `needs(...)`, `needed_by(...)`, `find_cycles()`, `verify_actions(...)`.
- Cache/sync dirs: `get_aux_cache_dir(...)`, `get_default_sync_dir(...)`, `calc_user_cache_dir_var()`.
- `check_version_compatibility() -> (bool, str)`; `go_interactive(client, admin)`.

### Owned state & persistence
State is per-invocation and centered on three stores: (1) the **global config-vars** singleton,
populated from `defaults/main.yaml`, `defaults/compile-info.yaml`, the user config file, CLI defines,
and the index YAML; (2) the **SQLite DB** (items table + info-map table), in-memory or file-backed
depending on whether the command needs a refreshed DB; (3) the **batch accumulator** (sections of
PyBatch commands) rendered to the main out-file or stdout. On disk it also touches the user/aux cache
dirs (downloaded includes, bookkeeping), require files, config-var dumps, and the readline history
file (interactive). `close()` tears down the tables and the DB connection.

### Dependencies
- **Out:** ConfigVar System; Data Tables (DB manager, index-item table, svn table); PyBatch (accumulator + command classes); curl helper / download tool; Sync Backends/Connections (URL translation); aYaml & Utils; the dependency-graph helper (lazy).
- **In:** all five command subclasses; the entry point (constructs subclasses, drives the lifecycle, calls `go_interactive`); the package init (exports the reader mixin).

### Design notes & constraints
- This is a god-object base class mixing many concerns and forcing them onto every command; config vars and DB tables are process/class-global shared state, which makes interactive mode (one client + one admin) and any multi-instance use delicate.
- Interactive listing/completion methods are monkey-patched at runtime by `go_interactive`, so they only exist after that call.
- Generated batch scripts can be run either by compile+exec in-process or by spawning a subprocess; the in-process path couples the generated namespace to the host process.

---

## 3. Client Commands (install / copy / remove / uninstall / report; doit; misc)

### Responsibility
Implement the end-user install workflow. Given a central-generated index YAML plus an info-map of
available files, resolve the install-item (IID) dependency graph, mark each item's install status in
the index DB, sort items by target folder, and emit an ordered batch of PyBatch commands to copy/
unwtar files, run pre/post actions, remove previous sources, uninstall items, and rewrite the site
require file. Also provides read-only reporting, a generic dependency-ordered action runner (`doit`),
and a grab-bag of standalone utility commands (`misc`).

### Key components
| Component | Responsibility |
|---|---|
| `InstlClient` | Base for all client operations; owns the `do_command()` pipeline (read YAML → resolve inheritance → calculate install items → dispatch `do_<command>` → write batch), plus cross-folder bookkeeping, sync-location computation, and require-file lifecycle. |
| `InstlClientFactory` | Command→class dispatcher; lazily instantiates the right subclass and builds the synccopy class inline. |
| `InstlClientCopy` | Generates copy/unwtar instructions per target folder and IID, plus pre/post-copy actions and the require-file update. |
| `InstlClientRemove` | Generates remove instructions (reverse-folder order) honoring per-item overrides. |
| `InstlClientUninstall` | Reference-counts which IIDs are no longer required and reuses remove instructions to uninstall them. |
| `InstlClientReport` | Read-only reporting; emits text/json/yaml to the out-file instead of running a batch. |
| `InstlDoIt` | Separate top-level mode; resolves a depends-ordered IID list and emits pre/doit/post action commands. |
| `InstlMisc` | Separate utility mode; standalone subcommands (wtar/unwtar/checksum/ls/resolve/exec/run-process/version/help/fail) and the download telemetry orchestration for check-checksum. |
| `installItemGraph` | Thin networkx wrapper for cycle/needed-by queries (not on the main copy/remove path, which uses SQL recursion). |

### Public interface
- `InstlClientFactory(initial_vars, command) -> InstlClient subclass` — called by the entry point for `client` mode.
- `InstlClient.do_command()` — the workflow entry invoked after `init_from_cmd_line_options()`.
- `InstlDoIt(initial_vars).do_command()` and `InstlMisc(initial_vars, command).do_command()` — `doit` / `do_something` (and command-list) modes.
- The `do_<fixed_command>()` convention resolved via `getattr` in `do_command`.
- `installItemGraph.create_dependencies_graph / create_inheritItem_graph / find_cycles / find_needed_by` — used by base-class dependency queries and admin `depend`.

### Owned state & persistence
Reads the index YAML into the index DB (item + detail tables) and the info-map into the svn table.
`calculate_install_items()` mutates per-IID install-status columns and writes derived lists into config
vars. In-memory bookkeeping (items-by-target-folder, no-copy-by-sync-folder, auxiliary IIDs) flows
between methods. The `do_<command>` methods append PyBatch commands into sectioned accumulators;
`command_output()` serializes them to a batch file, dumps config vars, and optionally runs it.
Persistent side effects: the index SQLite DB, the require-file lifecycle on disk, the generated batch
file, the sync-folder manifest, and the have-info-map copied to the site. Report mode routes output to
the out-file instead.

### Dependencies
- **Out:** Data Tables (index DB + info-map); ConfigVar System; PyBatch; Sync Backends/Connections; aYaml & Utils; Download Subsystem (misc check-checksum telemetry).
- **In:** the CLI dispatcher; admin; interactive.

### Design notes & constraints
- `InstlClient` is a god-class bundling pipeline orchestration, DB status mutation, target-folder bookkeeping, sync-location computation, require-file I/O, and name resolution; subclasses inherit all of it. *(Modernization: now composed from the `pyinstl/client/` mixin package — `_core`/`_install_items`/`_require`/`_actions`/`_binaries`/`_sync_locations`/`_remove_sources`/`_naming` — behind a `pyinstl/instlClient.py` shim; behavior identical. The deeper collaborator extraction remains pending.)*
- Calculation results are passed between methods implicitly through config-var keys, making data flow order-dependent.
- Mac/Win platform handling is interleaved through the copy logic.
- The misc check-checksum command has grown into a cross-subsystem download-telemetry orchestrator.
- There is **no `install` or `repair` subcommand**: the actual client command catalog (see `pyinstl/cmdOptions.py`) is `copy`, `sync`, `synccopy`, `remove`, `uninstall`, `report-versions`, `read-yaml`. "Install" is realized by `copy`/`sync`/`synccopy`, and "repair" is a *mode within* a sync/synccopy run, triggered by the `__REPAIR_INSTALLED_ITEMS__` pseudo-IID in `MAIN_INSTALL_TARGETS` (`InstlClient.update_mode`) — not a top-level command.
- Consumer mapping (Waves Central, the primary consumer, confirmed against its `ShellInstl` layer): online install → `synccopy`; create-installer (sync) → `sync`; offline install / create-installer (copy) → `copy`; uninstall → `uninstall`; report-versions → `report-versions`; version-organizer/permission-fixer/cleanup scripts → `exec`/`doit`. Central drives each via `"<instl>" <command> --in <in.yaml> --out <out.py> --log <buffer> --run`; `report-versions` is invoked **without `--run`** (it emits JSON directly rather than a runnable batch — matching `InstlClientReport.do_report_versions`, which writes `output_data` instead of accumulating a batch). The legacy `instl-V9`/`instl-V10` engines do not support `--log` and the consumer redirects stdout/stderr to a buffer file instead.

---

## 4. Sync Backends & Connections

### Responsibility
Decide how a client deployment fetches its files from a remote repository and generate the batch
instructions to do so. Provide an abstract sync-backend base with four concrete backends (URL/static-
links, SVN, P4, boto/S3) selected at runtime by the repo-type config var, plus a connection abstraction
handling URL translation, cookies/custom headers, and (optionally) S3 signed URLs. The URL backend is
the only fully-maintained path.

### Key components
| Component | Responsibility |
|---|---|
| `InstlInstanceSync` | Abstract base for all sync backends; owns the shared info-map read/mark pipeline used by download-style backends. |
| `InstlInstanceSync_url` | Primary backend; generates curl download instructions with resume, adaptive concurrency, pause/resume control, and redundant-file cleanup. |
| `InstlInstanceSync_svn` / `InstlInstanceSync_p4` | Emit `svn co` / `p4 sync` command strings per source (unmaintained). |
| `InstlInstanceSync_boto` | S3/boto stub; sets the local sync dir only, no instructions. |
| `ConnectionBase` / `ConnectionHTTP` / `ConnectionS3` | Abstract connection holding the global singleton; HTTP per-netloc session cache with permissive SSL; S3 signed-URL generation (currently disabled). |
| `SSLContextAdapter` | requests adapter forcing a maximally-permissive OpenSSL context to survive corporate SSL-inspection proxies. |
| `connection_factory` / `translate_url` / `inject_truststore` | Module-level entry points: create/return the singleton connection, translate a bare URL to `(url, headers)`, optionally swap in OS-native TLS. |
| `InstlClientSync` | Client command class that selects the backend by repo-type and runs the pre/sync/post pipeline. |

### Public interface
- `InstlClientSync.do_sync()` — entry invoked by client command dispatch (synccopy delegates to it).
- `syncer.init_sync_vars()` and `syncer.create_sync_instructions()` — the two methods `do_sync` calls on every backend.
- `connection_factory(config_vars) -> ConnectionBase` singleton; `translate_url(bare_url, config_vars) -> (url, headers)` (passed as a download callback); `inject_truststore()`.

### Owned state & persistence
For the URL path: downloads the remote info-map into the svn table, marks required/to-download flags,
and writes bookkeeping info-map text files (new-have / required / to-sync). Computes per-file resume
decisions and feeds URLs into the download tool. All emitted work lands in the client's batch
accumulator; post-sync copies the new-have info-map to the persisted have-info-map. Persisted state:
the info-map SQLite DB, bookkeeping info-map files, curl `.part` temp files, and download session state.
The connection singleton caches per-netloc sessions and a sync-URL cookie. SVN/P4 bypass the info-map
and write command strings directly.

### Dependencies
- **Out:** Data Tables (info-map + items tables); ConfigVar System; PyBatch (sync/download command objects); Download Subsystem (state, concurrency, observability, control channel, events, curl helper); aYaml & Utils; the client base (sync-location, manifest, dirs).
- **In:** client command dispatch (`sync`/`synccopy`); the client YAML reader (connection factory); the misc `translate_url` command; interactive `do_sync`; the file download/read helpers (translate-url callback).

### Design notes & constraints
- The abstraction does not actually unify the backends: the info-map read/mark pipeline in the base only matters for URL/boto, while SVN/P4 bypass it. The URL backend is effectively the only real implementation; SVN/P4 use a different (raw-command-string) paradigm and are unmaintained.
- The boto path is dead (gated off); a `BOTO` repo type silently produces no download work.
- The connection is a process-wide mutable singleton (not thread-safe, not reset between invocations); the HTTP SSL context is deliberately permissive for proxy survival.
- For online runs the consumer (Waves Central) supplies the repo-access parameters in the input YAML rather than instl discovering them: `BASE_LINKS_URL` (`https://<ResourceRootUrl>`), `COOKIE_JAR` (`<ResourceRootUrl>:CloudFront-Key-Pair-Id=..;CloudFront-Policy=..;CloudFront-Signature=..`), and `REPO_REV_EXT` (`.<repoRev>` or empty). The CloudFront signed-cookie credentials drive `translate_url`/`ConnectionHTTP`; the index is then fetched from `$(BASE_LINKS_URL)/$(TOP_DIR_FOR_VERSION)/$(REPO_REV)/instl/index.yaml`.

---

## 5. Download Subsystem (curl-based bulk download engine)

### Responsibility
Drive instl's bulk file download: build curl config files and parallel-run plans, classify and retry
transfer failures, support cooperative pause/resume/try-now via a stdin control channel, persist
per-session and per-file download state plus resume sidecars, sample throughput/errors, recommend
between-session concurrency, emit a structured JSON-line event channel to Central, and tag installs
into rollout cohorts. The curl driver itself lives in PyBatch; this subsystem provides the planning
and the side-channel machinery consumed at two choke points: URL sync planning and checksum-verify
redownload.

### Key components
| Component | Responsibility |
|---|---|
| `CUrlHelper` (+ `CurlDownloadEntry`/`CurlConfigFile`) | Accumulate download URLs; partition fresh vs resume entries; write curl config files and the parallel-run plan; emit the curl batch commands. |
| `DownloadControlChannel` | Daemon-thread stdin reader + shared pause/try-now state for cooperative pause/resume/offline-hold; module-level singleton. |
| `downloadFailures` | Normalize curl exit codes, HTTP statuses, and exceptions into one failure taxonomy with retryability and Retry-After. |
| `downloadRetry` | Data-driven per-class retry policy, exponential+jitter backoff honoring Retry-After, and a try-now-aware sleeper. |
| `downloadState` | On-disk download state: session and per-file records, `.part` temp naming/promotion, and the resume-eligibility decision. |
| `DownloadObservability` | In-process per-session aggregator; persists a session summary read by the concurrency controller next run. |
| `downloadConcurrency` | Between-session adaptive parallelism recommendation from the previous session summary. |
| `downloadEvents` | Single source of truth for the structured telemetry channel (with a privacy denylist and kill switch). |
| `downloadCohort` | Normalize/downgrade a rollout cohort label to match the active feature-flag set. |
| `ParallelRun` / `CurlWithInternalParallel` (in PyBatch) | The actual curl execution engine: pause/offline-hold loop, network-error backoff, and exit-33 fresh-restart fallback. `CurlWithInternalParallel` (the shipped path) additionally probes connectivity and holds through outages (`DOWNLOAD_OFFLINE_HOLD_ENABLED`), reconciles missing outputs after curl exit 0 (`DOWNLOAD_RECONCILE_MISSING_OUTPUTS`), and backstops silent stalls (`DOWNLOAD_CURL_STALL_DETECTION` + watchdog) — new-event emission gated on the client's `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` declaration. |

### Public interface
- `CUrlHelper.add_download_url(...)` and `CUrlHelper.create_download_instructions(dl_commands)` — called by URL sync planning; appends the curl batch commands.
- `downloadState.resume_decision_for_download_item(...) -> DownloadResumeDecision`; `promote_verified_temp_file(...)`; `update_session_state(...)`.
- `downloadFailures.classify_*(...) -> DownloadFailureInfo`; `downloadRetry.decide_retry(...) -> RetryDecision`; `downloadRetry.sleep_backoff(delay, channel=)`.
- `downloadControlChannel.get_global_channel()` and channel `wait_if_paused()` / `sleep_or_wake()` / `is_paused()` / `try_now_requested()` plus pause/resume callbacks.
- `downloadObservability` session/record/load functions; `downloadConcurrency.resolve_concurrency_from_config(...)`; `downloadEvents.emit_*(...)` / `set_telemetry_enabled(...)`; `downloadCohort.resolve_cohort_from_config(...)`.

### Owned state & persistence
On disk under the bookkeeping download-state folder: `session.json`, per-file sidecars, `.part` temp
artifacts, and `session-summary.json`. The session summary is the cross-run channel — written at
session end, read next run to recommend parallelism. In-memory: the control-channel pause/try-now
events (singleton), the active observability session (singleton), the curl-internal-parallel-support
cache, and the telemetry-enabled flag.

### Dependencies
- **Out:** ConfigVar System; connection layer (URL translation); PyBatch (curl drivers and emitted commands); its own internal modules (failures → retry/observability, state → planning, control channel → retry + drivers, observability → concurrency, cohort → events).
- **In:** URL sync planning; the PyBatch checksum-verify redownload command; the PyBatch curl drivers (control-channel singleton); Central (external consumer of events / producer of control commands).

### Design notes & constraints
- The pause/offline-hold/network-retry/exit-33-fallback loop is duplicated across the two curl drivers and has now drifted by design: the connectivity-loss self-sufficiency layer (offline-hold with probing, post-exit-0 output reconciliation, stall watchdog — all default-on kill switches, `defaults/InstlClient.yaml`) exists only in `CurlWithInternalParallel`; `ParallelRun` keeps the older bounded backoff (in-code `TODO(external-parallel)`), with the checksum phase as its completeness gate. The checksum-verify redownload cliff is also gone: with `DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES` (default yes) `MAX_BAD_FILES_TO_REDOWNLOAD` is a warn threshold and the redownload pass always runs, bounded by opt-in byte/time budgets (default unlimited) instead of a count cap.
- Several module-level mutable singletons (control channel, observability session, telemetry flag, parallel-support cache) require reset hooks for test isolation; coupling is via accessors rather than injection.
- The privacy denylist exists in two places kept "compatible" by comment and can silently diverge.
- Most modules are pure, side-effect-light, dependency-injected helpers; the design intent is that the two choke points wire them together.
- Control/observability is contracted with Waves Central (the consumer). The stdin control channel reads one-line JSON envelopes `{"cmd":"pause"|"resume"|"try_now","sessionId":...}` written by Central into instl's stdin (Central's `ILiveProcess.sendCommand`); pause is **cooperative between curl batches** (in-flight curl invocations finish naturally and `.part` artifacts are preserved), so pause latency is bounded by the current batch — it is **not** a process kill. The separate cancel path remains process-kill via the `run-process --abort-file` mechanism. `downloadEvents` emits `DOWNLOAD_EVENT <compact-json>` lines (schemaVersion 1; events `download.session_state`/`file_state`/`retry_decision`/`capability`/`session_summary`) that Central parses before the legacy `DOWNLOAD_RETRY_DECISION <json>` line, which is kept for backward compatibility.
- The control channel is only started for the URL-sync commands (`sync`, `synccopy`, `check-checksum`) — `_CONTROL_CHANNEL_COMMANDS` in `pyinstl/instl_main.py`.
- Feature-flag defaults live in instl's bundled `defaults/InstlClient.yaml`, **not** on the consumer side (Waves Central does not set these flags). On this branch the shipped values are: `DOWNLOAD_TELEMETRY_ENABLED`=yes, `DOWNLOAD_RETRY_POLICY_ENABLED`=yes, `DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED`=no, `DOWNLOAD_COHORT`=control, `DOWNLOAD_RESUME_ENABLED`=**yes**, and `DOWNLOAD_CENTRAL_UX_ENABLED`=**yes**. NOTE: per the POC decision log (D-004/D-005/D-018) the intended/merge-target defaults for `DOWNLOAD_RESUME_ENABLED` and `DOWNLOAD_CENTRAL_UX_ENABLED` are `no`; D-022 records that the POC branch intentionally ships Central UX (and resume) on-by-default and that these flags MUST be flipped back to default-off before merge to main. The on-branch `yes` values are deliberate POC state, not the steady-state contract. Resume is additionally gated to validated CloudFront hosts/paths plus a signed-URL TTL window (`DOWNLOAD_RESUME_MIN_SIGNED_URL_TTL_SECONDS`, default 300); a 200 response to a range request, an identity change, or a near-expiry signed URL forces a safe restart-from-zero. Adaptive concurrency is **between-session only** (reads the previous run's `session-summary.json`); its start value (`DOWNLOAD_CONCURRENCY_START`, default 8) differs from the legacy non-adaptive `PARALLEL_SYNC` default of 50. The connectivity-loss self-sufficiency gates also live there and default **on**: `DOWNLOAD_RECONCILE_MISSING_OUTPUTS`, `DOWNLOAD_OFFLINE_HOLD_ENABLED` (with probe/hold tunables), `DOWNLOAD_CURL_STALL_DETECTION` (+ watchdog), and `DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES` (+ opt-in redownload budgets, default unlimited) — each an independent kill switch surfaced on `download.capability.featureFlags`; only `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` (the handshake by which a new Central opts into the backend-hold event stream) defaults **off**, so an old Central sees exactly the legacy events while the engine recovers silently (see `docs/download-events.md` §3.6 and `docs/LLD.md` for the full table).

---

## 6. Admin Tooling

### Responsibility
The admin-side command monolith used by engineers/CI to build and maintain the deployment repository:
SVN maintenance (props/perms/symlinks, staging↔svn syncing, wtar-ing large files), info-map/index
integrity verification, building per-repo-rev artifacts and uploading them to S3 (`up2s3` /
`up-short-index`), activating a repo-rev on S3, a long-running Redis-triggered upload daemon, and
various utility/reporting commands. It owns almost no persistent state of its own; it orchestrates
PyBatch command objects and the inherited SQLite tables.

### Key components
| Component | Responsibility |
|---|---|
| `InstlAdmin` | God-class holding all admin command logic; one `do_<command>` method per CLI subcommand, dispatched dynamically. |
| `do_fix_props` / `do_fix_perm` / `do_fix_symlinks` | SVN-property / permission / symlink normalization. |
| `do_stage2svn` / `do_svn2stage` | Bidirectional staging↔SVN sync via directory comparison, with wtar checksum equivalence. |
| `prepare_conditions_for_wtar` / `do_wtar_staging_folder` | Decide which folders/files to wtar (split tar) and emit the commands. |
| `do_verify_index` / `do_verify_repo` | Cross-check the index against the info-map (missing inherit/depends, orphan sources, cycles, unrequired files). |
| `do_up2s3` / `up2s3_repo_rev` | Core release pipeline: checkout a repo-rev, build info maps, wzip the index, create short-index/repo-rev file, `aws s3 sync`, record in Redis, email a report. |
| `do_up_short_index` | Lightweight variant uploading only the short-index + repo-rev file. |
| `do_activate_repo_rev` | Promote an uploaded repo-rev file to the activated name in S3, verify, record, email. |
| `do_wait_on_action_trigger` | Long-running Redis daemon: pop triggers and spawn a fresh instl process per command. |
| `do_collect_manifests` / misc utilities | Manifest collection/merge, GUID translation, file sizes, integrity check, short-index, depend, config-var dump. |

### Public interface
- `InstlAdmin(initial_vars)` — instantiated by the entry point for `admin` and `interactive` modes.
- Standard run: `init_from_cmd_line_options(options)` → `do_command()` (dispatches `do_<fixed_command>`).
- `up2s3_repo_rev(...)` / `up_short_index_repo_rev(...)` — re-entered by the wait-trigger spawned subprocess.
- Module-level helpers: `start_redis_heartbeat_thread(...)`, `smart_merge_dicts(...)`, `dict_in_canonical_order(...)`.

### Owned state & persistence
Reads config from config vars (seeded from `InstlAdmin.yaml` + config files). Most commands build the
batch accumulator and write/run a batch script rather than acting directly. Persistent state is the
inherited SQLite info-map and items tables (populated from index/info-map files via PyBatch DB
commands). On-disk artifacts: temp svn proplist/info files, per-repo-rev folders with info maps, the
wzipped index, short-index and repo-rev files. External state lives in S3 (revision folders + admin
files) and Redis (done-lists, last/current keys, in-progress, heartbeat, waiting list, status via
config vars). The wait daemon spawns a separate instl process per trigger.

### Dependencies
- **Out:** Instance Base (batch accumulator, write/run batch, readers, tables, dependency queries); Data Tables (info-map + items); PyBatch (SVN/Wtar/InfoMap/Copy/Subprocess… commands); ConfigVar System; aYaml & Utils (checksums, email, regex); the dependency-graph helper; the entry point (re-entered by the daemon).
- **In:** the entry point (admin/interactive families, Mac/Linux only); interactive (receives an admin instance); CI/operators (lpush triggers to the daemon).

### Design notes & constraints
- Historically a single ~1500-line god-class spanning ~10 command clusters sharing mutable instance state. *(Modernization: `InstlAdmin` is now composed from the `pyinstl/admin/` mixin package — `_core`/`_repo`/`_wtar`/`_verify`/`_info`/`_publish` plus `_helpers` — behind a `pyinstl/instlAdmin.py` shim. Behavior, command dispatch, and emitted output are identical; the named command-cluster collaborators are still future work.)*
- `up2s3` and `up-short-index` share near-identical threshold/assert/Redis/email scaffolding kept in sync by hand.
- Config vars double as a status/inter-step messaging channel (status/exception keys feeding the email template).
- External clients (Redis, boto3) are constructed inline in multiple methods; some filesystem commands perform direct side effects (immediate unlink) rather than emitting batch ops; several silent except-pass blocks hide failures.

---

## 7. GUI

### Responsibility
A Tk/ttk desktop front-end with three tabs (Client, Admin, Activate). It does **not** run instl logic
in-process to execute commands; each tab builds an instl command line from config vars and spawns it
as an external subprocess. The GUI is itself an instl instance (subclasses Instance Base) and reuses
base-class config resolution, YAML read/write, version string, and history persistence. The Activate
tab additionally talks directly to Redis to display/activate/upload repo-revs.

> *Modernization:* the GUI was decomposed from one `pyinstl/instlGui.py` file into the
> `pyinstl/gui/` package (`_globals`/`_tkvars`/`_tooltip`/`_frame_base`/`_client_frame`/`_admin_frame`/
> `_activate_frame` + `__init__`) behind a `pyinstl/instlGui.py` shim. The components below are
> unchanged in behavior; the single Tk root still lives at module import time (now in
> `gui/_globals.py`, not yet lazy).

### Key components
| Component | Responsibility |
|---|---|
| `CreateTkConfigClass` (→ `TkConfigVarStr/Int/Bool`) | Factory producing a two-way binding between a Tk variable and an instl config var via a guarded double-callback. |
| `FrameController` | Base for per-tab controllers; owns a frame, the tk-var dict, and shared widget-building / file-dialog / subprocess / error-parsing helpers. |
| `ClientFrameController` | Client tab: choose command, input/output files, credentials, run flag; build and run the client command line. |
| `AdminFrameController` | Admin tab: pick admin command, config files, limit/run; read admin config YAMLs to populate displayed fields; build and run via per-command templates. |
| `ActivateFrameController` | Activate tab: connect to Redis, poll repo-rev/upload keys into a Treeview, show heartbeat/in-progress, push activate/upload requests onto a Redis waiting list. |
| `InstlGui` | The GUI instl instance; owns the Tk master window and the notebook, instantiates the controllers, persists GUI state to a YAML history file. |
| `admin_command_template_variables` | Module-level map from admin command name to the command-line template var. |

### Public interface
- `InstlGui(initial_vars)` — constructed by the entry point for `gui` mode.
- Standard lifecycle: `init_from_cmd_line_options(options)` → `do_command()` (build GUI, mainloop) → `close()`.
- `CreateTkConfigClass(...)` and the produced `TkConfigVar*` classes; the frame controllers are internal to `InstlGui`.

### Owned state & persistence
Tk widget values are bound bidirectionally to config vars. GUI window/tab/field state is serialized to
a YAML history file (read on startup, written on tab change/quit). The Activate tab owns separate
state in Redis: polled repo-rev/upload keys, heartbeat/in-progress keys, and activate/upload requests
pushed onto a per-host waiting list. Running a tab spawns the instl executable as a subprocess; stderr
is captured, scanned for a JSON exception blob, and surfaced in a message box.

### Dependencies
- **Out:** Instance Base; ConfigVar System; aYaml & Utils (history serialization, Redis client); the instl executable itself (spawned as a CLI); Tk/ttk, subprocess, Redis.
- **In:** the entry point (`gui` mode).

### Design notes & constraints
- The Tk root is created at import time (a global), which makes the module non-importable headless and couples consumers to a global window.
- `FrameController` mixes UI layout, file dialogs, subprocess spawning, and stderr parsing; the subprocess-spawn + platform branch is duplicated across four call sites with slight inconsistencies.
- Error reporting depends on fragile regex-over-stderr JSON parsing; the Activate tab reaches through the GUI instance into the notebook widget to schedule its polling timer.

---

## 8. PyBatch Command Objects

### Responsibility
Provide instl's object model for deployment actions. Every concrete installation/admin step (copy,
remove, download, wtar, chmod, svn, registry, symlink, conditional, reporting, subprocess) is a
command class with a **dual identity**: at runtime it executes the action via the context-manager/
call protocol, and its `repr` emits eval-able Python source so the whole plan can be written to a
standalone "python batch" script that runs the same classes later. An accumulator groups commands into
ordered sections and renders the entire script.

### Key components
| Component | Responsibility |
|---|---|
| `PythonBatchCommandBase` | Abstract base for all commands; dual identity (execute + serialize); owns the progress/staging/error-reporting/serialization machinery and the command-tree building. |
| `PythonBatchCommandAccum` | Top-level accumulator holding commands by named section; renders the full batch script via `repr`. |
| `RunProcessBase` | Base for any subprocess-spawning command (curl, shell, chmod/chown, svn, …); centralizes `subprocess.run`, stderr-as-error policy, and ignored exit codes. |
| `RsyncClone` | Base copy engine mimicking rsync (recursive copy, hard-link, ignore patterns, delete-extraneous); parent of all copy/move commands. |
| `CheckDownloadFolderChecksum` / `CurlWithInternalParallel` / `ParallelRun` | Runtime download/verify commands; checksum verification with control-channel-aware retry, and the curl execution engine with pause/offline-hold and fallback. |
| Conditionals (`If`, `Is*`, `ForInConfigVar`) | Flow control evaluating callable/bool/eval-able-string conditions and looping over config-var lists. |
| File-system / archive / svn / removal / info-map / platform command families | The full action taxonomy (MakeDir/Chmod/Chown, Wtar/Unwtar/Wzip, SVN*, Rm*, InfoMap*/IndexYamlReader, POSIX/Mac/Win commands). |
| `EvalShellCommand` | Bridge that `eval`s an index.yaml action string into a command object, falling back to a shell command. |

### Public interface
- `from pybatch import *` (or named imports) re-exports the entire taxonomy.
- `PythonBatchCommandAccum()` constructed by Instance Base; callers set the current section then `accum += SomeCommand(...)`; `repr(accum)` renders the full script written to the out-file.
- The `__init_subclass__` class params (`essential`, `call__call__`, `is_context_manager`, `is_anonymous`, `kwargs_defaults`) are the declarative authoring API.
- Runtime contract per command: `with Cmd(args) as c: c()` (or bare `Cmd(args)()` when not a context manager) — exactly what the generated script and internal composition use.
- Command-author contract: implement `__init__` (record args), `repr_own_args`, `progress_msg_self`, `__call__`.
- `RsyncClone` classmethods set process-wide copy policy; the DB-manager mixin gives info-map/svn commands their tables.

### Owned state & persistence
Build phase: an in-memory tree of child commands grouped by section (nothing persisted except config
vars). Serialize phase: `repr(accum)` emits the eval-able Python script (wrapped in a runtime) to the
out-file. Run phase: the script re-imports pybatch and re-instantiates the classes; run-scoped
counters, the stage stack, the timing map, and the repr config-vars snapshot are class-level (shared)
state on the base. Persisted by this subsystem: the emitted batch script and its timings twin; files
created/copied/removed by FS commands; the JSON error report; download temp files and resume sidecars.
The info-map/svn commands read/write the SQLite tables via the DB-manager mixin (owned by Data Tables).

### Dependencies
- **Out:** ConfigVar System (defaults, resolution, scopes); aYaml & Utils (path resolution, checksums, parallel run, multi-file reader, who-locks-file); Data Tables (DB-manager mixin for info-map/svn commands); aYaml emission; Download Subsystem (resume/retry/telemetry, imported by the download commands); third-party (requests, psutil, packaging; Windows/macOS specifics).
- **In:** Instance Base (owns the accumulator); client subclasses; admin; misc/doit/sync/curl helper; the generated batch scripts themselves; some utils/help modules; index.yaml action strings.

### Design notes & constraints
- The base class is a god-object mixing execution, serialization, progress accounting, the stage stack, timing, error-report assembly, and tree building.
- Run-scoped state (progress, stage stack) is class-level and therefore process-global and not thread-safe — a constraint for any threaded execution.
- The repr→eval round-trip means every command must keep `__init__` and `repr` in perfect sync, and arbitrary index.yaml strings reach `eval` — a security-sensitive, security/maintenance-sensitive footgun acknowledged in the design.
- Heavy platform branching lives inside individual classes; the platform-specific class selection happens at package import time.

---

## 9. ConfigVar System

### Responsibility
The configuration-variable engine underpinning all of instl. It models each config variable as a
multi-valued, lazily-resolved object held in a scoped stack of dicts, exposes a single process-wide
global `config_vars`, implements the `$(NAME<params>[index])` resolution mini-language via a
hand-written state-machine parser, and loads variable definitions from YAML (including conditionals,
includes, and environment imports). It is the substrate every other subsystem reads/writes settings
through.

### Key components
| Component | Responsibility |
|---|---|
| `ConfigVar` | One config variable holding zero-or-more string values, resolved lazily on access; behaves polymorphically as str/list/int/float/bool/path. |
| `ConfigVarStack` | The scoped stack of dicts implementing scoping/overrides and the `$()` resolution engine; full mutable-mapping protocol. |
| `config_vars` / `private_config_vars` | The single process-wide global stack; and a context manager yielding a throwaway fresh stack. |
| `var_parse_imp` (+ `VarParseImpContext`, `ParseRetVal`) | Generator-based state machine scanning a string and yielding literal segments and `$(...)` references with params and array index. |
| `ConfigVarYamlReader` | YamlReader subclass interpreting `!define` / `!define_if_not_exist`, includes, environment imports, conditionals, and the `!+=` append tag. |
| `smart_resolve_yaml` / `eval_conditional` | Recursively resolve `$()` in a YAML node tree (expanding list vars) and evaluate `__if*__` guards. |

### Public interface
- `from configVar import config_vars` — the global stack imported by ~all subsystems.
- Mapping API: `config_vars[KEY] = value`, `config_vars[KEY]` (returns a `ConfigVar`), `KEY in config_vars`, `get`, `setdefault`, `defined`.
- Resolution API: `resolve_str(s)`, `resolve_str_to_list(s)`, `resolve_list_to_list(list)`.
- Scope/lifecycle: `push_scope_context()`, `set_dynamic_var(name, callback, initial_value)`, `read_environment(names)`.
- `private_config_vars` for an isolated stack; `ConfigVarYamlReader` to load definitions (`read_yaml_file(path)`); `smart_resolve_yaml`, `eval_conditional`; `var_stack` (backward-compat alias).

### Owned state & persistence
All state lives in memory in the global stack (a list of dicts of `ConfigVar`); each var owns only its
raw string values, resolved lazily through the owner stack. There is **no** persistence to disk or DB
by this subsystem itself — it is the runtime source of truth, fed at startup by the YAML reader (and
include chains and environment imports). Scoping writes to the top level and shadows outer levels;
resolving params/index temporarily pushes a scope. Resolution short-circuits when no `$` is present.
Caching was removed (documented), so resolution is recomputed each time.

### Dependencies
- **Out:** aYaml (YamlReader base, dump wrap); aYaml & Utils (`SearchPaths`, str/number conversion).
- **In:** essentially every subsystem (pybatch/*, db, svnTree, pyinstl/*, help) imports and mutates the global stack.

### Design notes & constraints
- A process-wide mutable global singleton: ~50 modules import and mutate it, so state is implicit, test isolation is hard, and it is not concurrency-safe; `private_config_vars()` shows the local-stack pattern that could generalize.
- `eval_conditional` uses `eval()` on YAML-supplied conditions (with `os`/`sys` deliberately importable) — arbitrary code execution from config, a known constraint.
- `ConfigVarStack` is a god-object mixing container, resolver, YAML dumper, OS-native-pattern rewriting, environment import, and statistics; there are several overlapping resolution code paths (the canonical parser vs bespoke regexes).
- `ConfigVar` is tightly bound to the stack's resolver method names.

---

## 10. Data Tables (svnTree + db)

### Responsibility
The SQLite-backed data layer. It owns the single shared database (in-memory or on disk) and the
logical tables modeling an installation: the info-map / svn file table (every file and directory in
the repo with revision, checksum, size, download state), the index-item tables (the IID install items
parsed from index/require YAML with inheritance resolved), and auxiliary tables (active OSes, config
vars, iid↔svn-item bridge, found binaries, require-translate). It is a pure persistence/query layer:
it parses input files into rows, runs the heavy set-based SQL, and hands rows back; it does not decide
install policy or touch the filesystem beyond reading source files.

### Key components
| Component | Responsibility |
|---|---|
| `DBMaster` | Owns the sqlite3 connection/cursor and all lifecycle, transaction, and execution primitives; runs the DDL scripts; registers SQL functions; locks tables. |
| `DBAccess` | Descriptor lazily creating the singleton `DBMaster`, resolving the DB path and DDL folder from config vars and handling refresh. |
| `TableAccess` | Descriptor lazily instantiating a table object bound to the shared `DBMaster`. |
| `DBManager` | Mixin/base exposing the singletons `db`, `info_map_table`, `items_table` to every subclass; the public entry point. |
| `SVNTable` / `SVNRow` | All reads/writes/queries over the info-map table; parses svn-info/info-map/props/file-sizes; computes required/need-download flags via recursive SQL; resolves download URLs. Row wrapper with file/dir/wtar predicates. |
| `IndexItemsTable` | All reads/writes/queries over the index item + detail tables plus OS-activation/config-var/binaries/require tables; parses index/require YAML, resolves inheritance, answers install-planning queries. |

### Public interface
- Subclass `DBManager` to inherit the three lazy singletons (`db`, `info_map_table`, `items_table`) — the dominant access pattern.
- `DBManager.set_refresh_db_file(bool)` / `reset_db()` for lifecycle.
- `DBMaster` primitives: `open()`, `transaction()`/`selection()`/`temp_transaction()` context managers, `select_and_fetchone/all`, `create_function`, `lock_table/unlock_table`, `close()/close_and_delete()`.
- `SVNTable` surface: `read_from_file`, `get_items` / `get_required_items` / `get_download_items` / `get_items_in_dir`, `mark_required_for_source`, `mark_need_download`, `write_to_file`, `get_sync_url_for_file_item`, sync-folder diff.
- `IndexItemsTable` surface: `read_index_node`, `read_require_node`, `resolve_inheritance`, `activate_*_oses`, status changes, `get_resolved_details_*`, `get_sources_for_iid`, `iids_from_guids`, the `install_status` map.

### Owned state & persistence
All three table classes share one `DBMaster` (one sqlite3 connection) created lazily from the main-DB
config var (`:memory:` by default, or a file next to the in/out file or in the Logs folder). On open
it runs the create-tables/init-values/create-indexes DDL. It owns the svn-item table (one row per repo
file/dir), the index item and detail tables (IIDs and their property-bag details), the iid↔svn-item
bridge, and the auxiliary tables. Typical flow: YAML → insert rows → resolve inheritance → activate
OSes → set install status → load info-map → mark required/need-download → return rows to sync/copy.
Cross-table SQL joins the svn table against the index tables in single transactions.

### Dependencies
- **Out:** ConfigVar System (paths/values/flags); aYaml & Utils (grouping, checksums, SQL quoting, file helpers); aYaml/YamlReader (node parsing); the DDL schema scripts; PyBatch `RmFile` (on delete).
- **In:** Instance Base (the reader mixin inherits `DBManager`) and the whole instl command hierarchy; the sync backends; PyBatch svn/info-map commands.

### Design notes & constraints
- Both `SVNTable` and `IndexItemsTable` are god-objects (~1600 / large) mixing parsing, bulk insert, many query helpers, mutation, and reporting; the two "separate" tables are coupled because the info-map layer reaches directly into the index tables in raw SQL.
- The DB is an app-wide implicit global via the class-level descriptors (`reset_db()` exists precisely to fight this); it should ideally be an injected dependency.
- Transaction nesting is hand-rolled and fragile (and swallows operational errors); query-builder boilerplate and IN-list quoting are duplicated and inconsistent.
- `SVNRow` unpacks columns positionally, coupling it to `SELECT *` order.

---

## 11. aYaml & Utils

### Responsibility
Two foundational layers used everywhere. **aYaml** is instl's augmented-YAML layer on top of PyYAML:
it adds type/iteration/indexing helpers to YAML nodes, provides a tag-dispatching document-reader base
class (`YamlReader`) that other readers subclass, and a hand-rolled writer supporting tags, comments,
aliases, and controlled indentation PyYAML cannot easily produce. **Utils** is the shared toolkit:
file/URL I/O with checksum caching and wtar handling, OS/arch detection, checksum utilities, ordered/
unique collections, parallel subprocess execution with pause/abort/offline-resume semantics, a
multi-file streaming reader for split wtars, binary version/GUID extraction, disk listing, logging
configuration, macOS dock manipulation, and email sending.

### Key components
| Component | Responsibility |
|---|---|
| `YamlReader` / `YamlNodeStack` | Base reader: read a file/URL, split into tagged documents, dispatch each to a tag-specific reader; track a read stack and deferred post-documents. Node stack for source-location error messages. |
| `writeAsYaml` / `YamlDumpWrap` / `YamlDumpDocWrap` / `Indentor` | Recursive hand-written YAML serializer with tags/comments/sorting/aliases and controlled indentation. |
| node patching / `nodeToPy` | Import-time monkey-patches on PyYAML node classes adding type/iteration helpers; node-tree → Python conversion. |
| file/URL I/O (`open_for_read_file_or_url`, `download_*`, file ops) | Unified local-or-URL reading with checksum-gated caching and wtar handling; chown/chmod, safe-remove, smart copy, walks, path resolution, who-locks-file. |
| `misc_utils` | OS/arch detection, checksum suite, wtar name parsing, ordered/unique collections, formatting, timing, the action-breadcrumb stack. |
| `run_processes_in_parallel` / `MultiFileReader` | Parallel subprocess execution with abort/pause/offline-resume and SIGTERM-based termination; a continuous stream over split wtar parts. |
| `extract_info` / `ls` / `log_utils` / `dockutil` / `email_utils` | Binary version/GUID extraction; disk listings; logging configuration; macOS dock; SMTP email. |

### Public interface
- `aYaml` re-exports `YamlDumpDocWrap`, `YamlDumpWrap`, `writeAsYaml`, `nodeToPy`, `YamlReader`. Subclass pattern: `class X(aYaml.YamlReader)` overriding `init_specific_doc_readers()`; entry call `read_yaml_file(path, ...)`.
- `writeAsYaml(pyObj, out_stream, ...)` — used by pybatch, report/admin/client/gui modules, and the data tables.
- `utils/__init__` flattens the toolkit into the `utils` namespace; callers use `utils.<name>`. Key entries: `run_processes_in_parallel(...)`, `MultiFileReader(...)`, `check_binaries_versions_in_folder` / `extract_binary_info`, `disk_item_listing` / `single_disk_item_listing`, `config_logger` / `setup_file_logging`, `PAUSED_EXIT_CODE`, `NETWORK_ERROR_CURL_EXIT_CODES`.

### Owned state & persistence
`YamlReader` owns mutable read state (read stack, deferred post-documents, per-node reader registry) and
appends every read file path into config vars. Utils owns several module globals: the acting uid/gid
(set via a config-var callback, consumed by all chown/chmod), the parallel-run state (exit/aborted/
paused/process-list, reset per run), the action breadcrumb stack, and the buffer-until-error logger
state. Persistence to disk: cached/downloaded files keyed by checksum/url, log files under the user
data dir, and curl `.part` temp files preserved across pause/resume. No DB tables are owned here.

### Dependencies
- **Out:** str utilities; `SearchPaths` (path searcher); ConfigVar System (the config-vars dict contract; JSON-into-config-vars); third-party (PyYAML, urllib/requests, ssl/certifi, zlib, psutil, appdirs, win32/macOS subprocess tools, tarfile/hashlib/smtplib).
- **In:** ConfigVar System (its YAML reader subclasses `YamlReader`); pyinstl (yaml read/write, parallel run, ls, binaries); pybatch (`writeAsYaml`, multi-file reader, ls, extract-info, file ops); the data tables; help.

### Design notes & constraints
- aYaml monkey-patches global PyYAML node classes at import time — process-wide mutation that is order-dependent and brittle across PyYAML upgrades, and impossible to opt out of.
- `writeAsYaml` uses call-stack frame inspection to decide top-level newline emission (fragile); mapping lookup is O(n) and node iteration mutates nodes in place.
- Utils relies on module-global mutable state for parallel execution and acting uid/gid, making it non-reentrant and thread-unsafe.
- Heavy platform branching is scattered; some vendored code (dock utility) targets long-dead OS/Python APIs; broad except-pass and `eval()` (email templates) are present — known robustness/security constraints.
