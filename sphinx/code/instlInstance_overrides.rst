:mod:`InstlInstanceBase derivatives` --- Platform specific Overrides
=======================================================


Class InstlInstance_mac
------------------------------------------------------------

.. module:: instlInstance_mac
   :synopsis: Module `instlInstance_mac` implements :class:`InstlInstance_mac` by overriding :class:`instlInstanceBase.InstlInstanceBase` with Mac OSX specific code.

.. index:: module: instlInstance_win

**Source code:** :source:`pyinstl/instlInstance_mac.py`

.. class: InstlInstance_mac

    Inherits from :class:`instlInstanceBase.InstlInstanceBase` and overrides several methods required for Mac OSX platform specific behaviour.

    .. method:: __init__(self)

        Calls :func:`instlInstanceBase.InstlInstanceBase.__init__` and also assign Mac os suitable regular expression to :attr:`instlInstanceBase.InstlInstanceBase.var_replacement_pattern`.

    .. method:: get_install_instructions_prefix(self)

        Creates the first lines of the install batch file for Mac OSX. Overrides :func:`instlInstanceBase.InstlInstanceBase.get_install_instructions_prefix`.
    
    .. method:: get_install_instructions_postfix(self)

        Creates the last lines of the install batch file for Mac OSX. Overrides :func:`instlInstanceBase.InstlInstanceBase.get_install_instructions_postfix`.

    .. method:: make_directory_cmd(self, directory)
    
        Creates Mac OSX mkdir command for install script. Overrides :func:`instlInstanceBase.InstlInstanceBase.make_directory_cmd`.

    .. method:: change_directory_cmd(self, directory)
    
        Creates Mac OSX change dir command for install script. Overrides :func:`instlInstanceBase.InstlInstanceBase.change_directory_cmd`.

Class InstlInstance_win
------------------------------------------------------------

.. module:: instlInstance_win
   :synopsis: Module `instlInstance_win` implements :class:`InstlInstance_win` by overriding :class:`instlInstanceBase.InstlInstanceBase` with Windows specific code.

.. index:: module: instlInstance_win

**Source code:** :source:`pyinstl/instlInstance_win.py`

.. class: InstlInstance_win()

    Inherits from :class:`instlInstanceBase.InstlInstanceBase` and overrides several methods required for Windows platform specific behaviour.
 
    .. method:: __init__(self)

        Calls :func:`instlInstanceBase.InstlInstanceBase.__init__` and also assign Windows suitable regular expression to :attr:`instlInstanceBase.InstlInstanceBase.var_replacement_pattern`.
    
    .. method:: get_install_instructions_prefix(self)

        Creates the first lines of the install batch file for Windows. Overrides :func:`instlInstanceBase.InstlInstanceBase.get_install_instructions_prefix`.
        
    .. method:: get_install_instructions_postfix(self)

        Creates the last lines of the install batch file for Windows. Overrides :func:`instlInstanceBase.InstlInstanceBase.get_install_instructions_postfix`.

    .. method:: make_directory_cmd(self, directory)
        
        Creates Windows mkdir command for install script. Overrides :func:`instlInstanceBase.InstlInstanceBase.make_directory_cmd`.

    .. method:: change_directory_cmd(self, directory)
        
        Creates Windows change dir command for install script. Overrides :func:`instlInstanceBase.InstlInstanceBase.change_directory_cmd`.
