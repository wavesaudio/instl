import instlInstanceBase

class InstlInstance(instlInstanceBase.InstlInstanceBase):

    def create_install_instructions_prefix(self):
        self.install_instruction_lines.append("#!/bin/sh\n")
        self.install_instruction_lines.append("\nSAVE_DIR=`pwd`\n")


    def create_install_instructions_postfix(self):
        self.install_instruction_lines.append("\ncd '${SAVE_DIR}'")
        self.install_instruction_lines.append("exit 0\n")
