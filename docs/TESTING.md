# instl Testing & Coverage Map

> Purpose: give anyone refactoring instl a truthful picture of **what is tested, what isn't, and how to pin behavior before touching the dangerous parts.** This is a map for making refactors *safe*, not a tutorial on writing new features.

instl is a YAML-driven deployment engine whose central trick is *plan → emit an eval-able Python "batch" script → run it*. That repr→eval round-trip, a process-wide `config_vars` global, and several god-classes are the highest-risk things to change. The test suite covers the **download subsystem** and the **pybatch command objects** well, the **data/config/yaml foundations** moderately, and the **command-orchestration god-classes** thinly: `InstlClient` now has characterization goldens under `tests/characterization/` covering graph resolution and copy-command generation, while `InstlAdmin`, `InstlGui` and `InstlInstanceBase` still have **no tests at all**.

---

## 1. How to run the tests

### Prerequisites
- **Python 3.12** (shebangs and `create_venv.sh` hard-pin `python3.12`).
- A virtualenv created by the repo's own script:
  ```bash
  ./create_venv.sh          # creates ./venv, installs requirements_mac_only.txt then requirements.txt
  source venv/bin/activate
  ```
  On Windows/Linux substitute the matching `requirements_win_only.txt` / `requirements.txt`. `requirements_admin.txt` is only needed for admin-mode (svn/boto/redis) work.
- Tests are plain `unittest`; there is no `pytest.ini`, `tox.ini`, or `setup.cfg`. `pytest` is **not** used and not a requirement — it is absent from every `requirements*.txt`, and no test module imports it. A root `conftest.py` does exist, but it is a pytest-only import-order shim (it imports `pyinstl.curlHelper` first to sidestep the `pybatch` ↔ `pyinstl` cycle); it has no effect under `unittest`.

### Running everything
There is no per-package aggregate runner worth using. The only one left is `aYaml/test/test_all.py` (it runs just `TestAugmentedYaml`); `pyinstl/test_all.py` no longer exists. Everything else — `pybatch/test/*`, `configVar/test/*`, `utils/test/*`, every `pyinstl/test/test_download*.py`, and the `tests/characterization/` goldens — is reached only by discovery or by naming the module directly.

### Recommended way to actually run them all
From the repo root, with the venv active:
```bash
# discover-based aggregate run across every package (recommended)
python -m unittest discover -s . -p "test_*.py" -t .

# or per-package, e.g.:
python -m unittest discover -s pybatch/test -p "test_*.py" -t .
python -m unittest discover -s pyinstl/test -p "test_*.py" -t .
python -m unittest discover -s configVar/test -p "testConfigVar.py" -t .
python -m unittest discover -s aYaml/test -p "test_*.py" -t .
python -m unittest discover -s utils/test -p "test_*.py" -t .
python -m unittest discover -s tests/characterization -p "test_*.py" -t .

# single download module:
python -m unittest pyinstl.test.test_downloadState -v
```

