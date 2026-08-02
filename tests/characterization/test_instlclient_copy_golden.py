#!/usr/bin/env python3.12

"""CHARACTERIZATION (golden/snapshot) tests for the ``instl`` CLIENT install path.

These tests LOCK the current observable behavior of ``InstlClient`` /
``InstlClientCopy`` before the upcoming ``instlClient`` split and the
``config_vars`` containment work, so those refactors are verifiable:

  * install-item GRAPH RESOLUTION over a synthetic ``!index`` -- inheritance
    flattening, ``install_sources`` / ``depends`` resolution, and the recursive
    dependency expansion (``get_recursive_dependencies``) that turns a set of
    explicitly-requested ("main") iids into the full closure of iids that must
    be installed;
  * COPY command generation -- the exact pybatch command (its ``repr``) emitted
    by ``create_copy_instructions_for_{file,dir,dir_cont,source}`` for ``!file``,
    ``!dir``, ``!dir_cont`` and wtarred sources, against a synthetic info_map.

Everything here is HERMETIC: no network, no real repo, no svn. The index and the
info_map are tiny in-memory/synthetic fixtures; the database is ``:memory:``.

Style/fixtures follow the existing characterization goldens
(``tests/characterization/test_configvar_resolution_golden.py``) and
``pyinstl/test/test_itemTable.py`` (which builds an ``IndexItemsTable`` on a
``db_master``): a ``unittest.TestCase`` asserting exact strings / lists, clearing
shared singleton state in ``setUp``.

WHAT IS PINNED (and WHAT IS NOT) -- see module-level NOTES at the bottom.
"""

import sys
import os
import unittest
from pathlib import Path

# repo root on path (mirrors the sibling golden + pyinstl/test layout)
sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))

import utils  # noqa: F401  do not remove, prevents cyclic import problems
from configVar import config_vars


REPO_ROOT = Path(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))
DEFAULTS_FOLDER = REPO_ROOT / "defaults"


# --------------------------------------------------------------------------
# A tiny, fully synthetic !index used by the graph-resolution tests.
#
#   APP_IID      depends -> LIB_IID ; has a !file + a !dir source
#   LIB_IID      inherits COMMON_IID ; has a !dir_cont source
#   COMMON_IID   provides a shared post_copy action (inherited by LIB_IID)
#   TOUCH_IID    standalone dependency pulled in only via APP_IID->...->depends
# --------------------------------------------------------------------------
SYNTHETIC_INDEX = """--- !index
APP_IID:
    name: TheApp
    version: 1.2.3
    install_sources:
        - !file src/app.bin
        - !dir src/AppBundle
    install_folders:
        - /opt/dst
    depends:
        - LIB_IID
LIB_IID:
    name: TheLib
    install_sources:
        - !dir_cont src/libdir
    install_folders:
        - /opt/dst
    inherit:
        - COMMON_IID
    depends:
        - TOUCH_IID
COMMON_IID:
    name: Common
    actions:
        post_copy:
            - Echo("done common")
TOUCH_IID:
    name: Touch
    install_sources:
        - !file src/touch.txt
    install_folders:
        - /opt/other
"""


