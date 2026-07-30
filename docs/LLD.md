# instl — Low-Level Design (LLD)

Detailed, code-grounded design of each subsystem. See ARCHITECTURE.md for the cross-cutting view and HLD.md for the subsystem-level design.

> **Modernization note (branch `instl-modernization`).** Three former single-file god-objects are now
> packages behind thin re-export shims: `pyinstl/instlAdmin.py` → `pyinstl/admin/`,
> `pyinstl/instlClient.py` → `pyinstl/client/`, `pyinstl/instlGui.py` → `pyinstl/gui/` (behavior-identical
> mixin extracts). A typed `config_vars` seam lives at `configVar/accessors.py`. A characterization test
> net was added under `tests/characterization/` — `test_pybatch_serialization_golden.py`,
> `test_configvar_resolution_golden.py`, and `test_instlclient_copy_golden.py` — alongside the existing
> per-package suites (`pybatch/test/`, `configVar/test/`, `svnTree/test/`, `utils/test/`, `pyinstl/test/`).
> These goldens pin emitted output and must stay byte-stable; the suite is the GREEN gate
> (`./.venv/bin/python -m pytest -q -p no:cacheprovider`). Subsystem sections below are annotated with
> these deltas where the file layout changed; line numbers cite the original monolithic files.

## Contents

