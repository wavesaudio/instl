:mod:`instl` --- Main executable
================================

.. module:: instl
   :synopsis: Module instl implements the starting point (main function) for instl.

.. index:: module: instl

**Source code:** :source:`instl`
   

.. function:: main()

    The main entry into **instl**.
    Here command line options are read and instl is invoked in either interactive or batch mode. Here is also where the current os in detected and imports are made accordingly.

.. function:: run_instl_instructions()

    Normally the process that launched **instl** will run the batch file that was created. If the --run command line option was given **instl** will run the batch file.
    `run_instl_instructions` implements this functionality. The file to run is the file who's path is in `__MAIN_RUN_INSTALLATION__` variable.

.. data:: current_os

    Holds the current os discovered by a calling `platform.system()`. Values are either 'Mac' or 'Win'.