class TestInstlClientGraphResolutionGolden(unittest.TestCase):
    """Pins inheritance flattening, iid->sources mapping and dependency closure
    for a synthetic index. Pure DB/graph layer -- no filesystem, no info_map.

    Uses IndexYamlReaderBase (the same reader the admin index path uses) over an
    in-memory DBManager singleton table, clearing it in setUp/tearDown so the two
    test classes in this module stay isolated and deterministic.
    """

    def setUp(self):
        config_vars.clear()
        config_vars["__INSTL_DEFAULTS_FOLDER__"] = DEFAULTS_FOLDER
        config_vars["__MAIN_DB_FILE__"] = ":memory:"
        from pyinstl import IndexYamlReaderBase
        self.reader = IndexYamlReaderBase(config_vars)
        self.it = self.reader.items_table
        self.it.clear_tables()
        self.it.activate_all_oses()
        import tempfile
        tf = tempfile.NamedTemporaryFile(
            "w", suffix="-index.yaml", delete=False, encoding="utf-8")
        tf.write(SYNTHETIC_INDEX)
        tf.close()
        self._index_path = tf.name
        self.reader.read_yaml_file(self._index_path)
        self.it.resolve_inheritance()

    def tearDown(self):
        try:
            self.it.clear_tables()
        except Exception:
            pass
        try:
            os.unlink(self._index_path)
        except Exception:
            pass
        config_vars.clear()

    # ------------------------------------------------------------------
    def test_all_iids_present(self):
        self.assertEqual(
            ["APP_IID", "COMMON_IID", "LIB_IID", "TOUCH_IID"],
            self.it.get_all_iids())

    def test_sources_for_iid_with_tags(self):
        # all OSes active -> os-name is prefixed onto each source path.
        # (this is exactly the (resolved_path, tag) shape that
        # create_copy_instructions_for_target_folder iterates over.)
        # get_sources_for_iid only returns sources for iids with a non-zero
        # install_status (i.e. actually selected for install), so mark it first.
        self.it.change_status_of_iids(1, ["APP_IID"])  # 1 == "main"
        app_sources = [tuple(r) for r in self.it.get_sources_for_iid("APP_IID")]
        self.assertEqual(
            [('Mac/src/AppBundle', '!dir'),
             ('Mac/src/app.bin', '!file'),
             ('Win/src/AppBundle', '!dir'),
             ('Win/src/app.bin', '!file')],
            app_sources)

    def test_inherited_action_is_flattened_onto_child(self):
        # COMMON_IID's post_copy action must be inherited by LIB_IID.
        lib_post_copy = self.it.get_resolved_details_value_for_iid(
            "LIB_IID", "post_copy", unique_values=True)
        self.assertEqual(['Echo("done common")'], lib_post_copy)

    def test_direct_depends_resolution(self):
        self.assertEqual(
            ["LIB_IID"],
            sorted(self.it.get_resolved_details_value_for_iid(
                "APP_IID", "depends", unique_values=True)))
        self.assertEqual(
            ["TOUCH_IID"],
            sorted(self.it.get_resolved_details_value_for_iid(
                "LIB_IID", "depends", unique_values=True)))

    def test_recursive_dependency_closure(self):
        # request only APP_IID as a "main" install; the recursive expansion must
        # pull in LIB_IID (direct) and TOUCH_IID (transitive via LIB_IID).
        self.it.change_status_of_iids(1, ["APP_IID"])  # 1 == "main"
        closure = sorted(self.it.get_recursive_dependencies(look_for_status=1))
        self.assertEqual(["APP_IID", "LIB_IID", "TOUCH_IID"], closure)
        # COMMON_IID is an inheritance parent, NOT a dependency: it must NOT be
        # in the dependency closure.
        self.assertNotIn("COMMON_IID", closure)


# --------------------------------------------------------------------------
# COPY command generation.
#
# InstlClientCopy uses the DBManager singleton tables, so these tests construct
# a real (offline) client with a minimal set of initial_vars -- the same keys
# instl_main builds -- targeting Win to keep output deterministic across hosts
# (Mac targets emit extra chmod/chown commands keyed on uid/gid).
# --------------------------------------------------------------------------
SYNTHETIC_INFO_MAP = """\
src, d, 1
src/app.bin, f, 1, 1111111111111111111111111111111111111111, 100
src/AppBundle, d, 1
src/AppBundle/Contents, f, 1, 2222222222222222222222222222222222222222, 200
src/libdir, d, 1
src/libdir/lib.so, f, 1, 3333333333333333333333333333333333333333, 300
src/big.tar.wtar, f, 1, 4444444444444444444444444444444444444444, 1000
src/wtardir, d, 1
src/wtardir/pack.tar.wtar, f, 1, 5555555555555555555555555555555555555555, 700
"""


