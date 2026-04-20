#!/usr/bin/env python3.12

import unittest
from pathlib import Path


class TestOrganizerSecurityHardening(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[3]
        cls.organizer_paths = (
            repo_root / "wls/Central/res/external/data/organizer.py",
            repo_root / "wls/Central/buildResources/data/organizer.py",
        )

    def test_exec_is_not_using_module_globals(self):
        for organizer_path in self.organizer_paths:
            content = organizer_path.read_text(encoding="utf-8")
            self.assertNotIn("exec(py_compiled, globals())", content, organizer_path)
            self.assertIn("execution_globals = {", content, organizer_path)
            self.assertIn("exec(py_compiled, execution_globals)", content, organizer_path)

    def test_batch_output_path_is_validated(self):
        for organizer_path in self.organizer_paths:
            content = organizer_path.read_text(encoding="utf-8")
            self.assertIn("def validate_batch_output_name(main_out_file):", content, organizer_path)
            self.assertIn("if any(c in main_out_file for c in (", content, organizer_path)
            self.assertIn("def resolve_batch_output_path(script_folder, main_out_file):", content, organizer_path)
            self.assertIn("if out_path_candidate.is_absolute():", content, organizer_path)
            self.assertIn("if out_file_realpath.suffix.lower() != \".py\":", content, organizer_path)

    def test_generated_script_integrity_is_checked(self):
        for organizer_path in self.organizer_paths:
            content = organizer_path.read_text(encoding="utf-8")
            self.assertIn("if py_text != generated_script:", content, organizer_path)
            self.assertIn("raise RuntimeError(f\"Batch script was unexpectedly modified before execution:", content, organizer_path)

    def test_shell_string_construction_removed_for_icon_attr(self):
        for organizer_path in self.organizer_paths:
            content = organizer_path.read_text(encoding="utf-8")
            self.assertIn("def add_folder_icon_attr_command(batch_accum, dst_folder, src_path):", content, organizer_path)
            self.assertIn("batch_accum += Subprocess(set_icon_tool, target_folder, \"--force\", ignore_all_errors=True)", content, organizer_path)
            self.assertIn("batch_accum += Subprocess(\"attrib\", \"+S\", target_folder, ignore_all_errors=True)", content, organizer_path)
            self.assertNotIn("f'''\\'{config_vars['SET_ICON_TOOL_PATH']}\\' \\'{item['dst']}/{path.name}\\' --force'''", content, organizer_path)
            self.assertNotIn("ShellCommand(f'''attrib +S \"{item['dst']}/{path.name}\"'''", content, organizer_path)
            self.assertIn("Cleaner.add_folder_icon_attr_command(batch_accum, item['dst'], path)", content, organizer_path)


if __name__ == "__main__":
    unittest.main()
