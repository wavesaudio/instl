instl sync command
####

instl sync -  creates instructions for syncing installation files to local disk.

Synopsis
========
::

    instl sync --in install_def.yaml --out sync.sh [--run]


Description
============

Running instl with the sync command will create a batch file with instructions for syncing installation files to local disk. All definitions and index entries are read from the input file specified after the --in option. The input file can (and probably will) contain __include__ statements to other files, usually a url for the main index.yaml for the installation repository.