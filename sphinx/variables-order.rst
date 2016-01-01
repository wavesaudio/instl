Variable definition order
##################################

Variable are initialized in the following order:

#. **instl** code initializes variables depend on the environment at the time of execution. These are marked as internal variables by having a  dunder (double underscore) as a prefix and postfix to the variable name. These variables are constant and cannot be overriden. Some of these variable are:
    ::
    
        __INSTL_EXE_PATH__
        __CURR_WORKING_DIR__
        __INSTL_DATA_FOLDER__
        __INSTL_COMPILED__
        __PYTHON_VERSION__
        __COMMAND_NAMES__
        __CURRENT_OS__
        __CURRENT_OS_SECOND_NAME__
        __CURRENT_OS_NAMES__
        __SITE_DATA_DIR__
        __SITE_CONFIG_DIR__
        __USER_DATA_DIR__
        __USER_CONFIG_DIR__
        __USER_HOME_DIR__
        __USER_DESKTOP_DIR__


#. **instl** then reads it's internal main.yaml file which contain variables that are common to all commands. Some of these variable are:
    ::
    
        __INSTL_VERSION__
        TARGET_OS
        MKDIR_CMD
        BATCH_EXT
    
#. Next to be read an internal yaml file containing variables that are specific to the current command. The file is named after the python class implementing the command. So for admin commands the InstlAdmin.yaml is being read, and for client commands InstalClient.yaml is read. Some of the variables in InstalClient.yaml are:
    ::
        
        BOOKKEEPING_DIR_URL
        PARALLEL_SYNC
        LOCAL_SYNC_DIR

#. Now the local instl_config.yaml is read if one exists. This is an optional file that a user can place in the user folder in order to define or override variables and is typically used for development of **instl**, administration of **instl** repositories, or in rare cases fix problems for an end user. Such variables can be:
    ::
        
        __CREDENTIALS__
        LOCAL_REPOSITORIES_PATH
        LOCAL_SVN_CHECKOUT_PATH
        LOCAL_STAGE_CHECKOUT_PATH

#. Finally the file given to instl on the command line as "--in" option is being read. This file will contain the variable needed for the command, or contain __include__ statements to other files.


