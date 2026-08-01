# AGENTS.md — instl

> This file is also symlinked as `CLAUDE.md`. It is the entry document for both human contributors and coding agents. Keep it accurate; when in doubt, defer to the deep docs under `docs/`.
>
> **Before you finish any change, read §9 "Documentation rules". They are mandatory and they are not the usual "please update the docs" boilerplate — they exist because this suite drifted badly once already.**

## 1. What this repo is

**instl** is a YAML-driven, cross-platform software-deployment / installer engine by Waves Audio (GitHub: `wavesaudio/instl`). It turns a central, version-controlled description of *what should be installed* — an **index** of install-items plus an **info-map** of every file in the repository — into an ordered, executable plan that downloads, unpacks, copies, permissions, and registers files on an end-user machine, and into the admin tooling that builds and publishes those repositories.

The defining design choice: instl rarely touches the filesystem directly. It **generates a standalone Python "batch" script** (a tree of `pybatch` command objects serialized to eval-able Python source) that performs the actual work when run. The model is **plan → emit script → run script**.

Three personas:
- **Client (end-user)** — `instl sync` / `copy` / `synccopy` / `remove` / `uninstall` / `report-*`. Resolves the install-item dependency graph, downloads files from the remote repo (typically S3 via curl), copies/unwtars them, runs pre/post actions, rewrites the site `require.yaml`. Implemented by `InstlClient` and subclasses.
- **Admin (Waves engineer / CI)** — `instl admin <subcommand>`: SVN/staging maintenance, info-map/index verification, building per-repo-rev artifacts and uploading to S3 (`up2s3` / `up-short-index`), activating a repo-rev, and a Redis-triggered upload daemon. Implemented by `InstlAdmin`. **Admin mode only works when running from source (not frozen).**
- **GUI** — a Tk/ttk desktop front-end (`InstlGui`) with Client, Admin, and Activate tabs. It does **not** run instl logic in-process — each tab builds an instl command line and spawns the instl executable as a subprocess (the Activate tab also talks to Redis directly).

There is also a **doit** mode (`InstlDoIt`, a dependency-ordered generic action runner) and a **misc** / `do_something` mode (`InstlMisc`: `wtar`/`unwtar`/`checksum`/`ls`/`check-checksum`/etc.).

> Note on the consumer side: Waves Central — instl's primary consumer — drives instl **only as a CLI** (the Client persona, plus `exec`/`doit`/`run-process`). It never uses an instl "admin" or "GUI" persona; OS elevation is owned by Central (a `runAsAdmin` flag plus a Mac `InstlHelperApplication` LaunchDaemon, `com.waves.central.InstlHelper`), not by an instl admin mode. The admin/GUI personas above are instl-internal (Waves engineer / CI tooling).

For depth, read these:
- `docs/ARCHITECTURE.md` — layering, dependency graph, runtime flows. **Read this first.**
- `docs/HLD.md` — per-subsystem responsibilities, interfaces, owned state.
- `docs/LLD.md` — module internals.
- `docs/DOMAIN.md` — the input contract (index / info-map / config vocabulary).
- `docs/TESTING.md` — what is tested, what isn't, how to pin behavior first.
- `docs/REFACTORING.md` — the refactoring roadmap and its current status.
- `docs/download-events.md` — the structured event contract Waves Central parses.
- `manual/` — the user-facing manual (`SUMMARY.md`, `ch00-*`, `up2s3 automation.md`).

## 2. Repository layout

```
instl                  Executable launcher (python3.12 shebang); reopens stdio as UTF-8, calls instl_own_main
instl.spec             PyInstaller build spec (universal2, console app)
create_venv.sh         venv bootstrap (mac-only reqs first, then base)
requirements*.txt      Dependency sets: base / admin / mac_only / win_only
defaults/              Seed config YAML (main.yaml, Instl*.yaml) + SQLite DDL (*.ddl)
docs/                  ARCHITECTURE.md, HLD.md, LLD.md, DOMAIN.md, TESTING.md, REFACTORING.md, download-events.md
manual/                User-facing manual (markdown)

pyinstl/               CLI entry, command objects, sync backends, the download* subsystem
pybatch/               Dual-identity command objects (execute + serialize-to-Python); the batch accumulator
configVar/             The global config_vars stack + the $(NAME) resolution mini-language + YAML reader
aYaml/                 Augmented-YAML layer on PyYAML: tag-dispatching reader + hand-rolled writer
svnTree/               The info-map / "svn" SQLite table (SVNTable / SVNRow) — naming is historical
db/                    SQLite layer: DBMaster connection/lifecycle, DBManager singletons, IndexItemsTable
utils/                 Shared toolkit: file/URL I/O, checksums, OS/arch detection, parallel subprocess, ls, logging, email, dock
defaults/help, help/   helpHelper.py + instl_help.yaml (command help text)
```

