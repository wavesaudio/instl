import instlInstanceBase

class InstlInstance(instlInstanceBase.InstlInstanceBase):
    def __init__(self):
        super(InstlInstance, self).__init__()
        self.var_replacement_pattern = "%\g<var_name>%"

    def get_install_instructions_prefix(self):
        pass

    def get_install_instructions_postfix(self):
        pass

    def make_directory_cmd(self, directory):
        return " ".join(("mkdir", '"'+directory+'"'))

    def change_directory_cmd(self, directory):
        return " ".join(("cd", '"'+directory+'"'))
