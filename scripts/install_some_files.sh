#!/bin/sh

SVN_INSTALL_SERVER=localhost
WAVES_PLUGINS_FOLDER='/Volumes/Shmates/Waves Plug-Ins'
PROTOOLS_PLUGINS_FOLDER='/Library/Application Support/Digidesign/Plug-Ins'

SVN_PLUGINS_FOLDER='Mac/Plugins'
SVN_SHELLS_FOLDER='Mac/Shells'
SVN_VERSION_FOLDER=V9

mkdir -p "${WAVES_PLUGINS_FOLDER}"
cd "${WAVES_PLUGINS_FOLDER}"
svn checkout --revision HEAD svn://${SVN_INSTALL_SERVER}/${SVN_VERSION_FOLDER}/${SVN_PLUGINS_FOLDER}/AudioTrack.bundle
svn checkout --revision HEAD svn://${SVN_INSTALL_SERVER}/${SVN_VERSION_FOLDER}/${SVN_PLUGINS_FOLDER}/C1.bundle
svn checkout --revision HEAD svn://${SVN_INSTALL_SERVER}/${SVN_VERSION_FOLDER}/${SVN_PLUGINS_FOLDER}/Center.bundle


mkdir -p "${PROTOOLS_PLUGINS_FOLDER}"
cd "${PROTOOLS_PLUGINS_FOLDER}"
svn checkout "svn://${SVN_INSTALL_SERVER}/${SVN_VERSION_FOLDER}/${SVN_SHELLS_FOLDER}/WaveShell-DAE 9.0.dpm"
