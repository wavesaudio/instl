import instlInstanceBase

class InstlInstance_win(instlInstanceBase.InstlInstanceBase):
    def __init__(self):
        super(InstlInstance_win, self).__init__()
        self.var_replacement_pattern = "%\g<var_name>%"

    def get_install_instructions_prefix(self):
        return ()

    def get_install_instructions_postfix(self):
        return ()

    def make_directory_cmd(self, directory):
        return (" ".join(("mkdir", '"'+directory+'"')), )

    def change_directory_cmd(self, directory):
        return (" ".join(("cd", '"'+directory+'"')), )

    def get_svn_folder_cleanup_instructions(self):
        return ()

    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        retVal = list()
        head, tail = os.path.split(src_dir)
        tgr_dir = os.path.join(trg_dir, tails)
        retVal.append(self.make_directory_cmd(tgr_dir))
        retVal.append(" ".join( ("robocopy", "/E", src_dir, trg_dir) ))
        return retVal

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        retVal = (" ".join( ("robocopy", src_file, trg_dir) ), )
        return retVal

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        retVal = (" ".join( ("robocopy", "/E", src_dir, trg_dir) ), )
        return retVal
    
    def create_var_assign(self, identifier, value):
        return "SET "+identifier+'='+value
