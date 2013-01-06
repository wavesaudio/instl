#!/bin/sh

# import fresh copies of all installable from the staging area. 
# assuming staging was created with the prepare_staging_folder_structure.py script
# assuming subversion repositories were created with the create_repositories.sh
# assuming subversion repositories are empty!

# The folder when the staging folders are.
BASE_SVN_FOLDER="/Volumes/SvnSrv/staging"

# Base url for subversion
SVN_BASE_URL="svn://localhost"

# remove Mac Icon\r files first
# separate importing to few stages to make it easier to handle problems
svn import ${BASE_SVN_FOLDER}/V10/Win/ ${SVN_BASE_URL}/V10/Win/ -m "Initial V10 Win import"
svn import ${BASE_SVN_FOLDER}/V10/Mac/ ${SVN_BASE_URL}/V10/Mac/ -m "Initial V10 Mac import"

svn import ${BASE_SVN_FOLDER}/V9/Win/ ${SVN_BASE_URL}/V9/Win/ -m "Initial V9 Win import"
svn import ${BASE_SVN_FOLDER}/V9/Mac/ ${SVN_BASE_URL}/V9/Mac/ -m "Initial V9 Mac import"

svn import ${BASE_SVN_FOLDER}/V8/Win/ ${SVN_BASE_URL}/V8/Win/ -m "Initial V8 Win import"
svn import ${BASE_SVN_FOLDER}/V8/Mac/ ${SVN_BASE_URL}/V8/Mac/ -m "Initial V8 Mac import"

# do we need "common" folder for large files that are common to Mac and windows?
