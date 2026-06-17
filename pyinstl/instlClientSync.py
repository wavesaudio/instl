#!/usr/bin/env python3.12


from configVar import config_vars
from .instlClient import InstlClient
from .instlException import InstlFatalException


class InstlClientSync(InstlClient):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.read_defaults_file(super().__thisclass__.__name__)
        self.calc_user_cache_dir_var()
        self.action_type_to_progress_message.update({'pre_sync': "pre_sync step", 'post_sync': "post_sync step"})

    def do_sync(self):
        repo_type_defined = "REPO_TYPE" in config_vars
        repo_type = config_vars.get("REPO_TYPE", "URL").str()
        # REPO_TYPE can only be "URL", other types were not maintained or used in many years.
        # creating a sync class according to REPO_TYPE is only left here as an example format
        # if and when different sync class would be required.
        match repo_type:
            case "URL":
                from .instlInstanceSync_url import InstlInstanceSync_url
                syncer = InstlInstanceSync_url(self)
            case "BOTO":
                from .instlInstanceSync_boto import InstlInstanceSync_boto
                syncer = InstlInstanceSync_boto(self)
            case "SVN":
                from .instlInstanceSync_svn import InstlInstanceSync_svn
                syncer = InstlInstanceSync_svn(self)
            case "P4":
                from .instlInstanceSync_p4 import InstlInstanceSync_p4
                syncer = InstlInstanceSync_p4(self)
            case _:
                # REPO_TYPE was present but holds a value we do not support.
                # The old message ("REPO_TYPE is not defined") was misleading
                # in this branch since the variable IS defined here.
                if repo_type_defined:
                    raise InstlFatalException(
                        f"Cannot sync: unsupported REPO_TYPE '{repo_type}'.",
                        "Supported values are: URL, BOTO, SVN, P4 (URL is the maintained default).",
                        "Check the REPO_TYPE definition in the installation input file.")
                else:
                    raise InstlFatalException(
                        "Cannot sync: REPO_TYPE is not defined in the installation input file.",
                        "Define REPO_TYPE (e.g. 'URL') so instl knows how to fetch the files.")

        syncer.init_sync_vars()
        self.batch_accum.set_current_section('sync')

        self.batch_accum += self.accumulate_unique_actions_for_active_iids('pre_sync')
        syncer.create_sync_instructions()
        self.batch_accum += self.accumulate_unique_actions_for_active_iids('post_sync')
