:mod:`instlInstanceBase` --- instl base class
=============================================

.. module:: instlInstanceBase
    :synopsis: Module `instlInstanceBase` is the where most of **instl** functionality is implemented, it has one principle class InstlInstanceBase. 

.. index:: module: instlInstanceBase

**Source code:** :source:`pyinstl/instlInstanceBase.py`
   

Methods
-------

.. method:: prepare_args_parser()

    Prepares the command line argument parser for :class:`InstlInstanceBase`.
    
Class InstlInstanceBase
-----------------------

    .. class:: InstlInstanceBase
    
        InstlInstanceBase encapsulated the functionality of instl.
    
        InstlInstanceBase is inherited for the purpose of overriding platform specific functions. All inheritors from  InstlInstanceBase are called InstlInstance, the main module imports the appropriate one at run time, according to the current os.       
    
        .. attribute:: install_definitions_index
    
            A dictionary holding the index of install items.
    
        .. attribute:: cvl
    
            Object of type configVarList.ConfigVarList holding the variable definitions.
    
        .. attribute:: variables_assignment_lines
    
            A :class:`list` holding the lines to be written to the batch file, each line containing a variable definition. Function `create_variables_assignment` is responsible for creating these lines. 
    
        .. attribute:: install_instruction_lines
    
            A :class:`list` holding the lines to be written to the batch file, each line containing a install operation such as mkdir, or svn checkout. Function `create_install_instructions` is responsible for creating these lines. 

        .. attribute:: var_replacement_pattern

            A compiled regular expression stating how to convert $(ABC) style variable references to platform specific references such as %ABC% on Windows or ${ABC} on Mac. Initially :attr:`var_replacement_pattern` isn None, it must be assigned a real value by classes overriding :class:`InstlInstanceBase` such as :class:`instlInstance_mac.InstlInstance_mac` and :class:`instlInstance_win.InstlInstance_win`.

        .. method:: repr_for_yaml(self, what=None)

            Returns a :class:`list` of objects representing the current state of instl, in a format suitable for printing by :class:`augmentedYaml`. If parameter *what* is None, the list will contain two documents, one representing the define part, one representing the index part. If parameter *what* is a list of identifiers, only variables and index entries from the list are returned.
    

        .. method:: read_command_line_options(self, arglist=None)

            Parse the command line argument list. If *arglist* is non or contains no arguments, mode is changed to "interactive". Otherwise, if *arglist* has arguments, mode is "batch" and the arguments are parsed. Parser is created using :func:`prepare_args_parser`, and the parsing returns a :class:`cmd_line_options` object. Finally :func:`init_from_cmd_line_options` is called.

        .. method:: init_from_cmd_line_options(self, cmd_line_options_obj)

            Sets several variables according to the values given in the command line arguments. Called after the command line arguments were processed.
        +-------------------+---------------------------+---------------------------+
        | Cmd line option   | Variable                  | default                   |
        +===================+===========================+===========================+
        | files to read     | __MAIN_INPUT_FILES__      | Must be supplied          |
        +-------------------+---------------------------+---------------------------+
        | --out             | __MAIN_OUT_FILE__         | Output to stdout          |
        +-------------------+---------------------------+---------------------------+
        | --target          | __CMD_INSTALL_TARGETS__   | MAIN_INSTALL_TARGETS      |
        +-------------------+---------------------------+---------------------------+
        | --state           | __MAIN_STATE_FILE__       | None, optional            |
        +-------------------+---------------------------+---------------------------+
        | --run             | __MAIN_RUN_INSTALLATION__ | None, optional            |
        +-------------------+---------------------------+---------------------------+

        .. method:: digest(self)

            Called after reading all the input files. Initializes `__MAIN_INSTALL_TARGETS__` either from `__CMD_INSTALL_TARGETS__` (command line argument) or `MAIN_INSTALL_TARGETS` (from definitions file).

        .. method:: read_defines(self, a_node)
    
            Reads Yaml node containing variable definitions.

        .. method:: read_index(self, a_node)
    
            Reads Yaml node containing index items.
    
        .. method:: read_input_files(self)
    
            Reads the input files specified in variable `__MAIN_INPUT_FILES__`.
    
        .. method:: read_file(self, file_path)
    
            Reads a single yaml file. Calls :func:`read_defines` or :func:`read_index` according to the yaml tags in the file.
    
        .. method:: resolve(self)
    
            Resolve $() style references in variables. Calls :func:`ConfigVarList:resolve`. 
    
        .. method:: sort_install_instructions_by_folder(self)

            Returns a dictionary whose keys are folders and values are sets of IDDs of install targets that specified the folder as their `install_folder`. The targets are taken from the variable `__FULL_LIST_OF_INSTALL_TARGETS__`.    
    
        .. method:: create_install_list(self)

            Creates the variable `__FULL_LIST_OF_INSTALL_TARGETS__` and populates it's values with the full list of all targets that are marked for install. Initial list of targets is taken from the variable `__MAIN_INSTALL_TARGETS__`. The initial list is recursively seached for dependencies. Target IDDs that are referred to but are not in the index are added to the variable `__ORPHAN_INSTALL_TARGETS__`.
        
        .. method:: get_install_instructions_prefix(self)

            Creates the first lines of the install batch file. :func:`get_install_instructions_prefix` is overridden by platform-specific class that inherits from instlInstanceBase.
        
        .. method:: get_install_instructions_postfix(self)

            Creates the last lines of the install batch file. :func:`get_install_instructions_postfix` is overridden by platform-specific class that inherits from instlInstanceBase.

        .. method:: mkdir(self, directory)
        
            Creates platform specific mkdir command install script
            Overridden by :class:`instlInstance_mac.InstlInstance_mac` and  :class:`instlInstance_win.InstlInstance_win`.

        .. method:: cd(self, directory)
         
            Creates platform specific change dir command install script
            Overridden by :class:`instlInstance_mac.InstlInstance_mac` and  :class:`instlInstance_win.InstlInstance_win`.
    
        .. method:: create_variables_assignment(self)

            Creates the lines in the install batch file that assign values to variables. All variables in :attr:`cvl` are added to :attr:`variables_assignment_lines` except internal identifiers. internal identifiers are those beginning and ending in __, such as `__FULL_LIST_OF_INSTALL_TARGETS__`.
    
        .. method:: create_install_instructions(self)

            Creates the lines of the install batch file, by updating :attr:`install_instruction_lines`. Calls :func:`create_variables_assignment`, :func:`create_install_list`, :func:`sort_install_instructions_by_folder`. 
    
        .. method:: write_install_batch_file(self)

            Writes the install batch file to the path in variable `__MAIN_OUT_FILE__` or if it does not exist to stdout. Calls :func:`get_install_instructions_prefix`, :func:`get_install_instructions_postfix`, :func:`get_install_instructions_postfix`.
    
        .. method:: write_program_state(self)
    
            Writes the current state of instlInstance to the path in variable `__MAIN_STATE_FILE__` or if it does not exist to stdout.
    
        .. method:: evaluate_graph(self)

            Evaluates the install index. Attempts to find cycles in dependencies and find leafs - those items that do not depend on other items. Uses :class:`installItemGraph` to do it's work. Will only work if :class:`installItemGraph` can be loaded.
    
        .. method:: do_da_interactive(self)
    
            Activates **instl*'s interactive mode by calling :func:`instlInstanceBase_interactive.go_interactive`
    
 