#!/bin/sh

# creates subversion repositories, one for each main version.

# The folder when the repos folder will be placed.
BASE_SVN_FOLDER="/Volumes/SvnSrv"

# prepare the main folder and log file
mkdir -p ${BASE_SVN_FOLDER}/repos
mkdir -p ${BASE_SVN_FOLDER}/repos/logs
touch ${BASE_SVN_FOLDER}/repos/logs/log.txt

# start the server, -- root options tells the server to only look at this folder,
# and all svn urls will be relative to this folder.
# if svnserve already runs - kill it first.
svnserve -d --log-file ${BASE_SVN_FOLDER}/repos/logs/log.txt --root ${BASE_SVN_FOLDER}/repos

svnadmin create --fs-type fsfs ${BASE_SVN_FOLDER}/repos/V8
svnadmin create --fs-type fsfs ${BASE_SVN_FOLDER}/repos/V9
svnadmin create --fs-type fsfs ${BASE_SVN_FOLDER}/repos/V10

# adjust permissions in svnserve.conf files, for each repository.