### Gaps / caveats when running
- **`sys.path` hacking:** test files append parent dirs to `sys.path` at import time and then do top-level imports like `from downloadState import ...` and `from db.indexItemTable import ...`. Run from the repo root (or with the venv's site path set up) or imports break.
- **Platform-gated suites:** `test_MacOnlyBatchCommands.py` and `test_WinOnlyBatchCommands.py` are OS-specific; many pybatch tests branch on `sys.platform` and skip/alter behavior off-platform. A "full pass" on macOS is not the same set of assertions as on Windows.
- **Side-effecting tests:** the pybatch suite writes into a real `python_batch_test_results/` directory tree and `compile()`/`exec()`s generated scripts (real filesystem I/O). Some tests need write/permission access and a working `rsync` (the `RsyncClone` hard-link test is documented as flaky).
- **The full discovery run is not green on Windows.** A `python -m unittest discover -s . -p "test_*.py" -t .` from the repo root ran **740 tests: 19 failures, 79 errors, 76 skipped**. Every failure/error was in the side-effecting `pybatch` suites (`test_copyBatchCommands`, `test_fileSystemBatchCommands`, `test_WinOnlyBatchCommands`, `test_removeBatchCommands`, `test_subprocessBatchCommands`, `test_conditionalBatchCommands`, `test_reportingBatchCommands`, `test_wtarBatchCommands`) plus 2 in `configVar/test/testConfigVar.py` (`test_readFile`, and a `$()`-resolution case) that also fail in isolation. Causes seen include `Chmod`'s Windows symbolic-mode parsing, registry tests needing elevation, and missing `rsync` — i.e. mostly environmental, not download-related. **This has not been triaged item by item; do not read "green" into it.** The download suites (189 tests) and the characterization goldens (25 tests) both pass cleanly on their own.
- **No coverage tooling is configured.** `.codeclimate.yml` and `.landscape.yml` only configure *static* analysis (and `.landscape.yml` disables pyflakes); neither runs tests or measures coverage. There is no CI test gate in-repo.
- **No code coverage numbers exist** — assessments below are by inspection (test files present vs. source modules), not measured line coverage.

---

## 2. Current coverage map

Assessment scale: **Well-covered** (multiple dedicated tests exercising behavior, not just smoke) · **Moderate** (one focused file, real assertions) · **Thin** (token coverage / indirect only) · **None** (no test touches this module).

| Subsystem | Source (representative) | Test files present | Assessment |
|---|---|---|---|
| **Download subsystem** | `downloadState.py`, `downloadRetry.py`, `downloadFailures.py`, `downloadControlChannel.py`, `downloadObservability.py`, `downloadEvents.py`, `downloadTransfer.py`, `downloadVerify.py`, `curlHelper.py` | **15 files** in `pyinstl/test/`: `test_downloadPromotion` (33), `test_downloadEvents` (25), `test_downloadRetry` (21), `test_downloadState` (21), `test_downloadTweaks` (19), `test_downloadObservability` (13), `test_downloadControlChannel` (21), `test_redownloadBudget` (11), `test_resumeJournal` (11), `test_downloadChunkAbandon` (11), `test_installLifecycle` (9), `test_downloadFailures` (9), `test_prepPrefilter` (9), `test_parallelVerify` (8), `test_downloadEventsContract` (5) — 226 test methods | **Well-covered at the unit/integration level.** The standout of the whole repo. Pure-logic units (state/file-id/redaction, retry decisions, failure classification, event field denylist, reported feature flags, sidecar promotion) are tested directly with fakes. **Caveat:** this is coverage of *deterministic logic only*. The Central download-enhancement test-strategy lists network-simulation (latency/loss/throttle/DNS/TLS/429/5xx), soak, and manual-QA resume/offline scenarios as **required but not yet executed** — there is no recorded evidence for them. "Best-covered" is true for units, **not** for end-to-end network behavior. |
| **PyBatch command objects** | `pybatch/*BatchCommands.py`, `PythonBatchCommandBase`, `PythonBatchCommandAccum` | `test_subprocessBatchCommands` (47), `test_fileSystemBatchCommands` (37), `test_reportingBatchCommands` (26), `test_copyBatchCommands` (22), `test_WinOnlyBatchCommands` (20), `test_MacOnlyBatchCommands` (19), `test_conditionalBatchCommands` (18), `test_removeBatchCommands` (15), `test_svnBatchCommands` (10), `test_info_mapBatchCommands` (9), `test_parallelUnwtar` (8), `test_wtarBatchCommands` (6), plus `tests/characterization/test_pybatch_serialization_golden.py` (3); shared harness in `test_PythonBatchBase` | **Well-covered** for the command *catalog*: both the repr→eval round-trip and real execution-and-compare are tested per command (see §5). Note: this tests the *commands*, not the orchestration that assembles them. |
| **Data tables (db / index)** | `db/indexItemTable.py` (`IndexItemsTable`), DDL | `pyinstl/test/test_itemTable.py` (`TestConditionalsInIndex`, `TestReadWrite`, `TestItemTable` — 14) | **Moderate.** Index read/write, conditionals-in-index, and item-table queries are exercised. SVN-table query/mutation breadth is not deeply covered here. |
| **svnTree (info-map model)** | `svnTree/*`, `SVNItem`, `SVNTable` | **none** — `svnTree/test/` keeps only the `SVNInfoTest1.info`/`.ref.txt` fixtures; `test_SVNItem.py` and `test_SVNTree.py` were deleted on this branch as dead (outdated-API) tests. | **None.** Neither `SVNItem` tree behavior nor the 1620-line `SVNTable` SQL query/mutation surface is covered — a regression here would be caught by nothing. |
| **ConfigVar system** | `configVar/*`, `ConfigVarStack`, `var_parse_imp`, `ConfigVarYamlReader` | `configVar/test/testConfigVar.py` (11) + `tests/characterization/test_configvar_resolution_golden.py` (11) | **Moderate.** Covers `$()` resolution, var-in-var, arrays, defaults, bool, format, file read, resolve-time, dynamic vars, alternative resolve indicator. Does **not** cover OS-native pattern rewriting (`%X%`/`${X}`), `__environment__` import, or the `eval`-based `__if__` conditional path. |
| **aYaml** | `aYaml/*`, `writeAsYaml` | `aYaml/test/test_augmentedYaml.py` (4) | **Thin.** A few read/write/round-trip tests; the import-time PyYAML monkey-patching and frame-inspection newline logic are not directly characterized. |
| **utils** | `utils/*` (file/url I/O, checksums, parallel subprocess, ls, OS detect) | `utils/test/test_str_utils.py` (1), `pyinstl/test/test_utils.py` (4) | **Thin.** Two tiny files. The bulk of `utils` (checksum caching, multi-file streaming, parallel-run, OS dispatch, file-lock) is untested. |
| **InstlClient + subclasses** | `instlClient.py`, `instlClientCopy/Remove/Uninstall/Report/Sync.py` | `tests/characterization/test_instlclient_copy_golden.py` (13) | **Thin.** Characterization goldens pin install-item graph resolution (inheritance flattening, `depends`, `get_recursive_dependencies`) and the exact `repr` of the commands `create_copy_instructions_for_{file,dir,dir_cont,source}` emits, against synthetic index/info-map fixtures on a `:memory:` DB. `Remove`/`Uninstall`/`Report`/`Sync` and the end-to-end pipeline remain unverified. |
| **InstlAdmin** | `instlAdmin.py` (1481 lines, ~10 command clusters) | **none** | **None.** Zero tests for up2s3 / activate / svn-fix / stage-sync / verify / redis-daemon. |
| **InstlGui** | `instlGui.py` | **none** | **None.** No test; also Tk/subprocess-driven, hard to test as-is. |
| **InstlInstanceBase / Misc / DoIt** | `instlInstanceBase.py`, `instlMisc.py`, `instlDoIt.py` | **none** | **None.** The shared god-base (config loading, DB lifecycle, batch-file write/run, dependency graph) is exercised only incidentally via the item-table and pybatch suites. |
| **Sync backends / connections** | `instlInstanceSync_url/svn/p4/boto.py`, `connectionBase` | **none** | **None.** URL/SVN/P4/boto fetch logic untested. |
| **CLI / entry point** | `instl` launcher, `instl_own_main`, option parsing, dispatch | **none** | **None.** No end-to-end CLI fixture. |

**The contrast to internalize:** the download subsystem alone has 15 test files and 226 test methods. Of the god-classes that *drive the actual product*, only `InstlClient` has any dedicated coverage (13 characterization methods added on this branch); `InstlAdmin`, `InstlGui` and `InstlInstanceBase` still have **zero**.

---

## 3. Coverage gaps vs. refactor risk

Cross-referencing the refactor themes from `docs/ARCHITECTURE.md` §6 / `docs/HLD.md` against where tests exist:

### DANGEROUS — high refactor value, ~zero test cover (refactoring blind)
- **God-objects: `InstlInstanceBase`, `InstlAdmin`, `InstlGui` (Theme 1).** These are explicit refactor targets (extract PathResolver / BatchFileWriter / DependencyAnalyzer; split admin command clusters) and have **no tests at all**, so any extraction is unverifiable. **Highest danger.** `InstlClient` is the one exception: its graph resolution and copy-command generation are pinned by `tests/characterization/test_instlclient_copy_golden.py`, which covers the copy path only. Pin the rest with characterization tests first (§4).
- **`config_vars` global / hidden coupling (Theme 2).** `ConfigVarStack` has *moderate* unit cover for the resolution mini-language, but the dangerous part of the refactor — threading explicit context objects through ~50 modules that mutate the global, plus option-parsing side-effects — is exercised by **no integration test**. The OS-native rewriting and `__environment__` paths are untested. Changing global→injected here can silently break far-away callers.
- **`SVNTable` (1620 lines) SQL surface (Theme 1).** Neither `SVNItem` nor the table god-class's queries/mutations/transaction nesting is covered (the `svnTree` tests were deleted). The HLD flags the hand-rolled transaction nesting as fragile and swallowing `OperationalError`. Refactoring the query family is blind.
- **Sync backends + CLI dispatch.** No tests; a regression in URL/SVN backend selection or `match`-dispatch would not be caught.

### MODERATE — partial cover, mind the untested edges
- **eval/repr serialization model (Theme 3).** The pybatch round-trip (`repr` → `eval`/`compile`/`exec`) **is** well-tested per command via `reprs_test_runner` and `exec_and_capture_output` — this is the *good news* for replacing repr→eval with a structured IR: you have a behavioral oracle for individual commands. **But** the security-sensitive entry points — `EvalShellCommand` evaluating index.yaml action strings, `eval_conditional` on config `__if__`, `do_python`, `send_email_from_template_file` — are **not** directly tested. Tightening/whitelisting those is partly blind.
- **`PythonBatchCommandAccum.__repr__` (whole-script emission).** Individual commands round-trip well, but the accum's section-wrapping, runtime wrapper, imports, and `.timings.py` twin generation are only exercised indirectly. `tests/characterization/test_pybatch_serialization_golden.py` now pins exact `repr` strings and asserts the accum serializes to an executable script, but a golden of a *full* real `*-sync.py`/`*-copy.py` is still missing (§4).

### LOWER — covered enough to refactor with normal care
- Download subsystem internals (state/retry/failures/events/observability) — well-covered *as units*; safe to refactor the deterministic logic against the existing tests. The connectivity-loss self-sufficiency layer is likewise unit-dense: offline-hold/probing, output reconciliation, the stall-detection config lines, and the capability gate in `pybatch/test/test_subprocessBatchCommands.py` + `pyinstl/test/test_downloadTweaks.py` (which also pins the `curl --parallel` meter parser against real output from curl 8.7.1 and 8.21.0, whose time columns differ), the budget-bounded redownload pass in `pyinstl/test/test_redownloadBudget.py` (all with mocked probes/curl runs), the chunk-abandonment failure in `pyinstl/test/test_downloadChunkAbandon.py` (11 tests, curl stubbed: reconciliation on non-zero exits, the non-network-exit log line, the unparsable-config warning, the measured-not-planned cross-chunk progress base for both files and bytes, and that an unmeasurable chunk publishes neither), the installation-lifecycle reporting in `pyinstl/test/test_installLifecycle.py` (that the verify phase reports while it hashes rather than after, that hash results keep input order when the pool finishes out of order, that the recovery redownload gets a `retrying` phase of its own and the verify bar reaches full only after it, and that a failing run emits `failed`), the batched resume-sidecar journal in `pyinstl/test/test_resumeJournal.py` (a clean pass, resume after a mid-transfer kill and after a full process kill, a torn last append, a garbage journal, a schema-version mismatch, journal-without-part, part-without-journal, and the pre-journal per-file layout), and `DownloadManager`'s per-file overhead in `pybatch/test/test_downloadManagerReuse.py` (4 tests against a loopback HTTP server that counts accepted sockets: connection reuse, one `MakeDir` per directory, session closed once at the end). Be aware the **emergent** behavior (real resume vs. restart-from-zero, a real NIC-drop offline-hold) is exercised only by manual-QA scenarios that are not automated and have no recorded runs — those paths are characterization-thin even though the units are dense.
- Individual pybatch command classes — safe to refactor one command at a time behind the round-trip + exec tests.
- ConfigVar `$()` resolver core (unit tests plus a resolution golden) and IndexItemsTable read/write.

---

## 4. Characterization-test strategy (pin behavior BEFORE refactoring)

The goal for the untested god-classes is **characterization tests**: capture current output as a golden baseline, refactor, and assert the output is byte-identical. You are not judging correctness, only freezing behavior.

1. **Golden-file batch-script snapshots (highest leverage).** instl's whole job is to emit a `*-sync.py` / `*-copy.py` batch script. `tests/characterization/test_instlclient_copy_golden.py` already pins per-source copy-command `repr`s and `test_pybatch_serialization_golden.py` pins the accum's serialization, but neither snapshots a whole emitted script. To close that, before refactoring `InstlClient` / `InstlInstanceBase`:
   - Build small fixture indexes (reuse `pyinstl/test/test-index-in.yaml`, `test-index-ref.yaml`, `index_with_conditionals.yaml` as starting points).
   - Run `instl sync`/`copy`/`remove` with `--out plan.py` and **without** `--run`, capture the emitted script text as a golden file.
   - On refactor, regenerate and diff against the golden. Normalize volatile bits (absolute paths, temp dirs, timestamps, the `.timings.py` twin) before comparing.
   - This leans directly on the existing strength: the accum already serializes deterministically, and `test_PythonBatchBase`'s `exec_and_capture_output` shows the exact compile/exec pattern to reuse for asserting the script still *runs*.

2. **CLI end-to-end fixtures.** There is currently **no** CLI test. Add a thin harness that invokes `instl_own_main(argv)` (or the `instl` launcher as a subprocess) on canned argv + a fixture index against a `:memory:` DB and a temp output dir, asserting: exit behavior, the set of generated files, and (snapshotted) batch-script + config-var dump. This pins the option-parsing → dispatch → `do_command` path before you touch dispatch or `initial_vars` assembly.

3. **`InstlAdmin` per-command characterization.** Don't try to run real svn/S3/redis. Snapshot the **accumulated batch_accum** for each `do_*` command (e.g. `up2s3_repo_rev`) against a fixture config, mocking `Subprocess`/`aws`/`SVN*`/Redis at the boundary. Freeze the emitted command sequence per admin subcommand, then refactor the god-class.

4. **`config_vars` resolution golden table.** Partly done: `tests/characterization/test_configvar_resolution_golden.py` pins plain/var-in-var/list-join resolution, positive and negative indexing, positional and keyword parameterized forms, and `!define` vs `!define_const` vs `!define_if_not_exist` semantics. Still uncovered and worth adding before extracting context/injection: OS-native rewrite (`%X%`/`${X}`), `__environment__` import, and the `eval`-based `__if__` path.

5. **`SVNTable` query characterization.** Load a fixed `.info` fixture (the suite already ships `svnTree/test/SVNInfoTest1.info` + `.ref.txt`) into the table, then snapshot the results of each query helper / mark-required / mark-need-download. This freezes SQL behavior before deduping the `get_*details*` family.

6. **Pin the eval boundaries.** Add explicit tests for `EvalShellCommand` (string → command-or-ShellCommand fallback) and `eval_conditional` (representative `__if__` strings → bool) so that swapping in a whitelist / `ast.literal_eval` / safe evaluator is verifiable.

7. **Pin the download telemetry & resume contract (Central's hard dependency).** Central's download-system-enhancement consumes instl's structured output as a fixed protocol, so any refactor of the `download*` modules must preserve it byte-stably. Pin it as characterization tests, not just internal units:
   - **Telemetry line contract.** Assert the literal log prefix `DOWNLOAD_EVENT` (`downloadEvents.DOWNLOAD_EVENT_LOG_PREFIX`), `schemaVersion: 1` (`DOWNLOAD_EVENT_SCHEMA_VERSION`), the five event types (`download.session_state`/`file_state`/`retry_decision`/`capability`/`session_summary`), and the still-emitted legacy `DOWNLOAD_RETRY_DECISION <json>` line. Central parses `DOWNLOAD_EVENT` lines *before* the legacy regex in `ShellInstlProcessProgressHandler`, so changing the prefix, key sort order (`json.dumps(..., sort_keys=True)`), or the legacy line breaks the consumer. The `set_telemetry_enabled(False)` kill switch (`downloadEvents.py`) must mute `DOWNLOAD_EVENT` while leaving the legacy line intact — pin both.
   - **Privacy denylist (must never regress).** Snapshot that the fixed denylist (`url`/`headers`/`cookies`/`authorization`/`policy`/`signature`/`signedUrl`/`tempPath`/`finalPath`/`localPath`/`downloadPath`) is stripped from every event builder and from the `session-summary.json` snapshot. The existing `TestObservabilityPrivacy` / `TestTelemetryKillSwitch`-style assertions (no `Signature`/`Policy`/full URLs/`/<repo>/` path in the snapshot) are the oracle to extend — a careless module merge here is a telemetry-leak regression.
   - **`session-summary.json` shape.** `downloadObservability.py` writes `download-state/session-summary.json` (schema v1) under `$(LOCAL_REPO_BOOKKEEPING_DIR)` via same-dir temp + atomic replace; freeze its shape (per-host totals, `observedThroughputBytesPerSecond`, `errorRate`) because it is emitted verbatim as the `download.session_summary` event Central renders from.
   - **Resume decision oracle (the hard case).** `resume_decision_for_download_item` / `url_matches_resume_capability` / `has_sufficient_signed_url_ttl` decide RESUME vs. RESTART-from-zero. The non-negotiable rules to pin: a `200` answer to a range request → discard + restart; a `206` requires a correct `Content-Range`; `CHECKSUM_MISMATCH` / `MISSING_AFTER_TRANSFER` always force restart even when otherwise resume-eligible; expired/near-expiry signed URL (below `DOWNLOAD_RESUME_MIN_SIGNED_URL_TTL_SECONDS`, default 300s) forces safe restart; resume is host/path-gated to the validated CDN. **Add the negative control** (`DOWNLOAD_RESUME_ENABLED: no` → restart-from-zero): per Central's manual-QA-resume playbook this is "the most important control," because a real resume and a restart both write the same `<finalPath>.instl-<fileId[0:16]>.part` artifact and cannot be distinguished by eye — the discriminating evidence is the `.part` starting at the captured offset (not 0), a `download.capability` event with `resumeEnabled:true`, and a `retry`/`file_state` event with `decision:resume` (Central's manual-QA playbook also expects a `bytesResumed>0` figure in the session summary — note instl does not currently emit a field by that name, so confirm the actual `session-summary.json` key before asserting on it). A characterization test should assert on those structured signals rather than just "the file downloaded."

   **Runtime-flag setup gotcha:** these behaviors are gated by `DOWNLOAD_*` flags that live in instl's own `defaults/InstlClient.yaml` (the only runtime source — Central does not set them; they are bundled inside instl's PyInstaller output). This file ships `DOWNLOAD_RESUME_ENABLED: yes` and `DOWNLOAD_CENTRAL_UX_ENABLED: yes`; `downloadEvents._REPORTED_FLAGS` carries matching defaults, which apply only when a key is undefined — once `defaults/InstlClient.yaml` loads, the YAML wins. Characterization tests must set these flags explicitly via `config_vars` rather than relying on the shipped defaults, both so the test is hermetic and so it doesn't silently break when the defaults are flipped back at merge time.

