# AGENTS.md — instl

> This file is also symlinked as `CLAUDE.md`. It is the entry document for both human contributors and coding agents. Keep it accurate; when in doubt, defer to the deep docs under `docs/`.

## 1. What this repo is

**instl** is a YAML-driven, cross-platform software-deployment / installer engine by Waves Audio (GitHub: `wavesaudio/instl`). It turns a central, version-controlled description of *what should be installed* — an **index** of install-items plus an **info-map** of every file in the repository — into an ordered, executable plan that downloads, unpacks, copies, permissions, and registers files on an end-user machine, and into the admin tooling that builds and publishes those repositories.

The defining design choice: instl rarely touches the filesystem directly. It **generates a standalone Python "batch" script** (a tree of `pybatch` command objects serialized to eval-able Python source) that performs the actual work when run. The model is **plan → emit script → run script**.

Three personas:
- **Client (end-user)** — `instl sync` / `copy` / `synccopy` / `remove` / `uninstall` / `report-*`. Resolves the install-item dependency graph, downloads files from the remote repo (typically S3 via curl), copies/unwtars them, runs pre/post actions, rewrites the site `require.yaml`. Implemented by `InstlClient` and subclasses.
- **Admin (Waves engineer / CI)** — `instl admin <subcommand>`: SVN/staging maintenance, info-map/index verification, building per-repo-rev artifacts and uploading to S3 (`up2s3` / `up-short-index`), activating a repo-rev, and a Redis-triggered upload daemon. Implemented by `InstlAdmin`. **Admin mode only works when running from source (not frozen).**
- **GUI** — a Tk/ttk desktop front-end (`InstlGui`) with Client, Admin, and Activate tabs. It does **not** run instl logic in-process — each tab builds an instl command line and spawns the instl executable as a subprocess (the Activate tab also talks to Redis directly).

There is also a **doit** mode (`InstlDoIt`, a dependency-ordered generic action runner) and a **misc** / `do_something` mode (`InstlMisc`: `wtar`/`unwtar`/`checksum`/`ls`/`check-checksum`/etc.).

> Note on the consumer side: Waves Central — instl's primary consumer — drives instl **only as a CLI** (the Client persona, plus `exec`/`doit`/`run-process`). It never uses an instl "admin" or "GUI" persona; OS elevation is owned by Central (a `runAsAdmin` flag plus a Mac `InstlHelperApplication` LaunchDaemon, `com.waves.central.InstlHelper`), not by an instl admin mode. The admin/GUI personas above are instl-internal (Waves engineer / CI tooling).

For depth, read these (most exist today; the others are the intended home for that content):
- `docs/ARCHITECTURE.md` — layering, dependency graph, runtime flows. **Read this first.**
- `docs/HLD.md` — per-subsystem responsibilities, interfaces, owned state.
- `docs/LLD.md` — line-by-line internals.
- `manual/` — the user-facing manual (`SUMMARY.md`, `ch00-*`, `up2s3 automation.md`).
- DOMAIN / TESTING / REFACTORING content: not yet split into dedicated files — see the relevant sections below and the `*/test/` directories.

## 2. Repository layout

