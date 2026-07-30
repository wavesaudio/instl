# instl Testing & Coverage Map

> Purpose: give anyone refactoring instl a truthful picture of **what is tested, what isn't, and how to pin behavior before touching the dangerous parts.** This is a map for making refactors *safe*, not a tutorial on writing new features.

instl is a YAML-driven deployment engine whose central trick is *plan → emit an eval-able Python "batch" script → run it*. That repr→eval round-trip, a process-wide `config_vars` global, and several god-classes are the highest-risk things to change. The test suite covers the **download subsystem** and the **pybatch command objects** well, the **data/config/yaml foundations** moderately, and the **command-orchestration god-classes** (`InstlClient`, `InstlAdmin`, `InstlGui`, `InstlInstanceBase`) essentially **not at all**.

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
- Tests are plain `unittest` (no `pytest.ini`, `conftest.py`, `tox.ini`, or `setup.cfg` exist). `pytest` will still discover and run most of them, but nothing in-repo assumes it.

### Running everything (honest version)
There is no single green "run all tests" entry point. Each package has its own runner and they are **not** wired together:

| Runner | What it actually runs | Notes |
|---|---|---|
| `pyinstl/test_all.py` | **Only** `TestItemTable` and `TestReadWrite` from `test_itemTable.py`. | All other imports are commented out, and several of the commented names (`test_configVar`, `test_configVarList`, `test_InstallItem`, `test_platformSpecificHelper`) point at files **that no longer exist** — dead references. It does **not** import the ~10 download test files, `test_utils`, or any pybatch/configVar/aYaml/svnTree tests. |
| `aYaml/test/test_all.py` | Only `TestAugmentedYaml`. | |
| (no runner) | `pybatch/test/*`, `configVar/test/*`, `utils/test/*`, `svnTree/test/*`, and **every `pyinstl/test/test_download*.py`** | Must be invoked directly. |

**Bottom line: `test_all.py` is misleading. It runs a tiny slice. Most of the real coverage lives in files that no aggregate runner touches.**

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
python -m unittest discover -s svnTree/test -p "test_*.py" -t .
python -m unittest discover -s utils/test -p "test_*.py" -t .