**Workflow:** add the golden/characterization test → confirm it passes on `master` → branch → refactor → the test must still pass byte-for-byte. Wire all new tests into the recommended `unittest discover` command.

---

## 5. Test infrastructure notes (patterns & reusables)

### The pybatch test harness (`pybatch/test/test_PythonBatchBase.py`) — the most reusable asset
A composition-based base shared by every `*BatchCommands` test. Test classes hold a `TestPythonBatch` helper (`self.pbt`) and delegate `setUp`/`tearDown` to it.

- **Per-test sandbox:** `TestPythonBatch.setUp` builds a unique folder under `python_batch_test_results/<TestClass>/<test_name>/`, force-fixes permissions (`FixAllPermissions`) and `rmtree`s any stale copy, then recreates it. `path_inside_test_folder(...)` asserts paths don't pre-exist; `write_file_in_test_folder(...)` seeds inputs.
- **Two complementary verification styles — reuse both:**
  - **`reprs_test_runner(*objs)`** — the **repr→eval round-trip oracle**: for each command object, `eval(repr(obj))` must reconstruct an equal object (`assertEqual(obj, obj_recreated)`), with an `explain_diff` hook and an `OK/X` log file. This is exactly the invariant the eval-serialization refactor must preserve.
  - **`exec_and_capture_output(...)`** — the **real-execution oracle**: builds a `PythonBatchCommandAccum`, sets `__MAIN_OUT_FILE__`/`__MAIN_COMMAND__` config-vars, `repr`s the accum to a `.py` file, `compile()`s and `exec()`s it (i.e. runs the generated script the way production does), with `expected_exception` support for negative tests.