```
instl                  Executable launcher (python3.12 shebang); reopens stdio as UTF-8, calls instl_own_main
instl.spec             PyInstaller build spec (universal2, console app)
create_venv.sh         venv bootstrap (mac-only reqs first, then base)
requirements*.txt      Dependency sets: base / admin / mac_only / win_only
defaults/              Seed config YAML (main.yaml, Instl*.yaml) + SQLite DDL (*.ddl)
docs/                  ARCHITECTURE.md, HLD.md, LLD.md
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

That emitted `build-instl.py` calls `build_python.build_onedir(instl_folder, instl.spec, 'instl', verpatch_path)`, which drives PyInstaller via `instl.spec` to produce the onedir bundle, then copies it to the target. (Source: Central `build_instl/build_instl.py:44-52`, `build_instl.sh`.) The instl source is pulled from a local `instl/` folder (`git checkout download-enhancements`) or cloned from `github.com/wavesaudio/instl.git --branch download-enhancements` — i.e. the active integration branch is **`download-enhancements`**, not `master`.

- **Signing (Mac).** `sign_instl.py` signs every non-symlink file in the bundle (`codesign --force --verify --no-strict -vvvv --sign <identity>`, inner `instl` binary signed last), then signs the bundle root with `--timestamp --options runtime --entitlements <ent>` (hardened runtime). On universal builds, `tasks/afterSign.js` re-signs the bundle and the instl/WLE binaries are injected **after** the app is signed (an electron-builder universal-binary workaround). The production build takes instl from the build's `Tools/instl.bundle` (or Artifactory), **not** from a checked-in zip (`useEmbeddedInstl=false`).
- **Runtime layout.** Central resolves three side-by-side engines: the latest bundle at `Waves Central.app/Contents/Resources/res/external/bin/instl.bundle/Contents/{MacOS|Win64}/instl(.exe)`, plus checked-in legacy executables `bin/instl-V9` and `bin/instl-V10`. Engine selection is per-repository: `repositoryKey > centralOneRepository` ⇒ latest engine, else legacy V9; online actions (synccopy/sync/copy/report-versions) are forbidden on non-latest engines. Legacy V9/V10 do **not** support `--log` (Central redirects with `>> buffer 2>&1`). (Source: Central `src/services/instl/behaviours/shell/common.tsx:49-114`.)
- **Invocation contract.** Central drives instl as a pure CLI: `"<instl>" <command> --in <in.yaml> --out <out.py> --log <buffer> --run` for `copy`/`sync`/`synccopy`/`uninstall` (the latest engine emits a `.py` pybatch as `--out`). `report-versions` emits JSON directly and is **not** given `--run`. The version organizer uses `exec --config-file <locations.yaml> --in organizer.py --out <out.py> --log <log>` (the `exec` runs the in-process script, no `--run`). Elevated/live runs wrap the emitted command in an `.irl` run-list and call `run-process --abort-file <.abort> --in <.irl>`; cancellation deletes the abort-file (instl watches it to terminate). Central's external Python scripts (`reportVersions.py`, `install_cen.py`, `organizer.py`) build their own instl invocations from the `__INSTL_LAUNCH_COMMAND__` config var.

## 5. Running tests

Tests are stdlib `unittest`, colocated under each package's `test/` directory (`pyinstl/test`, `pybatch/test`, `configVar/test`, `aYaml/test`, `svnTree/test`, `utils/test`).

```bash
source venv/bin/activate
python3.12 -m unittest discover -s . -p 'test_*.py'
# or a single module:
python3.12 -m unittest pyinstl.test.test_downloadFailures
```

There is no `pyproject.toml`/`pytest.ini`/`setup.py`; tests assume the repo root on `sys.path` and a working venv. (A dedicated `docs/TESTING.md` is the intended home for fuller test guidance.)

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
- Good first contributions are the low-risk cleanups called out in `docs/ARCHITECTURE.md` §6 (Architectural Pain Points & Refactoring Themes) — the intended home for a fuller `REFACTORING.md`. Quick wins there:
  - Delete dead code (`if False:` blocks, no-op stubs, unreachable bodies, always-false debug flags).
  - Narrow swallowed exceptions (log instead of `except: pass`).
  - Fix the enumerated latent bugs (e.g. `verbatim=source_url==['url']` always False; `RmGlob` `log.wanging` typo; `IsSymlink` defining `repr_own_args` instead of `__repr__`; missing-`f` f-strings; `get_disk_free_space` referencing an unimported `win32file`).
  - Extract duplicated logic (the curl pause/offline/retry loop shared by `ParallelRun` and `CurlWithInternalParallel`; the telemetry denylist kept in two places; the repeated detail-query/atomic-write/timestamp helpers).
- When adding a pybatch command, keep `__init__` and `__repr__`/`repr_own_args` in sync and add a round-trip test under `pybatch/test`. When adding config behavior, prefer scoped contexts over mutating the global stack.
- Test before pushing: `python3.12 -m unittest discover -s . -p 'test_*.py'`. Commit/push only when explicitly asked; branch off `master` first.
