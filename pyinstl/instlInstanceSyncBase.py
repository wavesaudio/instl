#!/usr/bin/env python2.7
from __future__ import print_function
import abc


class InstlInstanceSync(object):
    """  Base class for sync object .
    """
    __metaclass__ = abc.ABCMeta
    @abc.abstractmethod
    def init_sync_vars(self):
        """ sync specific initialisation of variables """
        pass

    @abc.abstractmethod
    def create_sync_instructions(self, installState):
        """ sync specific creation of sync instructions """
        pass