- **Accum building pattern:** `self.pbt.batch_accum += Command(...)`, `with batch_accum.sub_accum(Cd(...)) as sub_bc:` for nested sections, and `clear(section_name=...)` / `set_current_section("doit")`.
- **Filesystem assertion helpers (top of the file):** `is_identical_dircmp`, `is_identical_dircomp_with_ignore`, `is_same_inode`, `is_hard_linked`, plus `capture_stdout` (contextmanager), `explain_dict_diff`, and an `assert_timeout` watchdog. Reuse these for any copy/remove/wtar characterization.
- **Randomized inputs:** tests use `MakeRandomDirs(...)` to generate tree structures, then copy and diff source vs target — a ready pattern for fuzz-style copy characterization.

### Download-test patterns
- **Hand-rolled fakes over mock frameworks:** e.g. `FakeDownloadItem` in `test_downloadState.py` (a plain object with `path/revision/checksum/size/download_path`). Pure-function modules (`make_file_id`, `redact_url_for_state`, `temp_path_for_*`, `resume_decision_for_download_item`, retry/failure deciders) are tested as units with `tempfile`/`Path` and direct assertions — no I/O against real S3/curl. Reuse this fake style for any download-adjacent refactor.

### ConfigVar / index / yaml patterns
- **Fixture-pair golden testing:** `configVar/test/` ships `test_input.yaml` + `expected_output.yaml`; `pyinstl/test/` ships `test-index-in.yaml`/`test-index-ref.yaml` and `index_with_conditionals.yaml`; `svnTree/test/` ships `SVNInfoTest1.info` + `.ref.txt`. These are the templates for new golden/characterization fixtures — add your batch-script snapshots alongside them.
- **`setUp` config bootstrapping:** index tests set `config_vars["__INSTL_DEFAULTS_FOLDER__"]` to the repo `defaults/` dir and feed YAML through `IndexYamlReader`, then dump with `aYaml.YamlDumpDocWrap` and assert on the rendered text (e.g. counting `_IID`/`OK`/`Bad`). A simple, copyable text-assertion approach for YAML-emitting code.
- **`timing` decorator** in `test_itemTable.py` for ad-hoc perf prints (informational, not a gate).

### Global-state caveat for test authors
Because `config_vars`, `DBManager` table descriptors, pybatch class-level progress/stage state, and the download module singletons are **process-global and mutable**, tests are order-sensitive and depend on `reset_*`/`clear()`/per-test folder teardown. When adding characterization tests, explicitly reset or scope this state in `setUp` (use `private_config_vars` / a `:memory:` DB) so a refactor that changes global lifecycle doesn't produce phantom failures or cross-test bleed.

### Known flaky / environment-dependent tests
- `TestPythonBatchCopy.test_RsyncClone` (hard-link variant) is documented in its own docstring as failing for unknown reasons when run from Python (works from a terminal). Treat as known-flaky, not a regression signal.
- Mac/Win-only suites assert different things per platform; a "pass" on one OS does not validate the other's branch.
