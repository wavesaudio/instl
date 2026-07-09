# Creation time: 02-07-26_16-26
import os
import sys
sys.path.append(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl")
import logging
log = logging.getLogger(__name__)
import utils
from configVar import config_vars
utils.set_acting_ids(config_vars.get("ACTING_UID", -1).int(), config_vars.get("ACTING_GID", -1).int())
from pybatch import *
PythonBatchCommandBase.total_progress = 48
PythonBatchCommandBase.running_progress = 7
if __name__ == '__main__':
    from utils import log_utils
    log_utils.config_logger()

with Stage(r"assign", prog_num=8):
    config_vars['ACCEPTABLE_YAML_DOC_TAGS'] = (r"define_Mac", r"define_Mac64", r"define_if_not_exist_Mac", r"define_if_not_exist_Mac64")
    config_vars['ACTING_GID'] = 418804322
    config_vars['ACTING_UID'] = 34474270
    config_vars['ADD_MANIFEST'] = r"False"
    config_vars['APPLICATION_NAME'] = r"Waves Central"
    config_vars['APPS_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Apps"
    config_vars['BASE_REPO_REV'] = 1
    config_vars['BATCH_EXT'] = r"py"
    config_vars['BINARIES_DIR_NAME'] = r"MacOS"
    config_vars['BUILD_NUMBER'] = r"by vitaliz"
    config_vars['BUILD_NUMBER_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XcodeBuildProducts/__AUTO_BUILD_NUMBER__.txt"
    config_vars['BUNDLE_EXTENSION'] = r".bundle"
    config_vars['CONFIG'] = ""
    config_vars['CONFIGURATION'] = r"Debug"
    config_vars['CONFIG_ROOT_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug"
    config_vars['CONFIG_VAR_NAME_ENDING_DENOTING_PATH'] = (r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/_DIR", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/_PATH")
    config_vars['CURRENT_DOIT_DESCRIPTION'] = r"Doing it"
    config_vars['DB_FILE_EXT'] = r"sqlite"
    config_vars['DEVELOPER_ID'] = r"Developer ID Application: Waves Inc (GT6E3XD798)"
    config_vars['DLL_EXTENSION'] = r".dylib"
    config_vars['DONT_WRITE_CONFIG_VARS'] = (r"__CREDENTIALS__", r"__HELP_SUBJECT__", r"__INSTL_DATA_FOLDER__", r"__INSTL_DEFAULTS_FOLDER__", r"__USER_TEMP_DIR__", r"AWS_.+", r"INDEX_SIG", r"INFO_MAP_SIG", r"PUBLIC_KEY", r"SVN_REVISION", r".+_template", r"template_.+", r"Clean_old_plist_Native_NI")
    config_vars['Default_CheckInternalVersions'] = r"$(Default_PluginLoadSpec_PluginLoadSpec_CheckInternalVersions)"
    config_vars['Default_PluginFolderHint'] = r"$(Default_PluginLoadSpec_PluginLoadSpec_PluginFolderHint)"
    config_vars['Default_ScanDepth'] = r"$(Default_PluginLoadSpec_PluginLoadSpec_ScanDepth)"
    config_vars['ENTITLEMENTS_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/build_instl/entitlements.mac.plist"
    config_vars['EXECUTABLE_ORIGINAL_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/$(PROJECT_COMPLETED_PRODUCT_PATH)/Contents/MacOS/$(EXECUTABLE_ORIGINAL_NAME)"
    config_vars['EXIT_ON_EXEC_EXCEPTION'] = r"True"
    config_vars['FIX_ALL_PERMISSIONS_SYMBOLIC_MODE'] = r"u+rwx,go+rx"
    config_vars['FIX_PERMISSIONS'] = r'chmod -R a+rwX "$(__FIX_PERMISSIONS_1__)"'
    config_vars['ICON_EXTENSION'] = r".icns"
    config_vars['INSTL_BUNDLE_NAME'] = r"instl"
    config_vars['INSTL_BUNDLE_NAME_WITH_VERSION'] = r"instl 2.6.3.7"
    config_vars['INSTL_COMMA_VERSION'] = r"2,6,3,7"
    config_vars['INSTL_EXEC_DISPLAY_NAME'] = r"instl"
    config_vars['INSTL_ICON_NAME'] = r"instl.icns"
    config_vars['INSTL_PRODUCT_NAME'] = r"instl"
    config_vars['INSTL_REQUIREMENTS_CURRENT_OS_TXT'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/requirements_mac_only.txt"
    config_vars['INSTL_REQUIREMENTS_TXT'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/requirements.txt"
    config_vars['INSTL_SOURCE_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl"
    config_vars['INSTL_SRC_DEFAULTS'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/defaults"
    config_vars['INSTL_SRC_HELP'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/help"
    config_vars['INSTL_TARGET_BUNDLE'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle"
    config_vars['INSTL_TARGET_BUNDLE_CONTENTS'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents"
    config_vars['INSTL_TARGET_BUNDLE_DEFAULTS'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/Resources/defaults"
    config_vars['INSTL_TARGET_BUNDLE_EXEC'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/MacOS/instl"
    config_vars['INSTL_TARGET_BUNDLE_HELP'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/Resources/help"
    config_vars['INSTL_TARGET_BUNDLE_IDENTIFER'] = r"com.WavesAudio.instl.2.6.3.7"
    config_vars['INSTL_TARGET_BUNDLE_INFO'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/info.xml"
    config_vars['INSTL_TARGET_BUNDLE_INSTL_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/MacOS"
    config_vars['INSTL_TARGET_BUNDLE_RESOURCE'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/Resources"
    config_vars['INSTL_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools"
    config_vars['INSTL_TEMP_BUNDLE'] = r"build_instl/temp_build_dir/instl"
    config_vars['INSTL_TEMP_BUNDLE_EXEC'] = r"build_instl/temp_build_dir/instl"
    config_vars['INSTL_VERSION_CHANGE_REASON'] = r"Download UX/perf enhancements and codebase modernization"
    config_vars['INSTL_VIRTUAL_ENVIRONMENT_BINARIES_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/venv/bin"
    config_vars['INSTL_VIRTUAL_ENVIRONMENT_BINARIES_DIR_NAME'] = r"bin"
    config_vars['INSTL_VIRTUAL_ENVIRONMENT_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/venv"
    config_vars['INSTL_VIRTUAL_ENVIRONMENT_PYTHON'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/venv/bin/python3.12"
    config_vars['INSTL_VIRTUAL_ENVIRONMENT_PYTHON_ORIGINAL'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/venv/bin/python.exe"
    config_vars['INSTL_VIRTUAL_ENVIRONMENT_VERSIOIN'] = r"16.2.0"
    config_vars['IOMODULES_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/IOModules"
    config_vars['LAB_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/__LAB__"
    config_vars['LAST_PROGRESS'] = 0
    config_vars['LIBRARY_APPSUPPORT_DIR'] = r"/Library/Application Support/Waves"
    config_vars['MAIN_DOIT_ITEMS'] = r"INSTL_BUILD"
    config_vars['MAIN_INSTALL_TARGETS'] = r"INSTL_BUILD"
    config_vars['MIXER_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Mixer"
    config_vars['MKDIR_SYMBOLIC_MODE'] = 493
    config_vars['MODULES_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Modules"
    config_vars['Mac_ALL_OS_NAMES'] = r"Mac"
    config_vars['NO_HARD_LINK_PATTERNS'] = r"*"
    config_vars['NUM_DIGITS_PER_FOLDER_REPO_REV_HIERARCHY'] = 0
    config_vars['NUM_DIGITS_REPO_REV_HIERARCHY'] = 0
    config_vars['PLATFORM_DIR_NAME'] = r"MacOS"
    config_vars['PLUGINS_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Plugins"
    config_vars['PRINT_COMMAND_TIME'] = r"yes"
    config_vars['PRODUCT_TEMP_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XcodeBuildProducts/$(PROJECT_NAME).build/Debug/$(PRODUCT_NAME)"
    config_vars['PROJECT_BUILD_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XcodeBuildProducts/$(PROJECT_NAME).build/Debug"
    config_vars['PROJECT_COMPLETED_PRODUCTS_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XcodeBuildProducts/$(PROJECT_NAME).build/Debug/Products"
    config_vars['PROJECT_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central"
    config_vars['PROJECT_ORIGINAL_CODE_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/Code"
    config_vars['PROJECT_ORIGINAL_RESOURCES_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/Resources"
    config_vars['PRO_AUDIO_BIN_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/bin/Mac"
    config_vars['PRO_AUDIO_DIR'] = r"/Users/vitaliz/source/Central/ProAudio"
    config_vars['PYTHON_BATCH_LOG_LEVEL'] = 20
    config_vars['PYTHON_EXE_BINARY_NAME'] = r"python3.12"
    config_vars['READ_YAML_FILES'] = (r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults/main.yaml", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults/compile-info.yaml", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults/InstlDoIt.yaml", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/build_instl/Build-index.yaml", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults/main.yaml", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/__postbuild__/postbuild-common.yaml")
    config_vars['REPO_REV_FILE_BASE_NAME'] = r"$(REPO_NAME)_repo_rev.yaml"
    config_vars['REPO_REV_FILE_SPECIFIC_NAME'] = r"$(REPO_NAME)_repo_rev.yaml.$(TARGET_REPO_REV)"
    config_vars['RESOLVE_TEMPLATE_IN_XML_FILE'] = r"""ShellCommand(r'''"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../bin/Mac/xmlman" --in "$(__RESOLVE_TEMPLATE_IN_XML_FILE_1__)" --out "$(__RESOLVE_TEMPLATE_IN_XML_FILE_2__)" --template''', message="Resolve XML templates in $(__RESOLVE_TEMPLATE_IN_XML_FILE_1__)")"""
    config_vars['RESOURCE_FROM_FILE'] = r'CopyFileToFile(r"$(__RESOURCE_FROM_FILE_1__)", r"$(PRODUCT_TARGET_DIR)/$(PRODUCT_NAME)$(TARGET_WRAPPER_EXTENSION)/Contents/Resources/$(__RESOURCE_FROM_FILE_2__)/$(__RESOURCE_FROM_FILE_3__)")'
    config_vars['RESOURCE_FROM_FILE_IF_EXIST'] = r'CopyFileToFile(r"$(__RESOURCE_FROM_FILE_IF_EXIST_1__)", r"$(PRODUCT_TARGET_DIR)/$(PRODUCT_NAME)$(TARGET_WRAPPER_EXTENSION)/Contents/Resources/$(__RESOURCE_FROM_FILE_IF_EXIST_2__)/$(__RESOURCE_FROM_FILE_IF_EXIST_3__)", ignore_if_not_exist=True)'
    config_vars['ROOT_BUILD_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XcodeBuildProducts"
    config_vars['ROOT_PROJECT_BUILD_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XcodeBuildProducts/$(PROJECT_NAME).build"
    config_vars['ROOT_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products"
    config_vars['S3_SECURE_URL_EXPIRATION'] = 86400
    config_vars['SEARCH_PATHS'] = ""
    config_vars['SHELLS_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Shells"
    config_vars['SIGN_INSTL_SCRIPT'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/build_instl/sign_instl.py"
    config_vars['SPECIAL_BUILD_IN_IIDS'] = (r"__ALL_ITEMS_IID__", r"__ALL_GUIDS_IID__", r"__UPDATE_INSTALLED_ITEMS__", r"__REPAIR_INSTALLED_ITEMS__")
    config_vars['TARGET_BINARIES_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/$(PRODUCT_TARGET_DIR)/$(PRODUCT_NAME)$(TARGET_WRAPPER_EXTENSION)/Contents/MacOS"
    config_vars['TARGET_CONTENTS_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/$(PRODUCT_TARGET_DIR)/$(PRODUCT_NAME)$(TARGET_WRAPPER_EXTENSION)/Contents"
    config_vars['TARGET_EXEC_EXTENSION'] = ""
    config_vars['TARGET_EXEC_NAME'] = r"$(PRODUCT_NAME)"
    config_vars['TARGET_INFO_PLIST_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/$(PRODUCT_TARGET_DIR)/$(PRODUCT_NAME)$(TARGET_WRAPPER_EXTENSION)/Contents/Info.plist"
    config_vars['TARGET_OS'] = r"Mac"
    config_vars['TARGET_OS_NAMES'] = (r"Mac", r"Mac64", r"MacArm")
    config_vars['TARGET_OS_SECOND_NAME'] = r"Mac64"
    config_vars['TARGET_RESOURCES_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/$(PRODUCT_TARGET_DIR)/$(PRODUCT_NAME)$(TARGET_WRAPPER_EXTENSION)/Contents/Resources"
    config_vars['TARGET_TEMP_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/build_instl"
    config_vars['TARGET_WRAPPER_BASE_NAME'] = r"$(PRODUCT_NAME)"
    config_vars['TARGET_WRAPPER_NAME'] = r"$(PRODUCT_NAME)$(TARGET_WRAPPER_EXTENSION)"
    config_vars['TARGET_WRAPPER_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/$(PRODUCT_TARGET_DIR)/$(PRODUCT_NAME)$(TARGET_WRAPPER_EXTENSION)"
    config_vars['TAR_MANIFEST_FILE_NAME'] = r"__TAR_CONTENT__.txt"
    config_vars['TEMP_BUILD_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/build_instl/temp_build_dir"
    config_vars['TOOLS_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools"
    config_vars['TOTAL_ITEMS_FOR_PROGRESS_REPORT'] = 37
    config_vars['USER'] = r"vitaliz"
    config_vars['USER_NAME'] = r"vitaliz"
    config_vars['VENDOR_NAME'] = r"Waves Audio"
    config_vars['VERSION'] = r"2.6.3.7"
    config_vars['VERSIONS_XML_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/WavesLib/Scripts/Versions.xml"
    config_vars['VERSIONS_YAML_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/WavesLib/Scripts/Versions.yaml"
    config_vars['WHO_LOCKS_FILE_DLL_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools\who_locks_file.dll"
    config_vars['WPAPI_TARGET_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/WPAPI"
    config_vars['WRITE_CONFIG_VARS_READ_FROM_ENVIRON_TO_BATCH_FILE'] = r"yes"
    config_vars['WZLIB_EXTENSION'] = r".wzip"
    config_vars['Win_ALL_OS_NAMES'] = (r"Win", r"Win32", r"Win64")
    config_vars['XMLMAN_PATH'] = r"/Users/vitaliz/source/Central/ProAudio/bin/Mac/xmlman"
    config_vars['XPLATFROM_DIR'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform"
    config_vars['ZLIB_COMPRESSION_LEVEL'] = 8
    config_vars['__ARGV__'] = (r"instl", r"doit", r"--in", r"../wls/Central/build_instl/Build-index.yaml", r"--out", r"build_instl/build-instl.py", r"--run", r"--no-system-log")
    config_vars['__COMMAND_NAMES__'] = (r"activate-repo-rev", r"check-checksum", r"check-instl-folder-integrity", r"checksum", r"collect-manifests", r"command-list", r"copy", r"depend", r"doit", r"dump-config-vars", r"exec", r"fail", r"file-sizes", r"fix-perm", r"fix-props", r"fix-symlinks", r"gui", r"help", r"ls", r"parallel-run", r"read-info-map", r"read-yaml", r"remove", r"report-versions", r"resolve", r"run-process", r"short-index", r"stage2svn", r"svn2stage", r"sync", r"synccopy", r"test-import", r"translate-guids", r"translate_url", r"uninstall", r"unwtar", r"up-short-index", r"up2s3", r"verify-index", r"verify-repo", r"version", r"wait-on-action-trigger", r"wtar", r"wtar-staging-folder", r"wzip")
    config_vars['__COMPILATION_TIME__'] = r"2026-07-02 16:22:20.337705"
    config_vars['__CURRENT_OS_DESCRIPTION__'] = r"macOS 26.5.2"
    config_vars['__CURRENT_OS_NAMES__'] = (r"Mac", r"Mac64", r"MacArm")
    config_vars['__CURRENT_OS_SECOND_NAME__'] = r"Mac64"
    config_vars['__CURRENT_OS__'] = r"Mac"
    config_vars['__CURR_WORKING_DIR__'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl"
    config_vars['__DATABASE_URL__'] = r":memory:"
    config_vars['__FULL_LIST_OF_DOIT_TARGETS__'] = (r"CLEAN_PREVIOUS_INSTL", r"CREATE_PIP_FREEZE_FILE", r"CREATE_COMPILE_INFO_FILE", r"PRINT_PIP_PACKAGES", r"COMPILE_INSTL", r"CREATE_BUNDLE", r"ADD_INFO_FILES", r"ADD_PYBATCH_HELP_FILE", r"ADD_VERSION_TO_INSTL_EXECUTABLES", r"ADD_ICON_TO_INSTL_BUNDLE", r"ADD_WHO_LOCKS_FILE_DLL", r"SIGN", r"INSTL_BUILD")
    config_vars['__GITHUB_BRANCH__'] = r"download-enhancements-cont"
    config_vars['__GROUP_ID__'] = 418804322
    config_vars['__INSTL_COMPILED__'] = r"False"
    config_vars['__INSTL_EXE_PATH__'] = r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/instl"
    config_vars['__INSTL_LAUNCH_COMMAND__'] = r'"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/instl"'
    config_vars['__INSTL_VERSION_STR_LONG__'] = r"instl version 2.6.3.7 2026-07-02 16:22:20.337705 vitaliz-mbp.local"
    config_vars['__INSTL_VERSION_STR_SHORT__'] = r"2.6.3.7"
    config_vars['__INSTL_VERSION__'] = (2, 6, 3, 7)
    config_vars['__INVOCATION_RANDOM_ID__'] = r"irthrrpsdddzhelb"
    config_vars['__JUST_WITH_NUMBER__'] = 0
    config_vars['__MAIN_COMMAND__'] = r"doit"
    config_vars['__MAIN_DB_FILE__'] = r":memory:"
    config_vars['__MAIN_INPUT_FILE__'] = r"../wls/Central/build_instl/Build-index.yaml"
    config_vars['__MAIN_OUT_FILE__'] = r"build_instl/build-instl.py"
    config_vars['__NOW__'] = r"2026-07-02 16:26:34.704219"
    config_vars['__PLATFORM_NODE__'] = r"vitaliz-mbp.local"
    config_vars['__PYSQLITE3_VERSION__'] = r"2.6.0"
    config_vars['__PYTHON_VERSION__'] = (3, 12, 0, r"final", 0)
    config_vars['__QUIET_UNTIL_ERROR__'] = r"False"
    config_vars['__RUN_BATCH__'] = r"True"
    config_vars['__SEARCH_PATHS__'] = (r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/build_instl", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults", r"/Users/vitaliz/source/Central/ProAudio/XPlatform/__postbuild__")
    config_vars['__SITE_CONFIG_DIR__'] = r"/Library/Application Support"
    config_vars['__SITE_DATA_DIR__'] = r"/Library/Application Support"
    config_vars['__SOCKET_HOSTNAME__'] = r"vitaliz-mbp.local"
    config_vars['__SQLITE_VERSION__'] = r"3.42.0"
    config_vars['__SUDO_USER__'] = r"no set"
    config_vars['__SYSTEM_LOG_FILE_PATH__'] = r"/Users/vitaliz/Library/Application Support/Waves Audio/Waves Central/Logs/instl/instl.log"
    config_vars['__USER_CONFIG_DIR__'] = r"/Users/vitaliz/Library/Application Support"
    config_vars['__USER_CONFIG_FILE_NAME__'] = r"instl_config.yaml"
    config_vars['__USER_CONFIG_FILE_PATH__'] = r"/Users/vitaliz/instl_config.yaml"
    config_vars['__USER_DATA_DIR__'] = r"/Users/vitaliz/Library/Application Support"
    config_vars['__USER_DESKTOP_DIR__'] = r"/Users/vitaliz/Desktop"
    config_vars['__USER_HOME_DIR__'] = r"/Users/vitaliz"
    config_vars['__USER_ID__'] = 34474270

with PythonBatchRuntime(r"doit", prog_num=9):
    with Stage(r"begin", prog_num=10):
        RsyncClone.add_global_ignore_patterns(config_vars.get("COPY_IGNORE_PATTERNS", []).list())
        RsyncClone.add_global_no_hard_link_patterns(config_vars.get("NO_HARD_LINK_PATTERNS", []).list())
        RsyncClone.add_global_no_flags_patterns(config_vars.get("NO_FLAGS_PATTERNS", []).list())
        RsyncClone.add_global_avoid_copy_markers(config_vars.get("AVOID_COPY_MARKERS", []).list())
        RemoveEmptyFolders.set_a_kwargs_default("files_to_ignore", config_vars.get("REMOVE_EMPTY_FOLDERS_IGNORE_FILES", []).list())
        log.setLevel(20)
    with Stage(r"pre_doit", prog_num=11):
        pass
    with Stage(r"doit", prog_num=12):
        with Stage(r"CLEAN_PREVIOUS_INSTL...", prog_num=13):
            # --- Begin CLEAN_PREVIOUS_INSTL CLEAN_PREVIOUS_INSTL
            with RmDir(r"build_instl/temp_build_dir", prog_num=14) as rm_dir_001_14:
                rm_dir_001_14()
            with MakeDirs(r"build_instl/temp_build_dir", prog_num=15) as make_dirs_002_15:
                make_dirs_002_15()
            with RmDir(r"$(INSTL_SOURCE_DIR/build)", prog_num=16) as rm_dir_003_16:
                rm_dir_003_16()
            with RmDir(r"$(INSTL_SOURCE_DIR/dist)", prog_num=17) as rm_dir_004_17:
                rm_dir_004_17()
            with RmDir(r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle", prog_num=18) as rm_dir_005_18:
                rm_dir_005_18()
            with MakeDirs(r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools", prog_num=19) as make_dirs_006_19:
                make_dirs_006_19()
            # --- End CLEAN_PREVIOUS_INSTL CLEAN_PREVIOUS_INSTL
        with Stage(r"CREATE_PIP_FREEZE_FILE...", prog_num=20):
            # --- Begin CREATE_PIP_FREEZE_FILE CREATE_PIP_FREEZE_FILE
            with ShellCommand(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/venv/bin/python3.12 -m pip freeze --disable-pip-version-check", out_file=r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/defaults/pip-freeze.txt", prog_num=21) as shell_command_007_21:
                shell_command_007_21()
            # --- End CREATE_PIP_FREEZE_FILE CREATE_PIP_FREEZE_FILE
        with Stage(r"CREATE_COMPILE_INFO_FILE...", prog_num=22):
            # --- Begin CREATE_COMPILE_INFO_FILE CREATE_COMPILE_INFO_FILE
            with Exec(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/build_instl/create-compile-info.py", args=[r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/defaults/compile-info.yaml"], prog_num=23) as exec_008_23:
                exec_008_23()
            # --- End CREATE_COMPILE_INFO_FILE CREATE_COMPILE_INFO_FILE
        with Stage(r"PRINT_PIP_PACKAGES...", prog_num=24):
            # --- Begin PRINT_PIP_PACKAGES PRINT_PIP_PACKAGES
            print("List installed packages:")
            with ShellCommand(r'"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/venv/bin/python3.12" -m pip list', prog_num=25, stderr_means_err=False) as shell_command_009_25:
                shell_command_009_25()
            # --- End PRINT_PIP_PACKAGES PRINT_PIP_PACKAGES
        with Stage(r"COMPILE_INSTL...", prog_num=26):
            # --- Begin COMPILE_INSTL COMPILE_INSTL
            with ShellCommand(r'"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/venv/bin/python3.12" "/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/build_instl/build_instl.py" --configuration Debug --instl-folder "/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl" --target-folder "build_instl/temp_build_dir"', prog_num=27) as shell_command_010_27:
                shell_command_010_27()
            # --- End COMPILE_INSTL COMPILE_INSTL
        with Stage(r"CREATE_BUNDLE...", prog_num=28):
            # --- Begin CREATE_BUNDLE CREATE_BUNDLE
            with CopyDirContentsToDir(r"build_instl/temp_build_dir/instl", r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/MacOS", copy_stat=True, prog_num=29) as copy_dir_contents_to_dir_011_29:
                copy_dir_contents_to_dir_011_29()
            with CopyDirContentsToDir(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/defaults", r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/Resources/defaults", copy_stat=True, prog_num=30) as copy_dir_contents_to_dir_012_30:
                copy_dir_contents_to_dir_012_30()
            with RmDir(r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/MacOS/_internal/Python.framework", prog_num=31) as rm_dir_013_31:
                rm_dir_013_31()
            with Glober(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/MacOS//_internal/*.dist-info", RmFile, r"path", prog_num=32) as glober_014_32:
                glober_014_32()
            with Glober(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/MacOS//_internal/setuptools/_vendor/*.dist-info", RmFile, r"path", prog_num=33) as glober_015_33:
                glober_015_33()
            # --- End CREATE_BUNDLE CREATE_BUNDLE
        with Stage(r"ADD_INFO_FILES...", prog_num=34):
            # --- Begin ADD_INFO_FILES ADD_INFO_FILES
            with CopyFileToFile(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/build_instl/Info.plist", r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/Info.plist", prog_num=35) as copy_file_to_file_016_35:
                copy_file_to_file_016_35()
            with Chmod(path=r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/Info.plist", mode="a+rw", prog_num=36) as chmod_017_36:
                chmod_017_36()
            with ReadConfigVarValueFromTextFile(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../XcodeBuildProducts/__AUTO_BUILD_NUMBER__.txt", r"BUILD_NUMBER", ignore_all_errors=True, prog_num=37) as read_config_var_value_from_text_file_018_37:
                read_config_var_value_from_text_file_018_37()
            with ResolveConfigVarsInFile(r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/Info.plist", config_files=[], prog_num=38) as resolve_config_vars_in_file_019_38:
                resolve_config_vars_in_file_019_38()
            # --- End ADD_INFO_FILES ADD_INFO_FILES
        with Stage(r"ADD_PYBATCH_HELP_FILE...", prog_num=39):
            # --- Begin ADD_PYBATCH_HELP_FILE ADD_PYBATCH_HELP_FILE
            with MakeDirs(r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/Resources/help", prog_num=40) as make_dirs_020_40:
                make_dirs_020_40()
            with ShellCommand(r"python3.12 /Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../instl/instl help pybatch-verbose > /Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/../../../../Products/Debug/Tools/instl.bundle/Contents/Resources/help/pybatch_help.txt", prog_num=41) as shell_command_021_41:
                shell_command_021_41()
            with CopyFileToDir(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/instl/help/helpHelper.py", r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/Resources/help", prog_num=42) as copy_file_to_dir_022_42:
                copy_file_to_dir_022_42()
            # --- End ADD_PYBATCH_HELP_FILE ADD_PYBATCH_HELP_FILE
        with Stage(r"ADD_ICON_TO_INSTL_BUNDLE...", prog_num=43):
            # --- Begin ADD_ICON_TO_INSTL_BUNDLE ADD_ICON_TO_INSTL_BUNDLE
            with CopyFileToFile(r"/Users/vitaliz/source/Central/ProAudio/XPlatform/CopyProtect/wls/Central/build_instl/instl.icns", r"/Users/vitaliz/source/Central/ProAudio/Products/Debug/Tools/instl.bundle/Contents/Resources/instl.icns", prog_num=44) as copy_file_to_file_023_44:
                copy_file_to_file_023_44()
            # --- End ADD_ICON_TO_INSTL_BUNDLE ADD_ICON_TO_INSTL_BUNDLE
        with Stage(r"sign instl...", prog_num=45):
            # --- Begin SIGN sign instl
            Print(r"not on build machine - not signing", prog_num=45)()
            # --- End SIGN sign instl
    with Stage(r"post_doit", prog_num=46):
        print("Done Doing it")

with Stage(r"epilog", prog_num=47):
    with PatchPyBatchWithTimings(r"build_instl/build-instl.py", prog_num=48) as patch_py_batch_with_timings_024_48:
        patch_py_batch_with_timings_024_48()

log.info("Shakespeare says: All's Well That Ends Well")
# eof


