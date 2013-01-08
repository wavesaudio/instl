Mapping and definition file format
##################################

**instl** client needs two type of data to operate:

#. **Mapping** of installation items to svn repository locations and to folders on disk. The mapping will typically be stored as a file on the svn server and will be updated when ever the svn repository is updated. During installation the mapping will be copied to the user's machine and passed as parameter to the **instl** client.

#. **Definitions** of variables used in the mapping. Definitions will typically be produced, on the user's machine, by the software that controls the **instl** client. For example the user might make choices by checking checkboxes and pressing "install" will create the definition file and call **instl** client.

Both types of data, Mapping and Definitions are formated as Yaml documents and can be placed in the same file or in different files. Sections of mapping and definitions can be mixed in the same file.

Mapping section format
----------------------
    The mapping part must start with the line:
    ::
        --- !install
    After which the will be zero or more items identifying installation parts, such as:
    ::
        PRODUCT_A:
            name: Product Type 'A'
            inherit:
                - GENERAL_PRODUCT_INSTALL_DEF
            install_sources: Products/Product-A.app/
            install_folders: $(APPLICATIONS_FOLDER)
            depends:
                - ZIP_DLL
                - FLIP_DLL
                - DOCUMENTAION
    **PRODUCT_A**
        The identifier for the item. Other items can refer to it by this identifier. It must be unique. Identifiers can include any combination of alpha numeric characters and the character'_'. They are case sensitive, although it is customary to use only upper case characters.

        *name*
            A human readable naming for the item, it has no part in the install process, but might appear in error message, log files etc.

        *inherit*
            A list of unique identifiers of other items. These items will be merged with the current item. Inheritance is useful in making and changing features common to several items at once.

        *install_sources*
            A list of partial paths into the svn repository. These paths will be pulled from the repository to the user's disk during installation. The left part of the path must be supplied in the definitions section.

        *install_folders*
            List of folders where the *install_sources* will be copied to. Typically there will be only one, but if more than one is found *install_sources* will copied to each of them.

        *depends*
            is a list of identifiers of items that must be installed when the current item is installed.

    Notes:

    #.  All the fields are optional, but it would be meaningless to omit them all.
    #.  The term 'list' means one or more items. A list can be a yaml scalar or sequence. The following are all valid lists:
        ::
            depends: ZIP_DLL

            depends:
                - ZIP_DLL

            depends:
                - ZIP_DLL
                - FLIP_DLL


Definitions file format
-------------------
    The mapping part must start with the line:
    ::
        --- !define
    After which the will be zero or more items with definitions.
