File formats: index and definition
##################################

**instl** client needs two types of data to operate:

#. **index** of installation items, their svn repository locations, and folders on disk where each item is to be installed, along with other information about how to install the item. The index will typically be stored as a file on the svn server and will be updated whenever the svn repository is updated. Another important feature of the index is *dependencies* - where an item can be required to be installed before another item. During installation the index will be copied to the user's machine and passed as parameter to the **instl** client.

#. **Definitions** of variables used in the index. Definitions will typically be produced, on the user's machine, by the software that controls the **instl** client. For example the user might make choices by checking checkboxes and pressing "install" will create the definition file and call **instl** client.

Both types of data, index and Definitions are formated as Yaml documents and can be placed in the same file or in different files. Sections of index and definitions can be mixed in the same file.

Index format
----------------------
    The index part must start with the line:
    ::
        --- !index
    After which the will be zero or more items identifying installation parts, such as:
    ::
        PRODUCT_A:
            name: Product Type 'A'
            inherit:
                - GENERAL_PRODUCT_INSTALL_DEF
            install_from: Products/Product-A.app/
            install_folders: $(APPLICATIONS_FOLDER)
            actions_before: touch "$(HOME)/Desktop/PRODUCT_A_Before"
            actions_after:
                    - touch "$(HOME)/Desktop/PRODUCT_A_After1"
                    - touch "$(HOME)/Desktop/PRODUCT_A_After2"
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

        *install_from*
            A list of partial paths into the svn repository. These paths will be pulled from the repository to the user's disk during installation. The left part of the path must be supplied in the definitions section.

        *actions_before*
            List of actions to perform before copying the install_from.

        *actions_after*
            List of actions to perform after copying the install_from.

        *install_folders*
            List of folders where the *install_from* will be copied to. Typically there will be only one, but if more than one folder is found *install_from* will copied to each of them.

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


Definitions format
-------------------
    The definitions part must start with the line:
    ::
        --- !define
    After which the will be zero or more items with definitions such as:
    ::
        SVN_SERVER: http://svn.mydomain.com/
        TARGET_INSTALLTION_FOLDER: /Users/name/myapp

    Values can be either a single value of a list, However, in the definitions part, if list is given, it is joined into a single value at runtime
    So:
    ::
        TARGET_ARCHITECTURES:
                        - i386
                        - x64

    is identical to:
    ::
        TARGET_ARCHITECTURES: i386 x64