def _make_copy_client():
    initial_vars = {
        "__INSTL_DATA_FOLDER__": REPO_ROOT,
        "__INSTL_DEFAULTS_FOLDER__": "$(__INSTL_DATA_FOLDER__)/defaults",
        "__INSTL_EXE_PATH__": REPO_ROOT / "instl",
        "__ARGV__": [os.fspath(REPO_ROOT / "instl")],
        "__MAIN_DB_FILE__": ":memory:",
        # instl_main sets this from sys.frozen during a real boot; this test
        # constructs the client directly, so it must declare it itself
        "__INSTL_COMPILED__": "False",
        "__CURRENT_OS__": "Win",
        "__CURRENT_OS_SECOND_NAME__": "Win64",
        "__CURRENT_OS_NAMES__": ["Win", "Win64"],
        "TARGET_OS": "Win",
        "COPY_SOURCES_ROOT_DIR": "/sync/root",
        "__USER_ID__": -1,
        "__GROUP_ID__": -1,
        "ACTING_UID": -1,
        "ACTING_GID": -1,
        "VENDOR_NAME": "Waves Audio",
        "APPLICATION_NAME": "Waves Central",
    }
    from pyinstl.instlClientCopy import InstlClientCopy
    client = InstlClientCopy(initial_vars=initial_vars)
    return client


def _child_reprs(accum):
    """The exact pybatch command sequence an AnonymousAccum would emit."""
    return [repr(c) for c in accum.child_batch_commands]


def native_source(relative_path):
    """ A copy source under $(COPY_SOURCES_ROOT_DIR) as this platform writes it.
        The copy commands normalize the joined path when building repr(), so the
        separators come out native - backslashes on Windows - and a POSIX literal
        would never match here.
    """
    return os.path.normpath(os.path.join("$(COPY_SOURCES_ROOT_DIR)", relative_path))


class TestInstlClientCopyGolden(unittest.TestCase):
    """Pins the pybatch command(s) emitted for each source type against a
    synthetic info_map. Targets Win so output is host-independent.
    """

    def setUp(self):
        config_vars.clear()
        self.client = _make_copy_client()
        # clear any rows left by a previous test on the singleton table
        self.client.info_map_table.clear_all()
        self.client.info_map_table.files_read_list.clear()
        import tempfile
        tf = tempfile.NamedTemporaryFile(
            "w", suffix="-info_map.txt", delete=False, encoding="utf-8")
        tf.write(SYNTHETIC_INFO_MAP)
        tf.close()
        self._info_map_path = tf.name
        self.client.info_map_table.read_from_file(
            self._info_map_path, a_format="text", disable_indexes_during_read=True)
        self.client.init_copy_vars()

    def tearDown(self):
        try:
            self.client.info_map_table.clear_all()
        except Exception:
            pass
        try:
            os.unlink(self._info_map_path)
        except Exception:
            pass
        config_vars.clear()

    # ------------------------------------------------------------------
    def test_copy_file_command(self):
        accum = self.client.create_copy_instructions_for_file("src/app.bin", "TheApp 1.2.3")
        self.assertEqual(
            [f'CopyFileToDir(r"{native_source("src/app.bin")}", r".")'],
            _child_reprs(accum))
        # plain (non-wtar) file accrues its raw size.
        self.assertEqual(100, self.client.bytes_to_copy)

    def test_copy_dir_command(self):
        accum = self.client.create_copy_instructions_for_dir("src/AppBundle", "TheApp 1.2.3")
        self.assertEqual(
            [f'CopyDirToDir(r"{native_source("src/AppBundle")}", r".", delete_extraneous_files=True)'],
            _child_reprs(accum))

    def test_copy_dir_cont_command(self):
        accum = self.client.create_copy_instructions_for_dir_cont("src/libdir", "TheLib")
        self.assertEqual(
            [f'CopyDirContentsToDir(r"{native_source("src/libdir")}", r".")'],
            _child_reprs(accum))

    def test_copy_wtar_file_emits_unwtar(self):
        # a wtarred source ("big.tar" stored as "big.tar.wtar") must emit Unwtar,
        # NOT a plain copy.
        accum = self.client.create_copy_instructions_for_file("src/big.tar", "Big")
        self.assertEqual(
            [f'Unwtar(what_to_unwtar=r"{native_source("src/big.tar.wtar")}", where_to_unwtar=r".")'],
            _child_reprs(accum))

    def test_wtar_source_plans_the_bytes_its_unwtar_will_report(self):
        # Unwtar reports the archive's COMPRESSED size, so planning an expanded
        # estimate left an all-wtar install topping its own bar out below 100%.
        self.client.create_copy_instructions_for_file("src/big.tar", "Big")
        self.assertEqual(1000, self.client.bytes_to_copy)

    def test_dir_cont_of_only_wtar_items_plans_its_bytes(self):
        # this directory emits an Unwtar and nothing else; its bytes used to be
        # accumulated only when the directory ALSO held non-wtar items
        accum = self.client.create_copy_instructions_for_dir_cont("src/wtardir", "Packed")
        self.assertEqual(
            [f'Unwtar(what_to_unwtar=r"{native_source("src/wtardir")}", where_to_unwtar=r"..")'],
            _child_reprs(accum))
        self.assertEqual(700, self.client.bytes_to_copy)

    def test_copy_instructions_for_source_dispatches_on_tag(self):
        # the (source_path, tag) tuple form used by the per-iid copy loop.
        for tag, source_path, expected in (
                ("!file", "src/app.bin",
                 f'CopyFileToDir(r"{native_source("src/app.bin")}", r".")'),
                ("!dir", "src/AppBundle",
                 f'CopyDirToDir(r"{native_source("src/AppBundle")}", r".", delete_extraneous_files=True)'),
                ("!dir_cont", "src/libdir",
                 f'CopyDirContentsToDir(r"{native_source("src/libdir")}", r".")'),
        ):
            accum = self.client.create_copy_instructions_for_source((source_path, tag), "x")
            self.assertEqual([expected], _child_reprs(accum), f"tag={tag}")

    def test_unknown_source_tag_raises(self):
        with self.assertRaises(ValueError):
            self.client.create_copy_instructions_for_source(("src/app.bin", "!bogus"), "x")