- [CLI & Entry Point](#cli-entry-point)
- [Instl Instance Base](#instl-instance-base)
- [Sync Backends & Connections](#sync-backends-connections)
- [Client Commands (install/copy/remove/report/uninstall)](#client-commands-install-copy-remove-report-uninstall)
- [Admin Tooling](#admin-tooling)
- [GUI](#gui)
- [Download Subsystem](#download-subsystem)
- [PyBatch Command Objects](#pybatch-command-objects)
- [ConfigVar System](#configvar-system)
- [Data Tables (svnTree + db)](#data-tables-svntree-db)
- [aYaml & Utils](#ayaml-utils)

---

## CLI & Entry Point

This subsystem is the single boot path for every `instl` run — both direct CLI invocation and recursive sub-process invocation (e.g. the `up2s3` admin command relaunching `instl_own_main` in a child process). It owns process startup, stdout/stderr UTF-8 normalization, command-line parsing into the global `config_vars`, assembly of the initial variable set, top-level logging/exception bracketing via a context manager, and dispatch to the correct command-mode handler.

### Files

- `instl` — executable launcher (shebang `#!/usr/bin/env python3.12`).
- `pyinstl/instl_main.py` — real entry point, path resolvers, SSL fixup, `InvocationReporter`, dispatch.
- `pyinstl/cmdOptions.py` — argparse glue: `OptionToConfigVar`, `CommandLineOptions`, `prepare_args_parser`, `read_command_line_options`.
- `pyinstl/instlCommandList.py` — `command-list` mode runner.
- `pyinstl/instlException.py` — `InstlException`, `InstlFatalException`.
- `instl.spec` — PyInstaller build spec (`target_arch='universal2'`, imports `yaml`).

### Boot sequence (numbered)

1. `instl` (launcher) reopens `sys.stdout` and `sys.stderr` as `open(stream.fileno(), mode='w', encoding='utf8', buffering=1, errors='backslashreplace')`, each wrapped in its own `try/except` that only prints a warning on failure (the run continues regardless). Then `if __name__ == "__main__": instl_own_main(argv=sys.argv)`.
2. `instl_own_main(argv)` enters `with InvocationReporter(argv, report_own_progress=False):`. The context manager's `enter_self` sets `VENDOR_NAME`/`APPLICATION_NAME` env defaults and calls `config_logger(...)` (logging must be configured before any path resolution so the system log file is correctly located).
3. `fix_ssl_paths()` then `from pyinstl.connectionBase import inject_truststore; inject_truststore()` (imported lazily, inside the function).
4. `argv = argv.copy()` (defends against `sys.argv` mutation in recursive/forked invocations), then `options = CommandLineOptions()` and `command_names = read_command_line_options(options, argv[1:])`. Parsing writes through descriptors into the global `config_vars` (see below).
5. The ~40-key `initial_vars` plain dict is assembled (resolved paths, OS identity, sqlite version strings, appdirs dirs, temp dir, invocation random id, `__ARGV__`, uid/gid, etc.), with platform branches.
6. If `options.__MAIN_COMMAND__ == "command-list"`, delegate to `run_commands_from_file(initial_vars, options)` and `return` early (no instance constructed here).
7. Otherwise `_start_control_channel_if_needed(options.__MAIN_COMMAND__)` (best-effort, sync-only).
8. `is_compiled = getattr(sys, 'frozen', False)`, then `match options.mode, is_compiled:` dispatch constructs the right command instance, calls `instance.init_from_cmd_line_options(options)`, then `instance.do_command()`.
9. After the match, `if instance is not None: instance.close()` for disposal.
10. On exit, `InvocationReporter.exit_self` logs `command_time_sec` and end time. Exception suppression/propagation is owned by the inherited `PythonBatchRuntime.__enter__/__exit__`.

### Component breakdown

#### `InvocationReporter(PythonBatchRuntime)` — `pyinstl/instl_main.py:104`
The outermost context manager for a run.
- `__init__(self, argv, **kwargs)` — calls `super().__init__(name="InvocationReporter", **kwargs)`; sets `self.start_time = datetime.datetime.now()`, `self.random_invocation_name` = 16 random lowercase letters, `self.argv = argv.copy()`.
- `enter_self(self) -> None` — `os.environ.setdefault("VENDOR_NAME", "Waves Audio")` and `"APPLICATION_NAME", "Waves Central"`; `config_logger(argv=self.argv, config_vars=config_vars)`; logs a `===== {random_invocation_name} =====` header, start time, `argv[0]`, and `argv[1:]`. The entire body is wrapped in `try/except` → `log.warning` so logging setup never aborts the run.
- `exit_self(self, exit_return) -> None` — logs `self.command_time_sec`, end time, and the closing `=====` banner; also `try/except`-guarded.
- Collaborators: `PythonBatchRuntime` (pybatch base; provides `__enter__/__exit__`, `command_time_sec`, exception machinery), `config_logger`, global `config_vars`.

#### `OptionToConfigVar` — `pyinstl/cmdOptions.py:6`
A descriptor that bridges argparse attribute set/get directly to the global `config_vars` singleton.
- `__init__(self, default=None, set_value=None)`.
- `__set_name__(self, owner, name)` — records `self.var_name = name`; **at class-definition (import) time**, if `default is not None`, seeds `config_vars[var_name] = default`.
- `__get__(self, instance, owner)` — returns `str(config_vars[var_name])` if present, else `None`.
- `__set__(self, instance, value)` — if `value is not None`: writes `self.set_value` when configured (force-a-constant pattern); else writes `value` directly when it `isinstance(value, collections.abc.Sequence)`, otherwise `str(value)`. (Note: a Python `str` is itself a `Sequence`, so plain string values take the Sequence branch.)

#### `CommandLineOptions` — `pyinstl/cmdOptions.py:42`
The namespace object handed to `parser.parse_args`. ~45 class attributes are `OptionToConfigVar` descriptors (`__MAIN_COMMAND__`, `__MAIN_INPUT_FILE__`, `__MAIN_OUT_FILE__`, `__RUN_BATCH__`, `__CONFIG_FILE__`, `__CREDENTIALS__`, `__MAIN_DB_FILE__`, `__FAIL_EXIT_CODE__`, `__JUST_WITH_NUMBER__` (default `"0"`), etc.). Because attributes are descriptors, parsing mutates `config_vars` in place — the namespace object itself holds almost no per-instance state.
- `__init__(self)` — sets only the three plain instance attrs `self.mode = None`, `self.which_revision = None`, `self.define = None` (these are NOT descriptors and live in the instance `__dict__`).
- `__str__` — dumps `vars(self)` sorted (only the plain attrs, not the descriptor-backed config vars).

#### `prepare_args_parser(in_command)` — `pyinstl/cmdOptions.py:98`
Builds the command catalog and an argparse parser for a single command.
- Returns `(parser, command_names)`. When `in_command is None`, returns `(None, command_names)` for catalog enumeration only (used to seed `__COMMAND_NAMES__`).
- `all_command_details` is assembled in four lazily-merged groups (client, do_something, admin, misc/gui/doit), each guarded by `if in_command not in all_command_details:` so only the group containing the requested command (and earlier ones) is built. Each entry is `{'mode': ..., 'options': (tokens...), 'help': ...}`.
- Installs `argparse.ArgumentParser.convert_arg_line_to_args = decent_convert_arg_line_to_args` (strips whitespace, drops `#` comment lines and end-of-line comments) to support `@file` argument expansion via `fromfile_prefix_chars='@'`. Parser uses `prefix_chars='-+'`.
- A single subparser is added for `in_command`; `command_parser.set_defaults(mode=command_details['mode'])` is how `options.mode` gets populated.
- Option groups are added per option token: `in_opt`/`in`/`in+` (`--in/-i`, optional/required/`nargs='+'`), `out` (`--out/-o`), `run` (`--run/-r` store_true → `__RUN_BATCH__`), `output_format`, `cred` (`--credentials`), `conf`/`conf_opt` (`--config-file/-s`, required only for `conf`), `prog` (start/total/no-numbers progress), `limit`, `parallel` (`--parallel/-p` → `__RUN_COMMAND_LIST_IN_PARALLEL__`), `rev`, `write-config-vars`, `quiet-until-error`.
- A `match in_command:` block adds per-command-only options: `read-yaml` (`--silent`), `activate-repo-rev` (`--just-with-number`), `unwtar` (`--no-artifacts`), `p2s3` (`--revision` → `which_revision`), `ls` (`--output-format` → `LS_FORMAT`), `fail` (`--exit-code`, `--sleep`), `report-versions` (`--only-installed`), `help` (positional `subject`), `run-process` (`--abort-file`, `--shell`, positional `RUN_PROCESS_ARGUMENTS` `nargs='...'`), `exec` (positional `args` `nargs=argparse.REMAINDER`), `resolve` (`--compare-dates`, `--resolve-as-yaml`, `--unresolve-indicator`).
- A `general:` group is always added: `--define` (`X=y,A=b` → `define`), `--no-stdout`/`--no-system-log` (`store_const`), `--log` (`nargs='+'`), `--db` (`__MAIN_DB_FILE__`).

#### `read_command_line_options(name_space_obj, arg_list=None)` — `pyinstl/cmdOptions.py:496`
Top-level parse entry. `command_name = arg_list[0] if arg_list else None`, then `prepare_args_parser(command_name)`. If a parser was returned, `parser.parse_args(arg_list, namespace=name_space_obj)`; otherwise (no args) `name_space_obj.mode = "interactive"`. Returns `command_names`. Used by `instl_own_main` and by `CommandListRunner.run_one_command`.

#### Path / launch resolvers — `pyinstl/instl_main.py:36-86`
All `@lru_cache(maxsize=None)`, branching on `getattr(sys, 'frozen', False)`:
- `get_path_to_instl_app()` — frozen: `Path(sys.executable).resolve()`; source: `Path(__file__).resolve().parent.parent.joinpath('instl')`.
- `get_instl_launch_command()` — frozen or non-Win: `quoteme_double(exec_path)`; on Win from source: joins `quoteme_double(sys.executable)` + `quoteme_double(exec_path)` (the interpreter must be invoked explicitly).
- `get_data_folder()` — frozen: `<app>.parent.parent / "Resources"` (matches the macOS `.app` layout produced by `instl.spec`); source: `<app>.parent`.
- `get_exec_folder()` — frozen: `Path(sys.executable).parent.resolve()`; source: empty `Path()`.

#### `fix_ssl_paths()` — `pyinstl/instl_main.py:88`
Frozen-only. Sets `os.environ["REQUESTS_CA_BUNDLE"]` and `["SSL_CERT_FILE"]` to `certifi.where()` to avoid OpenSSL 3.x `[ASN1] nested asn1 error` from malformed certs in the Windows cert store. Deliberately does **not** call `ssl.create_default_context()` (which would load the Windows store and trigger the same error).

#### `_start_control_channel_if_needed(main_command)` / `_CONTROL_CHANNEL_COMMANDS` — `pyinstl/instl_main.py:139`
`_CONTROL_CHANNEL_COMMANDS = frozenset({"sync", "synccopy", "check-checksum"})`. For those commands only, lazily imports `downloadControlChannel.get_global_channel().start()` to spawn the stdin reader daemon. Wrapped in `try/except` → `log.debug` only (best-effort; never breaks a sync run). Intentionally not started for other commands so they don't steal stdin from interactive callers.

#### `CommandListRunner` / `run_commands_from_file` — `pyinstl/instlCommandList.py`
Handles `command-list` mode (commands limited to `do_something`/`InstlMisc`).
- `run_commands_from_file(initial_vars, options)` — `config_vars.setdefault("__START_DYNAMIC_PROGRESS__", "0")` and `"__TOTAL_DYNAMIC_PROGRESS__"`; builds a `CommandListRunner`; `parallel_run = "__RUN_COMMAND_LIST_IN_PARALLEL__" in config_vars`; `runner.run(parallel=parallel_run)`.
- `CommandListRunner.__init__` — constructs **one** `InstlMisc(initial_vars, "command-list")` reused across all sub-commands; calls `init_from_cmd_line_options(options)` once.
- `prepare_command_list_from_file()` — reads every `__CONFIG_FILE__` line, `config_vars.resolve_str(line.strip())`, then `shlex.split` into an argv list.
- `run_one_command(argv)` — fresh `CommandLineOptions()` + `read_command_line_options(options, argv)`, then `with config_vars.push_scope_context():` re-inits the shared instance and `do_command()` (the scope push is what prevents cross-command config_vars contamination).
- `do_forked_command(argv)` — `os.fork()`; child runs `run_one_command(argv)` then `exit(0)`; parent appends pid to `self.child_pids`. Parallel `run()` forks all then `os.waitpid(pid, 0)` for each. (Fork-based → POSIX-only.)

#### `InstlException` / `InstlFatalException` — `pyinstl/instlException.py`
- `InstlException(in_message, in_original_exception=None)` — stores `self.original_exception` (chained cause).
- `InstlFatalException(*messages)` — joins parts via `" ".join(str(m) for m in messages)` into `self.message`; `__str__` returns it.
Raised across the codebase; caught explicitly at the interactive loop (`instlInstanceBase_interactive.py:149`) and otherwise handled by `PythonBatchRuntime.__exit__`.

### Public interfaces / contracts

- `instl_own_main(argv) -> None` — sole boot entry; called by the `instl` launcher and reused as a `multiprocessing.Process` target by `pyinstl/instlAdmin.py:1185` (up2s3 recursive invocation).
- `read_command_line_options(name_space_obj, arg_list=None) -> command_names`.
- `CommandLineOptions()` — constructed by callers before parsing; descriptors write through to `config_vars`.
- `instance.init_from_cmd_line_options(options)` — the contract every command instance implements (`pyinstl/instlInstanceBase.py:198`); called by `instl_main` (and `CommandListRunner`) after construction. It copies remaining namespace fields (`which_revision`, `subject`, `--define X=y` pairs) into `config_vars` and computes the default out file.
- `run_commands_from_file(initial_vars, options)` — invoked when `__MAIN_COMMAND__ == "command-list"`.

### Dispatch table (`match options.mode, is_compiled`)

| mode | is_compiled | handler |
|---|---|---|
| `client` | any | `InstlClientFactory(initial_vars, __MAIN_COMMAND__)` → `init_from_cmd_line_options` → `do_command` |
| `doit` | any | `InstlDoIt(initial_vars)` |
| `do_something` | any | `InstlMisc(initial_vars, __MAIN_COMMAND__)` |
| `admin` | **False only** | `InstlAdmin(initial_vars)` (also `raise EnvironmentError` unless `os_family_name in ("Linux","Mac")`) |
| `interactive` | **False only** | builds both `InstlClient` and `InstlAdmin`, calls `go_interactive(client, admin)` |
| `gui` | **False only** | `InstlGui(initial_vars)` |

`admin`/`interactive`/`gui` are intentionally unavailable in frozen builds (no `case` arm matches when `is_compiled` is True).

### `initial_vars` (selected keys — `instl_main.py:168`)

A plain dict (NOT yet `config_vars`) handed to the command instance, which loads it into `config_vars`. Notable keys: `__INSTL_EXE_PATH__`, `__CURR_WORKING_DIR__` (`utils.safe_getcwd()`), `__INSTL_LAUNCH_COMMAND__`, `__INSTL_DATA_FOLDER__`, `__INSTL_DEFAULTS_FOLDER__`, `__INSTL_COMPILED__`, `__PYTHON_VERSION__`, `__PYSQLITE3_VERSION__`/`__SQLITE_VERSION__` (version strings only), `__COMMAND_NAMES__`, `__CURRENT_OS__`/`__CURRENT_OS_SECOND_NAME__`/`__CURRENT_OS_NAMES__`/`__CURRENT_OS_DESCRIPTION__`, `__SITE_DATA_DIR__`/`__SITE_CONFIG_DIR__`/`__USER_DATA_DIR__`/`__USER_CONFIG_DIR__` (appdirs), `__USER_HOME_DIR__`/`__USER_DESKTOP_DIR__`/`__USER_TEMP_DIR__`, `__SYSTEM_LOG_FILE_PATH__`, `__INVOCATION_RANDOM_ID__` (16 random letters — a **second** random id distinct from `InvocationReporter.random_invocation_name`), `__SUDO_USER__`, `VENDOR_NAME`/`APPLICATION_NAME`, `__ARGV__`, `ACTING_UID`/`ACTING_GID` (= -1). If `hasattr(options, 'args')`, adds `__REMAINDER_ARGV__`.

### Platform branches & edge cases

- **Non-Win**: `__USER_ID__ = str(os.getuid())`, `__GROUP_ID__ = str(os.getgid())`. **Win**: `__USER_ID__ = -1`, `__GROUP_ID__ = -1`, plus `__WHO_LOCKS_FILE_DLL_PATH__ = f"{get_exec_folder()}/who_locks_file.dll"`.
- **OS-name derivation** (`instl_main.py:29-33`): `os_family_name = current_os_names[0]`; `os_second_name` is initialized to `current_os_names[0]` and only overwritten with `current_os_names[1]` if `len > 1`.
- **No args** → `read_command_line_options` sets `mode = "interactive"` (only reachable non-frozen).
- **command-list** short-circuits before the dispatch `match` (early `return`).
- **stdout/stderr reopen** failures are non-fatal (warn and continue).
- **Exit-code / exception policy is not in this subsystem**: there is no `try/except` in `instl_own_main`. Suppression vs. re-raise is owned by `PythonBatchRuntime.__enter__/__exit__`; the `fail` command computes its exit code in `InstlMisc` (`instlMisc.py:232`), not here.

### Refactoring notes (this subsystem)

1. **Global mutable state via descriptor side-effects** — `pyinstl/cmdOptions.py:6-39` (`OptionToConfigVar`) and the `CommandLineOptions` class body (`:46-87`). Parsing does not populate the namespace; it writes through `__set__`/`__set_name__` into the global `config_vars`, and `__get__` reads back from it. Defaults are seeded at import time (`__set_name__`), making parsing non-idempotent and order-dependent. Recursive/forked invocations rely on `push_scope_context()` to avoid contamination. Direction: have the parser fill a plain namespace, then one explicit step copies values into a `config_vars` scope; drop import-time default seeding.
2. **`instl_own_main` is a god-function** — `pyinstl/instl_main.py:156-276` still mixes SSL setup, truststore injection, path resolution, a ~40-entry `initial_vars` literal, OS branching, control-channel bootstrap, and a 6-arm dispatch. Direction: extract `build_initial_vars(options)`, `dispatch_command(options, initial_vars, is_compiled)`, and a small `bootstrap()` for SSL/truststore.
3. **Misleading initial assignment** — `os_second_name = current_os_names[0]` then conditionally overwritten (`instl_main.py:31-33`); collapse to `os_second_name = current_os_names[1] if len(current_os_names) > 1 else current_os_names[0]`. Also delete the commented `utils.set_max_open_files` at `:21` and the large commented fork block at `instlCommandList.py:70-84`.
4. **Scattered platform/frozen branching** — `getattr(sys,'frozen',False)` and `os_family_name == "Win"` are repeated across `get_path_to_instl_app`/`get_instl_launch_command`/`get_data_folder`/`get_exec_folder`/`fix_ssl_paths` and the `initial_vars` Win branch (`instl_main.py:36-102, 204-212`). Direction: a single `RuntimeLayout`/`Environment` object (frozen?, os, exec_dir, data_dir, launch_command) computed once.
5. **Implicit/indirect top-level error handling** — no handler in `instl_own_main`; exit-code policy is split (pybatch `__exit__` vs. `InstlMisc` for `fail`). Direction: document or centralize the exit-code contract at the entry point.
6. **Catalog + argparse wiring intertwined** — `prepare_args_parser` (`cmdOptions.py:98-493`) mixes the command→mode/options/help data with imperative argparse construction; the cascade of `if in_command not in all_command_details` is subtle. Direction: move the catalog to a declarative table/dataclasses and build groups from a token→builder map.
7. **Inconsistent `options` token syntax** — `cmdOptions.py:157-158`: `read-info-map` uses the string `'in+'` (not a tuple, so membership works only by substring accident) and `short-index` uses a set literal `{'in','out'}` while every other entry uses a tuple. Normalize all to tuples of tokens.
8. **Duplicated random-id and UTF-8 reopen logic** — `InvocationReporter.random_invocation_name` (`instl_main.py:109`) vs `__INVOCATION_RANDOM_ID__` (`:191`) generate two independent 16-char ids; the two stdout/stderr reopen blocks in `instl:8-19` are near-identical. Factor `make_random_id()` and `reopen_utf8(stream)` helpers and decide whether one id suffices.

---

I now have the full source for both files. Let me write the LLD section grounded in the actual code.

## Instl Instance Base

The instance-base subsystem defines the abstract root of every instl command. It lives in two files:

- `pyinstl/instlInstanceBase.py` — the `InstlInstanceBase` class hierarchy plus two module-level helpers (`check_version_compatibility`, the `IndexYamlReaderBase` mixin).
- `pyinstl/instlInstanceBase_interactive.py` — the interactive REPL (`CMDObj`) and the methods monkey-patched onto `InstlInstanceBase` for interactive mode.

`InstlInstanceBase` is the inheritance root for all five command objects: `InstlClient`, `InstlAdmin`, `InstlMisc`, `InstlDoIt`, `InstlGui`. It centralizes config-var loading, YAML index reading, SQLite DB lifecycle, cache/sync path resolution, batch-file generation/execution, dependency-graph queries, and YAML serialization.

### Component breakdown

#### `IndexYamlReaderBase` (mixin) — `pyinstl/instlInstanceBase.py:56-75`

Combines `DBManager` (DB tables) and `ConfigVarYamlReader` (config-var YAML parsing). Wires the index/require YAML document tags to the `items_table` read methods.

- `__init__(self, config_vars, **kwargs)` — only calls `ConfigVarYamlReader.__init__(self, config_vars)` (note: it does NOT call `DBManager.__init__`; that is done explicitly by the subclass).
- `init_specific_doc_readers(self)` — registers `!require → self.read_require`, `!index → self.read_index`, and if `TARGET_OS` is set, an OS-specific tag `!index_$(TARGET_OS)` (e.g. `!index_Mac`). **Invariant/edge case**: raises `AssertionError` if both `!index_Mac` and `!index_Win` end up registered simultaneously (line 67-68).
- `read_index(self, a_node, *args, **kwargs)` → `self.items_table.read_index_node(a_node, **kwargs)`.
- `read_require(self, a_node, *args, **kwargs)` → `self.items_table.read_require_node(a_node, **kwargs)`.

#### `InstlInstanceBase` — `pyinstl/instlInstanceBase.py:78-566`

`class InstlInstanceBase(IndexYamlReaderBase, metaclass=abc.ABCMeta)`.

**Class attribute**
- `commands_that_need_to_refresh_db_file` (lines 87-90) — list of command names that force a fresh DB file: `copy, sync, synccopy, uninstall, remove, doit, read-yaml, translate-guids, verify-repo, depend, fix-props, up2s3, activate-repo-rev, short-index, up-short-index, report-versions`.

**Key instance attributes** (set in `__init__`, lines 92-119)
- `total_self_progress` (int) / `internal_progress` (int) — drive `progress()` reporting.
- `the_command` / `fixed_command` — the main command string; `fixed_command` is the same with `-` replaced by `_` (set in `init_from_cmd_line_options`, not `__init__`).
- `path_searcher` — `utils.SearchPaths(config_vars, "__SEARCH_PATHS__")`, seeded with CWD, the resolved `__ARGV__[0]`, and `__INSTL_DATA_FOLDER__`.
- `url_translator = connectionBase.translate_url`.
- `batch_accum = PythonBatchCommandAccum()` — accumulator for generated batch commands.
- `dl_tool = CUrlHelper()`.
- `out_file_realpath` — resolved output path (or `"stdout"`); set by `write_batch_file`.
- `update_mode` (bool, default `False`).
- `python_batch_names = PythonBatchCommandBase.get_derived_class_names()` — set of valid pybatch command names, used by `verify_actions`.
- DB tables `items_table` (IndexItemsTable) and `info_map_table` (SVNTable) are class-level `TableAccess` descriptors inherited from `DBManager`.

**Construction order matters** (`__init__`): `DBManager.__init__(self)` → `IndexYamlReaderBase.__init__(self, config_vars)` → build `path_searcher` → `init_default_vars(initial_vars)` → `read_defaults_file(super().__thisclass__.__name__)` (reads the *subclass*-named defaults file, e.g. `InstlClient.yaml`). Then search paths and `batch_accum`/`dl_tool` are set up.

**Important methods**

- `progress(self, *messages)` (121-126) — no-op unless `total_self_progress > 0`. Increments `internal_progress`; when it reaches the threshold, multiplies the threshold by 5 (a growing-denominator progress heuristic) and logs `Progress: N of M; <messages>`.
- `init_specific_doc_readers(self)` (128-147) — extends the mixin's readers. Pops `__no_tag__`/`__unknown_tag__`. Registers `!define` and the deprecated `!define_const` (both → `read_defines`, i.e. const is treated as non-const). Builds the `ACCEPTABLE_YAML_DOC_TAGS` set, appending `define_Compiled` or `define_Uncompiled` based on `__INSTL_COMPILED__`, then registers `!define_if_not_exist*` → `read_defines_if_not_exist` and other `define*` → `read_defines`.
- `init_default_vars(self, initial_vars)` (157-179) — registers the dynamic var `__NOW__` (callback returns `str(datetime.datetime.fromtimestamp(time.time()))`), applies `initial_vars`, sets value-set callbacks for `ACTING_UID`/`ACTING_GID` (`utils.set_active_user_or_group_config_var_callback`), then reads `defaults/main.yaml` (mandatory: `ignore_if_not_exist=False`) and `defaults/compile-info.yaml`. If `__COMPILATION_TIME__` is absent it sets `"unknown compilation time"` (compiled) or `"(not compiled)"`. Finally `read_user_config()`.
- `read_defaults_file(self, file_name, allow_reading_of_internal_vars=True, ignore_if_not_exist=True)` (182-185) — reads `__INSTL_DEFAULTS_FOLDER__/<file_name>.yaml`.
- `read_user_config(self)` (188-190) — reads `__USER_CONFIG_FILE_PATH__` (ignored if missing).
- `check_prerequisite_var_existence(self, prerequisite_vars)` (192-196) — raises `ValueError` listing any missing required vars.
- `init_from_cmd_line_options(self, cmd_line_options_obj)` (198-224) — maps CLI options into config_vars. Sets `the_command`/`fixed_command` from `__MAIN_COMMAND__`. Computes `db_need_refresh = mode == "interactive" or the_command in commands_that_need_to_refresh_db_file` and calls `DBManager.set_refresh_db_file(...)`. Sets `__HELP_SUBJECT__`, `__WHICH_REVISION__`, parses `--define key=value` (comma-split, then `=` split), then `get_default_out_file()`. **Edge case**: `--define` parsing does `definition.split("=")` which breaks if a value itself contains `=`.
- `close(self)` (226-230) — `del self.info_map_table; del self.items_table; del self.db; config_vars.print_statistics()`.
- `get_default_out_file(self)` (232-235) — if `__MAIN_OUT_FILE__` unset but `__MAIN_INPUT_FILE__` set, derives `$(__MAIN_INPUT_FILE__)-$(__MAIN_COMMAND__).$(BATCH_EXT)`.
- `read_require(self, a_node, *args, **kwargs)` (237-239) — **redundant override**, identical to the parent mixin's method.
- `write_require_file(self, file_path, require_dict)` (241-255) — serializes a `!define` doc (`REQUIRE_REPO_REV`, `REQUIRE_REPO_NAME`, `REQUIRE_SYNC_BASE_URL`, `REQUIRE_S3_BUCKET_NAME`) followed by a `!require` doc via `aYaml.writeAsYaml`.
- `resolve_defined_paths(self)` (263-269) — adds `SEARCH_PATHS` to the searcher and resolves each var listed in `PATHS_TO_RESOLVE` via `path_searcher.find_file(..., return_original_if_not_found=True)`.
- `read_include_node(self, i_node, *args, **kwargs)` (271-315) — handles the `!include` tag (see algorithm below).
- `create_variables_assignment(self, in_batch_accum)` (317-329) — switches accum to the `assign` section; builds a case-insensitive regex from `DONT_WRITE_CONFIG_VARS` (plus `os.environ` keys unless `WRITE_CONFIG_VARS_READ_FROM_ENVIRON_TO_BATCH_FILE` is truthy) and emits `ConfigVarAssign(identifier, *values)` for every non-excluded config var.
- `init_python_batch(self, in_batch_accum)` (331-342) — switches to `begin` section; emits `PythonDoSomething` bootstrap lines for `RsyncClone` global ignore/no-hard-link/no-flags/avoid-copy-marker patterns (avoid-copy only when not `update_mode`), `RemoveEmptyFolders` default ignore files, and `log.setLevel(PYTHON_BATCH_LOG_LEVEL or 20)`.
- `calc_user_cache_dir_var(self)` (344-358) — platform branch on `__CURRENT_OS__`; computes `USER_CACHE_DIR` via `appdirs.user_cache_dir`. **Mac and Linux branches are identical**; Win passes app and author separately; unknown OS raises `RuntimeError`.
- `get_aux_cache_dir(self, make_dir=True)` (360-374) — returns `LOCAL_REPO_REV_BOOKKEEPING_DIR` if fully resolved (i.e. S3_BUCKET_NAME/REPO_NAME/REPO_REV are known), otherwise `USER_CACHE_DIR/cache`. Optionally creates it via `MakeDir`.
- `get_default_sync_dir(self, continue_dir=None, make_dir=True)` (376-383) — `USER_CACHE_DIR[/continue_dir]`, optionally created.
- `relative_sync_folder_for_source(self, source)` (385-394) and `relative_sync_folder_for_source_table(self, adjusted_source, source_type)` (396-404) — for `!dir`/`!file` return the path with the last segment stripped; for `!dir_cont` return the path as-is; else `ValueError`. These two are near-duplicates differing only in input shape.
- `write_batch_file(self, in_batch_accum, file_name_post_fix="")` (406-434) — see algorithm below.
- `run_batch_file(self)` (436-454) — if `out_file_realpath` ends `.py`, `compile(..., optimize=2)` and `exec(py_compiled, globals())` **in-process**; otherwise `subprocess.Popen` the file, print stdout/stderr, raise `SystemExit` on nonzero return code.
- `read_index(self, a_node, *args, **kwargs)` (456-460) — progress-wrapping override calling the mixin, then logs `REPO_REV`.
- `find_cycles(self)` (462-483) — lazy-imports `installItemGraph`; builds dependency + inherit graphs and logs any cycles; swallows `ImportError`.
- `needs(self, iid, all_iids_set=None, cache=None)` (485-502) — recursive transitive-dependency collection (see algorithm).
- `needed_by(self, iid, graph=None)` (504-513) — lazy-imports `installItemGraph`, returns sorted `find_needed_by` result or `None` on `ImportError`.
- `handle_yaml_read_error(self, **kwargs)` (515-530) — best-effort logging of YAML parse errors (path, position, permissions, exception); swallows any exception internally.
- `verify_actions(self, problem_messages_by_iid=None)` (532-556) — activates all OSes, pulls all index actions, and validates each by attempting `EvalShellCommand(action, None, self.python_batch_names, raise_on_error=True)`. Counts `ValueError`s as bad actions and records messages per IID.
- `write_config_vars_to_file(self, path_to_config_vars_file)` (558-565) — dumps `config_vars.repr_for_yaml()` as a `!define` YAML doc.
- `get_version_str(self, short=False)` (149-155) — resolves `__INSTL_VERSION_STR_SHORT__` / `__INSTL_VERSION_STR_LONG__`.

#### `check_version_compatibility()` — `pyinstl/instlInstanceBase.py:44-53`

Module-level. Returns `(retVal: bool, message: str)`. If `INSTL_MINIMAL_VERSION` is in config_vars, compares it element-wise (as `list(map(int, ...))`) against `__INSTL_VERSION__`; on failure builds a message. Imported by `pyinstl/instlClient.py`.

#### Interactive layer — `pyinstl/instlInstanceBase_interactive.py`

- `go_interactive(client, admin)` (70-78) — **monkey-patches** `InstlInstanceBase.create_completion_list = create_completion_list_imp` and `InstlInstanceBase.do_list = do_list_imp` onto the class at runtime, then runs `CMDObj(client, admin).cmdloop()` inside a `with` block; logs any exception.
- `CMDObj(cmd.Cmd, object)` (89-563) — REPL holding `client_prog_inst` and `admin_prog_inst`, a `restart` flag, and `this_program_name` from `INSTL_EXEC_DISPLAY_NAME`.
  - `__enter__` (100-123) — readline binds (libedit vs GNU tab handling, ignore-case, expand-tilde, etc.), creates history dir under `appdirs.user_data_dir`, reads history file (deletes it on read failure), sets prompt, saves CWD.
  - `__exit__` (125-136) — `compact_history()`, truncates history to 32, writes history file (all best-effort), restores CWD, and `restart_program()` if `restart` set.
  - `onecmd` (145-155) — wraps the base dispatcher; catches `InstlException` (prints `.message` + original traceback) and any other exception (prints traceback).
  - Command handlers: `do_apropos`, `do_list`, `do_statistics`, `do_set`/`do_del` (mutate config_vars), `do_read`/`do_readinfo`/`do_listinfo` (read index/info-map files into tables), `do_cycles`/`do_depend` (delegate to `find_cycles`/`needs`/`needed_by`), `do_sync`/`do_copy` (set `__MAIN_OUT_FILE__`/`__MAIN_COMMAND__` then call `client_prog_inst.do_command()`), `do_version`, `do_restart`/`do_r`, `do_quit`/`do_q`, `do_hist`, `do_hh` (lazy-imports `help.helpHelper.do_help`), `do_python` (**unguarded `eval`**, line 540), `do_resolve` (`config_vars.resolve_str`), `do_which`, `do_stam` (debug: `items_table.iids_from_guids2`). Each has matching `help_*`/`complete_*` where relevant.
  - `emptyline` (138-143) overridden to return `False` to avoid PyCharm double-execution.
- `do_list_imp(self, what=None, stream=sys.stdout)` (579-608) — dumps `define`/`index`/`guid` sections (or GUID-matched IIDs via `utils.guid_re`) as YAML using `aYaml.YamlDumpDocWrap`. **Edge case**: when `what is None` it writes `self` then continues with an empty `list_to_do` (the `return` is missing after the `None` write).
- `create_completion_list_imp(self, for_what="all")` (611-622) — builds tab-completion list from `items_table.get_all_iids()`, `config_vars.keys()`, and guid detail values; swallows exceptions.
- Utilities: `restart_program()` (`os.execl` re-exec, 81-86), `compact_history()` (dedupes readline history, 565-576), `insensitive_glob()` (61-67), `text_with_color(text, color)` (**no-op stub returning `text` unchanged**, 56-58). `current_os` is computed at module import via its own `platform.system()` match (19-26).

### Key algorithms

**1. `read_include_node` — `!include` handling (271-315)**
1. Scalar node: resolve the value as a path, `read_yaml_file`.
2. Sequence node: recurse into each child.
3. Mapping node with a `url` key:
   a. Resolve `url`; resolve optional `checksum`.
   b. `utils.download_from_file_or_url(...)` into `get_aux_cache_dir(make_dir=True)`, passing `expected_checksum` for verification and `connectionBase.translate_url` as the translator.
   c. `read_yaml_file(file_path)`; mark `file_was_downloaded_and_read`.
   d. On `FileNotFoundError`/`urllib.error.URLError`: if `ignore_if_not_exist` is set, log and continue; else re-raise.
   e. If `copy` key present and download succeeded: switch accum to `post` section; for each destination, copy is **skipped if** the destination already exists and its checksum matches `expected_checksum`; otherwise emit `MakeDir(parent, chowner=True)` + `CopyFileToFile(..., hard_links=False, copy_owner=True)`.

**2. `write_batch_file` — batch serialization (406-434)**
1. Assert `__MAIN_OUT_FILE__` exists.
2. Set `TOTAL_ITEMS_FOR_PROGRESS_REPORT = in_batch_accum.total_progress_count()`.
3. Set `in_batch_accum.initial_progress = self.internal_progress`.
4. `create_variables_assignment(in_batch_accum)` → fills the `assign` section.
5. `init_python_batch(in_batch_accum)` → fills the `begin` section.
6. `final_repr = repr(in_batch_accum)` (the accumulator's `__repr__` renders the full Python batch script across its named sections begin/assign/pre/post).
7. Resolve `__MAIN_OUT_FILE__`, append `file_name_post_fix` to the name, `MakeDir` the parent, set `out_file_realpath` (or `"stdout"`).
8. Write `final_repr` + newline via `utils.write_to_file_or_stdout`; log path + progress count.
   - Note `exit_on_errors` is computed (`the_command != 'uninstall'`) but is **not used** in this method.

**3. `needs` — transitive dependency closure (485-502)**
```
needs(iid, all_iids_set=None, cache=None):
    cache := cache or {}; if iid in cache: return sorted(cache[iid])
    all_iids_set := all_iids_set or set(items_table.get_all_iids())
    retVal := set()
    for dep in sorted(items_table.get_resolved_details_value_for_iid(iid,'depends',unique_values=True)):
        if dep in all_iids_set: retVal.add(dep); retVal |= set(needs(dep, all_iids_set, cache))
        else: retVal.append(dep + "(missing)")   # BUG: retVal is a set, .append does not exist
    cache[iid] := retVal
    return sorted(retVal)
```
**Bug**: `retVal` is a `set` but the missing-dependency branch calls `retVal.append(...)` (line 500), which raises `AttributeError`. This branch only fires when a declared dependency is not among the known IIDs.

### Data structures / on-disk artifacts owned

- **config_vars** — process-global singleton (`configVar.config_vars`) populated from `defaults/main.yaml`, `defaults/compile-info.yaml`, the per-subclass defaults file, `__USER_CONFIG_FILE_PATH__`, CLI `--define`, and the index YAML. Dynamic var `__NOW__`; value-set callbacks on `ACTING_UID`/`ACTING_GID`.
- **SQLite DB via `DBManager`** — `items_table` (IndexItemsTable) and `info_map_table` (SVNTable), class-level shared `TableAccess` descriptors; in-memory or file depending on `DBManager.refresh_db_file` (set by `init_from_cmd_line_options`). This subsystem does not define DDL itself (that lives in `db/`).
- **`batch_accum`** — `PythonBatchCommandAccum` with named sections (begin/assign/pre/post); serialized to `__MAIN_OUT_FILE__` or stdout.
- **On-disk files**: generated batch `.py`/script file (`__MAIN_OUT_FILE__`), user cache dir / aux cache dir (`appdirs`, downloaded includes + `LOCAL_REPO_REV_BOOKKEEPING_DIR`), require files, config-var dump files, and the readline history file under `appdirs.user_data_dir` named `.<prog>_console_history` (truncated to 32 entries).

### Invariants, edge cases, platform branches, error handling

- `!index_Mac` and `!index_Win` cannot both be registered (assert at line 67-68).
- `defaults/main.yaml` is mandatory (`ignore_if_not_exist=False`); the user config and `compile-info.yaml` are optional.
- DB-refresh decision is a **side effect on a class-level flag** in `init_from_cmd_line_options` (`DBManager.set_refresh_db_file`).
- Platform branching appears twice: `calc_user_cache_dir_var` (Mac/Win/Linux, Mac==Linux) and the interactive module's own import-time `current_os` match (Darwin/Windows/Linux). Unknown OS in `calc_user_cache_dir_var` raises `RuntimeError`.
- `run_batch_file` raises `SystemExit` when a spawned script returns nonzero; the `.py` path execs into the host process `globals()`.
- `find_cycles`/`needed_by` swallow `ImportError` for the optional `installItemGraph`; `needed_by` returns `None` in that case.
- `verify_actions` records syntax errors per-IID but continues; non-`ValueError` exceptions are caught and logged separately.
- Interactive `onecmd` and `compact_history`/history I/O are wrapped in broad `except` blocks; readline import failure degrades gracefully (Win tries `pyreadline`).

### Targeted refactoring notes (this subsystem)

1. **God-object base class** — `InstlInstanceBase` (whole class, ~79-566) mixes config loading, YAML tag reading, DB lifecycle, path resolution, batch generation, batch execution, dependency queries, action verification, and serialization. All five command subclasses inherit every concern. Extract collaborators: a `PathResolver` (`calc_user_cache_dir_var`/`get_aux_cache_dir`/`get_default_sync_dir`/`relative_sync_folder_*`), a `BatchFileWriter` (`create_variables_assignment`/`init_python_batch`/`write_batch_file`/`run_batch_file`), and a `DependencyAnalyzer` (`needs`/`needed_by`/`find_cycles`/`verify_actions`); compose rather than inherit.
2. **`needs` set/append bug** — line 500: `retVal.append(...)` on a `set` raises `AttributeError`. Use `retVal.add(dep + "(missing)")`.
3. **Global/class-level mutable state** — `config_vars` is a module singleton and `DBManager` exposes `items_table`/`info_map_table`/`refresh_db_file` as shared class attributes set via `set_refresh_db_file` (a side effect in `init_from_cmd_line_options`). This makes interactive mode (one client + one admin sharing class-level tables) fragile. Make these instance-scoped.
4. **Redundant override** — `InstlInstanceBase.read_require` (237-239) is byte-for-byte identical to the parent mixin's (`73-75`). Delete it; keep only the progress-wrapping `read_index` override.
5. **Runtime monkey-patching** — `go_interactive` (72-73) assigns `do_list`/`create_completion_list` onto the class at runtime; the methods don't exist until interactive mode runs, defeating static analysis. Define them as real methods on `InstlInstanceBase` or a small `InteractiveMixin`.
6. **`exec`/`eval` on dynamic input** — `run_batch_file` (441) execs the generated `.py` into the host `globals()`; `do_python` (540) is an unguarded `eval`. Prefer running generated scripts uniformly via subprocess (the else-branch already does) and scoping/limiting `do_python`.
7. **Dead/no-op code** — the `if False:` `DoingDecorator` block (30-41) and its commented decorators (181, 187); `text_with_color` no-op stub (56-58, but called throughout `do_depend`); the large commented-out `complete_listinfo` (375-404); empty `help_resolve` body (552-553). Remove or implement.
8. **Duplicated platform/OS detection** — collapse the identical Mac/Linux branches in `calc_user_cache_dir_var` (348-355) and centralize OS detection shared with the interactive module's import-time `current_os` (19-26).
9. **Unused local** — `exit_on_errors` computed in `write_batch_file` (415) is never used; either thread it through or remove it.
10. **Fragile `--define` parsing** — `init_from_cmd_line_options` (220-222) splits on `=` unconditionally, so values containing `=` break. Use `split("=", 1)`.
11. **Magic string config keys** — names like `__MAIN_OUT_FILE__`, `LOCAL_REPO_REV_BOOKKEEPING_DIR`, `DONT_WRITE_CONFIG_VARS`, `USER_CACHE_DIR`, `TARGET_OS` are scattered as string literals; typos fail at runtime. Define them as constants/enum in `configVar` and reference them.

---

I have all the details I need. Note one bug: `instlInstanceSync_boto.py` uses `os.fspath` but never imports `os` — a latent NameError. Let me write the section.

## Sync Backends & Connections

This subsystem decides **how a client deployment fetches its files from a remote repository** and emits the batch instructions that perform the fetch. It is rooted at an abstract sync-backend base (`InstlInstanceSync`) with four concrete backends selected at runtime by the `REPO_TYPE` config var, plus a connection abstraction (`ConnectionBase` and friends) that owns URL translation, cookie/header injection, TLS hardening, and (dead) S3 signed-URL generation. In practice **only the URL backend is maintained**; SVN/P4 emit raw shell-command strings and BOTO is a stub.

### Component breakdown

#### `InstlClientSync` — `pyinstl/instlClientSync.py`

The client command class that drives the whole sync. Subclasses `InstlClient`.

- `__init__(initial_vars)` — calls `super().__init__`, then `read_defaults_file(...)`, `calc_user_cache_dir_var()`, and registers progress messages for the `pre_sync`/`post_sync` action types.
- `do_sync()` — the public entry point. Reads `REPO_TYPE` (default `"URL"`) and `match`-dispatches to a backend via **lazy import**:
  - `"URL"` → `InstlInstanceSync_url`
  - `"BOTO"` → `InstlInstanceSync_boto`
  - `"SVN"` → `InstlInstanceSync_svn`
  - `"P4"` → `InstlInstanceSync_p4`
  - `_` → `raise ValueError('REPO_TYPE is not defined in input file')`

  It then calls `syncer.init_sync_vars()`, sets `batch_accum` section to `'sync'`, accumulates `pre_sync` actions, calls `syncer.create_sync_instructions()`, and accumulates `post_sync` actions. The two methods every backend must satisfy are therefore `init_sync_vars()` and `create_sync_instructions()`.

#### `InstlInstanceSync` (abstract base) — `pyinstl/instlInstanceSyncBase.py`

`class InstlInstanceSync(object, metaclass=abc.ABCMeta)`. Holds shared state plus the info-map read/mark pipeline used by download-style backends.

- Attributes: `self.instlObj` (back-reference to the `InstlClient`), `self.local_sync_dir = None`, `self.files_to_download = 0`.
- `init_sync_vars()` — reads `__SYNC_PREREQUISITE_VARIABLES__` and calls `instlObj.check_prerequisite_var_existence(...)`, raising `ValueError` if a mandatory var is missing.
- `create_sync_instructions()` — no-op returning `0`; overridden by subclasses.
- `create_no_sync_instructions()` — overridable hook, default `pass`.
- `read_remote_info_map()` — the core download-prep step:
  1. Lazily imports `connectionBase`, opens `info_map_table.reading_files_context()`, and `os.makedirs` the bookkeeping dirs.
  2. Derives `INFO_MAP_FILE_URL` if absent: builds `INSTL_FOLDER_BASE_URL = "$(BASE_LINKS_URL)/$(REPO_NAME)/$(REPO_REV_FOLDER_HIERARCHY)/instl"` (computing `REPO_REV_FOLDER_HIERARCHY` from `info_map_table.repo_rev_to_folder_hierarchy(REPO_REV)`), then `$(INSTL_FOLDER_BASE_URL)/info_map.txt`.
  3. Downloads the info_map via `utils.download_from_file_or_url(in_url=..., config_vars=config_vars, in_target_path=LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH, translate_url_callback=connectionBase.translate_url, cache_folder=..., expected_checksum=INFO_MAP_CHECKSUM)` and loads it into `instlObj.info_map_table.read_from_file(...)`.
  4. Fetches **additional per-iid info_maps** (`items_table.get_details_for_active_iids("info_map", ...)`), preferring the zipped `$(WZLIB_EXTENSION)` variant and falling back to unzipped, using each item's checksum, and merges them into the table.
  5. Writes `NEW_HAVE_INFO_MAP_PATH` with fields `('path','flags','revision','checksum','size')`.
  On any exception it logs `"Exception reading info_map: <url>"` and re-raises.
- `mark_required_items()` — `info_map_table.mark_required_files_for_active_items(...)`, writes `REQUIRED_INFO_MAP_PATH`, reports `sum(item.fileFlag for ...)` required files.
- `mark_download_items()` — calls `instlObj.set_sync_locations_for_active_items()`, then `info_map_table.mark_need_download(...)`, and writes `TO_SYNC_INFO_MAP_PATH`.
- `prepare_list_of_sync_items()` — orchestrates the three above in order (`read_remote_info_map` → `mark_required_items` → `mark_download_items`). Per the in-code comment, only download backends (URL/boto) call this; SVN/P4 bypass it.

#### `InstlInstanceSync_url` — `pyinstl/instlInstanceSync_url.py`

The primary maintained backend. Generates curl-config-based download instructions with resume, adaptive concurrency, and a pause/resume control channel.

Module-level typed config helpers (used only here): `_config_var_bool(name, default=False)`, `_config_var_int(name, default=0)`, `_config_var_list(name)` (the last also splits a single comma-joined value).

- `__init__(instlObj)` — adds `self.sync_base_url = None`.
- `init_sync_vars()` — `super().init_sync_vars()` then `self.local_sync_dir = os.fspath(config_vars["LOCAL_REPO_SYNC_DIR"])`.
- `create_sync_folders()` — builds an `AnonymousAccum` with `CreateSyncFolders()`; reports `num_items(item_filter="need-download-dirs")`.
- `get_cookie_for_sync_urls(sync_base_url)` — derives netloc, calls `connectionBase.connection_factory(config_vars).get_cookie(net_loc)`; if found, sets `COOKIE_FOR_SYNC_URLS` to the cookie text (`the_cookie[1]`).
- `create_sync_urls(in_file_list)` — for a list of `SVNRow` file items:
  - Resolves `SYNC_BASE_URL`, fetches cookie, reads resume config (`DOWNLOAD_RESUME_ENABLED`, `DOWNLOAD_RESUME_VALIDATED_HOSTS`, `..._VALIDATED_PATH_PREFIXES`, `..._REQUIRE_CONDITIONAL` default True, `..._MIN_SIGNED_URL_TTL_SECONDS` default 300) and `resolve_validated_hosts(...)`.
  - Binds the control channel (`_bind_control_channel`), then per file: `control_channel.wait_if_paused()` (cooperative pause between files; never interrupts an in-flight curl), gets `source_url` via `info_map_table.get_sync_url_for_file_item(file_item)`, computes a `resume_decision_for_download_item(...)`, and calls `instlObj.dl_tool.add_download_url(source_url, file_item.download_path, verbatim=source_url==['url'], size=..., download_last=source_url.endswith('Info.xml'), output_path=temp_path_for_download_item(file_item), resume_from_byte=resume_decision.resume_from_byte, conditional_headers=resume_decision.conditional_headers)`.
- `_bind_control_channel(bookkeeping_dir)` — gets the singleton via `get_global_channel()`, sets `session_id` from `__INVOCATION_RANDOM_ID__`, and installs `on_pause_event`/`on_resume_event` callbacks that (best-effort) `update_session_state(...)` to `PAUSED`/`DOWNLOADING` on disk and `downloadEvents.emit_session_state(...)`. Returns the channel.
- `create_curl_download_instructions()` — calls `_apply_adaptive_concurrency()`, then `dl_tool.create_download_instructions(dl_commands)` into a fresh `AnonymousAccum`.
- `_apply_adaptive_concurrency()` — calls `resolve_concurrency_from_config(config_vars, summary_loader=load_session_summary)`; on `OVERRIDE` sets `PARALLEL_SYNC` verbatim, on `DISABLED` sets it only if unset, otherwise sets the recommended value. Any exception is swallowed (controller must never break sync).
- `create_check_checksum_instructions(num_files)` — emits `Progress` + `CheckDownloadFolderChecksum(own_progress_count=num_files, max_bad_files_to_redownload=MAX_BAD_FILES_TO_REDOWNLOAD default 16)`.
- `create_instructions_to_remove_redundant_files_in_sync_folder()` — `os.scandir`/`os.walk` the sync dir (skipping `bookkeeping` and `.DS_Store`), builds partial paths, asks `info_map_table.get_files_that_should_be_removed_from_sync_folder(...)`, and emits `RmFile(f)` per redundant file plus a trailing `RemoveEmptyFolders(...)`.
- `create_download_instructions()` — computes already-synced vs to-download counts/bytes, sets `__NUM_FILES_TO_DOWNLOAD__`/`__NUM_BYTES_TO_DOWNLOAD__`, short-circuits when 0 files. Otherwise assembles: `create_sync_folders()` → `PrepareDownloadTempFiles(own_progress_count=0, report_own_progress=False)` → `ReportDownloadStarted(files_planned=..., bytes_planned=..., own_progress_count=0, report_own_progress=False)` → `create_sync_urls(file_list)` → `create_curl_download_instructions()` → `create_sync_folder_manifest_command("after-sync", back_ground=True)` → `create_check_checksum_instructions(...)`.
- `create_sync_instructions() -> int` — top-level orchestration. Opens nested `batch_accum.sub_accum` stages: `Stage("download", "$(SYNC_BASE_URL)")` → `prepare_list_of_sync_items()`, `MakeDir("$(LOCAL_REPO_SYNC_DIR)", chowner=True)`, `Cd("$(LOCAL_REPO_SYNC_DIR)")` → `Stage("remove_redundant_files_in_sync_folder")` then `create_download_instructions()` then `Stage("post_sync")` which (if `__NUM_FILES_TO_DOWNLOAD__ > 0`) appends `chown_for_synced_folders()` and always appends `CopyFileToFile("$(NEW_HAVE_INFO_MAP_PATH)", "$(HAVE_INFO_MAP_PATH)", hard_links=False, copy_owner=True)`. Ends with `Progress("Done sync")`.
- `chown_for_synced_folders()` — **Mac-only** (`__CURRENT_OS__ == "Mac"`): for each `info_map_table.get_download_roots()` emits `ChmodAndChown(path=dr, mode="a+rwX", user_id=ACTING_UID, group_id=ACTING_GID, recursive=True, ignore_all_errors=True)`.
- Module function `total_sizes_by_mount_point(file_list)` — sums sizes per `utils.find_mount_point(...)` (only referenced inside a dead `if False:` block).

Collaborators: `instlObj.dl_tool` (CUrlHelper), `info_map_table`, the `downloadState`/`downloadConcurrency`/`downloadObservability`/`downloadControlChannel`/`downloadEvents` modules, and `pybatch` command objects.

#### `InstlInstanceSync_svn` — `pyinstl/instlInstanceSync_svn.py`

- `init_sync_vars()` — `setdefault("REPO_REV", "HEAD")`; sets `REL_BOOKKEEPING_PATH` and `REL_SRC_PATH` via `utils.relative_url(SYNC_BASE_URL, BOOKKEEPING_DIR_URL)` / `relative_url(SYNC_BASE_URL, SYNC_BASE_URL)`.
- `create_sync_instructions()` — appends raw command strings to `batch_accum` via `platform_helper.progress/mkdir/cd/echo`; runs `svn co` on the bookkeeping dir, then iterates `__FULL_LIST_OF_INSTALL_TARGETS__` (calling `create_svn_sync_instructions_for_source`) and `__ORPHAN_INSTALL_TARGETS__` (emits an "Don't know how to sync" echo). Returns a count.
- `create_svn_sync_instructions_for_source(source)` — source is `(source_path, source_type)`; builds `"$(SVN_CLIENT_PATH)" co "<url>" "<target>" --revision $(REPO_REV)` with `--depth files` for `!file` (trimming the filename to sync the parent folder) or `--depth infinity` otherwise.

#### `InstlInstanceSync_p4` — `pyinstl/instlInstanceSync_p4.py`

- `create_sync_instructions()` — calls `create_download_instructions()` then sets `batch_accum` section to `'post-sync'`.
- `create_download_instructions()` — sets section `'sync'`, emits a start-progress line, iterates `__FULL_LIST_OF_INSTALL_TARGETS__` and calls `p4_sync_for_source(source)` per source.
- `p4_sync_for_source(source)` — `match`es `!file` → `p4 sync "$(SYNC_BASE_URL)/<path>"$(REPO_REV)`; `!dir`/`!dir_cont` → `p4 sync "$(SYNC_BASE_URL)/<path>/..."$(REPO_REV)`. **Note the suspicious quoting** (no space before the revision, closing quote before `$(REPO_REV)`) — see refactor notes.

#### `InstlInstanceSync_boto` — `pyinstl/instlInstanceSync_boto.py`

Stub. Only `init_sync_vars()` sets `self.local_sync_dir = os.fspath(config_vars["LOCAL_REPO_SYNC_DIR"])`. No sync instructions; `create_sync_instructions` inherits the base no-op (returns 0). **The module imports neither `os`** (used in `init_sync_vars`) — so for a `BOTO` repo type `init_sync_vars()` raises `NameError: name 'os' is not defined`.

#### Connection layer — `pyinstl/connectionBase.py`

- `SSLContextAdapter(HTTPAdapter)` — forces a maximally-permissive OpenSSL 3.x context (`_make_ssl_context()`): certifi CA bundle, `check_hostname=False`, `verify_mode=CERT_NONE`, `set_ciphers("DEFAULT:@SECLEVEL=0")`, and `OP_LEGACY_SERVER_CONNECT`. Injected via `init_poolmanager`/`proxy_manager_for`. Purpose: survive corporate SSL-inspection proxies that emit BER/malformed ASN.1 certs (which break OpenSSL even when verification is off).
- `inject_truststore()` — best-effort `import truststore; truststore.inject_into_ssl()`; silent no-op if not installed. The "only reliable fix" for the malformed-cert proxy case (swaps to OS-native Schannel/SecureTransport).
- `have_boto = False` — hardcoded; the boto3 import is commented out, so the entire S3 path is dead.
- `ConnectionBase` — `repo_connection = None` is a **class-level global singleton**. `get_cookie(net_loc)` parses `COOKIE_JAR` lines (`netloc:cookie`) and returns `('Cookie', text)`. `get_custom_headers(net_loc)` merges the cookie with json-parsed `CUSTOM_HEADERS` entries matching the netloc. `open_connection`/`translate_url` are `@abc.abstractmethod`.
- `ConnectionHTTP(ConnectionBase)` — owns `self.sessions: Dict[str, requests.Session]`. `translate_url(in_bare_url)` percent-quotes the path (`quote(path, "$()/:%")`) and reassembles the URL — note it is **still decorated `@abc.abstractmethod` despite being the concrete, production-used implementation**. `get_session(url)` lazily builds a per-netloc `requests.Session` with `verify=False`, the `SSLContextAdapter` mounted on http/https, and custom headers applied.
- `ConnectionS3(ConnectionHTTP)` — guarded by `if have_boto:` (dead). `open_connection(credentials)` does `boto3.connect_s3(...).get_bucket(...)`; `translate_url` returns a signed URL for keys in the open bucket, else falls back to `super().translate_url`.
- Module functions:
  - `connection_factory(config_vars)` — caches into `ConnectionBase.repo_connection`: `ConnectionS3` only if `__CREDENTIALS__` present **and** `have_boto` (never true), otherwise `ConnectionHTTP`.
  - `translate_url(in_bare_url, config_vars) -> (translated_url, headers)` — the `translate_url_callback` passed into `utils.download_from_file_or_url`/`read_from_file_or_url`; returns the translated URL plus `get_custom_headers(netloc)`.

### Key algorithms / logic

**URL sync end-to-end (`create_sync_instructions` flow):**
1. `prepare_list_of_sync_items()`: download remote `info_map.txt` (+ per-iid info_maps) into the SQLite-backed `info_map_table`, write `NEW_HAVE_INFO_MAP_PATH`; mark required items → `REQUIRED_INFO_MAP_PATH`; mark download items → `TO_SYNC_INFO_MAP_PATH`.
2. `MakeDir` sync root, `Cd` into it.
3. Remove redundant files (disk walk vs DB).
4. `create_download_instructions`: tally counts, create sync folders, prep temp files, announce session, build curl URLs (per-file resume decisions + pause gating), apply adaptive concurrency, emit curl config + manifest + checksum check.
5. `post_sync`: Mac chown, then copy `NEW_HAVE_INFO_MAP_PATH` → `HAVE_INFO_MAP_PATH` (the persisted record of what is on disk).

**Per-file resume decision (`create_sync_urls`):** resume only when `DOWNLOAD_RESUME_ENABLED` and the host/path-prefix is validated; `resume_decision_for_download_item` returns `resume_from_byte` (from the existing `.part` temp file at `temp_path_for_download_item(file_item)`) and `conditional_headers` (e.g. validators), honoring `require_conditional` and a minimum signed-URL TTL.

**Cooperative pause:** `wait_if_paused()` is checked **between files only**; in-flight curl processes are never interrupted and their `.part` artifacts remain valid for the next resume.

**URL translation (download callback):** `connectionBase.translate_url` → percent-quote path → return `(url, custom_headers_for_netloc)`. Headers carry cookie + `CUSTOM_HEADERS`.

### Data structures / on-disk artifacts owned

This subsystem does not define its own SQLite schema (that belongs to the info_map subsystem / `SVNRow` DB on `instlObj.info_map_table`), but it reads/mutates that DB and **owns these on-disk artifacts** under the bookkeeping dir:
- `LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH` — raw downloaded `info_map.txt`.
- `NEW_HAVE_INFO_MAP_PATH` — table dump, fields `(path, flags, revision, checksum, size)`; later copied to `HAVE_INFO_MAP_PATH`.
- `REQUIRED_INFO_MAP_PATH`, `TO_SYNC_INFO_MAP_PATH` — required / to-download item dumps.
- curl `.part` temp files (`temp_path_for_download_item`).
- `DownloadSessionState` persisted into `bookkeeping_dir` by `_bind_control_channel`'s callbacks.

In-memory: `ConnectionHTTP.sessions` (netloc → `requests.Session`) and the process-global `ConnectionBase.repo_connection` singleton; plus config-var state `COOKIE_FOR_SYNC_URLS`, `__NUM_FILES_TO_DOWNLOAD__`, `__NUM_BYTES_TO_DOWNLOAD__`, and `PARALLEL_SYNC` (mutated by adaptive concurrency).

### Invariants, edge cases, error handling, platform branches

- **Default `REPO_TYPE` is `URL`**; only URL is maintained (explicit in-code comment in `do_sync`).
- `init_sync_vars` raises `ValueError` when prerequisite vars are missing.
- `read_remote_info_map` wraps everything and re-raises on failure, logging the offending URL.
- `create_download_instructions` short-circuits (no curl/checksum work) when `to_sync_num_files == 0`.
- **Platform branches:** `import win32api` only on `win32` (and is unused in the file); `chown_for_synced_folders` runs only on Mac.
- Adaptive-concurrency and control-channel callbacks are fully exception-guarded so they can never break a sync.
- `verbatim=source_url==['url']` compares a string to a list literal — always `False` (see below).

### Targeted refactoring notes (this subsystem)

1. **`InstlInstanceSync_boto` will crash, not no-op** — `init_sync_vars` calls `os.fspath` but the module never imports `os` (`instlInstanceSync_boto.py:17`). A `BOTO` repo type raises `NameError` rather than silently doing nothing. Either remove the BOTO backend and the `case "BOTO"` in `do_sync` (`instlClientSync.py:25-27`), or add `import os` and implement real instructions.
2. **Dead S3/boto path** — `have_boto = False` is hardcoded (`connectionBase.py:104-109`); `ConnectionS3` (`191-213`) can never be constructed and `connection_factory` always returns `ConnectionHTTP`. Delete the boto path or reinstate it behind a real optional-dependency import.
3. **`@abc.abstractmethod` on a concrete method** — `ConnectionHTTP.translate_url` (`connectionBase.py:166-174`) is decorated abstract yet has the production body. Drop the decorator from the subclass (keep it only on `ConnectionBase`).
4. **`verbatim` flag is always False** — `verbatim=source_url==['url']` (`instlInstanceSync_url.py:143`) compares a `str` to `['url']`; the verbatim-URL path is unreachable. Determine the intended source-flag check (likely on the file item) and fix; add a test.
5. **P4 command quoting bug** — `p4 sync "$(SYNC_BASE_URL)/<path>"$(REPO_REV)` (`instlInstanceSync_p4.py:44-46`) has misplaced quotes and no separator before the revision. Harmless while unmaintained, malformed if re-enabled. Fix quoting and add tests, or remove the backend.
6. **Global mutable singleton** — `ConnectionBase.repo_connection` (`connectionBase.py:113,216-225`) is process-wide, not thread-safe, and not resettable; cached sessions can leak across multi-repo runs/tests. Inject the connection through `instlObj`/config or add an explicit reset/lifecycle hook.
7. **Leaky base class** — `read_remote_info_map`/`mark_*`/`prepare_list_of_sync_items` live in `InstlInstanceSync` but are only used by download backends; SVN/P4 ignore them. Split into a thin `AbstractSyncBackend` (just `init_sync_vars`/`create_sync_instructions`) and a `DownloadInfoMapMixin`.
8. **Two divergent instruction paradigms** — URL uses typed `pybatch` objects + `sub_accum` context managers; SVN/P4 append raw `platform_helper` strings (`instlInstanceSync_svn.py:28-43`, `instlInstanceSync_p4.py:24-46`). Port SVN/P4 to pybatch or gate/remove them and document URL-only support.
9. **Dead/unused code in URL backend** — unused `import win32api` (`instlInstanceSync_url.py:7-8`) and the `if False:` mount-point sizing block (`318-323`, plus `total_sizes_by_mount_point`). Remove them.
10. **Duplicated config coercion helpers** — `_config_var_bool/_config_var_int/_config_var_list` (`instlInstanceSync_url.py:29-52`) duplicate typed-read logic that likely belongs on the `config_vars`/`ConfigVar` API. Promote and reuse.

---

I have enough detail. Producing the LLD section.

## Client Commands (install/copy/remove/report/uninstall)

This subsystem implements the end-user-facing modes of `instl`: the install workflow (`copy`/`synccopy`), `remove`, `uninstall`, read-only `report-*`/`read-yaml`/`short-index`, the dependency-ordered action runner `doit`, and a grab-bag of standalone utility subcommands (`do_something` mode: wtar/unwtar/checksum/ls/resolve/exec/run-process/version/help/check-checksum). It consumes a central-generated YAML index (read into the SQLite index DB via `items_table`) plus an info-map (read into `info_map_table`), resolves the install-item (IID) dependency graph, marks install status per item, and emits an ordered batch of `pybatch` commands.

### Entry points and dispatch

- `InstlClientFactory(initial_vars, command) -> InstlClient` (`pyinstl/instlClient.py:627`): a `match command:` dispatcher that lazily imports and instantiates the right subclass. Called from `instl_main.py` for mode `client`. For `synccopy` it defines an ad-hoc class **inline**:
  ```python
  class InstlClientSyncCopy(InstlClientSync, InstlClientCopy):
      def do_synccopy(self):
          self.do_sync(); self.do_copy(); self.batch_accum += Progress("Done synccopy")
  ```
- `InstlClient.do_command()` is the workflow entry point (invoked by `instl_main` after `init_from_cmd_line_options()`).
- `InstlDoIt(initial_vars).do_command()` — mode `doit`.
- `InstlMisc(initial_vars, command).do_command()` — mode `do_something` and `command-list`.
- The `do_<fixed_command>()` convention: `do_command()` calls `getattr(self, "do_"+self.fixed_command)()`. So `do_copy`/`do_remove`/`do_uninstall`/`do_report_versions`/`do_read_yaml`/`do_synccopy` etc. are resolved dynamically.

### `InstlClient` (base, `pyinstl/client/` package; `pyinstl/instlClient.py` is now a shim)

Base class for sync/copy/synccopy/remove/uninstall/report. Historically a ~660-line "god class" owning the whole pipeline plus DB-status mutation, target-folder bookkeeping, sync-location resolution, require.yaml I/O, binary-version scanning, YAML representation, and name resolution.

> **Layout (post-modernization).** `pyinstl/instlClient.py` is a shim re-exporting `InstlClient`
> and `InstlClientFactory` from `pyinstl/client/`. `InstlClient` is composed from the mixins
> `_CoreClientMixin` (`client/_core.py`), `_InstallItemsClientMixin` (`_install_items.py`),
> `_RequireClientMixin` (`_require.py`), `_ActionsClientMixin` (`_actions.py`),
> `_BinariesClientMixin` (`_binaries.py`), `_SyncLocationsClientMixin` (`_sync_locations.py`),
> `_RemoveSourcesClientMixin` (`_remove_sources.py`), `_NamingClientMixin` (`_naming.py`).
> `InstlClientFactory` and the inline `InstlClientSyncCopy` class now live in `client/__init__.py`.
> Pure extract-module refactor; behavior and emitted output identical, so the references below
> still hold.

Key `__init__` state:
- `total_self_progress = 15000`, `internal_progress`.
- `__all_iids_by_target_folder: defaultdict(unique_list)` — copy targets keyed by normalized target folder.
- `__no_copy_iids_by_sync_folder: defaultdict(unique_list)` — direct-sync / sync-only sources keyed by sync folder. Both exposed via read-only `@property`.
- `auxiliary_iids: unique_list` (e.g. `UNINSTALL_AS_*` pseudo-items), `main_install_targets: list`, `action_type_to_progress_message: dict`.
- `self.read_defaults_file(super().__thisclass__.__name__)` — picks the per-class defaults file by class name (fragile idiom, see refactors).

Important methods:

- **`do_command()`** (`:66`) — the pipeline:
  1. `activate_specific_oses(*TARGET_OS_NAMES)`;
  2. read main YAML via `read_yaml_file(..., connection_obj=connection_factory(config_vars))`;
  3. `set_db_file_owner()`; `check_version_compatibility()` (raises on mismatch);
  4. `init_default_client_vars()`; re-activate OSes; `resolve_inheritance()`;
  5. optional binary-version scan if `should_check_for_binary_versions()`;
  6. `create_default_items(iids_to_ignore=self.auxiliary_iids)`; `resolve_defined_paths()`;
  7. set batch section to `'pre'`; `save_previous_state()`;
  8. `calculate_install_items()`; `read_defines_for_active_iids()`;
  9. `getattr(self,"do_"+fixed_command)()`; `command_output()`; `config_var_list_to_db(config_vars)`.
- **`command_output()`** (`:110`) — `write_batch_file(self.batch_accum)`, dump config_vars to `__WRITE_CONFIG_VARS_TO_FILE__`, and `run_batch_file()` iff `__RUN_BATCH__`.
- **`init_default_client_vars()`** (`:117`) — derive `SYNC_BASE_URL_MAIN_ITEM` from `SYNC_BASE_URL`; when `TARGET_OS != __CURRENT_OS__` recompute `TARGET_OS_NAMES`/`TARGET_OS_SECOND_NAME`; load `AUXILIARY_IIDS` (warns if absent); set `__MAIN_DRIVE_NAME__`.
- **`calculate_install_items()`** (`:177`) — `calculate_main_install_items()` then `calculate_all_install_items()`, then `lock_table("index_item_t")`/`("index_item_detail_t")` to freeze the DB against further inserts.
- **`calculate_main_install_items()`** (`:183`) — expand `MAIN_INSTALL_TARGETS`: split GUIDs from IIDs (`utils.separate_guids_from_iids`), resolve GUIDs→IIDs (`iids_from_guids`), `resolve_special_build_in_iids()`, re-resolve IIDs. Writes `__MAIN_INSTALL_IIDS__`, `__MAIN_UPDATE_IIDS__`, `__ORPHAN_INSTALL_TARGETS__`. Sets `self.update_mode = "__REPAIR_INSTALLED_ITEMS__" in main_install_targets`.
- **`calculate_all_install_items()`** (`:207`) — marks `install_status` columns: set ignored iids, mark `main`, recursively pull dependents (`get_recursive_dependencies`) as `depend`, mark `update` + its dependents, gather `main`+`depend` into `__FULL_LIST_OF_INSTALL_TARGETS__`; then `sort_all_items_by_target_folder(consider_direct_sync=True)` and `calc_iid_to_name_and_version()`. Status enum: `install_status = {"none":0,"main":1,"update":2,"depend":3}` (plus `remove` for uninstall).
- **`resolve_special_build_in_iids(iids)`** (`:261`) — expands `__REPAIR_INSTALLED_ITEMS__` / `__UPDATE_INSTALLED_ITEMS__` / `__ALL_GUIDS_IID__` / `__ALL_ITEMS_IID__` into their `depends`; repair takes precedence over update. Returns `(install_iids, update_iids)`.
- **`sort_all_items_by_target_folder(consider_direct_sync=True)`** (`:39`) — from `items_table.target_folders_to_items()` route each `(IID, folder, tag, direct_sync_indicator)` into `__no_copy_iids_by_sync_folder` (if direct-sync) or `__all_iids_by_target_folder` (else, `os.path.normpath`'d). Sets `__FULL_LIST_OF_DIRECT_SYNC_TARGETS__`; sorts each folder's iid list; then folds `source_folders_to_items_without_target_folders()` (sync-only sources, e.g. Icons) into `__no_copy_iids_by_sync_folder` under `$(LOCAL_REPO_SYNC_DIR)/...`.
- **`set_sync_locations_for_active_items()`** (`:459`) — per-source it computes per-file `download_path`/`download_root` and writes them via `info_map_table.update_downloads(items_to_update)`. Tag-dispatched (`!dir`/`!dir_cont`/`!file`), and branches on direct-sync vs copy. Key edge case: for direct-sync `!dir`/`!dir_cont` it short-circuits when an existing `Info.xml` on disk matches the source checksum (`utils.check_file_checksum`) — unless `update_mode` — calling `info_map_table.ignore_file_paths_of_dir()` to skip download. Maintains `ALL_SYNC_DIRS`.
- **`accumulate_unique_actions_for_active_iids(action_type, limit_to_iids=None) -> PythonBatchCommandBase`** (`:301`) — builds an `AnonymousAccum` of `EvalShellCommand` from de-duplicated action details (e.g. `pre_copy`, `post_remove`), with per-iid progress messages.
- **`accumulate_actions_for_iid(iid, detail_name)`** (`:323`) — same for per-iid action details like `pre_copy_item`/`post_remove_item` (not de-duplicated across iids).
- **require.yaml lifecycle**: `read_previous_requirements()` (`:285`, chmods then reads `SITE_REQUIRE_FILE_PATH`, renames to `*.failed_to_read` on parse error); `create_require_file_instructions()` (`:335`, emits Chmod + `CopyFileToFile` SITE→OLD, writes NEW from `repr_require_for_yaml()`, copies NEW→SITE, or `RmFile` if empty); `repr_require_for_yaml()` (`:378`, aggregates `require_%` details per `owner_iid`, translating `require_version`→`version`/`require_guid`→`guid`, excluding auxiliary-iid and non-original-iid guid rows); `save_previous_state()` (`:615`, debug copies `*_require_before.yaml`/`*_require_after.yaml`).
- **previous-source removal**: `create_remove_previous_sources_instructions_for_target_folder()` (`:546`, only if folder exists, wraps in `Cd`); `_for_source()` (`:561`, `!dir`→`RmDir`, `!file`→`RmFile`, `!dir_cont`→raises — illegal for previous_sources).
- **Name resolution**: `name_from_iid` (strips `_IID`, `_`→space), `name_and_version_for_iid`, `name_for_iid`.
- `create_sync_folder_manifest_command()` (`:356`) — one-shot `RunInThread(Ls(...))` writing `*-sync-folder-manifest.txt`, guarded by `SYNC_FOLDER_MANIFEST_FILE`.
- `get_version_of_installed_binaries()` / `should_check_for_binary_versions()` — mostly dormant; scans binaries via `utils.check_binaries_versions_in_folder`, gated by `CHECK_BINARIES_VERSIONS` or update-requested.

### `InstlClientCopy` (`pyinstl/instlClientCopy.py`)

Generates copy/unwtar instructions. `init_copy_vars()` (`:35`) sets `wtar_ratio` (default `WTAR_RATIO=1.3`), `bytes_to_copy=0`, and the **platform flags** `mac_current_and_target` / `win_current_and_target` (current OS *and* target OS both Mac/Win). Mutable state: `current_destination_folder`, `current_iid`, `bytes_to_copy`, `avoid_copy_markers`, `unwtar_batch_file_counter`.

- **`create_copy_instructions()`** (`:68`) — main driver:
  1. read `HAVE_INFO_MAP_COPY_PATH` info-map if not already read (skipped during synccopy);
  2. section `'copy'`, manifest command, `Progress`;
  3. `create_create_folders_instructions(sorted_target_folder_list)` first (avoids inter-folder symlink ordering bugs; `chowner=False` for `THIRD_PARTY_FOLDERS`);
  4. `pre_copy` actions; `pre_copy_mac_handling()` (Mac);
  5. per-folder loop: optional `create_remove_previous_sources_instructions_for_target_folder` (gated by `REMOVE_PREVIOUS_SOURCES`, default True), then `create_copy_instructions_for_target_folder`;
  6. no-copy folders loop; `post_copy`; section `'post-copy'` copies HAVE_INFO_MAP→SITE (skipped when HAVE==SITE, i.e. offline installers); `create_require_file_instructions()`; `Echo("Don't know how to install ...")` per orphan; `Progress("Done copy")`.
- **`create_copy_instructions_for_source(source, ...)`** (`:264`) — tag dispatch on `source[1]`: `!dir`→`_for_dir`, `!file`→`_for_file`, `!dir_cont`→`_for_dir_cont`; unknown tag raises `ValueError`.
- **`create_copy_instructions_for_file()`** (`:136`) — single file → `CopyFileToDir(..., hard_links=use_hard_links)` (+ Mac `ChmodAndChown` unless `.symlink`); if wtarred (asserts all-or-none wtar) → `Unwtar(first_wtar_full_path, os.curdir)`.
- **`create_copy_instructions_for_dir_cont()`** (`:168`) — `CopyDirContentsToDir(..., preserve_dest_files=True)` for non-wtar items (+ Mac per-item `ChmodAndChown a+rw` recursive and exec-bit `Chmod`); wtar items → `Unwtar(source_path_abs, os.pardir)` (parent, to avoid `X/X` nesting — unique to `!dir_cont`).
- **`create_copy_instructions_for_dir()`** (`:225`) — `CopyDirToDir(..., delete_extraneous_files=True)`; Mac exec-bit `Chmod` per non-wtar executable; `Unwtar` if wtars; Mac `Chown` recursive on destination folder. Falls back to `_for_file` if `get_dir_item` returns None (dir was wtarred).
- `create_copy_instructions_for_dir_extended()` (`:197`) — uses `CopyBundle(..., unwtar=has_wtars)`; contains a **dead commented-out block** (`:208-217`).
- **`create_copy_instructions_for_target_folder()`** (`:298`) — `CdStage("copy_to_folder", target_folder_path)`; accumulates `pre_copy_to_folder`; per IID computes `flags` (`no_hard_links` → `use_hard_links=False`, `dont_downgrade`); wraps each source in `ShouldCopySource(source_path_abs, target_folder_path, dont_downgrade=...)` guard with `pre_copy_item`/source/`post_copy_item`; sets `scs.skip_progress_count`; Mac counts symlinks and emits `ResolveSymlinkFilesInFolder` if any items copied; `post_copy_to_folder` only if accum `is_essential()`.
- **`create_copy_instructions_for_no_copy_folder()`** (`:341`) — for direct-sync / sync-only sources: `pre/post_copy_to_folder` + `pre/post_copy_item`; `Unwtar(sync_folder_name, os.curdir, no_artifacts=False)` if `count_wtar_items_of_dir>0`.
- `calc_size_of_file_item()` (`:128`) — wtar size scaled by `wtar_ratio`; accumulates `bytes_to_copy`.

### `InstlClientRemove` (`pyinstl/instlClientRemove.py`)

- **`create_remove_instructions()`** (`:30`) — reads `HAVE_INFO_MAP_PATH` (falls back to `SITE_HAVE_INFO_MAP_PATH` if missing); section `'remove'`; walks target folders **reverse-sorted** (children before parents); `pre_remove` (over `__FULL_LIST_OF_INSTALL_TARGETS__`); per folder sets `__TARGET_DIR__`, emits `pre/post_remove_from_folder`, and per IID `pre/post_remove_item` around `create_remove_instructions_for_source`; finally `post_remove`.
- **`create_remove_instructions_for_source(IID, folder, source)`** (`:76`) — three cases on the item's `remove_item` detail:
  1. *no* `remove_item` → default delete: `!dir`→`RmDir`, `!file`→`RmFile`, `!dir_cont`→expand via `info_map_table.get_items_in_dir(immediate_children_only=True)` + `utils.original_names_from_wtars_names` → `RmFileOrDir` per leaf;
  2. `remove_item: ~` → list is `[None]`, filtered out → no-op;
  3. explicit action(s) → `EvalShellCommand(action, message)`.

### `InstlClientUninstall` (`pyinstl/instlClientUninstall.py`)

Subclass of `InstlClientRemove`. Overrides `calculate_install_items()` (`:27`) to call `calculate_main_install_items()` + `calculate_all_uninstall_items_option_2()`.

- **`calculate_all_uninstall_items_option_2()`** (`:114`) — reference-counting over require-translate rows from `items_table.get_all_require_translate_items()`:
  1. honor `DO_NOT_REMOVE_TARGETS` (`set_ignore_iids`) and `FORCE_UNINSTALL_OF_MAIN_ITEMS`;
  2. build `how_many_require_by[iid]` and `iid_to_required_items[iid]` from `(iid, require_by, status)` rows;
  3. for each main candidate, decrement counts of items required only by uninstalled candidates; items still `require_by` someone are kept; `should_be_uninstalled = candidates - required_by_someone`;
  4. reset status, then BFS via a `deque` propagating uninstall to items whose count reaches 0;
  5. items with count 0 → `__FULL_LIST_OF_INSTALL_TARGETS__`; remainder → `__ORPHAN_INSTALL_TARGETS__`; mark `install_status["remove"]`; `sort_all_items_by_target_folder(consider_direct_sync=False)`.
- `calculate_all_uninstall_items_option_1()` (`:31`) — near-identical older algorithm, **dead code** (not wired in).
- **`create_uninstall_instructions()`** (`:100`) — if any targets: `create_remove_instructions()` + `create_require_file_instructions()`, and injects into section `'begin'` a `PythonDoSomething('PythonBatchCommandBase.set_a_kwargs_default("ignore_all_errors", True)')` so uninstall does not abort on a single failing command (also tolerates pre-python-batch index.yaml).

### `InstlClientReport` (`pyinstl/instlClientReport.py`)

Read-only. Overrides `calculate_install_items()` to a **no-op** (`:57`). Accumulates rows into `self.output_data` and overrides `command_output()` (`:29`) to serialize to `__MAIN_OUT_FILE__` (or stdout) per `OUTPUT_FORMAT`: `json` (`json.dumps`), `yaml` (`aYaml.writeAsYaml`), or `text` (comma-joined lines); suppressed when `__SILENT__`.
- `do_report_versions()` (`:49`) — `items_table.versions_report(report_only_installed=__REPORT_ONLY_INSTALLED__)`.
- `do_read_yaml()` (`:66`) — forces `OUTPUT_FORMAT=yaml`, `DEBUG_INDEX_DB=True`, calls `verify_actions()`, dumps config_vars (`!define`) + resolved index (`!index`).
- `do_report_gal()` — `get_version_of_installed_binaries()`. `report_no_current_installation()` returns a stock "no products installed" tuple.

### `InstlDoIt` (`pyinstl/instlDoIt.py`)

Separate top-level mode (extends `InstlInstanceBase`, *not* `InstlClient`). `do_command()` reads YAML, activates OSes, `init_default_doit_vars()`, `resolve_inheritance()`, `calculate_full_doit_order()`, `do_doit()`, writes the batch file.
- **`calculate_full_doit_order()`** (`:85`) — requires `MAIN_DOIT_ITEMS`; for each iid recurse `resolve_dependencies_for_iid` (post-order append into `full_doit_order: unique_list`, so dependencies precede dependents); orphan iids (not in DB) are warned, written to `__ORPHAN_DOIT_TARGETS__`, and removed; result → `__FULL_LIST_OF_DOIT_TARGETS__`.
- **`do_doit()`** (`:59`) — three sections in order: `pre_doit`, `doit`, `post_doit`; per iid `doit_for_iid()` emits `Stage` + `Remark` begin/end wrapping `EvalShellCommand`s.

### `InstlMisc` (`pyinstl/instlMisc.py`)

Separate `do_something` mode (extends `InstlInstanceBase`). `do_command()` (`:28`) sets up dynamic-progress vars (`__START/_TOTAL_DYNAMIC_PROGRESS__`, `PROGRESS_STACCATO_PERIOD`), dispatches via `getattr`, optionally times the command (`PRINT_COMMAND_TIME`). `dynamic_progress()` does staccato progress logging.

Subcommands mostly wrap a single pybatch command: `do_wtar`/`do_unwtar`/`do_wzip`, `do_checksum` (recursive checksums, formatted table), `do_ls` (per `__LIMIT_COMMAND_TO__`), `do_resolve` (`ResolveConfigVarsInFile` or `...InYamlFile`), `do_exec` (`Exec`, optionally reads `__CONFIG_FILE__` first), `do_translate_url`, `do_parallel_run` (`ParallelRun`), `do_version`/`do_help`/`do_fail`/`do_test_import`.
- **`do_run_process()`** (`:315`) — parses an input file or `RUN_PROCESS_ARGUMENTS` into `RunProcessInfo` namedtuples, handling `>`/`>>` redirects and `2>&1`; runs each via `Subprocess` (or stdout for `echo`). Calls `setup_abort_file_monitoring()`.
- **`setup_abort_file_monitoring()`** (`:289`) — if `ABORT_FILE` set, spawns a daemon `psutil` watchdog thread that, when the abort file disappears, kills all child processes and `os._exit`s.
- **`do_check_checksum()`** (`:86`) — the heavy one: wires the download observability/events/cohort telemetry around `CheckDownloadFolderChecksum(info_map_file, print_report=True, raise_on_bad_checksum=True)()`. It starts an observability session (`downloadObservability.start_session`), reads rollout flags (`downloadCohort.active_flags_from_config`, kill switches `DOWNLOAD_TELEMETRY_ENABLED`/`DOWNLOAD_RETRY_POLICY_ENABLED`/`DOWNLOAD_CENTRAL_UX_ENABLED`), resolves validated hosts and cohort, emits capability/session-state events, runs the check inside `try/finally`, and on finish marks/ends the session, persists a summary snapshot to `LOCAL_REPO_BOOKKEEPING_DIR`, and emits `completed`/summary events. Many nested `try/except: pass` blocks deliberately swallow telemetry errors so they cannot break the sync run.

### `installItemGraph` (`pyinstl/installItemGraph.py`)

Thin `networkx` wrapper, used for cycle/needed-by analysis (by `instlInstanceBase.find_cycles()/needed_by()` and `instlAdmin.py`), *not* by the main copy/remove path (which uses SQL recursion in `items_table`).
- `create_dependencies_graph(items_table)` / `create_inheritItem_graph(items_table)` — build `DiGraph`s of `depends`/`inherit` edges.
- `find_cycles(item_graph)` → `nx.simple_cycles`.
- `find_needed_by(item_graph, node)` — recursive predecessor closure into `utils.set_with_order()`.
- `find_leaves(item_graph)` (`:33`) — **buggy/dead**: `item_graph.neighbors(node)` returns an always-truthy iterator, so `if not the_neighbors` never matches; no callers.

### Data structures / on-disk formats owned here

- **In-memory**: `__all_iids_by_target_folder`, `__no_copy_iids_by_sync_folder` (both `defaultdict(unique_list)`), `auxiliary_iids`, `main_install_targets`, `full_doit_order`, `InstlMisc.curr/total_progress`.
- **config_vars derived lists** (implicit data passed between methods): `__MAIN_INSTALL_IIDS__`, `__MAIN_UPDATE_IIDS__`, `__FULL_LIST_OF_INSTALL_TARGETS__`, `__ORPHAN_INSTALL_TARGETS__`, `__FULL_LIST_OF_DIRECT_SYNC_TARGETS__`, `ALL_SYNC_DIRS`, `__FULL_LIST_OF_DOIT_TARGETS__`, `SYNC_FOLDER_MANIFEST_FILE`.
- **DB side-effects**: `items_table` `install_status` columns mutated (`index_item_t`/`index_item_detail_t`, then locked); `info_map_table.update_downloads()` writes `download_path`/`download_root` per SVNRow; `config_var_list_to_db(config_vars)` at end.
- **Files**: generated batch file, `__WRITE_CONFIG_VARS_TO_FILE__`, require.yaml lifecycle (`SITE`/`OLD`/`NEW` paths + `*_require_before/after.yaml` + `*.failed_to_read`), HAVE_INFO_MAP copied to SITE, `*-sync-folder-manifest.txt`, observability summary in `LOCAL_REPO_BOOKKEEPING_DIR`.
- **Batch sections** (ordering partitions): `begin`/`pre`/`copy`/`post-copy`/`remove`/`pre_doit`/`doit`/`post_doit` — `set_current_section` controls emission order.

### Key invariants, edge cases, platform branches

- Wtar invariant in `_for_file`: `assert (len==1 and num_wtars==0) or num_wtars==len` — a source is either a single plain file or an all-wtar set.
- Remove folders are processed reverse-sorted (children before parents); copy folders forward-sorted; folders are all created up front before any copy.
- Direct-sync `Info.xml` checksum short-circuit skips download entirely (unless repair/`update_mode`).
- `remove_item: ~` (Null) is an explicit no-op; absence of `remove_item` triggers default delete.
- `!dir_cont` is illegal as a `previous_sources` tag (raises) and unwtars to `os.pardir` to avoid `X/X` nesting.
- Platform branches via `mac_current_and_target`/`win_current_and_target`: Mac adds `ChmodAndChown`/`Chmod` exec-bit/`Chown`/`ResolveSymlinkFilesInFolder`/`SetExecPermissionsInSyncFolder`.
- Error handling: `check_version_compatibility` raises and aborts; `read_previous_requirements` renames unparseable require.yaml to `.failed_to_read`; uninstall sets `ignore_all_errors` default; `do_check_checksum` swallows all telemetry exceptions; `setup_abort_file_monitoring` hard-exits via `os._exit`.

### Refactoring notes (this subsystem)

1. **God-class `InstlClient`** (`pyinstl/instlClient.py`, whole class). Bundles orchestration, DB-status mutation, folder bookkeeping, sync-location computation, require.yaml I/O, binary-version scan, YAML repr, and name resolution. Extract `calculate_*`, `set_sync_locations_for_active_items`, and require-file management into collaborator classes; leave `InstlClient` as a thin orchestrator.
2. **Duplicated uninstall algorithms** (`instlClientUninstall.py:31` vs `:114`). `_option_1` is dead (~60 duplicated lines) and mutates `req_trans` `status` in place. Delete `_option_1` and factor the shared require-count/closure loop into one named method that treats require-translate rows as immutable input.
3. **Near-duplicate target-OS/sync-url init** (`instlClient.py:117-130` vs `instlDoIt.py:44-56`). The `SYNC_BASE_URL_MAIN_ITEM` + `TARGET_OS_*` block is copy-pasted; pull it up into `instlInstanceBase`.
4. **Implicit data flow via config_vars + in-place row mutation** (`instlClient.py:200-253`; `instlClientUninstall.py:138-194`). Calculation results round-trip through `__*__` config keys and uninstall mutates `req_trans['status']`. Return explicit structures from calculation methods.
5. **Scattered platform branching + dead comment block** (`instlClientCopy.py:151-153, 184-191, 243-258` and dead block `:208-217`). Isolate per-platform post-copy steps behind a strategy object and delete the commented-out `_for_dir_extended` body.
6. **`do_check_checksum` telemetry sprawl** (`instlMisc.py:86-189`). A misc utility now owns cross-subsystem session/event/cohort wiring with many silent `try/except: pass`. Move setup/teardown into a context manager in the `download*` package so `do_check_checksum` just enters it.
7. **Fragile `super().__thisclass__.__name__` idiom** (`instlClient.py:24`; `instlClientCopy.py:23`; `instlClientRemove.py:15`; `instlClientUninstall.py:17`; `instlClientReport.py:19`). Replace with `type(self).__name__` or an explicit class attribute for the defaults-file key.
8. **Buggy/dead `find_leaves`** (`installItemGraph.py:33-39`). `neighbors()` iterator is always truthy. Remove, or fix to `graph.out_degree(node) == 0`.
9. **Inline `InstlClientSyncCopy`** (`instlClient.py:650-659`). Defines a new type per `synccopy` invocation, hiding the Sync+Copy MRO. Promote to a real module/class for parity with the other subclasses.

---

I now have the full picture. Here is the LLD section.

## Admin Tooling

The admin subsystem is the build/maintenance side of `instl`, used by Waves Audio engineers and CI to populate and maintain the deployment repository (SVN + S3 + Redis). It was historically a single ~1480-line god-class, `InstlAdmin`, plus three module-level helper functions. Every `instl admin` subcommand is a `do_<command>` method dispatched dynamically.

> **Layout (post-modernization).** `pyinstl/instlAdmin.py` is now a thin shim that re-exports
> `InstlAdmin` (and `start_redis_heartbeat_thread`/`smart_merge_dicts`/`dict_in_canonical_order`)
> from the `pyinstl/admin/` package. `InstlAdmin` is composed via multiple inheritance from the
> mixins `_CoreAdminMixin` (`admin/_core.py`), `_RepoAdminMixin` (`_repo.py`), `_WtarAdminMixin`
> (`_wtar.py`), `_VerifyAdminMixin` (`_verify.py`), `_InfoAdminMixin` (`_info.py`),
> `_PublishAdminMixin` (`_publish.py`), with the free functions in `admin/_helpers.py`. This was a
> pure extract-module refactor: method names, signatures, the `getattr("do_"+name)` dispatch, and
> emitted output are identical, so the line-numbered breakdown below still describes the same code,
> now distributed across those submodules.

### Component breakdown

#### `class InstlAdmin(InstlInstanceBase)` — `pyinstl/instlAdmin.py:152`

Instantiated in `pyinstl/instl_main.py` for the `admin` and `interactive` command families (guarded to Mac/Linux). Owns almost no persistent state; orchestrates pybatch command objects and the SQLite-backed `self.info_map_table` / `self.items_table` inherited from `InstlInstanceBase`.

Key attributes set in `__init__(self, initial_vars)` (`:154`):
- `self.total_self_progress = 1000` — progress baseline; bumped per-iid in `verify_index_to_repo`.
- `self.fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')` — the info-map column set.
- `self.config_vars_stack_size_before_reading_config_files = None` — snapshot of the `config_vars` stack depth so config can be reset/reloaded.
- `self.wait_info_counter = 0` — throttles the wait-daemon banner (printed every 30th loop).
- Calls `read_defaults_file(...)` (reads `InstlAdmin.yaml` defaults) and `compile_exclude_regexi()`.
- Regex attributes compiled lazily by helpers: `compiled_forbidden_folder_regex`, `compiled_forbidden_file_regex` (in `compile_exclude_regexi`, `:287`), `compiled_should_be_exec_regex` (in `do_fix_props`/`do_fix_perm`), and the wtar regex family (`compiled_folder_wtar_regex`, `compiled_folder_exclude_wtar_regex`, `compiled_file_wtar_regex`, `compiled_wtar_by_file_size_exclude_regex`, `already_wtarred_regex`, `min_file_size_to_wtar`) set up in `prepare_conditions_for_wtar` (`:435`).

Dispatch / lifecycle methods:
- `do_command(self)` (`:184`) — calls `set_default_variables()` then `getattr(self, "do_"+self.fixed_command)()`. This dynamic dispatch is the contract: each CLI subcommand maps 1:1 to a `do_<command>` method.
- `set_default_variables(self)` (`:181`) → `read_config_files()`.
- `read_config_files(self, reset_previous=False)` (`:167`) — if `reset_previous`, resizes the `config_vars` stack back to the saved depth (used by the daemon's `reload-config-files`); pushes a new scope, resolves each `__CONFIG_FILE__` via `self.path_searcher.find_file`, reads each yaml, then `resolve_defined_paths()`.
- `get_default_out_file(self)` (`:163`) — derives `__MAIN_OUT_FILE__` as `$(__CONFIG_FILE__[0])-$(__MAIN_COMMAND__).$(BATCH_EXT)`.
- `get_revision_range(self)` (`:190`) — parses `REPO_REV` of form `min[:max]` (regex `(?P<min_rev>\d+)(:(?P<max_rev>\d+))?`); returns `(min_rev, max_rev)` as a half-open range (`max` is +1).
- `get_last_repo_rev(self)` (`:208`) — runs the `SVNLastRepoRev` pybatch command against `SVN_REPO_URL`, returns `int(__LAST_REPO_REV__)`.

The batch-emission idiom is uniform across filesystem commands: set `self.batch_accum.set_current_section('admin')`, append pybatch commands, then `self.write_batch_file(self.batch_accum)` and, iff `bool(config_vars["__RUN_BATCH__"])`, `self.run_batch_file()`. `instl` emits/executes a batch script rather than acting directly.

#### SVN-fix cluster: `do_fix_props` / `do_fix_perm` / `do_fix_symlinks`

- `do_fix_props(self)` (`:215`) — sets `PythonBatchCommandBase.ignore_progress = True`, runs `SVNPropList`+`SVNInfo` into temp files `svn-proplist-for-fix-props.txt` / `svn-info-for-fix-props.txt` in the work folder, ingests them via `SVNInfoReader(format='info'|'props')` into `info_map_table`. Then, for every item, emits `SVNDelProp("svn:"+extra_prop, ...)` for stray props and, by matching `(item.isExecutable(), should_be_exec(item))`, emits `SVNDelProp('svn:executable',...)` (True/False) or `SVNSetProp('svn:executable','yes',...)` (False/True). Other combinations are no-ops.
- `do_fix_perm(self)` (`:766`) — walks the staging folder (limited by `prepare_list_of_dirs_to_work_on`), emits `Unlock(...,recursive=True)`, and per file compares `is_file_exec()` (stat exec-bit) vs `should_file_be_exec()` (regex) to emit `Chmod(a+x)`/`Chmod(a-x)`; finally `Chmod(folder, "a+rw,+X", recursive=True)`. Forbidden files (matched by `compiled_forbidden_file_regex`) are deleted **immediately** with `os.unlink(item_path)` (`:786`) — a side effect inside a batch-building method (see refactor notes).
- `do_fix_symlinks(self)` (`:270`) — emits `CreateSymlinkFilesInFolder` per folder.
- Exec-bit predicates: `is_file_exec` (`:264`, stat `S_IXUSR|S_IXGRP|S_IXOTH`), `should_file_be_exec` (`:743`, `EXEC_PROP_REGEX`), `should_be_exec` (`:747`, file-only).

#### Staging↔SVN sync cluster: `do_stage2svn` / `stage2svn_with_comparator` / `do_svn2stage`

- `do_stage2svn(self)` (`:307`) — builds `(stage,svn)` path pairs (honoring `__LIMIT_COMMAND_TO__`), `raise_if_forbidden_dir`, emits `Unlock` + `Cd(svn_folder)`, then for each pair builds a `filecmp.dircmp(stage, svn, ignore=[".svn", ".DS_Store", "Icon\015"])` and calls `stage2svn_with_comparator`. The literal `"Icon\015"` (carriage-return Icon file) is a Mac-specific quirk.
- `stage2svn_with_comparator(self, comparator)` (`:341`) — recursive over `comparator.subdirs`. Handles three diff sets:
  - `left_only` (stage-only): rejects symlinks (`InstlException`, "run instl fix-symlinks"); skips forbidden files; **wtar transition special-case** — a `*.wtar.aa` file is *not* added if a `*.wtar` (same path minus `.aa`) exists with identical `utils.get_wtar_total_checksum` (`:362`), recording the bare name in `do_not_remove_items`; otherwise emits `CopyFileToDir` + `SVNAdd`. New dirs are recursively scanned for forbidden entries, then `CopyDirToDir` + `SVNAdd`.
  - `diff_files`: for first-wtar parts, compares total wtar checksums; if equal, suppresses copy of all split parts (`utils.find_split_files`) via `do_not_copy_items`. Else `CopyFileToDir`.
  - `right_only` (svn-only): `SVNRemove`, unless in `do_not_remove_items`.
- `do_svn2stage(self)` (`:552`) — `SVNCleanup` (if checkout exists), then per limit `SVNCheckout(depth="infinity")` + `CopyDirContentsToDir(..., delete_extraneous_files=True)`.

#### Wtar cluster: `prepare_conditions_for_wtar` / `should_wtar` / `do_wtar_staging_folder`

- `prepare_conditions_for_wtar(self)` (`:435`) — compiles `FOLDER_WTAR_REGEX`, `FOLDER_EXCLUDE_WTAR_REGEX` (defaults to `a^`, matches nothing), `FILE_WTAR_REGEX`, `MIN_FILE_SIZE_TO_WTAR`, `WTAR_BY_FILE_SIZE_EXCLUDE_REGEX` (defaults to `.+`), and `already_wtarred_regex = re.compile(r"wtar(\.\w\w)?$")`.
- `should_wtar(self, dir_item: Path)` (`:458`) — returns `(_should_wtar, _already_tarred)`. Folders: wtar if `FOLDER_WTAR_REGEX` matches and exclude doesn't. Files: wtar if `FILE_WTAR_REGEX` matches, else if size > `min_file_size_to_wtar` and not in size-exclude regex. **Wraps the whole body in `try/except Exception: pass`** (`:490`), silently swallowing stat/IO errors.
- `do_wtar_staging_folder(self)` (`:494`) — emits `Unlock`, `RmGlob('**/.DS_Store')`, `RmGlob('**/*~*')`, then runs a BFS worklist over the staging tree. For each non-wtar, non-symlink item it removes stale wtar parts (`utils.find_wtarred_parts_of_original` → `RmFile`); if `should_wtar` says yes, emits `Wtar(item, split_threshold=min_file_size_to_wtar)` + `RmFileOrDir(item)`; otherwise recurses into directory children. `total_redundant_wtar_files` is dead (always 0).

#### Verification cluster: `do_verify_index` / `do_verify_repo` + helpers

- `do_verify_index(self)` (`:584`) — reads index yaml + `FULL_INFO_MAP_FILE_PATH`, then `verify_actions()` (base class) + `verify_index_to_repo()`.
- `do_verify_repo(self)` (`:614`) — reads `STAGING_FOLDER_INDEX`, `info_map_table.initialize_from_folder(STAGING_FOLDER)`, `activate_all_oses()`. Runs `verify_inheritance` + `verify_dependencies` **before** `resolve_inheritance` (ordering is a hard invariant — both read raw detail rows). If any problems, prints and raises `AssertionError`. Otherwise `resolve_inheritance()`, `verify_actions()`, `verify_index_to_repo()`.
- `verify_inheritance` (`:632`) / `verify_dependencies` (`:641`) — collect missing `inherit`/`depends` IIDs via `items_table.get_missing_iids_from_details(...)` into a `defaultdict(list)` keyed by IID.
- `verify_index_to_repo(self, problem_messages_by_iid=None)` (`:659`) — for each IID: detects duplicate names (`names_to_iids`, excused by `COMMON_NAME_OK`), marks sources required via `info_map_table.mark_required_for_source(source_path, source_type)` and flags sources with zero files (excused by `NO_FILES_OR_FOLDERS_OK`; also reports case-insensitive near-matches), validates `previous_sources` (non-empty, type `!file`/`!dir`), and flags IIDs with sources but no install folders (excused by `NO_TARGET_FOLDER_OK`). Then `mark_required_completion()`, `find_cycles()` (base class, cyclic-dep detection), and reports `get_unrequired_items(what="file"|"dir")`.
- `do_depend(self)` (`:590`) — builds `installItemGraph.create_dependencies_graph`, computes per-IID `depends` (`self.needs`) and `needed_by` (`self.needed_by`); empty lists become `None` so yaml renders `~`. Writes via `aYaml.writeAsYaml`.

#### Release pipeline: `do_up2s3` / `up2s3_repo_rev`

- `do_up2s3(self)` (`:919`) → `up2s3_repo_rev(int(config_vars['TARGET_REPO_REV']), self.batch_accum)`.
- `up2s3_repo_rev(self, repo_rev, batch_accum)` (`:986`) — the core release algorithm (see below). Re-entered by the wait-daemon's spawned subprocess.

#### Lightweight variant: `do_up_short_index` / `up_short_index_repo_rev`

- `up_short_index_repo_rev(self, repo_rev, batch_accum)` (`:927`) — near-duplicate scaffolding of `up2s3_repo_rev` (same assert trio, Redis client, STATUS/EXCEPTION config-vars, try/except-reraise, finally-email). Skips checkout/sync; only emits `IndexYamlReader` → `ShortIndexYamlCreator` → optional `SetBaseRevision` → `CreateRepoRevFile`, then `aws s3 cp` of the short-index and repo-rev file.

#### Activation: `do_activate_repo_rev` (`:1205`)

Promotes an uploaded specific repo-rev file to the activated name using **boto3** (not the aws CLI). Nested `is_file_in_s3(...)` helper lists `admin/$(REPO_REV_FILE_SPECIFIC_NAME)`; if present, server-side `client.copy(...)` to `admin/$(REPO_REV_FILE_BASE_NAME)`; verifies via a second `is_file_in_s3`, downloads it back to the work folder, and regex-checks `^REPO_REV:\s+(?P<target_repo_rev>\d+)` against the requested rev (raises `ValueError` on mismatch). Records done-list/current in Redis. Sets `ACTIVATE_STATUS`/`ACTIVATE_EXCEPTION`. `is_file_in_s3` swallows all exceptions (`:1234`).

#### Redis daemon: `do_wait_on_action_trigger` (`:1105`) + helpers

Long-running loop. Optionally starts `start_redis_heartbeat_thread`. `BRPOP`s `WAITING_LIST_REDIS_KEY` (timeout 30s), writes `IN_PROGRESS_REDIS_KEY` status throughout. Control words: `stop` (break), `ping` (incr `<key>:ping`), `reload-config-files` (`read_config_files(reset_previous=True)`). Otherwise parses `what_to_do:domain:major_version:repo_rev`, maps trigger word → command via the inline dict `{'upload':'up2s3','up2s3':'up2s3','activate':'activate-repo-rev','short-index':'up-short-index'}` (`:1155`), writes a per-trigger `!define` config yaml that `__include__`s the domain/major config + main config, and **spawns a fresh `instl` process** via `mp.get_context("spawn").Process(target=instl_own_main, args=([..., instl_command_name, "--config-file", ..., "--log", ..., "--db", ":file:", "--run"],))`, then `join()`s it. The whole trigger branch is wrapped in `try/except Exception: log` (`:1197`) — an unknown trigger word's `KeyError` is logged and swallowed.
- `report_instl_info_to_redis(self, redis_instance)` (`:1081`) — `hmset` version/path/python/os to `INSTL_INFO_REDIS_KEY`.
- `print_wait_on_action_trigger_info(...)` (`:1092`) — usage banner, printed every 30th iteration.
- `get_work_folder(self)` (`:1281`) — `UPLOAD_WORK_AREA / domain / major / hierarchy`, created via `MakeDir`.
- `send_email_from_template_file(self, path_to_template)` (`:1293`) — `ResolveConfigVarsInFile` then `utils.send_email_from_template_file`; on failure appends the traceback to the resolved file rather than raising.

#### Manifest collection: `do_collect_manifests` (`:1329`) + writers

Walks each `COLLECT_MANIFESTS_DIR`, recursing one level per top-level dir (the dir name becomes `top_level_tag`), reading every `*manifest.yaml`. Two classes are defined **inside the method**: `ManifestItem` (`@dataclass`, `:1330`) and `ManifestYamlReader(ConfigVarYamlReader)` (`:1341`) which registers `manifest_node_reader` for `__no_tag__`, the generic map tag, and `!index`, collecting nodes (skipping `template*` keys) into `manifest_nodes[iid]`. Only IIDs ending in `_IID` are kept. Merge logic by count: 1 → tag `Common`; 2 → `dictdiffer.diff` (ignoring `top_level_tag`); identical → `Common`, different → `smart_merge_dicts` + `dict_in_canonical_order` → `Common`; >2 → reported and cleared. Results bucketed into `{Common, Mac, Win}` and written as yaml (`write_collected_manifests_yaml`, `:1440`, with tags `!index`/`!index_Mac`/`!index_Win`, prepending `COLLECT_MANIFESTS_BASE_INDEX` verbatim) or json (`write_collected_manifests_json`, `:1461`, flat list with `_children` for `depends`).

#### Misc utilities

- `do_file_sizes(self)` (`:814`) — emits `path, size` lines via `utils.excluded_walk` honoring forbidden regexes.
- `do_read_info_map(self)` (`:830`) — loads info-map files into `info_map_table`.
- `do_check_instl_folder_integrity(self)` (`:836`) — recomputes `utils.get_file_checksum` for `index.yaml`, `info_map.txt`, and each split info-map listed in the index, comparing to `INDEX_CHECKSUM`/`INFO_MAP_CHECKSUM`/per-item `checksum`.
- `do_translate_guids(self)` (`:866`) / `translate_guids_in_file` (`:896`) — annotates GUIDs (regex `[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}`) with `# <IID>` from `items_table.get_all_iids_with_guids`, preserving atime/mtime. Per-file body in `try/except Exception: pass` (`:890`) and a `finally` `except: pass` unlink (`:893`).
- `do_short_index(self)` (`:1303`) — `IndexYamlReader` → `ShortIndexYamlCreator`.
- `do_dump_config_vars(self)` (`:1312`) — dumps all config vars as a `!define` yaml doc, annotating raw vs resolved values.

#### Module-level functions

- `start_redis_heartbeat_thread(redis_host, redis_port, heartbeat_key, heartbeat_interval)` (`:30`) — daemon thread setting `heartbeat_key` to the current timestamp every interval; loop body wrapped in `try/except Exception: print` (`:43`).
- `smart_merge_dicts(by_os_dict)` (`:51`) — merges per-OS dicts (Linux/Mac/Win), hoisting keys identical across all OSes to the top level and keeping differing keys under their OS bucket, using `dictdiffer.diff` to compare. Assumes inputs already differ.
- `dict_in_canonical_order(to_order, order=None, single_value=None)` (`:120`) — recursively reorders mapping keys to `order` (extras appended), and collapses single-element sequences for keys in `single_value`.

### Key algorithm: `up2s3_repo_rev` (release pipeline) — `:986`

1. **Guard asserts** (`:987`): `repo_rev >= BASE_REPO_REV`, `repo_rev >= IGNORE_BELOW_REPO_REV`, `repo_rev not in IGNORE_SPECIFIC_REPO_REV`. These are bare `assert`s (disabled under `python -O`).
2. Construct `redis.Redis(host, port, decode_responses=True)`.
3. **try:** set `UP2S3_STATUS="FAILED"`, `UP2S3_EXCEPTION=""`, `REPO_REV`/`__CURR_REPO_REV__=repo_rev`, and `__CURR_REPO_FOLDER_HIERARCHY__ = info_map_table.repo_rev_to_folder_hierarchy(repo_rev)` (e.g. 345 → `03/45`).
4. Resolve checkout/revision paths from config vars (`UPLOAD_BASE_CHECKOUT_FOLDER`, `UPLOAD_REVISION_FOLDER`, etc.).
5. Build batch: if base folder is a valid `.svn` checkout → `SVNCleanup`, else `shutil.rmtree`; then `SVNCheckout(repo_rev=repo_rev)`, `MakeDir` for revision folders.
6. In `Cd(checkout_base_folder)`: `SVNInfo` → `info_map.info`, `SVNPropList` → `info_map.props`, `FileSizes` → `info_map.file-sizes`.
7. Ingest into tables: `IndexYamlReader(index.yaml)`, `SVNInfoReader(info)`, `SVNInfoReader(props)`, `SVNInfoReader(file-sizes)`; if `BASE_REPO_REV > 0` → `SetBaseRevision`.
8. `CopySpecificRepoRev(checkout_base, revision_folder, repo_rev)` (only this rev's files) + `CopyDirToDir` of the instl folder.
9. Write maps: `InfoMapFullWriter` (full info map), `InfoMapSplitWriter` (per-iid split maps), `Wzip(index)`, `ShortIndexYamlCreator(short-index.yaml)`, `CreateRepoRevFile()`.
10. In `Cd(revision_folder)`: `aws s3 sync . s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)` then `aws s3 cp` repo-rev file to `admin/`. Then `RmDirContents(revision_folder, exclude=['instl'])`.
11. `write_batch_file` + (if `__RUN_BATCH__`) `run_batch_file`.
12. Record completion in Redis: `hset` done-lists + `set` last-uploaded keys (both repo-rev and short-index keys). Set `UP2S3_STATUS="Completed"`.
13. **except** → store message in `UP2S3_EXCEPTION`, print, re-raise. **finally** → `send_email_from_template_file(UP2S3_EMAIL_TEMPLATE_PATH)`.

The email template is rendered from `config_vars`, so STATUS/EXCEPTION double as inter-step messaging *and* email-template data.

### Data structures / on-disk & external formats this subsystem produces

- **SQLite tables** (inherited): `info_map_table` (SVNTable: `path, flags, revision, checksum, size`, plus required-flags) and `items_table` (IndexItemsTable: IIDs, inherit/depends, install_sources, install_folders).
- **Temp files**: `svn-proplist-for-fix-props.txt`, `svn-info-for-fix-props.txt`.
- **Per-repo-rev artifacts**: `info_map.info`, `info_map.props`, `info_map.file-sizes`, full info map (`FULL_INFO_MAP_FILE_NAME`), split info maps, wzipped `index.yaml`, `short-index.yaml`, `V*_repo_rev.yaml.<rev>`.
- **Repo-rev folder hierarchy**: rev → 2-level zero-padded path (`345 → 03/45`).
- **S3 layout**: `s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/<hierarchy>/...` for revision data and `s3://$(S3_BUCKET_NAME)/admin/<repo_rev_file>` for repo-rev pointer files.
- **Redis keys**: heartbeat, `WAITING_LIST_REDIS_KEY` (BRPOP list), `IN_PROGRESS_REDIS_KEY`, done-list hashes, last-uploaded/current keys, `INSTL_INFO_REDIS_KEY` hash, `<key>:ping`.
- **Trigger string grammar**: `upload|up2s3|activate|short-index : domain : major_version : repo_rev`, or control words `stop|ping|reload-config-files`.

### Invariants, edge cases, platform branches

- **Dispatch invariant**: `self.fixed_command` must have a matching `do_<command>` method; no central registry validates this (an unknown command → `AttributeError`).
- **Verify ordering invariant**: inheritance/dependency checks must run before `resolve_inheritance()` (`do_verify_repo`).
- **Wtar identity invariant**: `.wtar.aa` ≡ legacy `.wtar` when total checksums match — prevents needless re-downloads on the extension rename (`stage2svn_with_comparator`).
- **Threshold guards** via `assert` in both upload paths — note these vanish under `-O`.
- **Platform-specific**: Mac `Icon\015` / `Icon\r` handling (`dircmp` ignore `:333`, immediate `os.unlink` `:786`); `.DS_Store`/`*~*` removal in wtar; the subsystem is restricted to Mac/Linux by `instl_main`.
- **Error handling shape**: each of up2s3 / up-short-index / activate uses try(set FAILED) / except(record exception + reraise) / finally(send email). The wait daemon wraps each trigger in a `push_scope_context(use_cache=True)` so per-trigger config-var pollution is discarded.

### Targeted refactoring notes (this subsystem)

1. **God-class** (`InstlAdmin`, whole file, `:152`). ~1480 lines spanning ~10 unrelated command clusters sharing mutable instance state. Suggest splitting into collaborator classes/mixins (`RepoMaintenance`, `StageSync`, `Wtar`, `Verification`, `S3Upload`, `RedisDaemon`, `ManifestCollector`) or a command-object registry replacing `getattr("do_"+name)`.
2. **Duplicated upload scaffolding** (`up_short_index_repo_rev` `:927` vs `up2s3_repo_rev` `:986`). Identical assert trio, Redis setup, STATUS/EXCEPTION bookkeeping, and try/except/finally-email block. Extract a context manager `_repo_rev_upload_session(status_var, exception_var, email_template)` wrapping the lifecycle.
3. **config_vars used as a status/messaging channel** (`UP2S3_STATUS`/`UP2S3_EXCEPTION` `:997`, `UP_SHORT_INDEX_*` `:938`, `ACTIVATE_*` `:1213`). Global mutable store doubles as inter-step state and email-template data. Suggest returning explicit result objects to the email renderer.
4. **Classes defined inside a method** (`ManifestItem` + `ManifestYamlReader`, `:1330`/`:1341`). Re-created each call, untestable. Hoist to module level (or a dedicated module).
5. **Silent exception swallowing**: `should_wtar` `try/except Exception: pass` (`:490`), `do_translate_guids` (`:890`/`:893`), `is_file_in_s3` (`:1234`), heartbeat thread (`:43`), and `write_collected_manifests_yaml` bare `except` around the base-index read (`:1445`). These hide real failures and can produce wrong artifacts silently. Catch specific exceptions and at least log; let unexpected ones propagate.
6. **Side effects in batch-building method** (`do_fix_perm` `os.unlink` `:786`). Move the Mac `Icon\r` quirk into a dedicated pybatch command so the method only emits batch ops.
7. **Dead/no-op code**: `skip_some_actions = False` threaded through pybatch calls (`:956`, `:1023`); `total_redundant_wtar_files` always 0 (`:512`/`:545`); commented-out `RmFile` guidance (`:782`). Remove or wire to a real debug flag.
8. **Magic trigger→command dict inline in the daemon** (`:1155`). A `KeyError` on an unknown trigger is swallowed by the surrounding `except`. Define a single validated trigger registry.
9. **Hardcoded service clients**: `redis.Redis(...)` constructed in `up_short_index_repo_rev` (`:935`), `up2s3_repo_rev` (`:994`), `do_wait_on_action_trigger` (`:1126`), `do_activate_repo_rev` (`:1209`) and `boto3.resource('s3')` (`:1216`). Untestable without live services; provide lazy cached accessors (`self._redis()`, `self._s3()`) or inject clients.
10. **Deprecated `hmset`** (`report_instl_info_to_redis` `:1090`) — `hmset` is removed in redis-py 4+. Replace with `hset(key, mapping=...)`.

Relevant files: `pyinstl/instlAdmin.py` (shim) and the `pyinstl/admin/` package
(`__init__.py`, `_core.py`, `_repo.py`, `_wtar.py`, `_verify.py`, `_info.py`, `_publish.py`,
`_helpers.py`). The line numbers cited above are relative to the original monolithic file.

---

Now I have a complete and accurate picture of the file. Let me write the LLD section.

## GUI

### Overview

The GUI subsystem is a Tk/ttk desktop front-end for `instl`, historically implemented entirely in one `pyinstl/instlGui.py` module and now decomposed into the `pyinstl/gui/` package behind a thin `pyinstl/instlGui.py` re-export shim (submodules `_globals.py` — the import-time Tk root + `default_font_size` —, `_tkvars.py`, `_tooltip.py`, `_frame_base.py`, `_client_frame.py`, `_admin_frame.py`, `_activate_frame.py`, `__init__.py`; behavior-identical, so the breakdown below still applies). Its defining architectural choice is that it does **not** call instl logic in-process to run commands. Instead, each of its three tabs (Client, Admin, Activate) builds an instl command line out of `config_vars` and spawns the instl executable (`config_vars["__INSTL_EXE_PATH__"]`) as an **external subprocess** via `subprocess.Popen`. The GUI is itself an `instl` "instance": `InstlGui` subclasses `InstlInstanceBase` and reuses base-class facilities for config-var resolution, YAML reading/writing (`read_yaml_file`), the version string (`get_version_str`), and history persistence.

The Activate tab is the exception to the "spawn a subprocess" rule: it talks **directly** to a Redis server (via `utils.redisClient.RedisClient`) to display, activate, and upload repo-revs.

The core abstraction is `TkConfigVar`: a two-way binding between a Tk variable (`StringVar`/`IntVar`/`BooleanVar`) and an instl `ConfigVar`.

Entry point flow (driven by `pyinstl/instl_main.py`): `InstlGui(initial_vars)` → `init_from_cmd_line_options(options)` (inherited) → `do_command()` → `close()` (inherited).

### Component breakdown

#### `CreateTkConfigClass(TkBase, convert_type_func)` — factory function (lines 50-105)

Produces a `TkConfigVar` class bridging a Tk variable subclass to an instl `ConfigVar`. The value of record lives in the Tk variable; the `ConfigVar` is kept in sync. A "double-callback" scheme is used because Tk variables cannot be subclassed and registered generically.

Module-level products (lines 108-110):
- `TkConfigVarStr = CreateTkConfigClass(StringVar, str)`
- `TkConfigVarInt = CreateTkConfigClass(IntVar, int)`
- `TkConfigVarBool = CreateTkConfigClass(BooleanVar, bool)`

Key members of the produced `TkConfigVar`:
- `__init__(self, config_var_name, master=None, value=None, debug_var=False)`: calls `config_vars.setdefault(config_var_name, value)` to create the ConfigVar if absent, then registers `_config_var_set_value_callback` via `set_callback_when_value_is_set` (needed because `setdefault` will not (re)assign the callback when the ConfigVar already exists), and registers `_internal_trace_write_callback` via `self.trace("w", ...)`.
- `_internal_trace_write_callback(self, *args, **kwargs)`: fired on Tk write; if not in the internal-update guard, reads the Tk value via `self._tk.globalgetvar(...)`, pushes it into `config_vars[name]`, and then invokes the optional `_our_trace_write_callback`.
- `_config_var_set_value_callback(self, var_name, new_var_value)`: fired whenever the ConfigVar is assigned; if not guarded, pushes the converted value into the Tk var via `TkBase.set`. If guarded (i.e. the change originated from the Tk side), writes back via `self._tk.globalsetvar(...)`.
- `__internal_update`: boolean guard flag that breaks the circular Tk↔ConfigVar callback loop.
- `set_trace_write_callback(self, trace_write_callback)`: lets a controller hook the Tk-write event (this is how controllers wire `update_state` to fire on edits).
- `_get_value_from_config_var(self)`: returns `convert_type_func(config_vars.get(name, convert_type_func()))`.

#### `FrameController` — base controller (lines 113-244)

Base class for per-tab controllers. Owns a Tk `Frame`, a `tk_vars: dict[str, TkConfigVar]`, and shared widget/file/subprocess helpers. It mixes UI construction, filesystem dialogs, subprocess invocation, and error parsing.

Attributes: `name`, `instl_obj` (the owning `InstlGui`), `tk_vars`, `master`, `frame`, `text_widget` (the read-only command-preview `Text`; also the clipboard-copy target).

Methods:
- `create_frame(self, master)`: stores `master`, creates `self.frame = Frame(master)`.
- `create_line_for_file(self, curr_row, curr_column, label, var_name, locate=True, save_as=False, edit=True, check=False, combobox=None, columnspan=1, label_stick=E)`: builds a Label + (Entry or supplied Combobox) + optional "..." locate button (open/save dialog), "Edit" button, and "Chk" button row using `functools.partial` bound commands.
- `open_file_dialog(self, config_var_name)` / `save_file_dialog(self, config_var_name)`: `tkinter.filedialog.askopenfilename` / `asksaveasfilename` wrappers that set the corresponding `tk_vars` entry.
- `open_file_for_edit(self, path_to_file=None, config_var_containing_path_to_file=None)`: resolves the path, verifies `is_file()`, then tries `os.startfile(path, 'edit')` (Windows) and falls back on `AttributeError` to `subprocess.call(['open', path])` (Mac). Platform branch via exception.
- `check_yaml(self, path_to_yaml=None, config_var_containing_path_to_file=None)`: spawns instl `read-yaml --in <path> --silent` as a subprocess; logs OK / non-zero exit.
- `dump_config_vars(self)`: resolves `config_vars["__ADMIN_CALL_DUMP_CONFIG_VARS_TEMPLATE__"]`, `shlex.quote`s each part, spawns instl, captures stderr, and routes through `prompt_msg_on_err`.
- `copy_to_clipboard(self)`: copies `text_widget` contents (`get("1.0", END)`) to the clipboard if non-empty.
- `prompt_msg_on_err(self, return_code, resolved_command_line_parts, err_msg='')`: on non-zero exit, `re.findall`s a JSON-ish blob in stderr, `json.loads` the first match, extracts `result['exception_str']`, and shows a `messagebox.showwarning`.
- `update_state(self, *args, **kwargs)`: no-op hook overridden by subclasses.

#### `ClientFrameController(FrameController)` (lines 247-376)

Controls the Client tab. `tk_vars`: `CLIENT_GUI_CMD` (Str), `CLIENT_GUI_IN_FILE` (Str), `CLIENT_GUI_OUT_FILE` (Str), `CLIENT_GUI_RUN_BATCH` (Int), `CLIENT_GUI_CREDENTIALS` (Str), `CLIENT_GUI_CREDENTIALS_ON` (Int). Widget handles: `client_input_combobox`, `client_run_batch_file_checkbox`.

- `create_frame(self, master)`: builds the command `OptionMenu` (values from `__CLIENT_GUI_CMD_LIST__`), the "Run batch file" checkbox, input combobox (with `set_trace_write_callback` → `update_state`), output "Batch file" row, credentials entry + enable checkbox, the "run:" button → `run_client`, the read-only preview `Text`, and a "clipboard" button.
- `update_client_input_file_combo(self, *args)`: lists the directory of the current input file and populates the combobox `values`.
- `create_client_command_line(self)`: assembles `[__INSTL_EXE_PATH__, CLIENT_GUI_CMD, "--in", in, "--out", out]`, appends `--credentials <cred>` if `CLIENT_GUI_CREDENTIALS_ON` and a credential string is present, appends `--run` if `CLIENT_GUI_RUN_BATCH == 1`, and prepends `sys.executable` on Windows when not frozen.
- `run_client(self)`: calls `update_state`, resolves the argv via `config_vars.resolve_list_to_list`, `Popen`s it (note: **not** `shlex.quote`d, unlike admin), captures stderr, runs `prompt_msg_on_err`, then `print("...")`.
- `update_state(self, *args, **kwargs)`: refreshes the combo, sets `CLIENT_GUI_IN_FILE_NAME`, enables/disables the run checkbox based on `__COMMANDS_WITH_RUN_OPTION__`, and rewrites the preview `Text` with `config_vars.resolve_str` of the joined command line.

#### `AdminFrameController(FrameController)` (lines 379-546)

Controls the Admin tab. `tk_vars`: `ADMIN_GUI_CMD`, `ADMIN_GUI_TARGET_CONFIG_FILE`, `ADMIN_GUI_LOCAL_CONFIG_FILE`, `ADMIN_GUI_OUT_BATCH_FILE`, `__STAGING_INDEX_FILE__`, `SYNC_BASE_URL`, `DISPLAY_SVN_URL_AND_REPO_REV`, `ADMIN_GUI_LIMIT` (all Str), `ADMIN_GUI_RUN_BATCH` (Int). Widget handles: `limit_path_entry_widget`, `admin_run_batch_file_checkbox`. Uses `ToolTip` on several widgets.

- `read_admin_config_files(self, ...)`: for `ADMIN_GUI_TARGET_CONFIG_FILE` and `ADMIN_GUI_LOCAL_CONFIG_FILE`, if the path `is_file()`, clears `config_vars["__SEARCH_PATHS__"]` (so stale `__include__` paths are not reused) then calls `self.instl_obj.read_yaml_file(config_path)`. This is what populates the displayed `__STAGING_INDEX_FILE__`, `DISPLAY_SVN_URL_AND_REPO_REV`, and `SYNC_BASE_URL` labels.
- `create_admin_command_line(self)`: looks up `admin_command_template_variables[command_name]` to get the template var, expands it via `list(config_vars[template_variable])`, then for non-`depend` commands appends `--limit <paths>` (using `shlex.split`, falling back to the raw string on `ValueError`) for commands in `__COMMANDS_WITH_LIMIT_OPTION__`, and `--run` for commands in `__COMMANDS_WITH_RUN_OPTION__`. Prepends `sys.executable` on Windows when not frozen.
- `run_admin(self)`: like `run_client` but `shlex.quote`s every resolved argv part before `Popen`.
- `update_state(self, ...)`: re-reads config files, sets `ADMIN_GUI_CONFIG_FILE_NAME`, toggles the limit entry and run checkbox by membership in the respective command-option lists, and rewrites the preview `Text`.
- Wires the "Save state" button to `instl_obj.write_history`, "ConfigVars to clipboard" to `dump_config_vars`, and "Command to clipboard" to `copy_to_clipboard`.

#### `ActivateFrameController(FrameController)` (lines 549-793)

Controls the Activate tab; talks directly to Redis rather than spawning subprocesses. `tk_vars` include `REDIS_HOST` (Str), `REDIS_PORT` (Int), `ACTIVATE_CONFIG_FILE`, `DOMAIN_REPO_TO_ACTIVATE`, `DOMAIN_REPO_TO_UPLOAD`, `IN_PROGRESS_VALUE`, `HEARTBEAT_VALUE`, `REPO_REV_TO_ACTIVATE`, `REPO_REV_TO_UPLOAD`, plus `REDIS_KEY_VALUE_1`/`_2` (Str). State attributes: `redis_conn` (`RedisClient` or `None`), `update_redis_table_working_id` (the pending `after` id), `last_heartbeat_value`, `heartbeat_no_diff_counter`, and `prev_focused_item` (set in `create_frame`), plus the `self.tree` Treeview.

- `read_activate_config_files(self)`: same pattern as admin but for `ACTIVATE_CONFIG_FILE` only.
- `update_state(self, ...)`: reads the config file; if `redis_conn` exists and host/port changed, stops polling and closes/clears it; if `redis_conn` is `None` and host+port are set, constructs a new `RedisClient(host, port)` and calls `start_update_redis_table()`.
- `update_redis_table(self)`: the polling body. Reads keys matching `ACTIVATE_REPO_REV_WILDCARD` and `UPLOAD_REPO_REV_WILDCARD`, parses each key as `prefix:domain:major_version`, merges into a `defaultdict(dict)` keyed by `domain → major_version → {activated, uploaded}`, and reconciles the Treeview (update existing item ids `domain:major_version`, insert new, delete leftovers). On focus change, syncs the selected row into `DOMAIN_REPO_TO_ACTIVATE`/`DOMAIN_REPO_TO_UPLOAD` and `REPO_REV_TO_ACTIVATE`/`REPO_REV_TO_UPLOAD`. Reads `HEARTBEAT_COUNTER_REDIS_KEY`; if the heartbeat value is unchanged for more than 10 polls, sets `IN_PROGRESS_VALUE = "Looks dead"`, otherwise reads `IN_PROGRESS_REDIS_KEY`. Finally clears the working id and re-arms via `start_update_redis_table()`.
- `start_update_redis_table(self)` / `stop_update_redis_table(self)`: schedule/cancel the 1500ms poll using `self.instl_obj.notebook.after(...)` / `after_cancel(...)` — the controller reaches through `instl_obj` into the `Notebook` widget it does not own.
- `activate_repo_rev(self)` / `upload_repo_rev(self)`: after a `messagebox.askyesno` confirm, `lpush` a value of the form `activate:<domain_repo>:<repo_rev>` (resp. `up2s3:...`) onto the key `$(REDIS_KEYS_PREFIX):<host>:waiting_list`. Both wrap their body in a bare `except Exception` that `print`s the error.
- Generic Redis helpers: `remove_redis_key(key_config_var, value_config_var=None)`, `lpush_redis_key(key_config_var, value_config_var)`, `get_redis_key(key_config_var, result_config_var)` (substitutes `"UNKNOWN KEY"` on missing), `set_redis_key(key_config_var, value_config_var)`.

#### `InstlGui(InstlInstanceBase)` (lines 797-895)

The GUI instl instance. Owns the Tk master window and ttk `Notebook`, instantiates the three controllers, and maps tab names to controllers.

- `__init__(self, initial_vars)`: `super().__init__`, `read_defaults_file(...)`, sets `self.master = tk_global_master`, registers `quit_app` for both the `exit` command (Command-Q) and `WM_DELETE_WINDOW`, builds the three controllers and the `tab_name_to_controller` dict.
- `do_command(self)`: `set_default_variables()` → `read_history()` → `create_gui()` → records `config_vars.stack_size()` → `self.master.mainloop()`.
- `create_gui(self)`: sets title to `get_version_str()`, builds the `Notebook`, binds `<<NotebookTabChanged>>` → `tabChangedEvent`, adds the three frames, selects the tab named by `SELECTED_TAB`, sets `resizable(0,0)`, and on Mac runs `osascript` to bring the Python window to the front.
- `read_history(self)` / `write_history(self)`: read/write the YAML history file named by `INSTL_GUI_CONFIG_FILE_NAME`. `write_history` records `SELECTED_TAB`, selects the var set named by `__GUI_CONFIG_FILE_VARS__`, serializes via `config_vars.repr_for_yaml(... resolve=False, ignore_unknown_vars=True)` wrapped in `aYaml.YamlDumpDocWrap('!define', ...)`.
- `tabChangedEvent(self, *args)`: dispatches `update_state(who="tabChangedEvent")` to the active controller, then `write_history()`.
- `set_default_variables(self)`: seeds `CLIENT_GUI_CMD`/`ADMIN_GUI_CMD` to the first list entry and creates `command_actual_name_<cmd>` vars for any command lacking one.
- `quit_app(self)`: `write_history()` then `master.destroy()`.

#### `ToolTip(Toplevel)` (lines 898-984)

A vendored reusable tooltip bound to `<Enter>`/`<Leave>`/`<Motion>` (`spawn`/`hide`/`move`, plus `show`). Holds text in a `msgVar` StringVar with `delay`/`follow` behaviour; used by `AdminFrameController` widgets. Its `move` handler swallows all exceptions when calling an optional `msgFunc`.

#### `admin_command_template_variables` — module dict (lines 36-47)

Maps each admin command name to the config-var template used to build its command line:
- `svn2stage`, `fix-symlinks`, `gather-manifest-files`, `wtar`, `stage2svn`, `fix-props`, `fix-perm` → `__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__`
- `verify-repo`, `collect-manifests` → `__ADMIN_CALL_INSTL_ONLY_CONFIG_FILE_TEMPLATE__`
- `depend` → `__ADMIN_CALL_INSTL_DEPEND_TEMPLATE__`

### Important algorithms / logic

**1. Tk ↔ ConfigVar two-way binding (double callback).**
```
On Tk write (_internal_trace_write_callback):
  if not __internal_update:
    value = read from Tk
    __internal_update = True
    config_vars[name] = value       # push to ConfigVar
    __internal_update = False
    if hooked: call _our_trace_write_callback()   # e.g. update_state
On ConfigVar set (_config_var_set_value_callback):
  if not __internal_update:         # change came from ConfigVar side
    Tk.set(convert(new_value))      # push to Tk var
  else:                             # change originated from Tk side
    __internal_update = True; globalsetvar(name, new_value); __internal_update = False
```
The `__internal_update` guard is the invariant that prevents infinite mutual recursion.

**2. Per-tab `update_state` cycle.** (1) Re-read referenced YAML config files, clearing `__SEARCH_PATHS__` first; (2) recompute derived display vars; (3) toggle widget enable-state by membership in `__COMMANDS_WITH_RUN_OPTION__` / `__COMMANDS_WITH_LIMIT_OPTION__`; (4) rebuild the command-preview `Text`: temporarily set `state='normal'`, delete, insert `config_vars.resolve_str(command_line)`, set `state='disabled'`.

**3. Command-line construction + run.** Build argv from a template/explicit list → resolve via `config_vars.resolve_list_to_list` → `Popen` the instl executable (Unix uses `preexec_fn=os.setsid`; Windows does not) → `communicate()` → decode stderr → `prompt_msg_on_err`.

**4. Redis poll loop.** `start_update_redis_table` arms a single `notebook.after(1500, update_redis_table)`; `update_redis_table` reconciles the Treeview against `ACTIVATE_/UPLOAD_REPO_REV_WILDCARD` keys, computes the heartbeat-stall counter (>10 unchanged polls ⇒ "Looks dead"), then re-arms itself. The `update_redis_table_working_id` guard ensures only one timer is pending.

### Data structures / on-disk formats owned

- **GUI history file** (path = `config_vars["INSTL_GUI_CONFIG_FILE_NAME"]`): a YAML `!define` document containing the vars listed in `__GUI_CONFIG_FILE_VARS__` plus `SELECTED_TAB`. Written unresolved (`resolve=False`) and sort-mapped; read back at startup by `read_history`.
- **Redis keys** (read/written by the Activate tab, not owned schema but the contract used): repo-rev keys parsed as `prefix:domain:major_version`; `HEARTBEAT_COUNTER_REDIS_KEY`; `IN_PROGRESS_REDIS_KEY`; and the work queue list `$(REDIS_KEYS_PREFIX):<host>:waiting_list` onto which `activate:<domain_repo>:<repo_rev>` / `up2s3:<domain_repo>:<repo_rev>` values are `lpush`ed.
- **In-memory Treeview model**: `defaultdict(dict)` keyed `domain → major_version → {'activated','uploaded'}`; Treeview item ids are `"<domain>:<major_version>"`, columns `('major version','uploaded','activated')`.

### Invariants, edge cases, error handling, platform branches

- **Single Tk root, created at import time** (`tk_global_master = Tk()`, line 29) and assigned to `InstlGui.master`. The mainloop runs from `do_command`.
- **`__internal_update` guard** is the key invariant of the binding (see algorithm 1).
- **`__SEARCH_PATHS__` must be cleared** before re-reading config YAMLs so stale `__include__` resolution paths are not reused (lines 399, 576).
- **Platform branches:** font size by `getattr(os, "setsid", None)` (lines 31-34); subprocess spawn uses `preexec_fn=os.setsid` on Unix vs plain `Popen` on Windows (4 call sites: 136-139, 222-225, 367-370, 539-542) — note `run_client` additionally pipes stdout on Windows only, an inconsistency; `sys.executable` prepended on Windows when not frozen (lines 356-359, 528-531); `open_file_for_edit` tries `os.startfile(...,'edit')` then falls back to `open` on `AttributeError`; Mac-only `osascript` raise-to-front (lines 894-895).
- **Error surfacing:** `prompt_msg_on_err` scrapes stderr with a regex for a JSON blob, `json.loads`es it, and reads `result['exception_str']` — brittle (see refactors). `read_history` wraps everything in `except Exception: pass`. `activate_repo_rev`/`upload_repo_rev` and `ToolTip.move` swallow exceptions (print or pass).
- **Edge case:** `update_redis_table` requires `self.redis_conn`; if `None` it logs and does not re-arm. Activate/upload only proceed if the selected `domain_repo` is currently in the tree and the user confirms.

### Targeted refactoring notes

1. **Module-level `Tk()` at import time** (line 29). Creating the Tk root as an import side effect makes the module non-importable in headless/test contexts and couples every consumer to a global window. *Direction:* construct Tk lazily inside `InstlGui.__init__`/`do_command` and pass it down.

2. **God base class `FrameController`** (lines 113-244) mixes UI layout, file dialogs, filesystem access, subprocess spawning, stderr parsing, and clipboard. *Direction:* extract a `CommandRunner` (Popen + stderr parse) and a `FileOps` helper, leaving `FrameController` a thin view-controller.

3. **Duplicated subprocess-spawn + Unix/Windows branch** repeated four times (`dump_config_vars` 136-139, `check_yaml` 222-225, `run_client` 367-370, `run_admin` 539-542), with subtle divergences (Windows stdout pipe only in `run_client`; `shlex.quote` only in `run_admin`/`dump_config_vars`, not `run_client`). *Direction:* one `run_instl_subprocess(argv) -> (rc, stderr)` helper used by all callers.

4. **Duplicated `read_*_config_files`** (`read_admin_config_files` 394-402, `read_activate_config_files` 571-579). *Direction:* a single `FrameController.read_config_files(self, var_names)` parameterized by var names.

5. **Activate tab couples to `InstlGui.notebook` for its timer** (lines 675, 680). The controller reaches through `instl_obj` into a widget it does not own to schedule callbacks. *Direction:* schedule via `self.frame.after` or inject a scheduler abstraction.

6. **Broad exception swallowing / debug prints** (`activate_repo_rev` 697-698, `upload_repo_rev` 713-714, `run_client` 376 `print("...")`, `read_history` 849-850). *Direction:* use `log.warning`/`log.exception` and narrow caught exceptions.

7. **Dead/unused code and stale TODOs:** `ADMIN_GUI_LIMIT_values` computed at 490-491 then never used; `DOMAIN_REPO_TO_UPLOAD`/`REPO_REV_TO_UPLOAD` and the upload feature marked `#todo oren - ??` (556-564, 684, 700); commented-out `grid_columnconfigure` (292-294) and log lines (676, 682). *Direction:* delete the dead assignment and comments; resolve or ticket the upload TODOs (referenced as SI-300).

8. **Fragile stderr error parsing** (`prompt_msg_on_err` 237-244): `re.findall` over JSON-like text then `json.loads(match[0])`, and `result['exception_str']` is accessed without fully guarding `KeyError` (also note the misspelled local `exception_sir` and message text "Procces finnished"). *Direction:* have the subprocess emit a structured error channel (marker/file) instead of scraping stderr.

9. **Scattered OS/platform checks** with inconsistent sources of truth — `getattr(os, "setsid", None)` (31, 136, 222, 367, 539) vs `'Win' in config_vars["__CURRENT_OS_NAMES__"]` (356, 528) vs `config_vars["__CURRENT_OS__"] == "Mac"` (894). *Direction:* centralize platform decisions in one place and reuse.

10. **Duplicated `import functools`** (lines 8 and 16). *Direction:* remove the redundant import.

---

I have all the detail I need. Here is the LLD section.

## Download Subsystem

This subsystem drives `instl`'s bulk file download. It builds `curl` config files and parallel-run plans, classifies and retries transfer failures, supports cooperative pause/resume/`try_now` via a stdin control channel, persists per-session and per-file download state plus resume sidecars, samples throughput/errors, recommends between-session concurrency, emits a structured JSON-line event channel to Central, and tags installs into rollout cohorts. The actual `curl` driver lives in `pybatch` (`ParallelRun` / `CurlWithInternalParallel`); the `curlHelper`-generated commands invoke it. Most modules are pure, dependency-injected helpers consumed at two choke points: `pyinstl/instlInstanceSync_url.py` (planning) and `pybatch/info_mapBatchCommands.py` `CheckDownloadFolderChecksum` (in-process redownload/verify).

> **Cross-checked against Waves Central's Download System Enhancement design (POC branch `feature/V17.0.10---POC-Download-Enhancements`).** The contracts this section documents match Central's authoritative design docs 1:1: the `DownloadSessionState`/`DownloadFileState` enums equal Central's canonical session/per-file state model (`state-model.md`); `DownloadFailureClass` is a superset of Central's FR-040 failure taxonomy and its retryable set / curl-exit-code map align with Central's `failure-corpus.md`; the `session.json` / `files/<fileId>.json` schema, `fileId = sha256(revision, repo_path, checksum, size)`, `<final>.instl-<fileId[0:16]>.part` temp name, and same-dir-temp + `os.replace` discipline match Central's persisted-state contract; the stdin `{cmd:pause|resume|try_now, sessionId?}` envelope, the `DOWNLOAD_EVENT <json>`/legacy `DOWNLOAD_RETRY_DECISION <json>` lines (schemaVersion 1), and the redaction denylist all match D-007/D-016/D-019. Central consumes these via `ShellInstlProcessProgressHandler`/`downloadEventParser.tsx`. Two Central-side nuances bound this engine: **offline-grace is no longer client-side-only** — the engine now detects an outage itself (connectivity probe + offline-hold in `CurlWithInternalParallel`) and, when the driving client declares `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD`, emits `paused, reason="offline_no_network"` session_states plus network-class per-probe `retry_decision`s (closing the old D-021 gap; with the capability absent — the shipped default — the hold recovers silently and only the legacy event stream is produced, so Central's client-side `onlineDetector.tsx` heuristic keeps working unchanged); and **adaptive concurrency is between-session only** (D-017) — within-session control remains an open Central decision.

### Component breakdown

#### `CUrlHelper` and value objects (`pyinstl/curlHelper.py`)

`CUrlHelper` (abstract base, line 63) is the command generator. It accumulates planned transfers and emits curl config files plus a `.parallel-run` plan.

Key attributes:
- `urls_to_download` / `urls_to_download_last` (lists of `CurlDownloadEntry`); `download_last` entries are forced to a final config file with a `wait` barrier before them so e.g. `Info.xml` is fetched last.
- `short_win_paths_cache` (Windows 8.3 short-path memoization).
- Class-level `cached_internal_parallel` (line 113): tri-state cache of curl internal-parallel support; `external_parallel_header_text` / `internal_parallel_header_text` config templates.

Value objects:
- `CurlConfigFile` (dataclass, line 24): `path`, write-fd `wfd`, `num_urls`.
- `CurlDownloadEntry` (dataclass, line 31): `url`, `final_path`, `output_path`, `size`, `resume_from_byte`, `conditional_headers`, `force_restart_from_zero`. `has_per_transfer_options()` (resume or conditional headers present), `is_resume_entry()` (`resume_from_byte > 0`), `fresh_restart_entry()` clones the entry with `force_restart_from_zero=True` for the exit-33 fallback.

Important methods:
- `add_download_url(url, path, verbatim=False, size=0, download_last=False, output_path=None, resume_from_byte=0, conditional_headers=())` (line 161): translates the URL via `connectionBase.connection_factory(config_vars).translate_url` (unless `verbatim`), validates `resume_from_byte >= 0` (raises `ValueError`), and rejects `\r`/`\n` in `conditional_headers`. Appends a `CurlDownloadEntry` to the normal or `_last` list. Called by `instlInstanceSync_url.py:140`.
- `is_internal_parallel_supported()` (line 126): lazily runs `curl --version`, parses with `re.search(r"curl\s+([0-9.]+)\s", ...)`, compares against `min_supported_parallel_curl_version = "7.66.0"` via `packaging.version.Version`, caches the result in the classvar. `use_internal_parallel()` (line 158) ANDs that with `config_vars["PARALLEL_DOWNLOAD_METHOD"] == "internal"`.
- `_create_config_files_for_entries(...)` (line 230): writes per-file curl config headers and per-transfer sections (see Algorithms). Owns the offline-grace retry-line policy.
- `_partition_resume_entries(entries)` (line 372): splits into fresh vs resume.
- `create_download_instructions(dl_commands)` (line 461): top-level entry called from `instlInstanceSync_url.py:227`. Partitions fresh/resume × normal/last into phases, builds config files, and appends `ParallelRun` (external) or `CurlWithInternalParallel` (internal) commands plus `Progress`/`MakeDir`.
- `create_parallel_run_config_file(path, config_files)` (line 551): writes one `"$(DOWNLOAD_TOOL_PATH)" --config "<path>"` line per config file; `None` entries become a `wait` line. On Windows it normalizes the config-file path via `win32api.GetShortPathName`.
- `fix_path(in_some_path_to_fix)` (line 191): Windows-only 8.3 short-path workaround for curl's unicode-path handling; creates the parent dir (needed because `GetShortPathName` requires an existing path) and falls back to the long path on failure.

#### `DownloadControlChannel` (`pyinstl/downloadControlChannel.py`)

Daemon-thread stdin reader plus shared pause/`try_now` state; a module-level singleton. Central writes one-line JSON commands (`{"cmd":"pause"|"resume"|"try_now", "sessionId":...}`) to `instl`'s stdin.

Key attributes:
- `_run_event` (`threading.Event`): **set == running**, so `_run_event.wait(timeout)` blocks while paused and returns immediately on resume.
- `_try_now_event` + `_try_now_pending`: a distinct wakeable primitive for the retry sleeper, so a `try_now` wake is not mistaken for a resume.
- `on_pause_event` / `on_resume_event`: optional callbacks fired from the reader thread on a paused↔running transition (the sync engine uses these to persist `state="paused"` and emit a session-state event). Exceptions in callbacks are swallowed.

Methods:
- `is_paused()`, `try_now_requested()` (consume-once read of the pending flag), `wait_if_paused(poll_seconds=0.5)` (polled block while paused), `sleep_or_wake(seconds) -> bool` (sleep, returns `True` if woken early by `try_now`).
- `start()` / `stop()` (lifecycle; `stop()` only flips `_stopped`, never closes stdin), `_reader_loop()`, `_handle_line(raw_line)` (parses one JSON object; filters by `sessionId` mismatch; dispatches `_apply_pause`/`_apply_resume`/`_apply_try_now`).
- Module accessors `get_global_channel()`, `set_global_channel()`, `reset_global_channel()` (test hook).

Consumed by `instlInstanceSync_url.py:162`, `info_mapBatchCommands.py:507`, the curl drivers (`subprocessBatchCommands.py:317/727`), and `downloadRetry.sleep_backoff`.

#### `downloadFailures` (`pyinstl/downloadFailures.py`)

Normalizes curl exit codes, HTTP statuses, and Python exceptions into one taxonomy.
- `DownloadFailureClass` (str Enum, line 21) and `RETRYABLE_FAILURE_CLASSES` (frozenset, line 46): the single source of truth for retryability.
- `DownloadFailureInfo` (frozen dataclass, line 84): `failure_class`, `retryable`, `source`, `reason`, `curl_exit_code`, `http_status`, `retry_after_seconds`; `to_dict()` emits camelCase.
- `classify_curl_exit_code(exit_code, http_status=None, headers=None, received_bytes=None)` (line 219): maps curl exit codes (e.g. 5/6→DNS, 7→TCP, 28→timeout split by `received_bytes`, 18/33→`PARTIAL_TRANSFER`, 23→`DISK_WRITE`, 22→delegates to `classify_http_status`).
- `classify_http_status(status_code, headers=None)` (line 163): 429→`HTTP_429` (+Retry-After), 408→timeout, 5xx→`HTTP_5XX`, 401/403/407→`HTTP_AUTH_POLICY`, other 4xx→`HTTP_4XX`.
- `classify_exception(exc)` (line 359): walks the `__cause__`/`__context__` chain; delegates to `requests`/`urllib`/`OSError` classifiers, then falls back to message-text heuristics.
- `retry_after_seconds(header_value, now=None)` (line 133): parses an integer-seconds or RFC HTTP-date `Retry-After`.

#### `downloadRetry` (`pyinstl/downloadRetry.py`)

Data-driven retry policy and backoff.
- `RetryPolicy` (frozen dataclass, line 76): `max_attempts`, `base_delay_seconds`, `max_delay_seconds`, `jitter_fraction`, `restart_required`, `respect_retry_after`.
- `DEFAULT_RETRY_MATRIX` (line 89): `{DownloadFailureClass -> RetryPolicy}`; terminal classes use `RetryPolicy()` (`max_attempts == 0`).
- `RetryAction` (Enum: `RESUME`/`RESTART`/`FAIL_TERMINAL`) and `RetryDecision` (frozen dataclass, line 184) with `will_retry` and `to_event(...)` (the `download.retry_decision` payload).
- `compute_backoff_seconds(attempt, policy, retry_after_seconds=None, random_unit_fn=None)` (line 146): exponential `base * 2^(attempt-1)`, capped by `max_delay_seconds`, multiplied by full-jitter `(1 + jitter_fraction * unit)`, overridden upward by `Retry-After` when the policy honors it.
- `decide_retry(failure, previous_retry_count, *, resume_eligible=False, matrix=DEFAULT_RETRY_MATRIX, random_unit_fn=None) -> RetryDecision` (line 234).
- `sleep_backoff(delay_seconds, *, channel=None) -> bool` (line 368): delegates to `channel.sleep_or_wake` (defaulting to `get_global_channel()`), drains the consume-once `try_now` flag, falls back to `time.sleep` when no channel is available.
- `format_retry_decision_log_line(decision, ...)` (line 330): emits the legacy `DOWNLOAD_RETRY_DECISION <json>` line, dropping `_DISALLOWED_EVENT_FIELDS`.

Consumed by `info_mapBatchCommands.py:222/238/561`.

#### `downloadState` (`pyinstl/downloadState.py`)

Owns on-disk download state and the resume-eligibility decision.
- `DownloadStateStore` (line 454): rooted at `<bookkeeping_dir>/download-state`; `session_path()` → `session.json`, `file_path(file_id)` → `files/{file_id}.json`. `from_bookkeeping_dir(...)`, `load/save_session`, `load/save_file`.
- Record dataclasses: `DownloadSessionRecord` (line 313), `DownloadFileRecord` (line 387), and sub-records `DownloadSourceState` / `DownloadTargetState` / `DownloadExpectedState` / `DownloadTransferState`; each with `from_dict`/`to_dict` and `schemaVersion` validation. Enums `DownloadSessionState` (line 24) and `DownloadFileState` (line 38).
- `write_json_atomic(path, data)` (line 430): tmp file + `fsync` + `os.replace`, indent=2/sort_keys, with `finally` cleanup.
- `temp_path_for_final_path(final_path, file_id)` (line 88): `<final>.instl-<first 16 of file_id>.part`. `make_file_id(...)` (line 74): sha256 over `(revision, repo_path, checksum, size)`. `promote_verified_temp_file(temp, final, expected_checksum, actual_checksum=None)` (line 140): verifies sha1 then `os.replace` (raises `ValueError("bad checksum ...")` on mismatch). `get_file_sha1`/`checksum_matches`.
- `update_session_state(bookkeeping_dir, new_state, reason=None, *, session_id=None)` (line 490): best-effort persisted transition; swallows all errors and returns `None`.
- `resume_decision_for_download_item(file_item, source_url, bookkeeping_dir, resume_enabled=False, validated_hosts=(), validated_path_prefixes=(), require_conditional=True, signed_url_min_ttl_seconds=300) -> DownloadResumeDecision` (line 774): the resume gate (see Algorithms). Called by `instlInstanceSync_url.py:130` and `info_mapBatchCommands.py:152`.
- Redaction helpers: `redact_url_for_state` (strips query/fragment), `object_key_from_url`, `resolve_validated_hosts` / `validated_hosts_from_base_url`, `conditional_headers_for_source` (prefers `If-Match: <etag>`, else `If-Unmodified-Since`), `has_sufficient_signed_url_ttl`.

#### `DownloadObservability` (`pyinstl/downloadObservability.py`)

In-process per-session aggregator; persists `session-summary.json`.
- `_HostCounters` (dataclass, line 101): totals plus per-host attempts/successes/failures/restarts/bytes/transfer-time/failure-classes.
- `DownloadOutcome` (string subclass, line 53): `SUCCESS`/`FAILED_RETRYABLE`/`FAILED_TERMINAL`/`RESTART_FORCED`.
- `DownloadObservability` methods: `set_plan(files, bytes)`, `record_outcome(*, outcome, url=None, host=None, failure_class=None, bytes_received=None, transfer_time_seconds=None)` (consumes only the host of `url`), `record_retry_decision(decision, ...)` (maps action→outcome), `mark_finished()`, `snapshot()` (computes `observedThroughputBytesPerSecond`, `errorRate`, `retryableErrorRate`), `save(bookkeeping_dir)`. All `record_*` calls swallow exceptions.
- Module singleton: `start_session()`, `active()`, `end_session(bookkeeping_dir)`, `record_outcome`/`record_retry_decision`/`set_plan` (no-ops when no active session), and `load_session_summary(bookkeeping_dir)` (read-side for the controller; returns `None` on schema mismatch).

#### `downloadConcurrency` (`pyinstl/downloadConcurrency.py`)

Between-session adaptive `PARALLEL_SYNC` controller.
- `ConcurrencyBounds` (frozen dataclass, line 57): `min/max/start` concurrency, `increase_step`/`decrease_step`, error-rate thresholds; `__post_init__` normalizes via `object.__setattr__`; `clamp(value)`. Defaults: min 2, max 50, start 8, +2/−4, backoff 0.15, grow 0.02.
- `AdaptiveAction` (Enum) and `ConcurrencyDecision` (frozen dataclass).
- `decide_next_concurrency(previous_summary, *, bounds=None, adaptive_enabled=True, user_override=None, configured_default=None)` (line 106): the decision matrix (see Algorithms).
- `resolve_concurrency_from_config(config_vars, summary_loader=None)` (line 240): reads bounds + flags + `LOCAL_REPO_BOOKKEEPING_DIR`, loads the previous summary, runs the controller. Called by `instlInstanceSync_url.py:232`. Private forgiving accessors `_bool_var`/`_str_var`/`_optional_positive_int`/`_optional_positive_float`.

#### `downloadEvents` (`pyinstl/downloadEvents.py`)

Single source of truth for the `DOWNLOAD_EVENT <json>` channel.
- `DownloadEventType` (Enum, line 114): `session_state`/`file_state`/`retry_decision`/`capability`/`session_summary`.
- `make_envelope(...)` (line 159): `event`/`schemaVersion`/`sessionId`/`timestamp`. `_DISALLOWED_EVENT_FIELDS` (line 128) + `_drop_disallowed`.
- Builders `make_session_state_event` / `make_file_state_event` / `make_capability_event` / `make_session_summary_event` / `make_retry_decision_event`, with matching `emit_*` convenience wrappers. `make_capability_event` (line 298) calls `downloadCohort.normalize_cohort`, filters `validated_hosts` to bare hosts, and forwards the flag map.
- `emit_event(event)` (line 185): honors the `_telemetry_enabled` kill switch and swallows all errors. `set_telemetry_enabled(bool)` / `is_telemetry_enabled()`.

#### `downloadCohort` (`pyinstl/downloadCohort.py`)

Normalizes the rollout cohort label and keeps it honest against the active flag set.
- `COHORTS` (line 39): ordered `control → atomicity → resume → retry → adaptive → ux`. `_REQUIRED_FLAGS_BY_COHORT` (line 49) maps each cohort to the flags that must be on.
- `normalize_cohort(raw)` (unknown → `control`), `resolve_cohort_from_config(config_vars)` (reads `DOWNLOAD_COHORT`, then downgrades), `downgrade_cohort_to_active_flags(cohort, active_flags)` (walks down `COHORTS` until all required flags are satisfied).
- `_TRACKED_FLAGS` (line 170) with defaults; `active_flags_from_config(config_vars)`, `tracked_flag_names()`. Consumed by `info_mapBatchCommands.py:644/659`. Now also tracks the connectivity-loss self-sufficiency gates (`DOWNLOAD_RECONCILE_MISSING_OUTPUTS`, `DOWNLOAD_OFFLINE_HOLD_ENABLED`, `DOWNLOAD_CURL_STALL_DETECTION`, `DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES` — default True) and the `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` capability handshake (default False), so they surface on `download.capability.featureFlags`.

#### Feature-flag defaults — the runtime contract (`defaults/InstlClient.yaml`)

These flags are the only runtime source of the download enhancement's behavior: **`instl` owns them in its bundled `defaults/InstlClient.yaml`; Waves Central does not set any `DOWNLOAD_*` flag from its side** (corroborated by Central's `defaults/InstlClient.yaml` being bundled inside `instl`'s PyInstaller output — a test build must edit this file and rebuild `instl`). Shipped values on this branch:

| flag | shipped default | rollout-plan / Central "default-off" contract |
|---|---|---|
| `PARALLEL_SYNC` | `50` | legacy non-adaptive default (adaptive `DOWNLOAD_CONCURRENCY_START` is `8`) |
| `DOWNLOAD_RESUME_ENABLED` | **`yes`** | contract default-off |
| `DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED` | `no` | default-off (matches contract) |
| `DOWNLOAD_TELEMETRY_ENABLED` | `yes` | default-on by design |
| `DOWNLOAD_RETRY_POLICY_ENABLED` | `yes` | default-on by design |
| `DOWNLOAD_CENTRAL_UX_ENABLED` | **`yes`** | contract default-off |
| `DOWNLOAD_COHORT` | `control` | baseline cohort |
| `DOWNLOAD_RESUME_REQUIRE_CONDITIONAL` | `no` | — |
| `DOWNLOAD_RESUME_MIN_SIGNED_URL_TTL_SECONDS` | `300` | — |
| `DOWNLOAD_RESUME_VALIDATED_HOSTS` | `[]` (empty → host derived from `BASE_LINKS_URL`) | resume host-gate; `DOWNLOAD_RESUME_VALIDATED_PATH_PREFIXES` defaults to `/$(REPO_NAME)/` |
| curl tunables | `CURL_CONNECT_TIMEOUT 64`, `CURL_MAX_TIME 600`, `CURL_RETRIES 12`, `CURL_RETRY_DELAY 12` | — |
| `DOWNLOAD_RECONCILE_MISSING_OUTPUTS` | `yes` | kill switch, D-005 pattern; `DOWNLOAD_RECONCILE_MAX_ROUNDS 3` |
| `DOWNLOAD_OFFLINE_HOLD_ENABLED` | `yes` | kill switch; `DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS 1800` (cumulative, active-time-only budget), `DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS 5`, `DOWNLOAD_OFFLINE_PROBE_TIMEOUT_SECONDS 5`, `DOWNLOAD_OFFLINE_HOLD_EVENT_INTERVAL_SECONDS 30` |
| `DOWNLOAD_CURL_STALL_DETECTION` | `yes` | kill switch; `DOWNLOAD_CURL_SPEED_LIMIT 1` bytes/s, `DOWNLOAD_CURL_SPEED_TIME 30` s (curl exits 28 on stall; lowered from 120 after 2026-07-30 field testing showed sub-2-minute outages went undetected); `DOWNLOAD_STALL_WATCHDOG_SECONDS 180` (poller observability backstop, 0 disables); `DOWNLOAD_STALL_PROBE_SECONDS 8` (fast offline detection: poller probes connectivity after this many seconds of zero byte growth and raises the offline-hold events without waiting for a curl exit; 0 disables) |
| `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` | **`no`** | capability handshake: a NEW Central injects `true`; gates emission of the backend-hold `retry_decision`/`session_state` events (silent recovery runs either way) |
| `DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES` | `yes` | recovery-cliff removal in checksum-verify; off restores the legacy `MAX_BAD_FILES_TO_REDOWNLOAD` count cliff |
| `DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES` / `DOWNLOAD_REDOWNLOAD_MAX_SECONDS` | `0` / `0` (unlimited) | opt-in budgets for the redownload pass; checked between files, paused time excluded from the seconds budget |
| `MAX_BAD_FILES_TO_REDOWNLOAD` (`InstlClientSync.yaml`) | `16` | with `DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES` on: a **warn threshold** (None/0 still means "verify only"); with it off: the legacy hard cap |

> **POC deviation (needs human decision before merge to main).** This is the POC `download-enhancements` branch: `DOWNLOAD_RESUME_ENABLED` and `DOWNLOAD_CENTRAL_UX_ENABLED` ship **`yes`**, whereas the rollout contract (Central decisions D-004/D-005/D-018, `rollout-plan.md`) requires every new behavior to be **default-off** and capability/cohort-gated. Per Central decision **D-022**, the new Central download UX is intentionally on-by-default on this branch and **must be re-gated (flip these back to `no`) before merge to main**. Any statement elsewhere that resume/UX is capability-gated is therefore *currently false on this branch*. Note also Central decision **D-023**: there is no "repairing" rendered Central state in v1 — checksum-mismatch repairs are folded into the "Retrying" state.

#### `ParallelRun` / `CurlWithInternalParallel` curl drivers (`pybatch/subprocessBatchCommands.py`)

The actual curl execution engine invoked by the `curlHelper`-generated commands.
- `_control_channel()` (line 309 / 720): lazy `get_global_channel()`, returning `None` if unavailable (so a non-curl `ParallelRun`, e.g. a copy, is never paused).
- `_run_with_pause_and_offline_hold(commands)` (line 322): the pause/offline-hold/network-retry/exit-33-fallback run loop (see Algorithms). `network_retry_budget = 12`.
- `_is_network_error(exit_code)` checks `utils.NETWORK_ERROR_CURL_EXIT_CODES`; `_can_run_fallback(exit_code)` (line 394) gates on `fallback_config_file` set and exit code in `fallback_exit_codes` (`(33,)`); `_run_fallback_after_curl_range_failure(exit_code)` (line 403) re-runs the fresh-restart fallback config. `CurlWithInternalParallel` carries its own (now richer) loop.
- **Connectivity-loss self-sufficiency (`CurlWithInternalParallel` only; a `TODO(external-parallel)` documents why `ParallelRun` keeps the older bounded-backoff behavior):**
  - `_run_config_with_recovery(config, pause_check, channel)` — the extracted re-run loop. On a network-class curl exit it emits a `retry_decision` (`reason="bulk_curl_network_error"`, gated on `_client_handles_backend_hold()`), then probes connectivity (`_probe_connectivity()`): when genuinely offline it holds (`_hold_until_online`) **without** burning the 12-attempt retry budget; when the host is reachable it falls back to the legacy bounded backoff (`min(2*attempt, 10)`s, budget 12).
  - `_probe_connectivity()` / `_probe_host_and_port()` / `_proxy_probe_target()` — DNS + TCP connect to the `BASE_LINKS_URL` host (fallback: first `url` in the curl config), or to the **proxy** endpoint when a proxy env var is set (curl transfers go through it; a direct probe on proxy-only networks would be a false offline). Fails **open** (assume online → legacy backoff) when no host is determinable or the proxy is unparsable.
  - `_hold_until_online(channel)` — pause-aware probe loop (probe every `DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS`); emits a throttled `paused/offline_no_network` session_state and a network-class `retry_decision` per failed probe (both gated on the capability), returns True on reconnect (`downloading/resuming_after_offline`) or False when the cumulative `DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS` budget is spent. The budget counts **active** hold time only — time blocked in `channel.wait_if_paused()` is subtracted. `_hold_seconds_used` is shared across holds in one command (a flapping network cannot hold forever).
  - `_reconcile_missing_outputs(...)` — after curl exit 0, verifies every `output` path in the config exists on disk (curl `--parallel` can exit 0 while individual transfers failed permanently); re-runs curl with a `.reconcile-NN` config containing only the missing entries (`_parse_curl_config_for_reconcile` / `_write_reconcile_config`), each rewritten by `_fresh_start_entry` (`continue-at = N` → `continue-at = -`, stale `If-*` conditional headers dropped — replaying a byte offset against a nonexistent output would silently corrupt the file). Up to `DOWNLOAD_RECONCILE_MAX_ROUNDS` rounds, each through `_run_config_with_recovery`; the checksum phase remains the final gate.
  - Stall watchdog (observability half) in `_run_download_progress_poller`: when total `.part` bytes have not grown for `DOWNLOAD_STALL_WATCHDOG_SECONDS` while curl is alive, log + emit a `downloading/stalled_no_progress` session_state; it never kills curl — enforcement is curl's own `speed-limit`/`speed-time` (see `curlHelper`), which makes a stalled transfer exit 28 and feed the loop above.
  - Fast offline detection (poller half, 2026-07-30 field finding): a mid-transfer link drop merely stalls curl's sockets — no exit code until `speed-time` — so the poller, which sees frozen bytes within a tick, probes connectivity (`_probe_connectivity`, proxy-aware, fails open) after `DOWNLOAD_STALL_PROBE_SECONDS` of zero growth. Probe-offline raises the throttled `paused/offline_no_network` hold events immediately while curl keeps running; flat-byte progress ticks and the `stalled_no_progress` backstop are suppressed while this hold is active (a non-paused session state would churn Central's backend-hold flag). The hold is released with `downloading/resuming_after_offline` only on real byte growth — probe success alone keeps the UI paused, because a wedged curl is speed-time-aborted and re-run by the recovery loop before real progress resumes. Emissions stay gated on the `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` handshake.
  - `_client_handles_backend_hold()` / `_download_config_flag` / `_download_config_int` — defensive config reads; all new event emission is additionally gated on `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` (default off) so an old Central sees exactly the legacy event stream while recovery stays silent.

### Key algorithms

**1. Config-file writing + offline-grace policy** (`_create_config_files_for_entries`, line 230)
1. Detect `has_resume_entries` across all entries.
2. Build `extra_retry_lines = ["retry-connrefused", "retry-max-time = <CURL_RETRY_MAX_TIME|90>"]`; append `retry-all-errors` **only** when there are no resume entries **and** `CURL_RETRY_ALL_ERRORS` is truthy. (Mutually exclusive with resume: `retry-all-errors` would retry the exit-33 request and defeat the range-failure fallback.)
   - **Stall detection (enforcement half, Workstream C):** when `DOWNLOAD_CURL_STALL_DETECTION` (default yes) is on, also append `speed-limit = <DOWNLOAD_CURL_SPEED_LIMIT|1>` and `speed-time = <DOWNLOAD_CURL_SPEED_TIME|120>` so a silent TCP stall exits 28 (network-class → retried in place, then the offline-hold loop) instead of hanging forever. Consistency rule: `retry-max-time` is bumped to at least `3 × speed-time` (never lowering an explicitly larger config value) — curl's retry window starts at the first attempt while a speed abort by definition fires only after `speed-time` seconds, so without the bump the promised in-place retry could never happen. Orthogonal to the `retry-all-errors`/resume exclusion; kill-switchable from config alone.
3. Choose header template (internal vs external parallel) and the number of config files (1 for internal; `min(len(urls), num_config_files)` for external), +1 if there are `_last` entries.
4. For each transfer: if `use_isolated_transfer_sections` (any per-transfer options) and the file already has URLs, write `next` + a fresh header. For a resume entry write `no-fail` + `continue-at = <resume_from_byte>`; for a fresh entry (unless `force_restart_from_zero`) write `no-fail` + `continue-at = -` (auto-resume any leftover `.part`). Then write any `header = "..."` lines, the `url`, and `output` path (through `fix_path`).
5. Externally, non-internal runs sort by size (smallest first, for early progress); internal runs preserve mixed sizes.
6. `_last` entries go to a popped final file; a `None` ("wait" barrier) is inserted before it unless internal-parallel or there were no other files.

**2. Plan orchestration** (`create_download_instructions`, line 461): partition fresh/resume × normal/last; for the resume path build four phases (`-fresh`, `-resume`, `-fresh-last`, `-resume-last`), the resume phases also getting a `-fallback` config built from `fresh_restart_entry()` clones; emit `CurlWithInternalParallel` per config file (internal) or `ParallelRun` per phase (external), with `fallback_exit_codes=(33,)`.

**3. Resume gate** (`resume_decision_for_download_item`, line 774): sequentially fail closed when — resume disabled, no bookkeeping dir, endpoint host not in `validated_hosts`, `.part` size ≤ 0, partial ≥ expected size, sidecar unusable/missing, expected identity (file_id/size/checksum) mismatch, source URL/object-key mismatch, signed-URL TTL insufficient, or (when `require_conditional`) no conditional validator. Otherwise returns `can_resume=True` with `resume_from_byte = received_bytes` and `conditional_headers`.

**4. Retry decision** (`decide_retry`, line 234): `next_attempt = previous_retry_count + 1`; `FAIL_TERMINAL` if the class is terminal/non-retryable or attempts exhausted; else compute backoff; action is `RESTART` if `restart_required`, `RESUME` if `resume_eligible`, otherwise `RESTART`.

**5. Adaptive concurrency** (`decide_next_concurrency`, line 106), in order: `user_override`→OVERRIDE (clamped); `adaptive` off→DISABLED (configured default or start); no prior summary→FRESH_START (start); zero attempts→KEEP; terminal failures or `restarts >= max(1, attempts//5)`→DECREASE; `retryableErrorRate >= backoff_threshold`→DECREASE; healthy (`errorRate <= grow_threshold` and `successes >= max(4, attempts//2)`) with headroom→INCREASE; else KEEP. Every move is `clamp`-bounded to `[min, max]`.

**6. Curl run loop** (`ParallelRun._run_with_pause_and_offline_hold`, line 322): run curl in parallel with `pause_check=channel.is_paused`; on `SystemExit`: code 0→return; `PAUSED_EXIT_CODE`→`wait_if_paused()`, reset `network_attempt`, retry (resumes from `.part`); fallback-eligible code→run exit-33 fresh-restart fallback; network-class curl error→`wait_if_paused()` then, while `network_retry_budget > 0`, decrement and back off `min(2*network_attempt, 10)` seconds via `channel.sleep_or_wake` (`try_now`/resume cuts it short) and retry; on budget exhaustion or non-network curl error raise `Exception(utils.get_curl_err_msg(code))`. *This describes the external-parallel driver; `CurlWithInternalParallel` (the shipped path) has since diverged — its loop additionally probes/holds offline, reconciles missing outputs, and emits capability-gated events (see the driver bullet list above and pybatch §3.2).*

### On-disk / data structures owned

Under `$(LOCAL_REPO_BOOKKEEPING_DIR)/download-state/`:
- `session.json` — one `DownloadSessionRecord` (`schemaVersion = 1`); fields include `sessionId`, `state` (`DownloadSessionState`), `createdAt`/`updatedAt`, repo version/revision, `plannedFiles`/`filesToDownload`/`bytesToDownload`, and the forward-compatible `reason`.
- `files/{file_id}.json` — one `DownloadFileRecord` each (atomic write); `source` (redacted URL, object key, etag, last-modified, content-length, version-id, signed-URL expiry), `target` (`finalPath`/`tempPath`/`sidecarPath`), `expected` (size/checksum/algorithm), `transfer` (state/receivedBytes/retryCount/lastFailureClass/lastUpdatedAt).
- `<final>.instl-<id>.part` — partial transfer artifacts (`id` = first 16 chars of the sha256 `file_id`); promoted via `os.replace` only after checksum verification.
- `session-summary.json` — observability snapshot (`schemaVersion = 1`); the cross-run channel written by `end_session` and read next run by `resolve_concurrency_from_config`.

In-memory shared state: control-channel `_GLOBAL_CHANNEL` singleton, observability `_active_observability` singleton, `downloadEvents._telemetry_enabled` flag, and `CUrlHelper.cached_internal_parallel` classvar.

Wire formats: `DOWNLOAD_EVENT <compact-json-sorted-keys>` and the legacy `DOWNLOAD_RETRY_DECISION <json>` log lines (INFO level, captured from stdout by Central); inbound one-line JSON commands on stdin.

### Invariants, edge cases, platform branches

- **Pause is cooperative.** The pause flag never interrupts curl mid-chunk; callers check `wait_if_paused()`/`sleep_or_wake()` between batches/sleeps, so `.part` and sidecar atomicity hold (`D-001`/`D-009`/`D-010`). `_run_event` is inverted (set == running).
- **Atomic writes.** Both `write_json_atomic` and observability's `_atomic_write_json` use tmp + `fsync` + `os.replace`; `.part` promotion is checksum-gated.
- **`retry-all-errors` vs resume are mutually exclusive** (see Algorithm 1) — a real correctness invariant, not just a style choice.
- **Privacy.** Events/retry lines drop a denylist; only redacted URLs and bare hosts flow out; signed-URL/auth material never reaches the channels.
- **Instrumentation never raises.** `record_*`, `update_session_state`, `emit_event`, and the control-channel callbacks all swallow exceptions.
- **`sessionId` filtering.** Control commands tagged with a non-matching `sessionId` are ignored; malformed/unknown commands are warned and dropped.
- **Forgiving config reads.** Missing/malformed config vars fall back to defaults so an old `InstlClient.yaml` keeps working; schema-version mismatches in `session-summary.json` are treated as "no data."
- **Platform branches.** `win32api` short-path handling in `fix_path` and `create_parallel_run_config_file`; curl-version gating of internal-parallel mode; `requests` import is optional.

### Targeted refactoring notes

1. **Duplicated (now diverging) curl run loop.** `ParallelRun._run_with_pause_and_offline_hold` and `CurlWithInternalParallel._run_config_with_recovery` share the pause budget, network-backoff, and exit-33 fallback logic (both lazily import `get_global_channel` identically) — and have now **drifted by design**: the internal-parallel driver gained offline-hold, output reconciliation, and stall detection that the external driver intentionally lacks (see the in-code `TODO(external-parallel)`: it drives many curl processes and only sees an aggregate exit code, so sharing is non-trivial; the checksum phase remains its completeness gate). Extract a shared `CurlRunController`/mixin parameterized by the run-callable and fallback strategy; have both delegate. *(High impact — behavior drifts between the two drivers.)*
2. **Duplicated privacy denylist.** `downloadEvents._DISALLOWED_EVENT_FIELDS` (line 128) and `downloadRetry._DISALLOWED_EVENT_FIELDS` (line 321) are near-identical (the events copy adds `localPath`/`downloadPath`). Define once in `downloadEvents` and import into `downloadRetry` to prevent silent divergence/leaks.
3. **Duplicated config-var accessors.** `downloadConcurrency` (`_bool_var`/`_str_var`/`_optional_positive_int`/`_optional_positive_float`, 286-328) vs `downloadCohort` (`_coerce_bool`/`_read_flag`/`_read_str`, 96-139) re-implement forgiving `config_vars` reading. Provide one shared adapter.
4. **Repeated ISO-UTC timestamp helper.** `downloadEvents._utc_now_iso` (136), `downloadObservability._utc_now_iso` (412), `downloadState.utc_now_iso` (52), and inline in `downloadRetry.RetryDecision.to_event` (228) all do `isoformat(timespec="seconds").replace("+00:00","Z")`. Centralize one helper.
5. **Duplicated atomic-JSON writers.** `downloadState.write_json_atomic` (430, indent=2/sort_keys, uuid temp name) vs `downloadObservability._atomic_write_json` (427, `tempfile.mkstemp`, compact). Unify into one utility parameterized by indent/sort.
6. **Long methods mixing config-format and orchestration.** `_create_config_files_for_entries` (230-367) and `create_download_instructions` (461-549) each own header policy, retry-line policy, file cycling, isolated sections, the last-file `wait` barrier, and parallel-vs-internal branching. Split per-entry config writing from plan orchestration for unit-testability.
7. **Duplicate Progress emission / leftover TODO.** In `create_download_instructions` the external-parallel path computes and appends the "Downloading with N processes" `Progress` message twice (lines 507-511, then 529-533); also a `# TODO: Move class someplace else` at line 501. Remove the duplicate `Progress` block and resolve the TODO.
8. **Scattered Windows path branching.** `curlHelper` imports `win32api` at module top (line 15) and again inside `fix_path` (line 206), with platform logic interleaved across `fix_path` and `create_parallel_run_config_file`. Isolate Windows path normalization behind a single helper imported once.
9. **Module-level mutable singletons.** `_GLOBAL_CHANNEL`, `_active_observability`, `_telemetry_enabled`, and `CUrlHelper.cached_internal_parallel` are process-wide mutable state requiring `reset_*` test hooks and making concurrent/test isolation fragile. Where feasible thread an explicit context object through the two choke points, keeping the singleton as a thin default.

Relevant files (all absolute):
`/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pyinstl/curlHelper.py`, `downloadFailures.py`, `downloadRetry.py`, `downloadControlChannel.py`, `downloadState.py`, `downloadObservability.py`, `downloadConcurrency.py`, `downloadEvents.py`, `downloadCohort.py` (same directory), and `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/subprocessBatchCommands.py`.

---

I now have all the grounding I need. Confirmed key bug locations: `log.wanging` at removeBatchCommands.py:241, missing f-prefix at baseClasses.py:429, `__hash__` over `self.__dict__.items()` at baseClasses.py:301-303, IsSymlink.repr_own_args at conditionalBatchCommands.py:116, duplicated imports at baseClasses.py:1-15. Let me write the section.

## PyBatch Command Objects

### 1. Overview and responsibilities

The `pybatch` package is instl's object model for deployment actions. Every concrete step — copy, remove, download, archive, chmod/chown, svn, registry, symlink, conditional, reporting, subprocess — is a subclass of `PythonBatchCommandBase` (`pybatch/baseClasses.py`). Each command object plays two roles simultaneously:

1. **Executor** — it runs the action at runtime through the context-manager + call protocol `__enter__` → `__call__` → `__exit__`.
2. **Serializer** — its `__repr__()` emits an *eval-able* Python source string, so an entire plan can be written out as a standalone "python batch" script (the `*-sync.py` / `*-copy.py` files) that re-imports `pybatch` and re-runs the same classes later.

`PythonBatchCommandAccum` (`pybatch/batchCommandAccum.py`) is the top-level container that groups commands into ordered named sections and renders the whole script via `__repr__`. The package `__init__.py` re-exports the entire command taxonomy and selects platform-specific classes at import time.

The three phases of the lifecycle:

- **Build** — `pyinstl` code does `accum.set_current_section('copy')` then `accum += Command(...)`. `add()` routes into the current section's `Stage`, building an in-memory tree of `child_batch_commands`. Nothing is persisted except configVars.
- **Serialize** — `repr(accum)` walks the tree, assigns each node a `prog_num`, wraps non-special sections in a `PythonBatchRuntime`, and emits eval-able Python to `__MAIN_OUT_FILE__`.
- **Run** — the emitted script re-instantiates the same classes; each runs through `__enter__`/`__call__`/`__exit__`.

### 2. Component breakdown

#### 2.1 `PythonBatchCommandBase` (`pybatch/baseClasses.py:23`)

Abstract base (`abc.ABC`) for all commands. It is a *god class* mixing execution, serialization, progress accounting, the stage stack, timing, error-report assembly, tree building, and equality/hashing.

**Class-level (process-global, shared by every command and thread):**
- `stage_stack: list` (`:47`) — push/pop on enter/exit; used to compute `major_stage_str()` / `stage` for error reports.
- `instance_counter`, `total_progress`, `running_progress` (`:48-50`) — global progress counters.
- `runtime_duration_by_progress: dict` (`:55`) — maps `runtime_progress_num` → seconds, consumed by `PatchPyBatchWithTimings`.
- `ignore_progress` (`:56`) — set True when commands run outside a python-batch file.
- `config_vars_for_repr` (`:57`) — set to the global `config_vars` only during `PythonBatchCommandAccum.__repr__()`, so `repr()` resolves configVar values.
- `essential`, `call__call__`, `is_context_manager`, `is_anonymous` — per-subclass flags (defaults at `:51-54`).
- `kwargs_defaults` (`:61-73`) — the declarative defaults dict (`own_progress_count`, `report_own_progress`, `ignore_all_errors`, `recursive`, `reply_config_var`, `prog_num`, `skip_action`, `suspend`, `skip_chmod`, `skip_chown`, `output_script`, …).

**Key methods:**
- `__init_subclass__(cls, essential=True, call__call__=True, is_context_manager=True, is_anonymous=False, kwargs_defaults=None, **kwargs)` (`:75`) — called once per subclass declaration. Sets the class flags and performs a **copy-on-write merge** of `kwargs_defaults`: it copies the parent's dict into a fresh dict (`:98-101`) before applying the subclass overrides, so a subclass cannot mutate the parent's defaults.
- `__init__(self, **kwargs)` (`:114`, abstract) — seeds every `kwargs_defaults` key as an instance attribute (`:118-120`), then initializes `exceptions_to_ignore` (seeded with `SkipActionException`), `child_batch_commands`, `doing`, `_error_dict`, `current_working_dir`, and `non_representative__dict__keys` (`:131`).
- `__enter__` (`:367`) — pushes self onto `stage_stack`, starts the timer, increments/outputs progress, captures cwd, calls the override hook `enter_self()`. On exception it routes to `__exit__`.
- `__exit__(exc_type, exc_val, exc_tb)` (`:386`) — exception policy: suppress if no exception or `ignore_all_errors`; else if `should_ignore__exit__exception()` matches, log and suppress; otherwise attach `raising_obj=self` to the exception (`:394-395`) so `PythonBatchRuntime.log_error` can find the originating command. Calls override hook `exit_self()`, records timing, honors `suspend`, warns on progress-count mismatch, pops the stage only when suppressing.
- `__call__(*args, **kwargs)` (`:211`, abstract) — base raises `SkipActionException` when `skip_action` is set; subclasses **must** call `PythonBatchCommandBase.__call__(self, ...)` first, then do the real work.
- `__repr__` (`:162`) + `repr_own_args(all_args)` (`:159`, override hook) + `repr_default_kwargs` (`:149`) + `named__init__param` / `unnamed__init__param` / `optional_named__init__param` (`:216-230`) — build the eval-able source. `optional_named__init__param` emits nothing when the value equals the default, keeping the script terse. All values are quoted/resolved via `utils.quoteme_raw_by_type(..., config_vars_for_repr)`.
- `add` / `__iadd__` / `sub_accum` (`:247-274`) — tree building. `add()` (`:251`) pattern-matches: a `PythonBatchCommandBase` whose `is_anonymous` is True has its children flattened into the parent (`:256-257`); a `str` is converted via `pybatch.EvalShellCommand(instructions, "")` (`:261`); anything iterable is recursed.
- `total_progress_count()` (`:232`), `is_essential()` (`:238`), `increment_progress()` (`:435`) — recursive progress accounting over `child_batch_commands`.
- `error_dict` / `error_dict_self` / `who_locks_file_error_dict` (`:208-365`) — assemble the JSON error report: instl/python version, `doing`, `major_stage`, dotted `stage` path, `instl_class` repr, representative `__dict__`, progress counter, cwd, OS description, optional minimal-version check, `CONFIG_VARS_FOR_ERROR_REPORT`, and exception/traceback fields. `who_locks_file_error_dict` is Windows-only (uses `__WHO_LOCKS_FILE_DLL_PATH__`) and is shaped to be passable to `shutil.rmtree(onerror=...)`.
- `representative_dict` / `__eq__` / `explain_diff` / `__hash__` (`:276-303`) — equality compares `__dict__` minus `non_representative__dict__keys`; `__hash__` hashes `tuple(sorted(self.__dict__.items()))`.

**Command-author API** (the contract every subclass implements): subclass with the appropriate `__init_subclass__` flags, implement `__init__` (record args only — *no work*), `repr_own_args(all_args)`, `progress_msg_self()`, and `__call__()`.

#### 2.2 `PythonBatchCommandAccum` (`pybatch/batchCommandAccum.py:30`)

Top-level accumulator; subclasses `PythonBatchCommandBase` but does no work (`__call__` is a no-op at `:214`).

- `section_order` (`:32`) — the ordered tuple of section names: `prepare, assign, begin, links, upload, pre, pre-sync, sync, post-sync, copy, post-copy, remove, admin, pre_doit, doit, post_doit, end, post, epilog`.
- `special_sections = ("assign", "epilog")` (`:35`) — rendered outside the `PythonBatchRuntime` wrapper.
- `sections: dict` (`:39`) — section name → `Stage` container.
- `set_current_section(section_name)` (`:52`) — validates against `section_order`, lazily creates the `Stage`.
- `add(child_commands)` (`:83`) — appends into the current section's `Stage`.
- `__repr__` (`:115`) — **the serializer** (algorithm below).
- `_python_opening_code` / `_python_closing_code` (`:87`, `:111`) — emit the prolog (imports, `sys.path.append`, `utils.set_acting_ids`, `from pybatch import *`, `PythonBatchCommandBase.total_progress`/`running_progress` globals, logger config) and the closing `# eof`.
- `camel_to_snake_case` (`:24`) + nested `_create_unique_obj_name` (`:120`) — generate the `with … as <name>:` variable names.

#### 2.3 `RunProcessBase` (`pybatch/subprocessBatchCommands.py:24`)

Abstract base for any command that spawns a subprocess. Parent of `CUrl`, `ShellCommand`, `Subprocess`/`ScriptCommand`/`ExternalPythonExec`, `Chmod`, `Chown`, `ChFlags`, `SVNClient`, ResHacker*, `FullACLForEveryone`.

- `kwargs_defaults`: `stderr_means_err=True`, `capture_stdout=False`, `out_file=None`, `detach=False`.
- `get_run_args(run_args)` (`:45`, abstract) — subclasses build the argv list.
- `__call__` (`:49`) — runs `subprocess.run(check=False, stderr=PIPE, shell=self.shell, bufsize=0)`; handles `detach` (Popen), `script`/`shell` single-string modes, `out_file`/`capture_stdout`. **stderr policy** (`:99-118`): if the process wrote to stderr and `stderr_means_err` and exit code was 0, the code is forced to **123**; `ignore_all_errors` forces returncode 0. Calls `handle_completed_process()`.
- `should_ignore__exit__exception` (`:133`) — additionally ignores `CalledProcessError` whose returncode is in `ignore_specific_exit_codes`.

`CUrl` (`:141`) builds a single-file curl argv (`--fail --raw --silent --show-error --connect-timeout --max-time --retry --retry-delay -o trg src`).

#### 2.4 `CurlWithInternalParallel` (`pybatch/subprocessBatchCommands.py:648`)

Runs the bulk download as a single `curl --config <file>` using curl's internal `--parallel`, parsing curl's progress lines and enforcing pause/resume + offline-retry through the stdin control channel. **Not** a `RunProcessBase` subclass — it drives `Popen` directly because it needs to interleave progress parsing and pause checks.

Constructor args: `curl_path`, `config_file_path`, `total_files_to_download`, `previously_downloaded_files`, `total_bytes_to_download`. `kwargs_defaults`: `fallback_config_file_path=None`, `fallback_exit_codes=()`.

- `bytes_to_string` / `string_to_bytes` (`:669`, `:692`) — human-readable byte conversions; `string_to_bytes` is intentionally fail-safe (returns 0, never raises, so progress accounting can't break curl).
- `__call__` — Windows long-path workaround via `win32api.GetShortPathName`; obtains pause channel via lazy `_control_channel()`; initializes the cumulative progress carry-over state `_files_high_water`, `_bytes_baseline`, `_bytes_high_water` and the shared offline-hold budget `_hold_seconds_used`; then delegates to `_run_config_with_recovery` (the pause/offline-hold/backoff re-run loop) and, on exit 0, `_reconcile_missing_outputs` (re-download entries whose expected `output` file is missing — curl `--parallel` can exit 0 with permanently failed transfers). See the Download Subsystem section for the full offline-hold / reconciliation / stall-watchdog method inventory and the `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` event gate.
- `_run_curl_once(config_file_path_fixed, pause_check)` (`:818`) — one curl pass. `Popen([...curl, "--config", path], stdout=PIPE, stderr=STDOUT, start_new_session=True, bufsize=1)`. `start_new_session=True` makes curl a process-group leader so `terminate_process()`'s `os.killpg()` can stop it on pause. Parses each progress line with the verbose regex (`:836`) capturing `DL_percent, Dled, Xfers, Live, Speed, …`. Returns `(returncode, paused)`.

#### 2.5 `CheckDownloadFolderChecksum` (`pybatch/info_mapBatchCommands.py:366`)

`DBManager + PythonBatchCommandBase`. Verifies every downloaded file's checksum against the info_map DB table, promotes verified temp files, and re-downloads bad/missing files.

- `__call__` — iterates `self.info_map_table.get_download_items(what="file")`; honors `BREAK_BEFORE_CHECKSUM` break-file; for each item: if the final file already matches checksum, records `ALREADY_VALID` and continues (warm-cache hit, not counted as transferred); if the temp file exists and matches, `promote_verified_temp_file` (os.replace) and records `VERIFIED` + SUCCESS observability; on mismatch or missing temp, increments `num_bad_files`, queues into `to redownload`, and emits a retry decision (`resume_eligible=False` — restart required).
- **Recovery-cliff removal (`DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES`, default on):** `max_bad_files_to_redownload` is reinterpreted as a **warn threshold** — the verify loop counts ALL bad/missing files (warning once at the crossing; `_bad_file_progress` throttles per-file bad lines past the threshold so a mass failure doesn't flood the log, while bookkeeping and per-file retry_decision events stay unthrottled) and the redownload pass ALWAYS runs when enabled (`None`/0 still means "verify only" — the in-process `check-checksum` command and old generated scripts rely on that). With the kill switch off, the legacy count cliff is restored exactly: the verify loop breaks at cap+1 and skips redownload entirely (which used to fail e.g. 33 missing files with zero recovery attempts at a cap of 32). The final `Bad checksum for N files / Missing M files` `ValueError` format is unchanged — Central regexes on it.
- `re_download_bad_files` / `_redownload_one_file` — pause-aware per-file bounded retry via `downloadControlChannel` and `downloadRetry`. With the flag on, the pass is bounded by `_RedownloadBudget` (`DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES` / `DOWNLOAD_REDOWNLOAD_MAX_SECONDS`, both default 0 = unlimited — the legacy pass always completed every attempted file, so a non-zero default would abandon slow-network recoveries that used to succeed) instead of a count cliff: the budget is checked **between** files (a file in flight is never abandoned), files beyond an exhausted budget stay counted as bad, and the seconds budget measures **active** time only — `_PauseTrackingChannel` (a delegating wrapper around the control channel) measures time blocked in `wait_if_paused` so an outage hold never burns the recovery budget. Tests: `pyinstl/test/test_redownloadBudget.py`.

This class imports ~8 `pyinstl.download*` modules (downloadState/downloadFailures/downloadRetry/downloadObservability/downloadEvents/downloadCohort/downloadControlChannel), making it the de-facto download orchestrator (see refactor notes).

#### 2.6 Conditionals (`pybatch/conditionalBatchCommands.py`)

- `If(condition, if_true=None, if_false=None)` (`:10`) — `__call__` (`:34`): if `condition` is a `str` it is **`eval`'d** (`:38`); the result is called if callable else coerced to bool; the matching branch (which may be a single object or an iterable) is run. Branch objects that are context managers get `own_progress_count=0` and run as `with obj as it: it()` (`:61-64`). `if_true`/`if_false` are added to `non_representative__dict__keys` to avoid serialization errors.
- `IsFile` / `IsDir` / `IsSymlink` / `IsEq` / `IsNotEq` / `IsConfigVarEq` / `IsConfigVarNotEq` / `IsEnvironVarEq` / `IsEnvironVarNotEq` / `IsConfigVarDefined` (`:69-281`) — **plain `object` predicates** (not `PythonBatchCommandBase`), each implementing `__call__() -> bool`, `__repr__`, `__eq__`. `IsConfigVarEq` returns True for an undefined var with no default (`:193`).
- `ForInConfigVar(list_var_name, target_var_name, call_str, resolve_indicator='@')` (`:284`) — `__call__` (`:308`) iterates the configVar list; per value it `push_scope_context()` + `push_resolve_indicator('@')`, resolves `call_str`, builds a command via `pybatch.EvalShellCommand`, sets `report_own_progress=False`, and runs it.

#### 2.7 Reporting / runtime wrappers (`pybatch/reportingBatchCommands.py`)

- `AnonymousAccum` (`:23`, `is_anonymous=True`, `call__call__=False`, `is_context_manager=False`) — pure container; `add()` flattens its children into the parent.
- `Stage` (`:78`, `call__call__=False`, `is_context_manager=True`) — section container; `stage_str()` feeds the error-report stage path; `__exit__` (`:107`) stores `__TIMING_<SECTION>_SEC__` configVar with `command_time_sec`.
- `PythonBatchRuntime(name)` (`:306`, `call__call__=False`, `is_context_manager=True`) — wraps the whole run. `__exit__` (`:311`): on exception calls `log_error`; logs total run time; pops the stage. `log_error` (`:329`) finds the originating command via `exc_val.raising_obj` and dumps `error_dict(...)` as JSON to the log.
- `Echo` / `Print` / `Remark` / `Progress` / `ConfigVarAssign` / `PythonDoSomething` / `EnvironVarAssign` — most have `own_progress_count=0`; `Echo`/`Remark`/`ConfigVarAssign` emit literal source rather than runtime actions. `EnvironVarAssign` (`:608`) subclasses `PythonDoSomething` to emit `os.environ[...] = ...` source.
- `PatchPyBatchWithTimings(out_file)` (`:628`) — `__call__` (`:642`) post-processes the emitted script, appending per-line timing comments from `runtime_duration_by_progress`, producing the `.timings.py` twin.

#### 2.8 Copy engine — `RsyncClone` (`pybatch/copyBatchCommands.py:23`)

Base copy engine mimicking rsync; parent of all `Copy*`/`Move*`/`Rename`/`CopyBundle`/`CopyGlobToDir`. Options documented in `options_doc_str` (`:28`). Maintains **class-level mutable global state**: `__global_ignore_patterns`, `__global_no_hard_link_patterns`, `__global_avoid_copy_markers`, `__global_no_flags_patterns` (`:45-48`) with `add_global_*` classmethods (`:50-64`). Per-instance it merges global + local patterns into `__all_*` lists (`:114-116`). Tracks `statistics` (defaultdict), `last_src`/`last_dst`/`last_step` for `error_dict_self`, and `hard_links_failed` (latches once so it stops retrying hard links). `CUrl`'s sibling copy commands (`CopyDirToDir`, `CopyFileToFile`, etc.) are re-exported from `__init__.py:7-8`.

#### 2.9 Removal taxonomy (`pybatch/removeBatchCommands.py`)

`RmFile`, `RmDir`, `RmFileOrDir`, `RmGlob`, `RmGlobs`, `RemoveEmptyFolders`, `RmDirContents` — all default `resolve_path=True`, ignore `FileNotFoundError`, and retry once after a `FixAllPermissions`. `RmFile.__call__` (`:40`) is a two-attempt unlink: on first `PermissionError`, if the path is a dir it delegates to `RmDir`, otherwise runs `FixAllPermissions` and retries; second failure calls `who_locks_file_error_dict` and re-raises. On macOS with `output_script` set, removals append `rm -f` lines to a post-install shell script instead of removing immediately (`:135`).

#### 2.10 Filesystem primitives (`pybatch/fileSystemBatchCommands.py`)

`MakeDir`, `Chmod`, `Chown`, `ChFlags`, `Cd`, `Touch`, `SplitFile`, `Glober`, `FixAllPermissions`, `Unlock`. Heavy `sys.platform` branching: `Chmod.symbolic_mode_re` differs darwin vs win32 (`:475-478`); `parse_symbolic_mode_mac` / `parse_symbolic_mode_win` (the latter manipulates win32security DACLs); `ChFlags.flags_dict` keyed by platform. `MakeDir` retries on `PermissionError`/`FileExistsError` and removes obstacles. `AdvisoryFileLock` (`call__call__=False`) is a print-debug stub commented out of `__init__.py:26`.

#### 2.11 Archive commands (`pybatch/wtarBatchCommands.py`)

`Wtar` creates split bzip2 PAX tars with a `total_checksum` pax header for idempotent skip; `Wtar.check_tarinfo` normalizes uid/gid/uname and adds per-file checksum+mtime pax headers. `Unwtar.unwtar_a_file` reads split parts via `utils.MultiFileReader`, compares `total_checksum`, and `RmDir`s before `extractall`. `Wzip`/`Unwzip` are zlib single-file; `ZipFlat`/`UnZip` are stdlib zip.

#### 2.12 SVN, info_map admin, platform commands

- `pybatch/svnBatchCommands.py` — `SVNClient` (RunProcessBase) builds svn argv; `SVNLastRepoRev.handle_completed_process` regex-extracts the revision into a `reply_config_var`; `SVNInfoReader` (DBManager) loads info-map/props/sizes into the DB table.
- `pybatch/info_mapBatchCommands.py` — DBManager-backed: `CreateSyncFolders`, `SetExecPermissionsInSyncFolder`, `PrepareDownloadTempFiles`, `ReportDownloadStarted`, `InfoMapFullWriter`/`InfoMapSplitWriter`, `IndexYamlReader`, `ShortIndexYamlCreator`, `CopySpecificRepoRev`, `CreateRepoRevFile`, `SetBaseRevision`. Module-level free helpers (`_save_resume_sidecar*`, `_emit_retry_decision`, `_emit_download_started`, `_config_var_*`).
- `pybatch/POSIXBatchCommands.py` / `MacOnlyBatchCommands.py` / `WinOnlyBatchCommands.py` — POSIX `CreateSymlink`/`RmSymlink`/`SymlinkToSymlinkFile`/`SymlinkFileToSymlink` (cloud-safe symlink round-tripping); Mac `MacDock`; Win `WinShortcut`, `*Registry*`, `ResHacker*`, `FullACLForEveryone`. On non-Windows, the Win classes are aliased to `PythonBatchCommandDummy` stubs (`__init__.py:50-77`).
- `pybatch/new_batchCommands.py` — `CopyDirToDirEx` (alternative copy composing `CopyDirToDir + Chown + Chmod + Unlock`); wildcard-imported by `__init__.py:82`.

#### 2.13 `EvalShellCommand` (`pybatch/__init__.py:85`)

`EvalShellCommand(action_str, message, python_batch_names=None, raise_on_error=False) -> PythonBatchCommandBase`. Bridges index.yaml action strings to command objects: it **`eval()`s** the string into a command; if that yields a non-command or raises `SyntaxError`/`TypeError`/`NameError`, it falls back to a `ShellCommand`. If a fallback's leading token matches a known pybatch class name, it warns (or raises when `raise_on_error`).

### 3. Key algorithms

#### 3.1 Script serialization — `PythonBatchCommandAccum.__repr__` (`batchCommandAccum.py:115`)

1. Set `PythonBatchCommandBase.config_vars_for_repr = config_vars` so nested `repr()`s resolve configVars (`:118`).
2. Append `PatchPyBatchWithTimings(__MAIN_OUT_FILE__)` to the `epilog` section (`:170-171`).
3. Recompute `total_progress` = sum of each section's `total_progress_count()` + 1 for the `PythonBatchRuntime` (`:173-177`).
4. Build the prolog (`_python_opening_code`), then render the `assign` special section into it.
5. Create a `PythonBatchRuntime(__MAIN_COMMAND__)` and `+=` every non-special section in `section_order` into it; render via `_repr_helper`.
6. Render the `epilog` section, append `_python_closing_code`.
7. Resolve configVars in the main body and replace unresolved with native-var patterns (`:201-202`); concatenate prolog + body + epilog.
8. Reset `config_vars_for_repr = None`.

`_repr_helper(batch_items, io_str, indent)` (`:134`) recurses lists, then for a single node: increments `running_progress_count` by `own_progress_count`, assigns `node.prog_num`, and emits source by matching `(call__call__, is_context_manager)`:
- `(False, False)` → bare `repr(node)` line (e.g. `ConfigVarAssign(...)`).
- `(False, True)` → `with repr(node):` (a `Stage`/`PythonBatchRuntime`), then children at +1 indent (or `pass`).
- `(True, False)` → `repr(node)()` line, children at same indent.
- `(True, True)` → `with repr(node) as <unique_name>:` then `<unique_name>()` and children at +1 indent.

#### 3.2 Bulk-download re-run loop (`CurlWithInternalParallel.__call__` → `_run_config_with_recovery`, `subprocessBatchCommands.py`)

```
files_high_water = 0; bytes_baseline = 0; bytes_high_water = 0
hold_seconds_used = 0.0                       # ONE overall offline-hold budget for the whole call
return_code = _run_config_with_recovery(config, pause_check, channel)
if return_code == 0:
    return_code = _reconcile_missing_outputs(pause_check, channel)   # Workstream A: don't trust exit 0
if _can_run_fallback(return_code): _run_fallback_after_curl_range_failure(return_code)
increment_progress()

_run_config_with_recovery(config, pause_check, channel):
    network_retry_budget = 12; network_attempt = 0
    loop forever:
        return_code, paused = _run_curl_once(config, pause_check)     # one curl pass
        if paused:
            channel.wait_if_paused(); network_attempt = 0; continue   # resume via continue-at
        if return_code != 0 and is_network_error(return_code):
            channel.wait_if_paused()
            network_attempt += 1
            emit retry_decision(reason="bulk_curl_network_error")     # only if client declared
                                                                      # DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD
            if DOWNLOAD_OFFLINE_HOLD_ENABLED and not _probe_connectivity():
                # genuinely offline: hold (does NOT consume the retry budget)
                if _hold_until_online(channel): continue              # back online: re-run
                return return_code                                    # hold timeout expired
            if network_retry_budget > 0:                              # reachable host: legacy backoff
                network_retry_budget -= 1
                backoff = min(2*network_attempt, 10)
                channel.sleep_or_wake(backoff)                        # resume/try_now cuts short
                continue
            log "retries exhausted, continuing"  # never raises; downstream checksum redownloads
        return return_code
```

`_reconcile_missing_outputs` loops up to `DOWNLOAD_RECONCILE_MAX_ROUNDS` (default 3): parse the original config into header + per-download entries; entries whose `output` path is missing on disk are rewritten as fresh-start (`continue-at = -`, stale `If-*` headers dropped) into a `.reconcile-NN` config that re-runs through `_run_config_with_recovery`. Terminal behavior is unchanged — after rounds/holds are exhausted it logs and continues; the checksum phase remains the final gate. All the new session_state/retry_decision emission is gated on `DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD` (default off).

**Progress carry-over invariant** (`_run_curl_once`, `:872-914`): because each re-run re-launches curl (Xfers/Dled restart at 0):
- **Files**: monotonic only — `downloaded_files = previously_downloaded_files + (Xfers - Live)`, clamped up via `_files_high_water`, capped at `total_files_to_download`. No per-run baseline (a re-run re-counts finished files, so the value trends back to the true total on its own).
- **Bytes**: cumulative — with curl `continue-at`, a run's `Dled` is only the *new* bytes, so `cumulative = _bytes_baseline + current_dled`, clamped via `_bytes_high_water`, capped at total. When the run ends/pauses, the run's final `Dled` is folded into `_bytes_baseline` (`:914`).

`ParallelRun._run_with_pause_and_offline_hold` (`:322`) implements a near-identical loop for the multi-process parallel runner; the pause check is only wired when the commands are curl (`_is_curl_command`, `:400`) so a pause can't affect e.g. a copy parallel-run.

#### 3.3 `kwargs_defaults` copy-on-write merge (`__init_subclass__`, `:95-103`)

At class-definition time each subclass gets a *fresh* dict copied from the parent's `kwargs_defaults`, then its own overrides are applied. This prevents a subclass declaring `kwargs_defaults={...}` from mutating a sibling's or the parent's defaults (the naive `parent.update(...)` bug it explicitly avoids).

### 4. Data structures and on-disk formats owned by this subsystem

- **The emitted python-batch script** at `__MAIN_OUT_FILE__` (e.g. `*-sync.py`, `*-copy.py`) and its `.timings.py` twin (written by `PatchPyBatchWithTimings`).
- **JSON error report** logged by `PythonBatchRuntime.log_error` — keys include `instl_version`, `python_version`, `doing`, `major_stage`, `stage` (dotted), `instl_class`, `obj__dict__`, `progress_counter`, `current_working_dir`, `operating_system`, plus `exception_type`/`exception_str`/`batch_file`/`batch_line` and (Windows) `locked_file_info`.
- **Download temp files** and per-file **resume sidecar JSON** (downloadState, written only when `DOWNLOAD_RESUME_ENABLED`).
- **Filesystem artifacts** created/copied/removed by the fs/copy/wtar commands.

This subsystem does **not** own the SQLite info_map DB (`svn_item_t` / items table); that belongs to the `db` subsystem and is reached via the `DBManager` mixin (`self.info_map_table`, `self.items_table`, `self.db`).

### 5. Invariants, edge cases, platform branches

- **Repr/init synchrony invariant**: `__init__` must record exactly the args that `repr_own_args` emits, because the plan round-trips through `repr()` → `eval()`. A mismatch silently produces a script that re-instantiates the wrong object.
- **`__call__` chaining**: every subclass must call `PythonBatchCommandBase.__call__(self, ...)` first so `skip_action` → `SkipActionException` is honored (and the base counts as the skip gate).
- **Progress is global/non-reentrant**: `running_progress`, `total_progress`, `stage_stack`, `runtime_duration_by_progress`, `config_vars_for_repr` are class attributes. `RunInThread` runs commands in threads while `__enter__`/`__exit__` mutate the shared `stage_stack`/`running_progress` — not thread-safe.
- **stderr=error**: `RunProcessBase` turns any stderr output with exit 0 into exit **123** unless `stderr_means_err=False` or `ignore_all_errors`.
- **Anonymous flattening**: `is_anonymous` containers (`AnonymousAccum`) never appear in the output; only their children do.
- **Special sections** (`assign`, `epilog`) render outside the `PythonBatchRuntime` wrapper.
- **Platform branches**: `Chmod`/`Chown`/`ChFlags` switch hard on `sys.platform` (darwin vs win32; linux often a no-op); Win-only classes alias to `PythonBatchCommandDummy` on POSIX; macOS `output_script` mode reroutes removals/shell commands into a post-install `.command` script; `CurlWithInternalParallel` uses `win32api.GetShortPathName` for curl on Windows.

### 6. Refactoring notes (this subsystem)

1. **God base class** — `baseClasses.py` `PythonBatchCommandBase` mixes execution, serialization, progress, staging, error-report assembly, tree building, and equality. Any change ripples to every command. Split into focused collaborators: a `Serializable` (repr) mixin, a `ProgressReporter`, a `StageContext`, an `ErrorReportBuilder`, and a `CommandTree`, leaving the base a thin lifecycle shell.
2. **Class-level mutable global state** (`baseClasses.py:47-57`) — `stage_stack`, `running_progress`, `total_progress`, etc. are process-global and mutated during enter/exit, which breaks `RunInThread` (subprocessBatchCommands.py:460) reentrancy. Move run-scoped state into an explicit run/session object (or thread-local) passed down the tree.
3. **repr→eval round-trip is security-sensitive and fragile** — `__init__.py:85` `EvalShellCommand` and `conditionalBatchCommands.py:38` `If.__call__` both `eval()` arbitrary strings from index.yaml; serialization requires `__init__`/`repr` to stay in perfect sync. Introduce a structured (dataclass/JSON) IR + registry-based deserializer; restrict `EvalShellCommand` to a whitelist of registered command names.
4. **Duplicated pause/offline/network-retry loop** — `ParallelRun._run_with_pause_and_offline_hold` (`subprocessBatchCommands.py:322`) and `CurlWithInternalParallel._run_config_with_recovery` plus their `_control_channel`/`_is_network_error`/`_can_run_fallback`/`_run_fallback_after_curl_range_failure` started as near-identical copies and have now diverged: the internal driver added offline-hold/probing, output reconciliation, and stall handling that the external one deliberately lacks (in-code `TODO(external-parallel)`). Extract a shared `CurlRunLoop`/`DownloadRunner` helper holding pause-check, backoff budget, and fallback logic.
5. **Download orchestration buried in a batch command** — `CheckDownloadFolderChecksum` (`info_mapBatchCommands.py:366`) imports ~8 `pyinstl.download*` modules and embeds resume/retry/telemetry/control-channel logic. Move the redownload/retry orchestration into a dedicated `pyinstl` download service and have the command call a small interface, keeping it focused on checksum verification.
6. **Duplicated copy path** — `new_batchCommands.py` `CopyDirToDirEx.can_copy_be_avoided` reimplements ignore/avoid-copy/chown logic that `RsyncClone` already has and contains real bugs (`next()` on a list, `src_marker_checksum` referenced before assignment). Delete it or rebuild as a thin wrapper over `CopyDirToDir + Chown + Chmod + Unlock`.
7. **Heavy platform branching inside single classes** — `fileSystemBatchCommands.py` `Chmod`/`Chown`/`ChFlags` interleave darwin/win32 logic in method bodies and class-body `if sys.platform`; `ExternalPythonExec.get_run_args:561` hardcodes `python3.12`/`py -3.12`. Extract per-OS strategy objects (`PermissionBackend`, `FlagBackend`) and move the import-time platform selection in `__init__.py` into an explicit registry.
8. **Confirmed latent bugs/typos**:
   - `removeBatchCommands.py:241` — `log.wanging(...)` (typo) will raise `AttributeError` when `RmGlob` is called with `pattern=None`, instead of warning. Fix to `log.warning`.
   - `baseClasses.py:429` — the f-string is missing its leading `f`: `full_message += "; {exception_obj.__class__.__name__}: {exception_obj}"` emits literal braces. Add the `f` prefix.
   - `baseClasses.py:301-303` — `__hash__` over `tuple(sorted(self.__dict__.items()))` will raise on unhashable attribute values and includes non-representative keys; base it on `representative_dict` with hashable normalization, or drop `__hash__`.
   - `conditionalBatchCommands.py:116` — `IsSymlink` defines `repr_own_args` instead of `__repr__`; since it is a plain `object` (not a command), that method is never called, so `repr(IsSymlink(...))` falls back to the default object repr and breaks serialization of `If(IsSymlink(...))`. Give the `Is*` predicates a small common base with a real `__repr__`.
9. **Dead/disabled code** — `wtarBatchCommands.py` `can_skip_unwtar` (retVal forced False), `fileSystemBatchCommands.py` `AdvisoryFileLock` (print-debug stub, commented out of `__init__.py:26`), and the commented Dummy block in `new_batchCommands.py`. Remove or finish them.
10. **Duplicated imports** — `baseClasses.py:1-15` imports `abc`, `inspect`, `sys`, `time`, `contextmanager`, and `typing` twice (merge cruft). Deduplicate.

Relevant files (all absolute):
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/baseClasses.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/batchCommandAccum.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/__init__.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/subprocessBatchCommands.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/conditionalBatchCommands.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/reportingBatchCommands.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/info_mapBatchCommands.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/copyBatchCommands.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/removeBatchCommands.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/fileSystemBatchCommands.py`
- `/Users/matantiram/Library/CloudStorage/OneDrive-Waves/Documents/projects/instl/pybatch/wtarBatchCommands.py`

---

I have all the details I need. Writing the section now.

## ConfigVar System

### Purpose & Scope

The `configVar` package is the configuration-variable engine that underpins every other subsystem in `instl`. It models each config variable as a multi-valued, lazily-resolved object (`ConfigVar`), held in a scoped stack of dicts (`ConfigVarStack`), exposes a single process-wide global `config_vars` instance, implements the `$(NAME<params>[index])` resolution mini-language via a hand-written state-machine parser (`var_parse_imp`), and loads variable definitions from YAML files (`ConfigVarYamlReader`). State lives entirely in memory; this subsystem performs no persistence of its own — it is the runtime source of truth, fed at startup by YAML config files, `__include__` chains, and `os.environ`.

Package layout (`configVar/`):
- `configVarOne.py` — the `ConfigVar` value object plus module helpers.
- `configVarStack.py` — the `ConfigVarStack` container/resolver and the global `config_vars`.
- `configVarParser.py` — the `$()` mini-language parser (`var_parse_imp`).
- `configVarYamlReader.py` — YAML loading of variable definitions.
- `accessors.py` — *(modernization)* typed, documented accessor helpers over the hottest read keys (OS identity, main input/output file, run-batch flag, repo-revs, instl version), the first `config_vars` containment seam (REFACTORING.md W7 / ARCHITECTURE.md Theme 2).
- `__init__.py` — public re-exports and the `var_stack` backward-compat alias.

The public surface re-exported from `configVar/__init__.py`:
```python
from .configVarStack import config_vars
from .configVarStack import private_config_vars
from .configVarYamlReader import ConfigVarYamlReader, eval_conditional, smart_resolve_yaml
from .accessors import (current_os, current_os_names, is_current_os,
                        main_input_file_path, main_input_file_str,
                        main_out_file_path, run_batch, repo_rev,
                        target_repo_rev, instl_version, target_os, target_os_names)
var_stack = config_vars  # backward compatibility for scripts run via "exec"
```

> **`configVar/accessors.py` seam (modernization).** These helpers are a thin, typed wrapper over
> the handful of most-read `config_vars` keys. Each documents the type/shape its key resolves to and
> takes an optional `cv` parameter that defaults to the global stack, so a future injected stack
> (a `RunContext`) can be threaded through without touching call sites again. They are
> behavior-preserving (still read the global default). Call sites already routed through them include
> `instlDoIt`, `instlMisc`, `instlInstanceBase`, `instlClientCopy`, `admin/_info.py`,
> `admin/_verify.py`, and `client/_core.py`/`_require.py`/`_install_items.py`. The remaining direct
> `config_vars[...]` hotspots are tracked as W6/W7 follow-ups.

---

### Component Breakdown

#### `ConfigVar` (configVar/configVarOne.py)

Represents one configuration variable holding zero or more **string** values. It behaves polymorphically as str/list/int/float/bool/path depending on the calling context. Resolution of each value is lazy and delegated to the owner stack.

Key attributes (declared via `__slots__` — flat fixed layout, no `__dict__`):
- `owner` — the `ConfigVarStack` that holds this var and performs resolution.
- `name: str` — the key under which the owner keeps it (used mainly for debugging and for path-semantics detection).
- `values: List[str]` — the only owned state; always a flat list of strings (never hierarchical).
- `callback_when_value_is_set` / `callback_when_value_is_get` — per-value set/get hooks.
- `dynamic: bool` — flips `True` when a custom get-callback is installed.

Constructor: `__init__(self, owner, name: str, *values, callback_when_value_is_set=None, callback_when_value_is_get=None)`. It calls `set_callback_when_value_is_get(...)` then `set_callback_when_value_is_set(...)`, initializes `values = list()`, and `self.extend(values)` (which flattens).

Important methods:
- `set_callback_when_value_is_get(cb)` — if `cb is None`, defaults the get-callback to `self.owner.resolve_str`; otherwise installs `cb` and sets `self.dynamic = True`. **This is the tight coupling point: a `ConfigVar` cannot resolve without an owner exposing `resolve_str`/`resolve_str_to_list`.**
- `set_callback_when_value_is_set(cb)` — defaults to a no-op `_do_nothing_callback_when_value_is_set`.
- `resolve_values() -> List` — `[self.callback_when_value_is_get(val) for val in self.values]`.
- `join(sep) -> str` — joins resolved values with `sep`.
- `__str__()` — returns `None` if the sole value is `None`, else `self.join(sep='')`. The primary single-value resolution path. `str()` is a convenience wrapper for `str(self)`.
- `__iter__()` — for each raw value: if `dynamic`, runs the get-callback first; then yields from `self.owner.resolve_str_to_list(val)`. **This is the list-expansion semantic — a var whose value is `"$(OTHER)"` expands into OTHER's list.** `list()`/`set()` wrap `iter(self)`.
- `__getitem__(index)` — resolves a single raw value by index through the get-callback.
- `__contains__(val)` — membership against `resolve_values()`.
- `__len__()` — number of raw values.
- `__bool__()` — `True` only when there is **exactly one** value and `something_to_bool(values[0], False)` reads it truthy. (Empty or multi-valued vars are falsy.)
- `__int__()` / `__float__()` — `utils.str_to_int` / `utils.str_to_float` of `self.join(sep='')`.
- `is_path_var()` — `name.endswith("_DIR") or name.endswith("_PATH")`.
- `__fspath__()` — implements `os.PathLike`: `os.fspath(PurePath(self.str()))`.
- `Path(resolve: bool=False) -> Optional[Path]` — returns `None` if no truthy first value; with `resolve=True` does `os.path.expandvars(self.str())` then `Path(...).resolve()`, else `Path(self.str())`. `PurePath()` similar without resolution.
- `append(value)` — `None` is ignored; otherwise `str(value)` appended and the set-callback fired.
- `extend(values)` — `match`-dispatches: `str|int|float|None` → single `append`; `collections.abc.Sequence` → recurse per item (flatten nested lists); `os.PathLike` → `append(os.fspath(values))`; anything else → `TypeError`.
- `clear()` — empties `values`.
- `raw(join_sep: Optional[str] = "")` — returns **UNresolved** values: the raw list if `join_sep is None`, else the joined raw string.

Module helpers in the same file:
- `something_to_bool(something, default=False)` — `match` on `bool`/`0|0.0`/`int|float`/`str` (`"yes"|"true"|"y"|"t"|"1"` → True, `"no"|"false"|"n"|"f"|"0"` → False). Backs `__bool__`.
- `value_is_set(name, value)` / `value_is_get(value)` — no-op debug stubs whose docstrings describe how to hand-wire set/get callbacks on a specific var in `__init__`. Dead in production.

#### `ConfigVarStack` (configVar/configVarStack.py)

A stack (list) of dicts of `ConfigVar`s implementing scoping/overrides, and simultaneously the resolution engine and a mapping container. Its docstring documents that resolved-string caching was removed in version 2.1.6.0 (last cached version 2.1.5.5), because params-resolution constantly invalidated the cache and dynamic vars cannot be cached; the surviving optimization is the **simple-resolve fast path** (skip parsing when no `$` is present, ~60% of resolve time saved on large installs).

Attributes (`__init__`):
- `var_list: List[Dict] = [dict()]` — the stack; level `[-1]` is the innermost/top scope; lookups iterate `reversed(self.var_list)` so inner scopes shadow outer.
- `resolve_counter` / `simple_resolve_counter: int` — instrumentation.
- `resolve_time: float = 0.0` — **dead**; all timing is commented out, so it stays 0.0.
- `resolve_indicator = '$'` — the trigger character, swappable via `push_resolve_indicator`.

Mapping protocol:
- `__getitem__(key) -> ConfigVar` — `reversed` scan, inner wins; `KeyError` if absent, `TypeError` if key is non-str.
- `__setitem__(key, *values)` — **always writes to the top level** `var_list[-1]`. If a var of that name already exists on the top level its values are `clear()`ed then re-extended; a same-named var on a lower level is left untouched (override semantic).
- `__delitem__(key)` — deletes only the innermost occurrence.
- `__contains__(key)` — True if present on any level.
- `defined(key)` — True only if the var exists **and** `any(list(var_obj))` (has values that are not all empty/None).
- `get(key, default="")` — returns the var if present; otherwise a fresh `ConfigVar(self, key, default)` **not** inserted into the stack.
- `setdefault(key, default, callback_when_value_is_set=None)` — like `get`, but inserts the new var into `var_list[-1]` when missing.
- `update(update_dict)` / `keys()` / `__len__()` (counts all occurrences across all levels) / `clear()` (resets to a single empty dict).
- `set_dynamic_var(key, callback_func, initial_value=None)` — sets an initial dummy value (the callback's `__name__` if no initial value, so the callback fires at least once) then installs `callback_func` as the get-callback. Used for computed vars (e.g. `__NOW__`).

Scope management:
- `push_scope()` / `pop_scope()` / `stack_size()` / `resize_stack(new_size)` (pops down to size).
- `push_scope_context(use_cache=True)` — contextmanager that pushes a scope on entry and pops on exit. (`use_cache` is a vestigial parameter — caching is gone — but is still passed `use_cache=False` at the params-resolution call site.)

Resolution API:
- `resolve_str(val_to_resolve) -> str` — fast path returns the input unchanged (incrementing `simple_resolve_counter`) when `resolve_indicator not in val_to_resolve`; otherwise joins `resolve_str_to_list_with_statistics(...)` results.
- `resolve_str_to_list(val_to_resolve) -> List` — fast path returns `[val]`; otherwise: if the string resolved to exactly **one variable and no literals** (`num_literals == 0 and num_variables == 1`), it `extend`s with the var's full list (list expansion); otherwise it appends the single joined string.
- `resolve_str_to_list_with_statistics(str_to_resolve)` — the core driver (see algorithm below). Returns `(resolved_parts, num_literals, num_variables)`.
- `resolve_list_to_list(strs_to_resolve_list)` — per string: if it is the name of an existing var, extend with its full resolved list; else append `resolve_str(s)`.
- `variable_params_to_config_vars(parser_retVal)` — materializes parsed params into temp vars and computes the array slice range (see algorithm).
- `is_str_resolved(str_to_check)` — regex check for a remaining `$(...)`.

Serialization / OS / misc:
- `repr_var_for_yaml(var_name, resolve=True)` / `repr_for_yaml(which_vars=None, resolve=True, ignore_unknown_vars=False)` — dump vars to `aYaml.YamlDumpWrap`; resolved or raw (`raw(join_sep=None)`); collapses single-element lists to a scalar; emits an "UNKNOWN VARIABLE" wrap for unknown names unless ignored.
- `read_environment(vars_to_read_from_environ=None)` — imports `os.environ`; with `None` imports all (skipping empty keys); otherwise **platform branch**: if `'Win' in self["__CURRENT_OS_NAMES__"]` it builds a lowercased-key copy of the environment and matches case-insensitively, else matches case-sensitively.
- `replace_unresolved_with_native_var_pattern(str_to_replace, which_os)` — rewrites `$(X)` to `%X%` (Win) or `${X}` (Mac) via a **bespoke** verbose regex (handles balanced-parenthesis names and an optional `[index]`), defaulting to configVar style otherwise.
- `shallow_resolve_str(val_to_resolve)` — regex-based single-pass resolve (no functions, nesting, or recursion) for index.yaml templates used with `private_config_vars`. Its docstring documents the order-dependent quirk: each `$(NAME)` match is `.replace`d in turn, so an earlier-substituted occurrence won't be re-resolved later.
- `push_resolve_indicator(resolve_indicator)` — contextmanager to temporarily swap the `$` trigger.
- `does_config_var_name_means_path(config_var_name)` — True if name ends with any suffix listed in `CONFIG_VAR_NAME_ENDING_DENOTING_PATH`.
- `print_statistics()` — gated on `PRINT_CONFIG_VAR_STATISTICS`; the per-resolve and total-time figures are permanently 0.0 because `resolve_time` is never updated.

Module globals:
- `config_vars = ConfigVarStack()` (line 450) — **the single global stack** imported by ~all subsystems.
- `private_config_vars()` (contextmanager) — yields a fresh throwaway `ConfigVarStack` then deletes it; used by `db/indexItemTable.py` for an isolated stack.

#### `var_parse_imp` & friends (configVar/configVarParser.py)

Generator-based hand-written state machine scanning a string char-by-char and yielding `ParseRetVal` namedtuples.

- `ParseRetVal` — 8 fields: `literal_text`, `variable_str` (full original `$(...)` text, used as fallback when resolution fails), `variable_params_str`, `variable_name`, `positional_params`, `key_word_params`, `array_index_str`, `array_index_int`.
- `VarParseImpContext` — mutable parse-state holder; `reset_return_tuple()`/`get_return_tuple()` unpack/pack the 8 fields plus tracks `parenthesis_balance`. Class attribute `variable_name_acceptable_characters` = letters + digits + `_` + `-`.
- `var_parse_imp(f_string, resolve_indicator='$')` — the generator. Inner state functions: `literal_state`, `var_ref_started_state`, `var_name_state`, `var_name_ended_state`, `params_state`, `params_ended_state`, `array_state`, `array_ended_state`, and the `discard_variable` demotion helper. `parse_var_params(cont)` splits the params string into positional/key-word.
- Standalone helpers: `params_to_dict(params_text)`, `resolve_variable_1` / `resolve_variable_2` / `parse_str(str_to_parse, var_resolver)` — used **only** by the module's `__main__` self-test harness (a table of ~30 parse cases), not elsewhere in the app.
- Module regexes: `vars_split_level_1_re` (split on commas) and `vars_split_level_2_re` (split on `=`).

#### `ConfigVarYamlReader` & helpers (configVar/configVarYamlReader.py)

Subclass of `aYaml.YamlReader` that interprets YAML docs into config var definitions. Constructed as `ConfigVarYamlReader(config_vars, path_searcher=None, url_translator=None)`; `.read_yaml_file(path)` (inherited) is the load entry point.

- `init_specific_doc_readers()` — registers readers: `__no_tag__` and `!define` → `read_defines`; `__unknown_tag__` → `do_nothing_node_reader`; `!define_const` (deprecated) → `read_defines`; `!define_if_not_exist` → `read_defines_if_not_exist`.
- `read_defines(a_node, ...)` — per identifier in the mapping, `match`-dispatches: identifiers starting `__if` → `read_conditional_node`; `__include__` → `read_include_node`; `__include_if_exist__` → same with `ignore_if_not_exist=True`; `__environment__` → `config_vars.read_environment([...])`; otherwise (gated by `_allow_reading_of_internal_vars` or the name not being a `__dunder__`) `setdefault` the var, `clear()` it **unless** the YAML tag is `!+=` (append semantic), then `extend` with the read values.
- `read_defines_if_not_exist(a_node, ...)` — writes only vars not already present; **forbids** `__include__`/`__include_if_exist__` (raises `ValueError`).
- `read_values_for_config_var(...)` — collects values, enforcing each is `str`/`int`/`None` (else `TypeError`).
- `allow_reading_of_internal_vars(allow=True)` (contextmanager) + `_allow_reading_of_internal_vars` flag — gate for reading `__dunder__` identifiers.
- `read_include_node(i_node, ...)` — scalar: resolve path via `config_vars.resolve_str` then recurse `read_yaml_file`; sequence: recurse per item. (The **map form** `__include__: {url:, copy:, checksum:}` — remote-fetch-then-cache, heavily used by Waves Central's `V*-online-common.yaml`/`offline.tmplt.yaml` to load the index itself — is NOT handled here; it is the `InstlInstanceBase.read_include_node` override, documented under *Instl Instance Base → read_include_node*. This reader supports only the scalar/sequence path forms.)
- `read_conditional_node(identifier, contents, ...)` — if `eval_conditional(identifier, config_vars)` is true, `read_defines(contents)`.
- `path_searcher = SearchPaths(config_vars, "__SEARCH_PATHS__")`.

Module helpers:
- `eval_conditional(conditional_text, config_vars)` — parses `__if<type>__(cond)` via `conditional_re`. `def` → `cond in config_vars`; `ndef` → `cond not in config_vars`; `""` (`__if__`) → resolve the condition then `eval(resolved_condition, globals(), locals())`. (This is why `os` and `sys` are imported at the top "do not remove, might be used in eval".)
- `smart_resolve_yaml(a_node, config_vars)` — recursively resolves `$()` across a YAML node tree, wrapping results in `aYaml.YamlDumpWrap` and preserving `!`-prefixed tags. In a sequence, a scalar that `resolve_str_to_list` expands to more than one value extends the sequence in place; otherwise the item is recursed.

---

### Key Algorithms

#### 1. `$(...)` parse state machine (`var_parse_imp`)

```
state := literal_state, balance := 0
for each char c in f_string:
    state, yield_val := state(c, cont)
    if yield_val is not None: yield yield_val
# at EOF: if still inside a variable state, demote the partial
# variable_str back into literal_text (variable_name := None) and
# force one final literal yield; a truly broken state raises ValueError.
```
- `literal_state`: accumulate into `literal_text` until `resolve_indicator` ('$') → `var_ref_started_state`.
- `var_ref_started_state`: requires `(` next → enter `var_name_state` (balance += 1); anything else → `discard_variable` (the `$x` is literal text).
- `var_name_state`: name chars accumulate; `(` increments balance and is kept in the name (Windows-quirk balanced parens); `)` decrements balance and **only when balance hits 0** does it yield and return to `literal_state`; `<` → `params_state`; `[` → `array_state`; whitespace → `var_name_ended_state`; unknown char → `discard_variable`.
- `params_state` collects until `>` → `params_ended_state`; `array_state` collects until `]` → `array_ended_state`. The `*_ended_state`s skip whitespace before the closing `)`.
- `array_ended_state` does `int(array_index_str)` on `)`; a non-integer index → `discard_variable` (so `$(a[!])` becomes literal).
- `discard_variable(c, cont)`: rolls the in-progress `variable_str` back into `literal_text`; if the offending char is itself a `$`, it re-enters `var_ref_started_state` (so back-to-back `$(b$(c)` parses the second var). 

**Edge cases / invariants:** an unterminated variable at EOF is always demoted to literal (never raises in practice); parentheses inside a name must be balanced; the original `variable_str` is preserved on every `ParseRetVal` so callers can fall back to the literal text when the variable name is undefined.

#### 2. Resolution driver (`resolve_str_to_list_with_statistics`)

```
for parser_retVal in var_parse_imp(str_to_resolve, self.resolve_indicator):
    if parser_retVal.literal_text:
        resolved_parts.append(literal_text); num_literals += 1
    if parser_retVal.variable_name:
        if name in self:
            with self.push_scope_context(use_cache=False):   # temp scope
                array_range = self.variable_params_to_config_vars(parser_retVal)
                resolved_parts.extend(list(self[name])[array_range[0]:array_range[1]])
        else:
            resolved_parts.append(parser_retVal.variable_str)  # leave $(...) unresolved
        num_variables += 1
return resolved_parts, num_literals, num_variables
```
A new scope is pushed only when the variable has params/index; temp vars injected there vanish on scope exit. Iterating `self[name]` triggers `ConfigVar.__iter__`, giving recursive/nested resolution. Undefined variables resolve to their literal `$(NAME)` text rather than erroring.

#### 3. Param materialization & array slicing (`variable_params_to_config_vars`)

- Positional params become temp vars named `__<VARNAME>_<n>__` (1-based): e.g. `$(F<x,y>)` injects `__F_1__=x`, `__F_2__=y`.
- Key-word params (`k=v`) become temp vars `k=v` directly.
- Array range: default `(0, None)` (whole list). For `array_index_int >= 0` → `(i, i+1)`. For negative index → normalized to `len(self[name]) + i` then `(normalized, normalized+1)` (because Python's `a[-1:0]` would yield an empty slice).

---

### Data Structures & Formats Owned

- **In-memory only.** No DB tables, no on-disk format owned by this subsystem. The authoritative structure is `config_vars.var_list: List[Dict[str, ConfigVar]]`. Each `ConfigVar` owns only its flat `values: List[str]`.
- **Input format consumed:** YAML config documents with tags `!define`, `!define_const` (deprecated), `!define_if_not_exist`, and the per-value append tag `!+=`; plus special mapping keys `__include__`, `__include_if_exist__`, `__environment__`, and conditionals `__if__` / `__ifdef__` / `__ifndef__`.
- **The `$(NAME<params>[index])` mini-language** is the de-facto reference grammar; the canonical implementation is `var_parse_imp`.

---

### Invariants, Edge Cases, Platform Branches

- `ConfigVar.values` is always a flat list of strings; `extend` flattens nested sequences and rejects unknown types with `TypeError`.
- `__setitem__` writes to the top scope only; lower-scope vars of the same name are shadowed, not mutated.
- `__bool__` is true only for a single truthy value; multi-valued and empty vars are falsy — relevant when testing flags.
- Mapping methods raise `TypeError` on non-`str` keys and `KeyError`/`KeyError`-via-`__getitem__` on absent keys; `get`/`setdefault` synthesize a `ConfigVar` instead.
- Undefined `$(NAME)` resolves to the literal `$(NAME)` text (no exception).
- Fast path: any string without the `resolve_indicator` is returned verbatim, bypassing the parser.
- Platform branches: `read_environment` lowercases keys on Windows (keyed off `__CURRENT_OS_NAMES__`); `replace_unresolved_with_native_var_pattern` switches `%X%` (Win) vs `${X}` (Mac).
- `eval_conditional`'s `__if__` path runs `eval()` on a resolved condition string with full `globals()`/`locals()` — arbitrary YAML-supplied expressions are executed.
- `print_statistics` and `resolve_time` are inert (timing code is commented out).

---

### Refactoring Notes (this subsystem)

1. **Process-wide mutable global singleton** — `configVar/configVarStack.py:450` (`config_vars = ConfigVarStack()`) and the `var_stack` alias in `configVar/__init__.py:5`. ~50 modules import and mutate this single object, making state implicit, test isolation hard (tests must `clear()`), and concurrency unsafe. *Direction:* inject the `ConfigVarStack` into constructors/commands, keeping the global as a thin default; generalize the existing `private_config_vars()` local-stack pattern.

2. **`eval()` on YAML-supplied conditions** — `configVar/configVarYamlReader.py:42`. Arbitrary code execution from config; `os`/`sys` are imported (lines 6–7) solely so `eval` can reach them. *Direction:* replace with a restricted/whitelisted expression evaluator (e.g. `ast`-based) and drop the `os`/`sys` imports.

3. **`ConfigVarStack` is a god-object** — `configVar/configVarStack.py` (whole class). It mixes mapping container, `$()` resolver, YAML dumper (`repr_for_yaml`), native-pattern rewriting, env import, and statistics. *Direction:* extract a `Resolver`, a `YamlSerializer`, and an `EnvironmentImporter` collaborating with a lean container.

4. **Three+ overlapping resolution implementations** — `resolve_str` (252), `resolve_str_to_list` (272), `shallow_resolve_str` (412), and `replace_unresolved_with_native_var_pattern` (380), plus the canonical parser path in `resolve_str_to_list_with_statistics` (231). The shallow/native-rewrite paths re-implement `$()` matching with their own regexes that can diverge from the `var_parse_imp` grammar. *Direction:* funnel everything through `var_parse_imp`; have `resolve_str`/`resolve_str_to_list` share one helper.

5. **Dead performance-statistics code** — `configVar/configVarStack.py:47, 253–265, 295–297, 408–410`. `resolve_time` is never written (timing commented out), so `print_statistics` permanently reports 0ms. *Direction:* remove the timing fields/`resolve_time`, or restore timing behind a debug flag.

6. **Debug-only stubs in production** — `configVar/configVarOne.py:34–46` (`value_is_set`/`value_is_get` no-ops with how-to-wire docstrings). *Direction:* move to a test/debug helper or remove.

7. **Inline self-test harness in the parser module** — `configVar/configVarParser.py:288–347` (`__main__` table) plus `resolve_variable_1`/`resolve_variable_2`/`parse_str` used only by it. *Direction:* migrate the parse cases into `configVar/test/testConfigVar.py` and drop the `__main__`/helpers from the importable module.

8. **OS platform branching baked into the engine** — `read_environment` (370–378, keyed on `__CURRENT_OS_NAMES__`) and `replace_unresolved_with_native_var_pattern` (380–401). *Direction:* push OS behavior behind a small platform-policy abstraction injected into the stack.

9. **`ConfigVar` hard-bound to the concrete owner's method names** — `configVar/configVarOne.py:83` (`set_callback_when_value_is_get` defaults to `owner.resolve_str`) and `:193` (`__iter__` calls `owner.resolve_str_to_list`). The value object cannot resolve without an owner exposing exactly these methods. *Direction:* define a narrow `Resolver` protocol (`resolve_str`, `resolve_str_to_list`) and depend on the abstraction.

10. **Redundant/dead constructor params in `ConfigVarYamlReader`** — `configVar/configVarYamlReader.py:53` then `:58`: `self.path_searcher` is set from the parameter then immediately overwritten with a new `SearchPaths(...)`, and `url_translator` is stored but unused. *Direction:* remove the redundant first assignment and unused params, or honor a passed-in `path_searcher` when provided.

11. **Vestigial `use_cache` parameter** — `push_scope_context(use_cache=True)` (354) and `resolve_str_to_list_with_statistics`'s `use_cache=False` call site (244): caching was removed in 2.1.6.0 but the parameter remains and does nothing. *Direction:* drop the parameter.

---

I now have comprehensive grounding. Let me write the LLD section.

## Data Tables (svnTree + db)

The SQLite-backed persistence and query layer of `instl`. It owns one shared `sqlite3` connection and the logical tables that model an installation: the **info-map** (`svn_item_t`, every repo file/dir), the **index items** (`index_item_t` + `index_item_detail_t`, the IID install items parsed from `index.yaml`/`require.yaml` with inheritance resolved), and **auxiliary** tables (`active_operating_systems_t`, `config_var_t`, `iid_to_svn_item_t`, `found_installed_binaries_t`, `require_translate_t`). It parses input files into rows, runs the heavy set-based SQL (mark-required, mark-need-download, inheritance resolution, GUID/IID translation), and hands rows back to the rest of `instl`. It does not decide install policy, run downloads, or touch the filesystem beyond reading source files into the DB.

Files: `db/dbMaster.py`, `db/indexItemTable.py`, `svnTree/svnTable.py`, plus the schema scripts in `defaults/*.ddl`. The packages re-export the public surface: `db/__init__.py` exposes `DBManager`; `svnTree/__init__.py` exposes `SVNTable`, `SVNRow`.

### Component breakdown

#### `DBMaster` — `db/dbMaster.py:53`
Owns the `sqlite3` connection/cursor and all lifecycle, transaction, and execution primitives.

- **Attributes**: `memory_db` (bool), `db_file_path` (`Path` or `None`), `ddl_files_dir` (`Path`), `__conn`/`__curs`, `locked_tables` (set), `statistics` (`defaultdict(Statistic)`), `top_user_version = 1`, `transaction_depth` (hand-rolled nesting counter).
- `__init__(db_url: str, ddl_folder: Path)` — `db_url == ":memory:"` sets `memory_db=True` and `db_file_path=None`; any other value is treated as a filesystem path.
- `open()` (`:87`) — connects, sets `row_factory = sqlite3.Row`, calls `configure_db()`. If the db is new (in-memory, or the file does not yet exist) it runs `create-tables.ddl`, `init-values.ddl`, `create-indexes.ddl` via `exec_script_file`. Idempotent: no-op if `__conn` already set. Both `SVNTable.__init__` and `IndexItemsTable.__init__` call `db.open()`.
- `configure_db()` (`:112`) — `PRAGMA foreign_keys = ON`, `PRAGMA user_version = 1`, sets `row_factory`, clears trace callback.
- `transaction(description=None, progress_callback=None, progress_callback_n_instructions=50*1024*1024)` (`:209`) — `@contextmanager` yielding `self.__curs`; calls `begin()` then `commit()` on success. `selection()` (`:235`) and `temp_transaction()` (`:255`) yield a *fresh* `self.__conn.cursor()` and do **not** commit (read-only / TEMP-table use). All three derive `description` from `inspect.stack()[2][3]` when not passed (with a `try/except IndexError` guard in `transaction`).
- `begin()/commit()/rollback()` (`:168-182`) — `begin()` first calls `commit()`, then `execute("begin")`, `transaction_depth += 1`; `commit()` does `__conn.commit()`, `transaction_depth -= 1`; `rollback()` resets depth to 0. All safety asserts are commented out.
- `exec_script_file(file_name)` (`:275`) — loads a `.ddl` from `ddl_files_dir` (or treats the name as a path if it is an existing file) and `executescript`s it inside a transaction.
- `select_and_fetchone(query, params=None)` / `select_and_fetchall(...)` (`:285`, `:311`) — run a SELECT via `selection()`; flatten single-column results to plain Python values/lists; multi-column results are returned as `sqlite3.Row` lists. Re-raise `sqlite3.Error`.
- `create_function(func_name, num_params, func_ptr)` (`:128`) — registers a Python SQL function on the connection (used for `need_to_download_file`, `name_and_version`, direct-sync indicator).
- `lock_table(table_name)` / `unlock_table` / `unlock_all_tables` (`:337-372`) — install/drop three `BEFORE INSERT/UPDATE/DELETE` triggers per table that `raise(abort, ...)`, making the table read-only; tracks names in `locked_tables`. `IndexItemsTable.__del__` calls `unlock_all_tables()`.
- `set_progress_handler(cb, n)` + nested `ProgressCallBacker` (`:188`) — wires the sqlite progress callback (fired every *n* VM instructions) to a user progress function while inside a transaction/selection context.
- `close()` (`:138`) — closes the connection; if `PRINT_STATISTICS_DB` is set, prints `statistics`. `close_and_delete()` (`:131`) also imports `pybatch.RmFile` and deletes the on-disk db file.

#### `DBAccess` (descriptor) — `db/dbMaster.py:375`
Lazily creates the singleton `DBMaster` on first attribute access.
- `__get__` (`:385`) — calls `get_default_db_file()`, then builds `DBMaster(os.fspath(__MAIN_DB_FILE__), __INSTL_DEFAULTS_FOLDER__)` and caches it; also sets `__DATABASE_URL__`.
- `get_default_db_file()` (`:400`) — resolves `__MAIN_DB_FILE__` (defaulting to `:memory:`). Cases: `:memory:` → in-memory; `:file:` → choose a path next to `__MAIN_OUT_FILE__`, else `$(__MAIN_INPUT_FILE__)-$(__MAIN_COMMAND__)`, else the system Logs folder, appending `.$(DB_FILE_EXT)`; any other value → `utils.ExpandAndResolvePath`. If `_owner.refresh_db_file` is set and the file exists, it is removed via `utils.safe_remove_file`.
- `__delete__` — closes and clears the cached db.

#### `TableAccess` (descriptor) — `db/dbMaster.py:441`
Lazily instantiates a table object bound to the shared `DBMaster`.
- `__set_name__` asserts the attribute name maps to the expected type via `{'items_table': IndexItemsTable, 'info_map_table': SVNTable}[self._name]`.
- `__get__` does `self._table = self._type(instance.db)` (triggering `db.open()`).

#### `DBManager` (mixin / public entry point) — `db/dbMaster.py:464`
Class-level descriptors shared app-wide:
```python
db              = DBAccess()
info_map_table  = TableAccess(SVNTable)
items_table     = TableAccess(IndexItemsTable)
refresh_db_file = False
```
- `set_refresh_db_file(cls, to_refresh)` / `reset_db(cls)` (`:474`, `:478`) — `reset_db` does `close_and_delete()` then re-creates the three descriptors and clears `refresh_db_file`; this is the escape hatch for tests/repeated runs against the shared singleton state.

#### `Statistic` — `db/dbMaster.py:33`
Tiny `(count, time)` accumulator aggregated in `DBMaster.statistics`. Largely dormant — all recording call sites in `transaction`/`selection`/`temp_transaction` are commented out, so it is only meaningful via `PRINT_STATISTICS_DB` when timing is manually re-enabled.

#### `SVNRow` — `svnTree/svnTable.py:59`
`__slots__` wrapper over an `svn_item_t` row (22 columns), constructed positionally in `__init__` (`:68`).
- Predicates: `isDir/isFile` (`fileFlag`), `isExecutable` (`'x' in flags`), `isSymlink` (`'s' in flags`), `is_wtar_file` (`wtarFlag > 0`), `is_first_wtar_file` (path ends `.wtar`/`.wtar.aa`).
- Helpers: `get_ancestry()`, `name()`, `path_starting_from_dir(dir)`, `chmod_spec()` (`"a+rw"` + `"x"` for executables/dirs), `extra_props_list()`, `__fspath__()`.
- `__str__` (`:104`) renders the comma-separated `info_map.txt` line: `path, flags, revision[, checksum][, size if != -1][, url][, dl_path:'...'][, needed_for_iid]`. `str_specific_fields(fields)` (`:119`) renders only a subset (for dirs, only fields in `fields_relevant_to_dirs`).

#### `SVNTable` — `svnTree/svnTable.py:230`
All reads/writes/queries over `svn_item_t`. ~1600 lines. Constructed with the shared `DBMaster`; calls `db.open()`.
- **Readers**, dispatched by `read_func_by_format` (`info`/`text`/`props`/`file-sizes`) from `read_from_file(in_file, a_format="guess", ...)` (`:332`). Skips files already in `files_read_list`.
  - `read_from_svn_info` (`:359`) — parses `svn info` blocks via regex, builds rows, bulk-inserts with `utils.iter_grouper(8192)`.
  - `read_from_text` (`:431`) — CSV parse of `info_map.txt`; derives `level/parent/leaf` (`level_parent_and_leaf_from_path`), `fileFlag`, `wtarFlag`/`unwtarred` (via `utils.wtar_file_re`), `symlinkFlag`.
  - `read_props` (`:640`) — appends `x`/`s` to `flags` (executable/special) and other svn props into `extra_props`.
  - `read_file_sizes` (`:617`) — bulk `UPDATE size WHERE path=...`.
- **Index management**: `create_indexes()` (`:311`) creates the unique `path` index, runs `update_parent_ids_q` (resolves `parent_id` by matching `parent` to a parent row's `path`), creates `parent_id` and `unwtarred` indexes, and sets `MIN_REPO_REV`/`MAX_REPO_REV` config vars. `reading_files_context()` (`:326`) drops indexes, yields, recreates.
- **Query helpers** returning `List[SVNRow]` via `SVNRowListToObjects`: `get_items`, `get_required_items`, `get_unrequired_items`, `get_download_items`, `get_file_items_of_dir`, `get_items_in_dir` (recursive vs `immediate_children_only`), `get_required_exec_items`, `get_any_item_recursive`. Counters: `num_items(item_filter)` (`:570`, large `match` over filter names), `get_to_download_num_files_and_size`, `count_wtar_items_of_dir`.
- **Mutators**: `mark_required_for_file/dir/source/revision`, `mark_required_completion` (`:1211`, recursive UPDATE marking parent dirs of required files), `mark_need_download` (`:1239`, registers `need_to_download_file` SQL fn then sets `need_download=1` for required+non-ignored files whose checksum/path needs fetching, then recursively marks parent dirs), `clear_required`, `ignore_file_paths_of_dir`, `ignore_unrequired_where_parent_unrequired`, `update_downloads`, `set_base_revision`.
- **Cross-table SQL** (joins into the index tables — see coupling note): `mark_required_files_for_active_items` (`:1317`, `executescript` of 3 statements: mark sources of `install_status>0 AND ignore=0` items, mark their children, mark their parents), `populate_IIDToSVNItem` (`:1434`, fills `iid_to_svn_item_t`), `set_info_map_file`/`mark_items_required_by_infomap` (`:1453`/`:1397`), and `get_files_that_should_be_removed_from_sync_folder` (`:761`).
- **URL resolution**: `get_sync_url_for_file_item(file_item)` (`:1617`); `repo_rev_to_folder_hierarchy` (`:1599`, `@lru_cache`); `get_sync_base_url_for_iid(iid, default_url)` (`:1575`, `@lru_cache`).
- **Writers**: `write_to_file`/`write_as_text` (`:494`/`:513`) serialize rows back to `info_map.txt` in 8192-row batches.

#### `IndexItemsTable` — `db/indexItemTable.py:29`
All reads/writes/queries over `index_item_t` + `index_item_detail_t` and the auxiliary tables. Constructor calls `db.open()`, then `add_triggers()` (`create-triggers.ddl`) and `add_views()` (`create-views.ddl`). `__del__` unlocks all tables.
- **Class enums mirroring the schema**: `os_names_to_num` (`common`=0 … `Linux`=7, `MacArm`=8, `MacIntel`=9), `install_status = {"none":0,"main":1,"update":2,"depend":3,"remove":-1}`, `action_types` (18 action hooks), `not_inherit_details = ("name","inherit")`.
- **YAML parsing**: `read_index_node` (`:628`) → `read_index_node_helper` (`:609`, recurses into templates via `read_index_template_node`) → `item_from_index_node` → `read_item_details_from_node` (`:527`). The detail reader handles `__if` conditionals (`eval_conditional`), OS-name sub-nodes, `actions`, `define`, and special-cases `install_sources` (absolute vs relative path; relative paths fan out into per-OS-group `Mac`/`Win`-prefixed rows), `depends` (resolves to a list), and lowercases `guid`. `read_index_node_one_by_one` (`:649`) is a debug-only full duplicate gated on `DEBUG_INDEX_DB`.
- **Require parsing**: `read_require_node` (`:801`), `read_item_details_from_require_node`, `clean_require_items` — map previous→current IIDs.
- **Inheritance resolution**: `resolve_inheritance` (`:435`) → `prepare_inherit_order` (`:458`, topological order via recursive `resolve_iid` plus a `check_inherit_order` assertion) → `get_resolve_item_query_for_iid` (`:495`, INSERTs inherited details with `generation+1`, skipping `not_inherit_details`, only for active OSes). In non-debug mode all per-IID scripts are concatenated and run as one `executescript`, then the `owner_iid` index is created.
- **OS activation**: `activate_all_oses` (`:75`), `activate_specific_oses(*for_oses)` (`:96`, always adds `"common"`, `UPDATE active_operating_systems_t.os_is_active`), `reset_active_oses`, `get_active_oses`. The DDL trigger `adjust_active_os_for_details2` propagates `os_is_active` to every `index_item_detail_t` row on this UPDATE.
- **Detail queries** (the `get_*_details*` family, `:286-433` and `:1199-1268`): original vs resolved, active-only vs all-OS, with optional DISTINCT / `limit_to_iids`. E.g. `get_resolved_details_value_for_active_iid(iid, detail_name, unique_values=False)` (`:378`), `get_sources_for_iid(the_iid)` (`:1452`).
- **Install-status state machine**: `change_status_of_iids(new_status, iid_list)` (`:1052`), `change_status_of_iids_to_another_status(old, new, iid_list, ...)` (`:1022`), `change_status_of_all_iids`, `get_iids_by_status`, `get_recursive_dependencies`. Updating `install_status` fires DDL triggers that synthesize `require_by`/`require_version`/`require_guid` details (and remove them on uninstall, status `< 0`).
- **GUID/IID translation**: `iids_from_guids(guid_list)` (`:928`) and `iids_from_iids` build a TEMP table to map.
- **Default items**: `create_default_items` (`:1270`) and helpers synthesize `__ALL_ITEMS_IID__`, `__ALL_GUIDS_IID__`, `__REPAIR_INSTALLED_ITEMS__`, `__UPDATE_INSTALLED_ITEMS__`.
- **Binaries reconciliation**: `add_binary_versions` (`:1306`), `add_require_version_from_binaries`, `add_require_guid_from_binaries` — populate `found_installed_binaries_t`; DDL triggers `add_iid_to_FoundOnDiskItemRow_guid_*` back-fill the `iid` column by matching guid or filename against `install_sources`/`previous_sources`.
- **Misc**: `mark_direct_sync_items` (`:1395`), `set_name_and_version_for_active_iids`, `config_var_list_to_db`/`add_config_vars` (persist to `config_var_t` for reference only), `get_data_for_short_index`/`versions_report` (`:909`, runs report views/`short-index.ddl`).

### DB schema (owned tables — `defaults/create-tables.ddl`)

- **`svn_item_t`** (info-map; one row per repo file/dir): `_id` PK, `path`, `flags` (`d`/`f`/`x`/`s`), `revision`, `checksum`, `size`, `url`, `fileFlag`, `wtarFlag`, `leaf`, `parent`, `level`, `required`, `need_download`, `download_path`, `download_root`, `extra_props` (reused to hold the info-map file name), `parent_id` (default 0), `unwtarred`, `symlinkFlag`, `ignore` (default 0), `needed_for_iid` → FK `index_item_t(iid)`.
- **`index_item_t`** (one row per IID): `_id`, `iid` UNIQUE, `inherit_resolved`, `from_index`, `from_require`, `install_status` (default 0), `ignore`, `direct_sync`.
- **`index_item_detail_t`** (property bag): `_id`, `original_iid`, `owner_iid`, `os_id` → `active_operating_systems_t`, `detail_name`, `detail_value`, `generation` (0 = original, +1 per inheritance hop), `tag`, `os_is_active`. UNIQUE on `(original_iid, owner_iid, os_id, detail_name, detail_value, generation)`; FKs to `index_item_t(iid)` with `ON DELETE CASCADE`.
- **`active_operating_systems_t`**: `_id`, `name` UNIQUE, `os_is_active`. Seeded by `init-values.ddl`: `common`=0, `Mac`=1, `Mac32`=2, `Mac64`=3, `Win`=4, `Win32`=5, `Win64`=6, `Linux`=7, `MacArm`=8, `MacIntel`=9 (note the numeric order does not match `os_names`).
- **`iid_to_svn_item_t`**: bridge `iid` → `svn_id`, FK to both tables, `iid` FK `ON DELETE CASCADE`.
- **`config_var_t`** (`name` UNIQUE, `raw_value`, `resolved_value`), **`found_installed_binaries_t`** (`path`,`name`,`version`,`guid`,`iid`), **`require_translate_t`** (`iid`,`require_by`,`status`, UNIQUE`(iid,require_by)`).

Triggers (`create-triggers.ddl`) carry significant logic out of Python: OS-activation propagation, `require_*` synthesis on `install_status` change, binary→IID back-fill, and `set_needed_for_iid_after_required_is_set` (when an `svn_item_t.required` flips to 1, populate `needed_for_iid` from the matching `install_sources` detail).

### Key algorithms

**1. `parent_id` resolution (`update_parent_ids_q`, run in `create_indexes`)**
After bulk insert each row has only the string `parent` path. The UPDATE sets `parent_id = (SELECT COALESCE(parent_t._id, 0) FROM svn_item_t parent_t WHERE parent_t.path == svn_item_t.parent)`, turning the path hierarchy into an integer adjacency list so all later recursive CTEs (`get_children`, `get_parents`) walk on the indexed `parent_id`.

**2. Inheritance resolution (`resolve_inheritance`)**
1. `prepare_inherit_order` collects `(original_iid → [inherited iids])` from active-OS `inherit` details into `inherit_dict`.
2. Recursive `resolve_iid` DFS appends an IID to `inherit_order` *after* its parents (post-order), producing a topological order; `check_inherit_order` asserts no duplicates and that every parent precedes its child.
3. For each IID, `get_resolve_item_query_for_iid` emits an INSERT copying every active-OS detail from the inherited IIDs (except `not_inherit_details`) with `generation+1`.
4. All per-IID scripts are concatenated and run as a single `executescript`; the `owner_iid` index is created afterward (creating it first measurably slowed `__ALL_GUIDS__`).

**3. Mark-required → mark-need-download pipeline (`SVNTable`)**
1. `mark_required_files_for_active_items` (3-statement script): UPDATE `required=1` for `svn_item_t` whose `unwtarred` matches an active-OS `install_sources` of an item with `install_status>0 AND ignore=0`; recurse to children; recurse to parents.
2. `mark_need_download` registers the `need_to_download_file(download_path, checksum)` SQL fn, sets `need_download=1` for `required AND ignore=0 AND fileFlag=1` files that need fetching, then recursively marks their parent dirs.
3. `get_download_items` / `get_to_download_num_files_and_size` read the result.

**4. Sync-folder diff (`get_files_that_should_be_removed_from_sync_folder`, `:761`)**
1. Insert all on-disk candidate paths into TEMP `cache_folder_file_paths_t (path, remove DEFAULT 1)`.
2. Build TEMP `do_not_remove_file_paths_exact_t` (every `svn_item_t.path`) and `do_not_remove_file_paths_prefix_t` (folder prefixes for IIDs whose custom `info_map` is not in `svn_item_t`), index both.
3. Phase 1 — set `remove=0` for exact index matches. Phase 2 — set `remove=0` for prefix matches using a **range scan** `c.path >= p.path AND c.path < p.path || char(0x10FFFF)` (the max Unicode code point bounds the prefix tightly so the B-tree index is used instead of `LIKE`).
4. Return all paths still `remove=1`.

### Invariants, edge cases, error handling, platform branches
- **Single shared connection / global singleton**: every `DBManager` subclass across `pyinstl/*` and `pybatch/*` shares one `DBMaster` (and one `sqlite3.Connection`). `reset_db()` exists to fight this for tests/repeated runs.
- **`size == -1`** is the sentinel for "unknown size"; `SVNRow.__str__` omits it. `read_from_text` defaults missing size to 0.
- **`required` gating**: `mark_need_download` only considers `required AND ignore==0 AND fileFlag==1`; folders get `need_download` only by parent-propagation from a needed child.
- **`os_is_active`** gates nearly every detail query; it is maintained transactionally by the `adjust_active_os_for_details2` trigger and set per-row on insert by `set_active_os_for_details2`. `activate_specific_oses` always appends `"common"`.
- **`read_from_svn_info`** raises `ValueError` on a `Tree conflict` line and on `Node Kind` mismatch; `read_from_file` raises `ValueError` for an unknown format and silently skips files already in `files_read_list`.
- **OS path fan-out** (`read_item_details_from_node`): a relative `install_sources` under `common` produces two detail rows (Mac- and Win-prefixed); `assert count_insertions < 3`.
- **`OperationalError` swallowed**: `DBMaster.transaction` catches `sqlite3.OperationalError`, logs disk usage (`shutil.disk_usage`) for on-disk DBs, rolls back, and returns *without re-raising* — callers can proceed on rolled-back state (see refactor note).
- **No explicit OS branching** in this layer; OS differences are pure data (`active_operating_systems_t`) and the `Mac`/`Win` path-prefix rule above. `rich` import in `read_index_node_one_by_one` is optional/debug.

### Refactoring notes (this subsystem)
1. **Broken transaction nesting & swallowed errors** — `db/dbMaster.py:168-233`. `begin()` calls `commit()` first, asserts are commented out, and `transaction()` swallows `OperationalError` (rollback then return as success). Use the `sqlite3` connection as a real context manager or explicit `SAVEPOINT`s, and re-raise (or return an explicit failure) on `OperationalError`.
2. **`SVNTable` god object** — `svnTree/svnTable.py` (whole class). Parsing, bulk insert, query helpers, `mark_*`/`ignore_*`, sync-folder diffing, URL policy, and serialization are entangled. Split into `SVNInfoMapReader`/`Writer`, `SVNQuery`, `SVNMutator`, and a small URL resolver over the same `DBMaster`.
3. **`IndexItemsTable` god object** — `db/indexItemTable.py` (whole class). Separate `IndexYamlReader`/`RequireYamlReader` (parsing) from `IndexItemQuery`, an `InheritanceResolver`, and a reporting collaborator.
4. **Cross-table coupling** — `svnTree/svnTable.py` `mark_required_files_for_active_items` (`:1317`), `populate_IIDToSVNItem` (`:1434`), `set_info_map_file` (`:1453`), `get_files_that_should_be_removed_from_sync_folder` (`:761`) all join `index_item_detail_t`/`iid_to_svn_item_t`, so the two "separate" tables are not independently usable and schema changes silently break `SVNTable`. Move these joins into a dedicated coordinator (e.g. `InstallPlanner`) depending on both tables.
5. **Duplicated detail-query boilerplate** — `db/indexItemTable.py:286-433` and `:1199-1268`. The `os_is_active`/`detail_name`/DISTINCT/`limit_to_iids` filters are copy-pasted ~10 times. Introduce one parametrized detail-query builder.
6. **Inconsistent IN-list quoting / SQL injection of status values** — `change_status_of_iids` (`:1052`) and `change_status_of_iids_to_another_status__` (`:1009`) build `'("a","b")'` by hand and f-string `install_status` values directly; `change_status_of_iids_to_another_status` (`:1022`) uses bound `?`. Standardize on bound placeholders for IN-lists and never f-string status values.
7. **Dead / debug-duplicated code** — delete `change_status_of_iids_to_another_status__` (trailing `__`, unused), collapse `read_index_node_one_by_one` (`:649`) into a thin `DEBUG_INDEX_DB` wrapper instead of a full copy, and remove `get_items_for_default_infomap` (`svnTree/svnTable.py:1418`, marked "maybe use this").
8. **`SVNRow` positional/incomplete dunders** — `svnTree/svnTable.py`. `__init__` (`:68`) unpacks 22 columns by index (coupled to `SELECT *` order); `__eq__` for the `tuple` branch (`:200-222`) stops at index 20 and omits `needed_for_iid`; `__repr__` (`:92`) is a broken f-string (literal `{self.checksum}` etc. — only the first line is interpolated). Build `SVNRow` from `sqlite3.Row` by column name (or a dataclass), fix `__repr__`, and derive `__eq__` from the full field tuple.
9. **Brittle `inspect.stack()` descriptions** — `db/dbMaster.py:209-273`. `transaction`/`selection`/`temp_transaction` infer `description` from stack frames (with an `IndexError` guard). Most call sites already pass a description; require it explicitly and drop the introspection.
10. **Module-level mutable globals & singleton-via-descriptor** — `db/dbMaster.py:29-30` (`force_disk_db`, `unique_name_to_disk_db`, both unused) and the class-level `db`/`info_map_table`/`items_table` descriptors. Remove the dead globals and consider making the DB/tables an injected dependency rather than shared class state.

---

I now have enough detail to write an accurate section.

## aYaml & Utils

This subsystem provides two foundational layers used throughout `instl`: **aYaml** (an augmented-YAML read/write layer on top of PyYAML) and **utils** (a shared standard-library-style toolkit for I/O, checksums, OS detection, parallel process execution, binary inspection, logging, etc.). Neither layer owns database tables; persistence is limited to checksum-keyed cache files, log files, and curl `.part` temp files.

### 1. aYaml

The package re-exports its public surface in `aYaml/__init__.py`:

```python
from .augmentedYaml import YamlDumpDocWrap, YamlDumpWrap, writeAsYaml, nodeToPy
from .yamlReader import YamlReader
```

The standard subclass pattern is `class X(aYaml.YamlReader)` overriding `init_specific_doc_readers()`, then calling `reader.read_yaml_file(path, **kwargs)` (e.g. `configVar/configVarYamlReader.py` `ConfigVarYamlReader`, plus `pyinstl` `InstlInstanceBase` and `db` readers).

#### 1.1 Node monkey-patching (`augmentedYaml.py:42-143`)

At **import time**, the module mutates the global PyYAML node classes (`yaml.ScalarNode`, `yaml.SequenceNode`, `yaml.MappingNode`, `yaml.Node`). This is a global side effect: any module that imports `aYaml` changes PyYAML behavior process-wide. Patches added:

- `isNone()` on `yaml.Node` — `self.tag.endswith(":null")`.
- `GetYamlType()` → `YAML_TYPE.{SCALAR,SEQUENCE,MAPPING}` enum (defined `augmentedYaml.py:36-40`).
- `isScalar()/isSequence()/isMapping()` — constant per class.
- `__len__` — scalar=1, mapping/sequence=`len(self.value)`.
- `__iter__` — scalar yields itself once (`iter_scalar`); sequence iterates values (`iter_sequence`); mapping iterates **keys** as strings (`iter_mapping_keys`). `yaml.MappingNode.items` is bound to `iter_mapping`, yielding `(str(key), value)` tuples.
- `__getitem__` — scalar accepts index 0/-1; mapping does a **linear key scan** (`get_mapping_item`, `:115-122`) comparing `str(item[0].value) == str(key)`; sequence supports +/- indices.
- `__contains__` on mapping — try/except wrapper over `__getitem__`.

Both `iter_mapping` and `iter_sequence` have a **side effect**: when an item `isNone()`, they assign `item.value = None` in place during iteration.

#### 1.2 `YamlReader` (`yamlReader.py:54-203`)

Base class for all instl yaml/json readers. Constructor takes `config_vars` and seeds `config_vars.setdefault("READ_YAML_FILES", None)`.

Key mutable state (attributes):
- `config_vars` — caller-provided dict; reader appends every actually-read path to `config_vars["READ_YAML_FILES"]` and `read_json_from_stream` writes values straight into it.
- `path_searcher` / `url_translator` — resolution callbacks (set by subclass).
- `specific_doc_readers: Dict[str, Callable]` — tag → reader function, **rebuilt per node** (cleared and re-populated via `init_specific_doc_readers()` inside `read_yaml_from_node`).
- `file_read_stack: List[str]` — recursion guard / error breadcrumb (used to build a `" -> "`-joined history on failure).
- `post_nodes: List[Tuple[Node, Callable]]` — deferred `_post`-tagged documents.
- `exception_printed: bool` — guards against recursive error printing.

Important methods:
- `read_yaml_file(file_path, *args, **kwargs)` (`:91`) — entry point. Pushes path onto `file_read_stack`, fetches bytes via `utils.read_file_or_url_utf8(...)` (which may checksum-gate/cache), wraps the text in `io.StringIO` (setting `.name` for error reporting), then dispatches on extension: `.json` → `read_json_from_stream`, otherwise `read_yaml_from_stream`. When the outermost file finishes (`len(self.file_read_stack) == 0`), drains `post_nodes`. Catches `FileNotFoundError`/`URLError`/`YAMLError` (honoring `ignore_if_not_exist`) and a broad `Exception`; both log the file history and re-raise.
- `read_yaml_from_stream(stream, ...)` (`:149`) — `yaml.compose_all(stream)` yields nodes; each is pushed on the `YamlNodeStack` and dispatched.
- `read_yaml_from_node(node, ...)` (`:173`) — runs `convert_standard_tags`, clears+rebuilds `specific_doc_readers`, resolves the reader; `_post`-tagged docs are appended to `post_nodes` rather than executed immediately.
- `get_read_function_for_doc(node)` (`:72`) → `(reader, is_post_tag, effective_tag)`. No tag → `"__no_tag__"`; tag ending in `_post` strips the suffix and sets `is_post_tag=True`; unknown tag → `"__unknown_tag__"`.
- `read_json_from_stream(stream, ...)` (`:158`) — loads a JSON dict directly into `config_vars`; each value coerced to a `list` of str/int (raises `TypeError` on non-str keys or unsupported value types).
- `convert_standard_tags(node)` (static, `:185`) — recursively normalizes `tag:yaml.org,2002:null` / `python/none` to `value = None`.
- `init_specific_doc_readers()` — override hook; base registers `__no_tag__`/`__unknown_tag__` to `do_nothing_node_reader`.

`YamlNodeStack` (`:30-51`) is a contextmanager-callable push/pop stack of nodes so error messages can report the exact source `start_mark`.

#### 1.3 `writeAsYaml` and dump wrappers (`augmentedYaml.py:344-461`)

Signature: `writeAsYaml(pyObj, out_stream=None, indentor=None, sort=False, alias_indicator=None, top_level_blank_line=False)`. A recursive hand-written serializer for `None`, str/int/etc. scalars, `list`/`tuple`, `dict`/`OrderedDict`, and `YamlDumpWrap`. Used by `pybatch/reportingBatchCommands.py`, several `pyinstl` report/admin/client/gui modules, and `db/indexItemTable.py`.

Algorithm (per recursion level):
1. Default `out_stream=sys.stdout`, `indentor=Indentor(4)`.
2. `None` → `~`; empty list/tuple → `[]`.
3. Sequence: push `'l'`, emit `"- "` per item (recursing with +1 indent); a `YamlDumpDocWrap` item is written with no parent.
4. Mapping: push `'m'`, optionally `sort` keys (skipped for `OrderedDict`), pull an alias via `alias_indicator`, write `key:` then recurse the value; emit a blank line at top level if `top_level_blank_line` and indent depth 1.
5. `YamlDumpWrap`: `writePrefix` → recurse `value` → `writePostfix`.
6. Else: use `repr_for_yaml()` if present, otherwise `str(pyObj)` (empty string → `'""'`).
7. **Trailing-newline hack** (`:414`): emits the final EOL only when `sys._getframe(0).f_code.co_name != sys._getframe(1).f_code.co_name` — i.e. detecting top-level vs recursive call by comparing call-frame function names. The code comment notes this "will not work" if recursed from an outside function of the same name.

- `YamlDumpWrap(value=None, tag="", comment="", sort_mappings=False, include_comments=True)` (`:154`) — wraps a value with tag/comment/sort. `writePrefix`/`writePostfix` emit tags+comments; `ReduceOneItemLists` collapses single-element sequences; `GetYamlType/isMapping/isSequence/isScalar` delegate to module helpers.
- `YamlDumpDocWrap(..., explicit_start=True, explicit_end=False, ...)` (`:210`) — adds document markers `---` (with optional tag/comment) on prefix and `...` on postfix, resetting the `Indentor`.
- `Indentor(indent_size)` (`:240`) — tracks `cur_indent`, `num_extra_chars`, and an `item_type_stack` of `'l'`/`'m'` markers. `__iadd__/__isub__` adjust depth; `lineSepAndIndent` writes newline + `indent_size*cur_indent` spaces; `write_extra_chars`/`fill_to_next_indent` handle inline padding.

`nodeToPy(a_node, order=None, single_value=None, preserve_tags=False)` (`:418`) converts a node tree to python `OrderedDict`/list, reordering mapping keys per `order` (unknown keys appended), collapsing single-item sequences named in `single_value`, and optionally preserving `!`-tags (prepended to strings or set as a `tag` attribute on collections). `nodeToYamlDumpWrap` (`:450`) does the inverse conversion to `YamlDumpWrap` trees.

### 2. utils

`utils/__init__.py` flattens the toolkit into the top-level `utils` namespace (`from .files import *`, `from .misc_utils import *`, `from .str_utils import *`) plus explicit re-exports of `SearchPaths`, `run_processes_in_parallel`, `run_process`, `PAUSED_EXIT_CODE`, `NETWORK_ERROR_CURL_EXIT_CODES`, `MultiFileReader`, `extract_binary_info`, `check_binaries_versions_in_folder`, `check_binaries_versions_filter_with_ignore_regexes`, `get_info_from_plugin`, `disk_item_listing`, `single_disk_item_listing`, `log_utils *`, `dock_util` (Darwin only), and the email functions. Callers use `utils.<name>`.

#### 2.1 File / URL I/O (`utils/files.py`)

- `read_file_or_url_utf8(in_file_or_url, config_vars, path_searcher=None, save_to_path=None, checksum=None, connection_obj=None)` (`:242`) — primary reader used by `YamlReader`. If `save_to_path` already has the expected `checksum` it short-circuits by **recursively calling itself** on the cached file (dropping `path_searcher`/`connection_obj`). Local files are resolved via `path_searcher.find_file` then `abspath` (Win) / `realpath` (other); URLs go through `connection_obj.get_session(...).get(..., timeout=(33.05, 180.05))`. Returns `(buffer, actual_file_path)`.
- `open_for_read_file_or_url` (class, `:277`) — context manager. For URLs it builds a `urllib.request` opener (custom headers via `translate_url_callback`), wraps the open in `patch_verify_ssl`, and retries **12 times** with `time.sleep(1.0)` between attempts. `actual_path` property exposes the resolved path/url.
- `read_from_file_or_url(...)` (`:350`) — reads and optionally verifies an expected checksum (errors on empty content, on `encoding != None` while checksumming, or on mismatch).
- `download_and_cache_file_or_url(in_url, config_vars, cache_folder, translate_url_callback=None, expected_checksum=None)` (`:375`) — checksum-gated cache. Cached filename = checksum if known, else the URL leaf. Re-downloads when the file is missing or its checksum fails. No checksum forces a fresh download.
- `download_from_file_or_url(...)` (`:406`) — caches then places on target, decompressing `.wzip` via `zlib`.
- `patch_verify_ssl(verify_ssl)` (contextmanager, `:190`) — when `verify_ssl` is falsey, swaps `ssl._create_default_https_context` for a permissive factory: loads certifi CAs only (avoids the Windows cert store, which can trigger OpenSSL 3.x ASN1 errors), sets `CERT_NONE`, `check_hostname=False`, `@SECLEVEL=0`, and `OP_LEGACY_SERVER_CONNECT`; restores the original on exit. No-op when `verify_ssl` is True.

File-ops helpers: `chown_chmod_on_fd/chown_chmod_on_path` honor module globals `global_acting_uid`/`global_acting_gid` (`:23-24`), set via `set_active_user_or_group_config_var_callback` (config-var hook for `ACTING_UID`/`ACTING_GID`) or `set_acting_ids`. `utf8_open_for_read` retries once through `FixAllPermissions` on `PermissionError`. Also: `safe_remove_file/_folder/_file_system_object`, `smart_copy_file` (hardlink-then-copy), `excluded_walk`/`scandir_walk`, `find_split_files`/`find_wtarred_parts_of_original`, `ExpandAndResolvePath`, `who_locks_file` (Windows DLL), and `wait_for_break_file_to_be_removed`.

#### 2.2 misc_utils (`utils/misc_utils.py`)

- OS/arch: `get_current_os_names()` (`:80`, returns a tuple like `('Mac', 'Mac10.x')`), `GetMacArch`, `Is64Mac/Is64Windows/Is32Windows`, `GetProgramFiles32/64`.
- Checksums: `get_buffer_checksum`, `check_buffer_checksum`, `check_file_checksum`, `get_file_checksum(path, follow_symlinks=True)`, `compare_files_by_checksum`, `need_to_download_file`, and `get_recursive_checksums(some_path, ignore=None)` (`:632`) — produces `{relative_path: sha1, ..., "total_checksum": sha1}`, where `total_checksum` is the sha1 of the sorted, concatenated list of all checksums **and** paths (so renames change it; order does not).
- wtar parsing: `wtar_file_re` (`:586`, groups `base_name`/`wtar_extension`/`split_numerator`), `is_wtar_file`, `is_first_wtar_file` (true for unsplit or `.aa`; rejects `._`-prefixed phantom files), `original_name_from_wtar_name`, `original_names_from_wtars_names`.
- `get_wtar_total_checksum(wtar_file_path)` (`:699`) — appends `.aa` if needed, feeds `find_split_files` into a `MultiFileReader("br", ...)` and reads `tar.pax_headers["total_checksum"]`. Swallows all exceptions (returns `None`).
- Collections: `unique_list` (`:114`, a `list` subclass maintaining a backing set for O(1) membership and dedup), `set_with_order`, `write_to_list`.
- Formatting/timing: `max_widths`, `format_by_width`, `timing`/`time_it` decorators, `Timer_CM`.
- Action breadcrumb: module-global `doing_stack = []` (`:33`) with `add_to_actions_stack(action)` / `get_latest_action_from_stack()` (`:845-850`).
- `get_curl_err_msg(key)` (`:854`) lazily imports `downloadFailures`. JSON helpers `extra_json_serializer`/`JsonExtraTypesDecoder`. System log path via `get_system_log_folder_path/_file_path`.

#### 2.3 Parallel execution (`utils/parallel_run.py`)

Module globals `exit_val`, `aborted`, `paused`, `process_list` (`:19-22`) are **reset at the start of each run**. Sentinels: `PAUSED_EXIT_CODE = 9990` (`:27`) and `NETWORK_ERROR_CURL_EXIT_CODES = frozenset({6, 7, 18, 28, 35, 52, 55, 56})` (`:32`).

`run_processes_in_parallel(commands, shell=False, do_enqueue_output=True, abort_file=None, pause_check=None)` (`:52`):
1. Reset globals + `install_signal_handlers()` (handles SIGABRT/FPE/ILL/INT/SEGV/TERM).
2. `utils.partition_list(commands, lambda c: c[0]=="wait")` splits the command list on `"wait"` sentinels.
3. Each partition runs in a `ThreadPoolExecutor(len(partition))` mapping `run_process` across commands; partitions run sequentially (a `wait` is a barrier).
4. After all complete, `exit_val = PAUSED_EXIT_CODE if paused else 0`, then `killall_and_exit()` (which SIGTERMs any survivors and calls `sys.exit(exit_val)`).

`run_process(command, shell, do_enqueue_output=True, abort_file=None, pause_check=None)` (`:78`) polls in a loop:
- If `pause_check()` returns True → set `paused=True`, `terminate_process` (SIGTERM via `os.killpg`, or `kill_proc_tree` on Windows) so curl flushes its `.part` for later resume, and break.
- `abort_file` arg starts a `ContinuousTimer(1, check_abort_file, ...)`; if the abort file disappears, sets `aborted=True` and `killall_and_exit()`. Using `abort_file` disables `do_enqueue_output`.
- On process exit: if `aborted` raise `ProcessTerminatedExternally`; nonzero status raise `RuntimeError`.

`launch_process` sets `preexec_fn=os.setsid` on Unix for group-kill support; `enqueue_output` streams subprocess stdout into the log line-by-line and also honors `pause_check`.

#### 2.4 `MultiFileReader` (`utils/multi_file.py`)

`io.RawIOBase` subclass exposing a list of files as one continuous stream (`MultiFileReader(mode, paths)`), used to feed split `.wtar.aa/.ab/...` parts into `tarfile`. Inner `OpenFileData` records `path_to_file`, `size`, `starting_pos`, `fd`. `open()` computes cumulative `starting_pos` offsets and `total_size`; `read(size)` rolls to the next file when the current one is exhausted (recursing to satisfy short reads); `seek` maps an absolute position to the owning file; `tell` returns global offset. Write/`readline`/`fileno`/`truncate` raise `UnsupportedOperation`. Context-manager support via `__enter__/__exit__`. Used by `get_wtar_total_checksum`, `ls.wtar_ls_func`, and `pybatch/wtarBatchCommands.py`.

#### 2.5 `extract_info` (`utils/extract_info.py`)

`extract_binary_info(in_os, in_path)` (`:253`) dispatches on file extension via `extract_info_funcs_by_extension` (`:260`, a Mac/Win dict of extension → handler, default `default_extract_info`) and returns `(path, version, guid)`. Handlers: `Mac_bundle/Mac_framework/Mac_dylib/Mac_pkg`, `Win_bundle/Win_aaxplugin/Win_file`, with `plugin_bundle`, `get_info_from_plugin`, `get_guid`, `get_wfi_version` helpers (Mac uses `otool`/`PlistBuddy`/`pkgutil`/`uuidgen`). `check_binaries_versions_in_folder(current_os, in_path, in_filter=lambda p: True)` (`:315`) walks a folder collecting versions, and `check_binaries_versions_filter_with_ignore_regexes` (`:286`) is a callable filter built from ignore regex lists. Used by `pybatch/info_mapBatchCommands.py`.

#### 2.6 `log_utils` (`utils/log_utils.py`)

`config_logger(argv=None, config_vars=None)` (`:24`) and `setup_file_logging(log_file_path, level=logging.DEBUG, rotate=True, config_vars=None)` (`:87`) configure the root logger at startup with stdout/stderr stream handlers, `SameLevelFilter`/`ParentLogFilter`, rotating or plain file handlers, and per-level formatters (`PerLevelFormatter`, `CustomLogFormatter`, `JsonLogFormatter`). `func_log_wrapper` decorates functions for debug-level entry/exit logging.

`BufferUntilErrorHandler` (`:282`) is a proxy handler that **buffers records below `flush_level` (default ERROR)** in a bounded `deque(maxlen=max_records)`; on the first ERROR+ it emits a synthetic warning about dropped records, flushes the buffer to its targets, forwards the triggering record, and then **latches open** (subsequent records pass through). Installed/removed via `set_buffer_non_errors_until_error`/`set_log_quiet_until_error` using module globals `_buffer_until_error_proxy`/`_buffer_until_error_original_handlers` (`:351-352`). Note `teardown_file_logging` (`:193`) begins with an unconditional `return` — its body is dead code.

#### 2.7 `ls` (`utils/ls.py`)

`disk_item_listing(files_or_folder_to_list, ls_format='*', output_format='text')` (`:16`) and `single_disk_item_listing(the_path, ls_format="PuUgGRTf", root_folder=None, output_format="text")` (`:457`) produce manifests of files/folders/wtars. A format-character mini-language drives per-item collection (e.g. `R`=permissions, `I`=inode, `L`=nlinks, `U`/`u`=user, `g`/`G`=group, `T`=mtime, `f`=checksum, `p`/`P`=path) via a `match`-based dispatch. Output can be `text` (column-formatted via `format_by_width`), dicts, or json (`format_char_to_json_key`). Platform branches: `unix_folder_ls`/`unix_item_ls` vs `win_folder_ls`/`win_item_ls`; `wtar_ls_func`/`wtar_item_ls_func` list inside split wtars via `MultiFileReader`. Used by `pybatch/reportingBatchCommands.py` and `pyinstl`.

#### 2.8 `dockutil` and `email_utils`

`utils/dockutil.py` is vendored third-party (Kyle Crawford) macOS Dock manipulation, exporting `dock_util` (a `getopt` CLI) plus `addItem/removeItem/moveItem/readPlist/writePlist/commitPlist` editing `com.apple.dock.plist` via `defaults`/`plutil`. Exported only on Darwin.

`utils/email_utils.py`: `send_email(subject, content, sender, recipients, smtp_server, smtp_port)` (STARTTLS SMTP) and `send_email_from_template_file(path_to_template)` (`:39`) which builds parameters by `eval()`-ing the template file contents.

### 3. Key invariants, edge cases, platform branches

- aYaml node patches are **process-global** and applied at import; correctness assumes any code touching PyYAML nodes has imported `aYaml`.
- `YamlReader.post_nodes` are guaranteed to run only when `file_read_stack` is empty (outermost file done) — nested includes accumulate post-docs until the top finishes.
- `read_file_or_url_utf8` requires a `connection_obj` for URL inputs (`assert connection_obj`); local files require a successful `path_searcher.find_file` or raise `FileNotFoundError`.
- `is_first_wtar_file` deliberately rejects `._`-prefixed phantom files.
- `run_processes_in_parallel` distinguishes pause (`PAUSED_EXIT_CODE`, not a failure — caller holds and re-runs), abort (abort file removed), and genuine failure (nonzero exit / signal). SIGTERM (not SIGKILL) is used so curl preserves `.part` files.
- Platform branches: `'Win'/'Mac' in utils.get_current_os_names()` in `files.get_disk_free_space`, `ls`, and `extract_info`; `os.killpg`/`os.setsid` are Unix-only (Windows falls back to `kill_proc_tree`); `dock_util` Darwin-only.
- Many utils functions intentionally swallow exceptions and return sentinels (`get_wtar_total_checksum` → `None`; most `extract_info` handlers → empty/`None`; `safe_remove_*` ignore errors by default).

### 4. Targeted refactoring notes (this subsystem)

1. **Import-time monkey-patching of PyYAML** (`augmentedYaml.py:42-143`, high impact): mutating `yaml.ScalarNode/SequenceNode/MappingNode/Node` process-wide is order-dependent and brittle across PyYAML upgrades. Prefer a thin adapter wrapping nodes, or explicit helper functions, instead of patching library classes.
2. **`writeAsYaml` frame-name trailing-newline hack** (`augmentedYaml.py:414`, medium): comparing `sys._getframe(0/1).f_code.co_name` to detect top level silently breaks when called from a same-named wrapper. Thread an explicit `is_top_level` flag through the recursion.
3. **O(n) mapping lookup + side-effecting iteration** (`augmentedYaml.py:115-122` `get_mapping_item`, and `:79-98` `iter_mapping`/`iter_sequence` which assign `item.value = None`): build a key→value dict once per mapping node and move null normalization entirely into the explicit `convert_standard_tags` pass.
4. **Module-global mutable run state** (`parallel_run.py:19-22`, `files.py:23-24`, `misc_utils.py:33`, high): `exit_val/aborted/paused/process_list`, `global_acting_uid/gid`, and `doing_stack` make the code non-reentrant/thread-unsafe and `killall_and_exit` calls `sys.exit` on the shared list. Encapsulate per-run state in a `ParallelRunner` object and pass uid/gid via a context object.
5. **`get_disk_free_space` references undefined `win32file`** (`files.py:526`): `win32file` is never imported, so this raises `NameError` on Windows. Add the import (guarded) or centralize OS dispatch.
6. **Pervasive bare `except: pass`** (`extract_info.py`, `files.py:463-498`, `misc_utils.py:699-711`): corrupt plists / wrong versions / failed reads vanish silently. Narrow exception types and log at debug/warning instead.
7. **Dead/disabled code**: `log_utils.teardown_file_logging` (`:193`) returns immediately, making its body unreachable; `multi_file.py:163-198` and `augmentedYaml.py:464-476` carry `__main__` test blocks with hard-coded personal absolute paths; `dockutil` has commented-out legacy plist code. Remove or move into the real test suite.
8. **`dockutil` targets dead macOS/Python APIs** (`dockutil.py`, high if exercised): checks for OS X 10.4/10.9 and calls `plistlib.writePlist`/`readPlistFromBytes` removed in Python 3.9+, so it would crash on the declared python3.12. Rewrite plist I/O with `plistlib.dump/load(fp)` and drop the pre-10.9 branches.
9. **`send_email_from_template_file` uses `eval()`** on file contents (`email_utils.py:39`): arbitrary code execution risk. Use `ast.literal_eval` or a structured (yaml/json) template format.
10. **Duplicated download/checksum logic** (`files.py` `read_file_or_url_utf8` recursion at `:248` vs `open_for_read_file_or_url`, plus `download_and_cache_file_or_url`/`need_to_download_file`): one path uses `requests`, the other `urllib`; the recursion also drops `path_searcher`/`connection_obj`. Consolidate fetch+checksum+cache into one function and delegate.
11. **Duplicated ls walk/format logic** (`ls.py` `unix_folder_ls`/`win_folder_ls` and `unix_item_ls`/`win_item_ls`): parameterize `folder_ls` with the item-ls callable and share a single format-char loop.
