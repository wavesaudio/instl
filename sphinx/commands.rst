.. raw:: html

   <META HTTP-EQUIV="refresh" CONTENT="1">

.. _commands:

##################
**instl** commands
##################

instl is the command line tool for installing and creating installers.  Its functionality is offered via a collection of task-specific commands, most of which accept a number of options for fine-grained control of the program's behavior.
Basic

When using the instl program, commands must appear after the program name on the command line. Options, may appear anywhere on the command line after the program name and the command name, and in general, their order is irrelevant. For example, all of the following are valid ways to use instl sync, and are interpreted in exactly the same way::

$ instl sync --in my_install.yaml --out sync.bat
$ instl sync --out sync.bat --in my_install.yaml

The following are not valid because the command (sync) does not appear right after the program name::

$ instl --in my_install.yaml sync --out sync.bat
$ instl --out sync.bat --in my_install.yaml sync

The following sections describe each of the various subcommands and options provided by the instl command-line client program, including some examples of each subcommand's typical uses.


.. toctree::
    :maxdepth: 1

    sync <commands/sync>
    commands/copy
    commands/synccopy
    commands/trans
    commands/create-links
    commands/up2s3
    commands/version
    commands/help