# single download module:
python -m unittest pyinstl.test.test_downloadState -v
```

### Gaps / caveats when running
- **`sys.path` hacking:** test files append parent dirs to `sys.path` at import time and then do top-level imports like `from downloadState import ...` and `from db.indexItemTable import ...`. Run from the repo root (or with the venv's site path set up) or imports break.
- **Platform-gated suites:** `test_MacOnlyBatchCommands.py` and `test_WinOnlyBatchCommands.py` are OS-specific; many pybatch tests branch on `sys.platform` and skip/alter behavior off-platform. A "full pass" on macOS is not the same set of assertions as on Windows.
- **Side-effecting tests:** the pybatch suite writes into a real `python_batch_test_results/` directory tree and `compile()`/`exec()`s generated scripts (real filesystem I/O). Some tests need write/permission access and a working `rsync` (the `RsyncClone` hard-link test is documented as flaky).
- **No coverage tooling is configured.** `.codeclimate.yml` and `.landscape.yml` only configure *static* analysis (and `.landscape.yml` disables pyflakes); neither runs tests or measures coverage. There is no CI test gate in-repo.
- **No code coverage numbers exist** — assessments below are by inspection (test files present vs. source modules), not measured line coverage.

---

## 2. Current coverage map

Assessment scale: **Well-covered** (multiple dedicated tests exercising behavior, not just smoke) · **Moderate** (one focused file, real assertions) · **Thin** (token coverage / indirect only) · **None** (no test touches this module).

| Subsystem | Source (representative) | Test files present | Assessment |
|---|---|---|---|
| **Download subsystem** | `downloadState.py`, `downloadRetry.py`, `downloadFailures.py`, `downloadControlChannel.py`, `downloadObservability.py`, `downloadConcurrency.py`, `downloadEvents.py`, `downloadCohort.py`, `curlHelper.py` | **~10 files** in `pyinstl/test/`: `test_downloadState` (21), `test_downloadPromotion` (22), `test_downloadConcurrency` (24), `test_downloadRetry` (21), `test_downloadEvents` (19), `test_downloadCohort` (18), `test_downloadObservability` (15), `test_downloadControlChannel` (12), `test_downloadFailures` (9) — ~160 test methods | **Well-covered at the unit/integration level.** The standout of the whole repo. Pure-logic units (state/file-id/redaction, retry decisions, failure classification, concurrency recommendation, event field denylist, cohorts, sidecar promotion) are tested directly with fakes. **Caveat:** this is coverage of *deterministic logic only*. The Central download-enhancement test-strategy lists network-simulation (latency/loss/throttle/DNS/TLS/429/5xx), soak, and manual-QA resume/offline scenarios as **required but not yet executed** — there is no recorded evidence for them. "Best-covered" is true for units, **not** for end-to-end network behavior. |
| **PyBatch command objects** | `pybatch/*BatchCommands.py`, `PythonBatchCommandBase`, `PythonBatchCommandAccum` | `test_copyBatchCommands` (22), `test_fileSystemBatchCommands` (37), `test_reportingBatchCommands` (26), `test_subprocessBatchCommands` (25), `test_MacOnlyBatchCommands` (19), `test_WinOnlyBatchCommands` (20), `test_conditionalBatchCommands` (18), `test_removeBatchCommands` (15), `test_svnBatchCommands` (10), `test_info_mapBatchCommands` (9), `test_wtarBatchCommands` (6); shared harness in `test_PythonBatchBase` | **Well-covered** for the command *catalog*: both the repr→eval round-trip and real execution-and-compare are tested per command (see §5). Note: this tests the *commands*, not the orchestration that assembles them. |
| **Data tables (db / index)** | `db/indexItemTable.py` (`IndexItemsTable`), DDL | `pyinstl/test/test_itemTable.py` (`TestConditionalsInIndex`, `TestReadWrite`, `TestItemTable` — 18) | **Moderate.** Index read/write, conditionals-in-index, and item-table queries are exercised; this is the only suite `test_all.py` actually runs. SVN-table query/mutation breadth is not deeply covered here. |
| **svnTree (info-map model)** | `svnTree/*`, `SVNItem`, `SVNTable` | `test_SVNItem` (13), `test_SVNTree` (1) | **Moderate** for `SVNItem` tree behavior; `test_SVNTree` is a single smoke test. The ~1600-line `SVNTable` god-class's SQL query/mutation surface is **largely untested**. |
| **ConfigVar system** | `configVar/*`, `ConfigVarStack`, `var_parse_imp`, `ConfigVarYamlReader` | `configVar/test/testConfigVar.py` (11) | **Moderate.** Covers `$()` resolution, var-in-var, arrays, defaults, bool, format, file read, resolve-time, dynamic vars, alternative resolve indicator. Does **not** cover OS-native pattern rewriting (`%X%`/`${X}`), `__environment__` import, or the `eval`-based `__if__` conditional path. |
| **aYaml** | `aYaml/*`, `writeAsYaml` | `aYaml/test/test_augmentedYaml.py` (4) | **Thin.** A few read/write/round-trip tests; the import-time PyYAML monkey-patching and frame-inspection newline logic are not directly characterized. |
| **utils** | `utils/*` (file/url I/O, checksums, parallel subprocess, ls, OS detect) | `utils/test/test_str_utils.py` (1), `pyinstl/test/test_utils.py` (4) | **Thin.** Two tiny files. The bulk of `utils` (checksum caching, multi-file streaming, parallel-run, OS dispatch, file-lock) is untested. |
| **InstlClient + subclasses** | `instlClient.py`, `instlClientCopy/Remove/Uninstall/Report/Sync.py` | **none** | **None.** No test references `InstlClient`. The whole client install/sync/copy/uninstall pipeline is unverified end-to-end. |
| **InstlAdmin** | `instlAdmin.py` (~1480 lines, ~10 command clusters) | **none** | **None.** Zero tests for up2s3 / activate / svn-fix / stage-sync / verify / redis-daemon. |
| **InstlGui** | `instlGui.py` | **none** | **None.** No test; also Tk/subprocess-driven, hard to test as-is. |
| **InstlInstanceBase / Misc / DoIt** | `instlInstanceBase.py`, `instlMisc.py`, `instlDoIt.py` | **none** | **None.** The shared god-base (config loading, DB lifecycle, batch-file write/run, dependency graph) is exercised only incidentally via the item-table and pybatch suites. |
| **Sync backends / connections** | `instlInstanceSync_url/svn/p4/boto.py`, `connectionBase` | **none** | **None.** URL/SVN/P4/boto fetch logic untested. |
| **CLI / entry point** | `instl` launcher, `instl_own_main`, option parsing, dispatch | **none** | **None.** No end-to-end CLI fixture. |

**The contrast to internalize:** the download subsystem alone has ~10 test files and ~160 test methods, while the three god-classes that *drive the actual product* — `InstlClient`, `InstlAdmin`, `InstlGui` (plus `InstlInstanceBase`) — have **zero** dedicated tests.

---

## 3. Coverage gaps vs. refactor risk

Cross-referencing the refactor themes from `docs/ARCHITECTURE.md` §6 / `docs/HLD.md` against where tests exist:

### DANGEROUS — high refactor value, ~zero test cover (refactoring blind)
- **God-objects: `InstlInstanceBase`, `InstlClient`, `InstlAdmin` (Theme 1).** These are the explicit refactor targets (extract PathResolver / BatchFileWriter / DependencyAnalyzer; split admin command clusters). They have **no tests at all**. Any extraction here is currently unverifiable — you cannot tell if you preserved behavior. **Highest danger.** Pin them with characterization tests first (§4).
- **`config_vars` global / hidden coupling (Theme 2).** `ConfigVarStack` has *moderate* unit cover for the resolution mini-language, but the dangerous part of the refactor — threading explicit context objects through ~50 modules that mutate the global, plus option-parsing side-effects — is exercised by **no integration test**. The OS-native rewriting and `__environment__` paths are untested. Changing global→injected here can silently break far-away callers.
- **`SVNTable` (~1600 lines) SQL surface (Theme 1).** `SVNItem` is covered but the table god-class's queries/mutations/transaction nesting are not. The HLD flags the hand-rolled transaction nesting as fragile and swallowing `OperationalError`. Refactoring the query family is blind.
- **Sync backends + CLI dispatch.** No tests; a regression in URL/SVN backend selection or `match`-dispatch would not be caught.

### MODERATE — partial cover, mind the untested edges
- **eval/repr serialization model (Theme 3).** The pybatch round-trip (`repr` → `eval`/`compile`/`exec`) **is** well-tested per command via `reprs_test_runner` and `exec_and_capture_output` — this is the *good news* for replacing repr→eval with a structured IR: you have a behavioral oracle for individual commands. **But** the security-sensitive entry points — `EvalShellCommand` evaluating index.yaml action strings, `eval_conditional` on config `__if__`, `do_python`, `send_email_from_template_file` — are **not** directly tested. Tightening/whitelisting those is partly blind.
- **`PythonBatchCommandAccum.__repr__` (whole-script emission).** Individual commands round-trip well, but the accum's section-wrapping, runtime wrapper, imports, and `.timings.py` twin generation are only exercised indirectly. A golden-file snapshot of full emitted scripts is missing (§4).

### LOWER — covered enough to refactor with normal care
- Download subsystem internals (state/retry/failures/concurrency/events/cohort/observability) — well-covered *as units*; safe to refactor the deterministic logic against the existing tests. The connectivity-loss self-sufficiency layer is likewise unit-dense: offline-hold/probing, output reconciliation, the stall-detection config lines, and the capability gate in `pybatch/test/test_subprocessBatchCommands.py` + `pyinstl/test/test_downloadTweaks.py`, and the budget-bounded redownload pass in `pyinstl/test/test_redownloadBudget.py` (all with mocked probes/curl runs). Be aware the **emergent** behavior (real resume vs. restart-from-zero, a real NIC-drop offline-hold, throughput-driven concurrency) is exercised only by manual-QA scenarios that are not automated and have no recorded runs — those paths are characterization-thin even though the units are dense.
- Individual pybatch command classes — safe to refactor one command at a time behind the round-trip + exec tests.
- ConfigVar `$()` resolver core, IndexItemsTable read/write, SVNItem tree.

---

## 4. Characterization-test strategy (pin behavior BEFORE refactoring)

The goal for the untested god-classes is **characterization tests**: capture current output as a golden baseline, refactor, and assert the output is byte-identical. You are not judging correctness, only freezing behavior.

1. **Golden-file batch-script snapshots (highest leverage).** instl's whole job is to emit a `*-sync.py` / `*-copy.py` batch script. Before refactoring `InstlClient` / `InstlInstanceBase`:
   - Build small fixture indexes (reuse `pyinstl/test/test-index-in.yaml`, `test-index-ref.yaml`, `index_with_conditionals.yaml` as starting points).
   - Run `instl sync`/`copy`/`remove` with `--out plan.py` and **without** `--run`, capture the emitted script text as a golden file.
   - On refactor, regenerate and diff against the golden. Normalize volatile bits (absolute paths, temp dirs, timestamps, the `.timings.py` twin) before comparing.
   - This leans directly on the existing strength: the accum already serializes deterministically, and `test_PythonBatchBase`'s `exec_and_capture_output` shows the exact compile/exec pattern to reuse for asserting the script still *runs*.

2. **CLI end-to-end fixtures.** There is currently **no** CLI test. Add a thin harness that invokes `instl_own_main(argv)` (or the `instl` launcher as a subprocess) on canned argv + a fixture index against a `:memory:` DB and a temp output dir, asserting: exit behavior, the set of generated files, and (snapshotted) batch-script + config-var dump. This pins the option-parsing → dispatch → `do_command` path before you touch dispatch or `initial_vars` assembly.

3. **`InstlAdmin` per-command characterization.** Don't try to run real svn/S3/redis. Snapshot the **accumulated batch_accum** for each `do_*` command (e.g. `up2s3_repo_rev`) against a fixture config, mocking `Subprocess`/`aws`/`SVN*`/Redis at the boundary. Freeze the emitted command sequence per admin subcommand, then refactor the god-class.

4. **`config_vars` resolution golden table.** Before extracting context/injection, capture a table of `(input definitions, query) → resolved value` across the resolver's feature set (var-in-var, arrays, defaults, OS-native rewrite, `__environment__`, `__if__`). The existing `configVar/test/testConfigVar.py` + its `test_input.yaml`/`expected_output.yaml` fixtures are the seed pattern — expand the expected-output fixture to cover the currently-untested paths.

5. **`SVNTable` query characterization.** Load a fixed `.info` fixture (the suite already ships `svnTree/test/SVNInfoTest1.info` + `.ref.txt`) into the table, then snapshot the results of each query helper / mark-required / mark-need-download. This freezes SQL behavior before deduping the `get_*details*` family.

6. **Pin the eval boundaries.** Add explicit tests for `EvalShellCommand` (string → command-or-ShellCommand fallback) and `eval_conditional` (representative `__if__` strings → bool) so that swapping in a whitelist / `ast.literal_eval` / safe evaluator is verifiable.

7. **Pin the download telemetry & resume contract (Central's hard dependency).** Central's download-system-enhancement consumes instl's structured output as a fixed protocol, so any refactor of the `download*` modules must preserve it byte-stably. Pin it as characterization tests, not just internal units:
   - **Telemetry line contract.** Assert the literal log prefix `DOWNLOAD_EVENT` (`downloadEvents.DOWNLOAD_EVENT_LOG_PREFIX`), `schemaVersion: 1` (`DOWNLOAD_EVENT_SCHEMA_VERSION`), the five event types (`download.session_state`/`file_state`/`retry_decision`/`capability`/`session_summary`), and the still-emitted legacy `DOWNLOAD_RETRY_DECISION <json>` line. Central parses `DOWNLOAD_EVENT` lines *before* the legacy regex in `ShellInstlProcessProgressHandler`, so changing the prefix, key sort order (`json.dumps(..., sort_keys=True)`), or the legacy line breaks the consumer. The `set_telemetry_enabled(False)` kill switch (`downloadEvents.py`) must mute `DOWNLOAD_EVENT` while leaving the legacy line intact — pin both.
   - **Privacy denylist (must never regress).** Snapshot that the fixed denylist (`url`/`headers`/`cookies`/`authorization`/`policy`/`signature`/`signedUrl`/`tempPath`/`finalPath`/`localPath`/`downloadPath`) is stripped from every event builder and from the `session-summary.json` snapshot. The existing `TestObservabilityPrivacy` / `TestTelemetryKillSwitch`-style assertions (no `Signature`/`Policy`/full URLs/`/<repo>/` path in the snapshot) are the oracle to extend — a careless module merge here is a telemetry-leak regression (Central risk R-011).
   - **`session-summary.json` shape.** `downloadObservability.py` writes `download-state/session-summary.json` (schema v1) under `$(LOCAL_REPO_BOOKKEEPING_DIR)` via same-dir temp + atomic replace; freeze its shape (per-host totals, `observedThroughputBytesPerSecond`, `errorRate`) because adaptive concurrency reads the *previous* run's summary to choose `PARALLEL_SYNC` between sessions.
   - **Resume decision oracle (the hard case).** `resume_decision_for_download_item` / `url_matches_resume_capability` / `has_sufficient_signed_url_ttl` decide RESUME vs. RESTART-from-zero. The non-negotiable rules to pin: a `200` answer to a range request → discard + restart; a `206` requires a correct `Content-Range`; `CHECKSUM_MISMATCH` / `MISSING_AFTER_TRANSFER` always force restart even when otherwise resume-eligible; expired/near-expiry signed URL (below `DOWNLOAD_RESUME_MIN_SIGNED_URL_TTL_SECONDS`, default 300s) forces safe restart; resume is host/path-gated to the validated CDN. **Add the negative control** (`DOWNLOAD_RESUME_ENABLED: no` → restart-from-zero): per Central's manual-QA-resume playbook this is "the most important control," because a real resume and a restart both write the same `<finalPath>.instl-<fileId[0:16]>.part` artifact and cannot be distinguished by eye — the discriminating evidence is the `.part` starting at the captured offset (not 0), a `download.capability` event with `resumeEnabled:true`, and a `retry`/`file_state` event with `decision:resume` (Central's manual-QA playbook also expects a `bytesResumed>0` figure in the session summary — note instl does not currently emit a field by that name, so confirm the actual `session-summary.json` key before asserting on it). A characterization test should assert on those structured signals rather than just "the file downloaded."

   **Runtime-flag setup gotcha:** these behaviors are gated by `DOWNLOAD_*` flags that live in instl's own `defaults/InstlClient.yaml` (the only runtime source — Central does not set them; they are bundled inside instl's PyInstaller output). On the current `download-enhancements` branch this file ships `DOWNLOAD_RESUME_ENABLED: yes` and `DOWNLOAD_CENTRAL_UX_ENABLED: yes` (on-by-default for the POC; Central decision D-022 requires re-gating both to default-off before merge to main). Characterization tests must set these flags explicitly via `config_vars` rather than relying on the shipped defaults, both so the test is hermetic and so it doesn't silently break when the defaults are flipped back at merge time.

**Workflow:** add the golden/characterization test → confirm it passes on `master` → branch → refactor → the test must still pass byte-for-byte. Wire all new tests into the recommended `unittest discover` command (and, ideally, fix `test_all.py` to discover rather than hand-list).

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