Key files inside `pyinstl/`: `instl_main.py` (boot + dispatch), `instlClient*.py` (client workflow), `instlAdmin.py` (admin god-class), `instlInstanceBase.py` (root command class), `curlHelper.py` + `download*.py` (download engine), `instlGui.py`.

## 3. Getting started

- **Python: 3.12** (per the launcher shebang `#!/usr/bin/env python3.12` and the `universal2` spec). Use exactly this.
- **Create the venv:**
  ```bash
  ./create_venv.sh        # creates ./venv, installs mac-only reqs first (for universal wheels), then base
  source venv/bin/activate
  ```
- **Requirements files:**
  - `requirements.txt` — base runtime (PyYAML, requests, networkx, appdirs/platformdirs, packaging, certifi, truststore, xmltodict, PyInstaller).
  - `requirements_admin.txt` — admin-only (boto3, awscli, redis, rich, dictdiffer).
  - `requirements_mac_only.txt` / `requirements_win_only.txt` — platform extras (psutil, charset-normalizer; pywin32 family on Windows). Note PyYAML/requests/psutil are installed `--no-binary` to get the right native builds.
- **Run instl from source:**
  ```bash
  ./instl <command> [options]
  ./instl sync   --in index.yaml --out plan.py --run
  ./instl help
  ./instl version
  ```
  With no args, instl defaults to interactive mode (a `cmd.Cmd` REPL).

## 4. How to run / build

- **From source:** `./instl <command>` (or `python3.12 instl <command>`). This is the only mode where `admin`, `interactive`, and `gui` are permitted.
- **PyInstaller build:** `instl.spec` uses `COLLECT` to produce a **onedir** `universal2` console bundle named `instl` (not a single-file binary). The spec **excludes** tkinter, boto3, botocore, redis, rich, networkx, colorama, etc. — so the frozen binary is **client-only**: no GUI, no admin, no boto sync backend, no dependency-graph queries that need networkx.
- **Compiled-mode branches matter** wherever you see `getattr(sys, 'frozen', False)` / `sys.frozen`. The boot dispatcher (`instl_main.py`) `match`es on `(mode, is_compiled)`; admin/interactive/gui cases are gated to the `False` (source) branch. Path resolution (app/data/exec dirs, SSL paths) also branches on frozen vs source. If you add a feature that depends on an excluded package, it must be client-irrelevant or guarded.

### How instl ships inside Waves Central (the primary consumer)

instl's main downstream consumer is **Waves Central** (an Electron app). Central does **not** invoke `pyinstaller` directly — it builds the "latest" instl engine by running **instl on itself**:

```bash
# Central build_instl/build_instl.sh, inside a python3.12 venv from the cloned instl repo:
instl doit --in Build-index.yaml --out build_instl/build-instl.py --run --no-system-log
```

That emitted `build-instl.py` calls `build_python.build_onedir(instl_folder, instl.spec, 'instl', verpatch_path)`, which drives PyInstaller via `instl.spec` to produce the onedir bundle, then copies it to the target. (Source: Central `build_instl/build_instl.py` `main`, `build_instl.sh`.) The instl source is pulled from a local `instl/` folder (`git checkout download-enhancements-cont`) or cloned from `github.com/wavesaudio/instl.git --branch download-enhancements-cont` — i.e. the active integration branch is **`download-enhancements-cont`**, not `master`.

