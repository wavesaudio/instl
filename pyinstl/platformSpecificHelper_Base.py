#!/usr/bin/env python2.7
from __future__ import print_function
import abc

class PlatformSpecificHelperBase(object):
    @abc.abstractmethod
    def get_install_instructions_prefix(self):
        """ platform specific """
        pass

    @abc.abstractmethod
    def get_install_instructions_postfix(self):
        """ platform specific last lines of the install script """
        pass

    @abc.abstractmethod
    def make_directory_cmd(self, directory):
        """ platform specific mkdir for install script """
        pass

    @abc.abstractmethod
    def change_directory_cmd(self, directory):
        """ platform specific cd for install script """
        pass

    @abc.abstractmethod
    def get_svn_folder_cleanup_instructions(self, directory):
        """ platform specific cleanup of svn locks """
        pass

    @abc.abstractmethod
    def create_var_assign(self, identifier, value):
        pass

    @abc.abstractmethod
    def create_echo_command(self, message):
        pass

    @abc.abstractmethod
    def create_remark_command(self, remark):
        pass

def PlatformSpecificHelperFactory(in_os):
    if in_os == "Mac":
        import platformSpecificHelper_Mac
        retVal = platformSpecificHelper_Mac.PlatformSpecificHelperMac()
    elif in_os == "Win":
        import platformSpecificHelper_Win
        retVal = platformSpecificHelper_Win.PlatformSpecificHelperWin()
