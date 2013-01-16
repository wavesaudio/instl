import os

import instlInstanceBase
import configVar

class InstlInstance(instlInstanceBase.InstlInstanceBase):

    def create_install_instructions_prefix(self):
        self.install_instruction_lines.append("#!/bin/sh")
        self.install_instruction_lines.append(os.linesep)
        self.install_instruction_lines.append("SAVE_DIR=`pwd`")
        self.install_instruction_lines.append(os.linesep)


    def create_install_instructions_postfix(self):
        self.install_instruction_lines.append(os.linesep)
        self.install_instruction_lines.append(" ".join(("cd", configVar.DereferenceVar("SAVE_DIR"))))
        self.install_instruction_lines.append("exit 0")
        self.install_instruction_lines.append(os.linesep)