- **Signing (Mac).** `sign_instl.py` signs every non-symlink file in the bundle (`codesign --force --verify --no-strict -vvvv --sign <identity>`, inner `instl` binary signed last), then signs the bundle root with `--timestamp --options runtime --entitlements <ent>` (hardened runtime). On universal builds, `tasks/afterSign.js` re-signs the bundle and the instl/WLE binaries are injected **after** the app is signed (an electron-builder universal-binary workaround). The production build takes instl from the build's `Tools/instl.bundle` (or Artifactory), **not** from a checked-in zip (`useEmbeddedInstl=false`).
- **Runtime layout.** Central resolves three side-by-side engines: the latest bundle at `Waves Central.app/Contents/Resources/res/external/bin/instl.bundle/Contents/{MacOS|Win64}/instl(.exe)`, plus checked-in legacy executables `bin/instl-V9` and `bin/instl-V10`. Engine selection is per-repository: `repositoryKey > centralOneRepository` ⇒ latest engine, else legacy V9; online actions (synccopy/sync/copy/report-versions) are forbidden on non-latest engines. Legacy V9/V10 do **not** support `--log` (Central redirects with `>> buffer 2>&1`). (Source: Central `src/services/instl/behaviours/shell/common.tsx`, `getInstlBinaryPath` / `getProductsGroupedByEngineAndMajorVersion` / `getLegacyInstlCommandForInstlRunScript`.)
- **Invocation contract.** Central drives instl as a pure CLI: `"<instl>" <command> --in <in.yaml> --out <out.py> --log <buffer> --run` for `copy`/`sync`/`synccopy`/`uninstall` (the latest engine emits a `.py` pybatch as `--out`). `report-versions` emits JSON directly and is **not** given `--run`. The version organizer uses `exec --config-file <locations.yaml> --in organizer.py --out <out.py> --log <log>` (the `exec` runs the in-process script, no `--run`). Elevated/live runs wrap the emitted command in an `.irl` run-list and call `run-process --abort-file <.abort> --in <.irl>`; cancellation deletes the abort-file (instl watches it to terminate). Central's external Python scripts (`reportVersions.py`, `install_cen.py`, `organizer.py`) build their own instl invocations from the `__INSTL_LAUNCH_COMMAND__` config var.

## 5. Running tests

Tests are stdlib `unittest`, colocated under each package's `test/` directory (`pyinstl/test`, `pybatch/test`, `configVar/test`, `aYaml/test`, `utils/test`), plus the characterization goldens under `tests/characterization/`.

```bash
source venv/bin/activate
python3.12 -m unittest discover -s . -p 'test_*.py'
# or a single module:
python3.12 -m unittest pyinstl.test.test_downloadFailures
```

There is no `pyproject.toml`/`pytest.ini`/`setup.py`; tests assume the repo root on `sys.path` and a working venv. See `docs/TESTING.md` for the coverage map and the characterization-test strategy.

## 6. Key conventions an agent must know

- **The global `config_vars` singleton.** `from configVar import config_vars` gives the single process-wide `ConfigVarStack` — a scoped stack of dicts of multi-valued, lazily-resolved `ConfigVar`s. ~50 modules read **and mutate** it. It is the de-facto message bus: pipeline stages communicate by writing/reading config-var keys. Writes hit the top scope; lookups scan inner→outer (inner shadows). Use `config_vars.push_scope_context()` / `private_config_vars()` for isolation.
- **The `$()` variable language.** Strings are resolved through `$(NAME<params>[index])` via a hand-written state-machine parser (`configVar/configVarParser.py`). Supports parameters, array indexing/slicing, and per-OS native rewriting (`%X%` on Windows, `${X}` on POSIX). A fast path skips the parser when no `$` is present. See `docs/HLD.md` §9 (and the intended `DOMAIN.md`) for the full grammar.
- **The pybatch repr→eval command model.** Every action is a `PythonBatchCommandBase` subclass with a *dual identity*: it **executes** (`__enter__`/`__call__`/`__exit__`) and its **`__repr__` emits eval-able Python source**. `PythonBatchCommandAccum` groups commands into named sections and renders the whole `*-sync.py` / `*-copy.py` script, which is later re-imported and re-run. **`__init__` and `__repr__`/`repr_own_args` must stay in perfect sync** — a mismatch silently corrupts the generated script. Author commands declare behavior via `__init_subclass__` flags (`essential`, `call__call__`, `is_context_manager`, `is_anonymous`, `kwargs_defaults`).
- **Custom YAML tags.** Definitions are loaded via `aYaml.YamlReader` subclasses that register tag handlers: `!define`, `!define_if_not_exist`, `!+=` (append), `!include`/`__include__`, `__environment__`, `!index` / OS-specific `!index_*`, `!require`. Conditionals (`__if__`) are evaluated per-document. aYaml also monkey-patches PyYAML node classes at import time.
- **Cross-platform branching.** OS/runtime handling is **scattered, not centralized**. Expect `os_family_name` / `sys.platform` branches in `instl_main`, `configVar`, `utils`, and inside individual pybatch classes (`Chmod`/`Chown`/`ChFlags`). pybatch also selects platform command classes (`POSIXBatchCommands`, `MacOnlyBatchCommands`, `WinOnlyBatchCommands`) **at import time**; the inactive platform's classes are aliased to dummies.
- **`svnTree` / "svn" naming is largely historical.** The `svn_item_t` table and `SVNTable`/`SVNRow` model the **info-map** (every repo file/dir with revision, checksum, size, download state). The default/maintained sync backend is the URL/curl path; the actual SVN backend is unmaintained. Don't assume Subversion is involved just because of the name.

