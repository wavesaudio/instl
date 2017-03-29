

import os
from collections import defaultdict, OrderedDict

import utils
from configVar import var_stack
from pyinstl.installItem import iids_from_guids

class InstallItemLists(object):
    """ holds state for specific creating of install instructions """

    def __init__(self):
        self.__original_install_items = utils.unique_list()
        self.__root_install_items = utils.unique_list()
        self.__update_install_items = utils.unique_list()
        self.__full_install_items = utils.unique_list()
        self.__orphan_install_items = utils.unique_list()
        self.__install_items_by_target_folder = defaultdict(utils.unique_list)
        self.__no_copy_items_by_sync_folder = defaultdict(utils.unique_list)

    @property
    def original_install_items(self):
        """ return the original list of items to install as given in var MAIN_INSTALL_ITEMS"""
        return self.__original_install_items

    @original_install_items.setter
    def original_install_items(self, the_items):
        """ set the original list of items to install given from InstlClient """
        self.__original_install_items = the_items

    @property
    def root_install_items(self):
        """ return the original list of items to install with guids translated to iids """
        return self.__root_install_items

    @property
    def update_install_items(self):
        """ return the list of items that were marked for update """
        return self.__update_install_items

    @property
    def top_level_install_items(self):
        yield from self.__root_install_items
        yield from self.__update_install_items

    @property
    def full_install_items(self):
        """ return the list full of items to install including original, update and dependencies, excluding orphans """
        return self.__full_install_items

    @property
    def orphan_install_items(self):
        """ return the list of items to install that were not found in index """
        return self.__orphan_install_items

    @property
    def install_items_by_target_folder(self):
        """ return a dictionary mapping install destination folder to iid  """
        return self.__install_items_by_target_folder

    @property
    def no_copy_items_by_sync_folder(self):
        """ return a dictionary mapping sync folders to iid, for items that are not being copied  """
        return self.__no_copy_items_by_sync_folder

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['original_items'] = list(self.original_items)
        retVal['root_install_items'] = list(self.root_install_items)
        retVal['update_install_items'] = list(self.update_install_items)
        retVal['full_install_items'] = list(self.full_install_items)
        retVal['orphan_install_items'] = var_stack.ResolveVarToList("__ORPHAN_INSTALL_TARGETS__")
        retVal['install_items_by_target_folder'] = {folder: list(self.install_items_by_target_folder[folder]) for folder
                                                    in self.install_items_by_target_folder}
        retVal['no_copy_iids_by_sync_folder'] = list(self.no_copy_items_by_sync_folder)
        return retVal

    def sort_install_items_by_target_folder(self, instlObj):
        for IID in self.full_install_items:
            with instlObj.install_definitions_index[IID].push_var_stack_scope():
                folder_list_for_idd = [folder for folder in var_stack["iid_folder_list"]]
                if folder_list_for_idd:
                    for folder in folder_list_for_idd:
                        norm_folder = os.path.normpath(folder)
                        self.install_items_by_target_folder[norm_folder].append(IID)
                else:  # items that need no copy
                    for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                        source = var_stack.ResolveVarToList(source_var)
                        relative_sync_folder = instlObj.relative_sync_folder_for_source(source)
                        sync_folder = os.path.join("$(LOCAL_REPO_SYNC_DIR)", relative_sync_folder)
                        self.no_copy_items_by_sync_folder[sync_folder].append(IID)

    def calculate_full_install_items_set(self, instlObj):
        """ calculate the set of iids to install by starting with the root set and adding all dependencies.
            Initial list of iids should already be in self.root_install_items.
            If an install items was not found for a iid, the iid is added to the orphan set.
        """

        # root_install_items might have guid in it, translate them to iids

        for IID in self.original_install_items:
            # if IID is a guid iids_from_guid will translate to iid's, or return the IID otherwise
            iids_from_the_guid = iids_from_guids(instlObj.install_definitions_index, IID)
            if len(iids_from_the_guid) > 0:
                self.__root_install_items.extend(iids_from_the_guid)
            else:
                self.__orphan_install_items.append(IID)

        for IID in self.top_level_install_items:
            try:
                # all items in the root list are marked as required by themselves
                # instlObj.install_definitions_index[IID].__required_by.append(IID)
                instlObj.install_definitions_index[IID].get_recursive_depends(instlObj.install_definitions_index,
                                                                              self.__full_install_items,
                                                                              self.__orphan_install_items)
            except KeyError:
                self.__orphan_install_items.append(IID)

        self.sort_install_items_by_target_folder(instlObj)
