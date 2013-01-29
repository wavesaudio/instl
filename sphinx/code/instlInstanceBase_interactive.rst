

:mod:`InstlInstanceBase_interactive` --- Interactive mode implementation
==============================================================================

:synopsis: Implements the interactive mode of **instl**. 

.. module:: instlInstanceBase

.. index:: module: instlInstanceBase

**Source code:** :source:`pyinstl/instlInstanceBase_interactive.py`

Methods
-------

.. method:: insensitive_glob(pattern)

    Helper function to enable case insensitive directory completion.

.. method:: go_interactive(instl_inst)

    The gateway to interactive mode. This function is the interface :class:`InstlInstanceBase` calls this function to pass control interactive mode code in :file:`instlInstanceBase_interactive.py`.

.. class:: instlCMD
    
    Overrides :class:`cmd.Cmd` and implements all the interactive mode commands as do_command_name methods. Also implements complete_command_name methods and help_command_name methods.
    
    .. attribute:: instl_inst
    
        The instance of instlInstanceBase to work with.
        
    .. method:: __init__
    
        Initialised :class:`cmd.Cmd`.
        
        Initialised :attr:`instl_inst`.
        
    .. method:: __enter__(self)
    .. method:: __exit__(self, type, value, traceback)
        
        Enable the usage of :class:`instlCMD` as a context_manager_.

.. _context_manager: http://docs.python.org/2/reference/datamodel.html#with-statement-context-managers