## 7. Gotchas / landmines

- **`eval`/`exec` on serialized commands and config.** The plan is shipped as Python source and `eval`'d (`EvalShellCommand`, `If.__call__`, `batch_accum.__repr__`); config `__if__` conditions are `eval`'d; `run_batch_file` can `exec` into host globals; `do_python` and the email-template path also `eval`. This is powerful but security-sensitive and hard to sandbox — treat any index.yaml/config string reaching these as untrusted.
- **Import-time side effects.** Option parsing uses `OptionToConfigVar` descriptors that **mutate the global `config_vars` at parse time**, with import-time-seeded defaults. Parsing is therefore **not idempotent**; recursive/forked invocations rely on scoped config-var contexts to avoid cross-contamination. aYaml patches PyYAML node classes at import; pybatch picks platform classes at import; `instlGui` creates the Tk root at import (non-importable headless).
- **God-object modules.** `InstlInstanceBase` (root of all commands), `InstlClient` (~660 lines), `InstlAdmin` (~1480 lines, `getattr`-dispatched `do_*`), `PythonBatchCommandBase`, `SVNTable` (~1600 lines), `IndexItemsTable`, `ConfigVarStack`. Changes ripple widely; data flows between methods implicitly via config-var keys, so order matters.
- **Swallowed exceptions.** Broad `except: pass` hides failures in several places (`should_wtar`, `do_translate_guids`, `extract_info`, the Redis heartbeat thread, GUI activate/upload). Don't trust "it ran without error" — log and narrow when you touch these.
- **Process-global, non-reentrant state.** `config_vars`, the `DBManager` class-level table descriptors, `ConnectionBase.repo_connection`, the download module singletons (control channel, observability, telemetry flag), and pybatch's class-level progress/stage stack are all shared. The runtime is **not thread-safe**; tests rely on `reset_*`/`clear()` hooks for isolation.
- **DB coupling.** One shared SQLite DB (`:memory:` by default) via lazy descriptors; transaction nesting is hand-rolled and can swallow `OperationalError`. `SVNRow` unpacks columns **positionally**, coupling it to `SELECT *` order.

## 8. Contributing / where to start

- Read `docs/ARCHITECTURE.md` then `docs/HLD.md` before making structural changes; `docs/LLD.md` for internals.
- Good first contributions are the low-risk cleanups called out in `docs/ARCHITECTURE.md` §6 (Architectural Pain Points & Refactoring Themes); `docs/REFACTORING.md` tracks the roadmap and what has actually been done. Quick wins there:
  - Delete dead code (`if False:` blocks, no-op stubs, unreachable bodies, always-false debug flags).
  - Narrow swallowed exceptions (log instead of `except: pass`).
  - Fix the enumerated latent bugs (e.g. `verbatim=source_url==['url']` always False in `instlInstanceSync_url.py`; `IsSymlink` defining `repr_own_args` instead of `__repr__`; missing-`f` f-strings, e.g. the `SVNRow.__repr__` continuation lines in `svnTree/svnTable.py` and the `WHERE iid == "{iid}"` clauses in `db/indexItemTable.py` / `svnTree/svnTable.py`).
  - Extract duplicated logic (the telemetry denylist kept in two places — `downloadEvents._DISALLOWED_EVENT_FIELDS` and `downloadRetry._DISALLOWED_EVENT_FIELDS`; the repeated detail-query/atomic-write/timestamp helpers). Note the two `_run_fallback_after_curl_range_failure` methods (`ParallelRun` and `CurlTransfer`) are **deliberately** not shared — a comment at each site records the decision.
- When adding a pybatch command, keep `__init__` and `__repr__`/`repr_own_args` in sync and add a round-trip test under `pybatch/test`. When adding config behavior, prefer scoped contexts over mutating the global stack.
- Test before pushing: `python3.12 -m unittest discover -s . -p 'test_*.py'`. Commit/push only when explicitly asked; branch off `master` first.

## 9. Documentation rules (mandatory)

The docs under `docs/` plus this file are treated as part of the code. A change that makes a
document wrong is an incomplete change. These rules are specific because the generic version
("keep docs updated") was already in force elsewhere and the suite still drifted: a reverted
refactor stayed documented as done in six files, and 186 `file.py:NNN` citations rotted.

