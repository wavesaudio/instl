.. _code:

Code documentation
==================

Module instl
------------
.. module:: instl
:synopsis: Module instl implements the starting point (main function) for instl.
   
.. function:: main()

    The main entry into **instl**.
    Here command line options are read and instl is invoked in either interactive or batch mode. Here is also where the current os in detected and imports are made accordingly.

.. function:: run_instl_instructions()

    Normally the process that launched **instl** will run the batch file that was created. If the --run command line option was given **instl** will run the batch file.
    `run_instl_instructions` implements this functionality. The file to run is the file who's path is in `__MAIN_RUN_INSTALLATION__` variable.

.. data:: current_os

    Holds the current os discovered by a calling `platform.system()`. Values are either 'mac' or 'win'.
    
    
Module instlInstanceBase
------------------------
.. module:: instlInstanceBase
:synopsis: Module `instlInstanceBase` is the where most of **instl** functionality is implemented, it has one principle class InstlInstanceBase. 

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