.. raw:: html

   <META HTTP-EQUIV="refresh" CONTENT="60">

.. _commands:

##################
**instl** commands
##################

instl is the command line tool for installing and creating installers.  Its functionality is offered via a collection of task-specific commands, most of which accept a number of command line options for fine-grained control of the program's behavior.
Basic

When using the instl program, commands must appear after the program name on the command line. Options, may appear anywhere on the command line after the program name and the command name, and in general, their order is irrelevant. For example, all of the following are valid ways to use instl sync, and are interpreted in exactly the same way::

$ instl sync --in my_install.yaml --out sync.bat
$ instl sync --out sync.bat --in my_install.yaml

The following are not valid because the command (sync) does not appear right after the program name::

$ instl --in my_install.yaml sync --out sync.bat
$ instl --out sync.bat --in my_install.yaml sync

The following sections describe each of the various subcommands and options provided by instl, including some examples of each subcommand's typical uses.

instl commands can be divided to three types

#. Client commands
These are commands the are used to install something. These commands can be either entered directly on the command line, or activated through a GUI application.
.. toctree::
    :maxdepth: 1

    sync <commands/sync>
    copy <commands/copy>
    synccopy <commands/synccopy>

#. Admin commands
These are commands used by an administrator to create and maintain an installer.
.. toctree::
    :maxdepth: 1

    commands/trans
    commands/create-links
    commands/up2s3

#. Misc commands
These are commands that do a specific job and are typically used internally by instl's other client or admin commands.
.. toctree::
    :maxdepth: 1

    commands/version
    commands/help

