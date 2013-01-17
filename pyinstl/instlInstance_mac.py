import os

import instlInstanceBase
import configVar

class InstlInstance(instlInstanceBase.InstlInstanceBase):
    def __init__(self):
        super(InstlInstance, self).__init__()
        self.var_replacement_pattern = "${\g<var_name>}"
        
    def get_install_instructions_prefix(self):
        return ("#!/bin/sh", "SAVE_DIR=`pwd`")

    def get_install_instructions_postfix(self):
        return (" ".join(("cd", '"$(SAVE_DIR)"')), "exit 0")

        

