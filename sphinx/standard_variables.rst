Standard Varables
#################

Required user supplied variables
================================
These variable must be supplied by the used in the !define file. These are written to the output scripts.

    * MAIN_INSTALL_TARGETS: List of IIDs required by the user to be installed.
    * SYNC_BASE_URL: Main URL of the Subversion reprository.

Optional user supplied variables
================================
These variable can be supplied by the used in the !define file, but have deafult values. These are written to the output scripts.

    * BASE_SRC_URL: Base Subversion URL for all install_sources sections in the index file. Defaults to "$(SYNC_BASE_URL)/$(TARGET_OS)". 
    * BOOKKEEPING_DIR_URL: Subversion URL for the folder holding the index file. Defaults to "$(SYNC_BASE_URL)/instl"
    * COPY_TOOL: The commandline tool used to copy files. Deafault to 'rsync' on Mac and 'robocopy' on Windows.
    * CURRENT_OS: The os **instl** is currently running on. Values are 'Win' for Windows and 'Mac' for Mac OS.
    * LOCAL_SYNC_DIR: The folder where **instl** will sync the installation sources to. Defaults to the systam's temporary folder.
    * REPO_NAME: The part of SYNC_BASE_URL representing the name of the repository. Defaults to the last URL element of SYNC_BASE_URL.
    * REPO_REV: The version of the subversion reprository to sync. defaults to HEAD.
    * SYNC_LOG_FILE: Path to a file where sync log will be written. Defaults to "${LOCAL_SYNC_DIR}/${REPO_NAME}/"+time.time()+"sync.log.
    * TARGET_OS: The os **instl** is installing to.  Values are 'Win' for Windows and 'Mac' for Mac OS. Defaults to CURRENT_OS.
    
Public **instl** created variables
=================================
These variables are creaedt internally by **instl** and are writtent to the output script.
    * REL_BOOKKIPING_PATH: The path element to added to SYNC_BASE_URL to create BOOKKEEPING_DIR_URL. Calculeted by **instl**.
    * REL_SRC_PATH: The path element to added to SYNC_BASE_URL to create BASE_SRC_URL. Calculeted by **instl**.

Private **instl** created variables
==================================
These variables are created by **instl** at runtime and are not printed to the output scripts.

    * __FULL_LIST_OF_INSTALL_TARGETS__: List of all the iids to install. Created by following dependencies of iids in MAIN_INSTALL_TARGETS variable.
    * __INSTL_VERSION__: List of thee numbers of the current version of instl.
    * __MAIN_INPUT_FILES__: List of files specified on the command line with the '--in' option.
    * __MAIN_INPUT_FILES_ACTUALLY_OPENED__: list of input files that were actually read.
    * __MAIN_OUT_FILE__: The output file specified on the command line with the '--out' option.
    * __MAIN_RUN_INSTALLATION__: If set true or yes, current out file will be executed after it is written.
    * __MAIN_STATE_FILE__: File to dump the current state of **instl**. Optional.
    * __ORPHAN_INSTALL_TARGETS__: List of iids that where part of MAIN_INSTALL_TARGETS but did not appear in the index file.
    * __SEARCH_PATHS__: A list of paths where **instl** looks for files read through '__include__'. The folder of the main file is automatically added and so are folders of other files that are read.