# ==========================================================================
# NOTES -- what these goldens DO and DO NOT pin (read before refactoring):
#
# PINNED hermetically:
#   * inheritance flattening (COMMON_IID action -> LIB_IID),
#   * iid -> (source_path, tag) mapping incl. os-name prefixing when all oses
#     are active (get_sources_for_iid),
#   * direct + recursive dependency expansion (get_recursive_dependencies):
#     APP_IID -> LIB_IID -> TOUCH_IID, and that inheritance parents are NOT
#     dependencies,
#   * the exact pybatch command repr for each source type:
#       !file       -> CopyFileToDir
#       !dir        -> CopyDirToDir(..., delete_extraneous_files=True)
#       !dir_cont   -> CopyDirContentsToDir
#       wtarred !file -> Unwtar
#     plus tag dispatch in create_copy_instructions_for_source and the
#     ValueError on an unknown tag, and bytes_to_copy accrual for a plain file.
#
# NOT pinned hermetically (documented gap):
#   * The full end-to-end create_copy_instructions batch (the whole
#     batch_accum tree, stages, progress, require-file + have-info-map copies):
#     it depends on a synced repo layout on disk (HAVE_INFO_MAP_COPY_PATH,
#     SITE_HAVE_INFO_MAP_PATH), the active-iid status tables populated by the
#     full command init, and Mac-only chmod/chown/symlink resolution keyed on
#     real uid/gid -- none of which are stubbable offline without inventing a
#     fake filesystem. We pin the largest deterministic sub-steps instead: the
#     per-source command generation (above) and graph resolution.
#   * Mac-target copy variants (extra ChmodAndChown / Chown / ResolveSymlink
#     commands) are intentionally NOT pinned: their output embeds host uid/gid
#     and would be non-deterministic across machines. Win target is used.
# ==========================================================================


if __name__ == "__main__":
    unittest.main()
