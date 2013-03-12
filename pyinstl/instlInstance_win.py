import instlInstanceBase
import os

def quoteme(to_qoute):
    return "".join( ('"', to_qoute, '"') )

class InstlInstance_win(instlInstanceBase.InstlInstanceBase):
    def __init__(self):
        super(InstlInstance_win, self).__init__()
        self.var_replacement_pattern = "%\g<var_name>%"

    def get_install_instructions_prefix(self):
        return ("SET SAVE_DIR=%CD%", )

    def get_install_instructions_postfix(self):
        return ("chdir /d %SAVE_DIR%", )

    def make_directory_cmd(self, directory):
        mk_command = " ".join( ("mkdir", '"'+directory+'"'))
        return (mk_command, )
 
    def change_directory_cmd(self, directory):
        cd_command = " ".join( ("cd", '"'+directory+'"') )
        return (cd_command, )

    def get_svn_folder_cleanup_instructions(self):
        return ()

    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        copy_command = " ".join( ("robocopy", src_dir, trg_dir, "/XD .svn", "/E") )
        retVal.append(copy_command)
        return retVal

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        src_dir, src_file = os.path.split(src_file)
        copy_command = " ".join( ("robocopy", src_dir, trg_dir, src_file) )
        return (copy_command, )

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        copy_command = " ".join( ("robocopy", src_dir, trg_dir, "/E", "/XD .svn") )
        return (copy_command, )
    
    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        copy_command = " ".join( ("robocopy", src_dir, trg_dir, "/XD .svn", "/LEV:1") )
        return (copy_command, )
        
    def create_var_assign(self, identifier, value):
        return "SET "+identifier+'='+value

    def create_echo_command(self, message):
        echo_command = " ".join(('echo', quoteme(message)))
        return echo_command