### 9.1 The same-change rule

If your change alters something a document asserts, update that document **in the same commit** —
not in a follow-up. Trigger table:

| You changed | Update |
|---|---|
| A module/class/function name, or moved code between modules | `docs/LLD.md`, plus `docs/HLD.md` if a subsystem's responsibilities moved |
| Subsystem boundaries, layering, or a runtime flow | `docs/ARCHITECTURE.md`, `docs/HLD.md` |
| A `DOWNLOAD_EVENT` field, event type, enum value, or the log prefix | `docs/download-events.md` **and** flag it for Waves Central (see §9.6) |
| A config-var name or default in `defaults/*.yaml` or a `setdefault(...)` in code | wherever it is tabulated (`docs/LLD.md`, `docs/HLD.md`) |
| Index / info-map / require YAML input surface | `docs/DOMAIN.md` |
| Tests added, deleted, or a runner changed | `docs/TESTING.md` |
| Refactoring work started, finished, abandoned, or reverted | `docs/REFACTORING.md` |
| Repo layout, commands, build, or agent conventions | this file |

### 9.2 Cite symbols, never line numbers

Write `curlHelper.create_download_instructions`, not `curlHelper.py:461`. Symbols survive edits;
line numbers rot silently and there is no test that catches them. Do not add `file.py:NNN`,
`(line 230)`, or `(230-367)` to any document. Ranges quoted as *sizes* ("a 1481-line module") are
fine when measured; ranges used as *locations* are not.

### 9.3 Reverting code reverts its docs

If you revert, abandon, or reduce the scope of a change, delete or correct the text describing it in
the same commit. Never leave a doc saying a thing exists when it does not — that is worse than
having never documented it, because readers act on it. The same applies to "planned" work: if it was
not done, do not write it in the present tense.

### 9.4 Reference docs describe the present; only the roadmap carries status

`ARCHITECTURE.md`, `HLD.md`, `LLD.md`, `DOMAIN.md`, `download-events.md` describe what the code **is
now**, in present tense. Keep out of them: "landed", "now decomposed", "previously", "as of this
refactor", branch names as state, and internal process labels (workstream numbers, phase numbers,
ticket ids). Those mean nothing to a reader six months out. `REFACTORING.md` is the one document
that legitimately carries status — and it must distinguish **done / not started / attempted and
reverted** truthfully, including *why* a reverted approach failed, so nobody retries it blindly.

### 9.5 Do not assert what you did not check

Every number goes in only if you measured it in that session: line counts, method counts, test
counts, config-var defaults, pass/fail baselines. Do not copy a number forward from an older doc.
Two specific traps:

- **Config-var defaults live in two places.** `defaults/*.yaml` and `config_vars.setdefault(...)` /
  `_TRACKED_FLAGS` can disagree. The YAML wins once loaded; the code default only applies when the
  key is undefined. If they differ, say which is authoritative.
- **Do not claim a file or test exists without opening it.** A doc here once cited a Central contract
  test that had never been written.

If you cannot verify something, write that in the doc ("not verified", "no recorded runs") rather
than guessing. And when a statement turns out wrong, replace it with the correct **specific**
statement — do not soften it into something vague that is merely un-falsifiable.

### 9.6 `download-events.md` is a cross-repo contract

It documents the wire format Waves Central parses, and an error there breaks a shipped consumer.
Its sources of truth are `pyinstl/downloadEvents.py`, `pyinstl/downloadState.py`,
`pyinstl/downloadFailures.py`; the consumer lives in Central under
`src/services/instl/behaviours/shell/progress/`. Check it field by field against the emitters after
any change, keep `pyinstl/test/test_downloadEventsContract.py` passing, and remember additive
optional fields keep `schemaVersion` at 1 while renames/removals/retypes must bump it.

Central carries the mirror of this rule in its own `AGENTS.md` / `documentation/agent.md`
("Cross-repo contract with instl"). If you change the wire shape, say so explicitly in the PR
description of **both** repos — a silent divergence here breaks installs in the field. Note Central's
progress bar still parses instl's **legacy text** progress line, so that line must keep being emitted
even though the structured channel exists.

### 9.7 Finish-line check

Before you call a change done:

1. `git diff` your own doc edits and confirm each claim against the code you just wrote.
2. Grep your additions for `\.py:[0-9]` and for process labels; there should be none.
3. If you touched `download*`, re-read `docs/download-events.md` §3–§4 against the emitters.
4. Say plainly in your summary which docs you updated, and which claims you could not verify.
