# Introduction

Welcome to *instl: installation without magic* the instl manual. **instl** is a tool for creating installers.

**instl** is written in the python programming language but no knowledge of python is required in order to create installers or use them.

**instl** uses SubVersion as it's back-end database for storing installation sources. Some knowledge SubVersion is required in order to setup an installer.

**instl** is published as Open Source under BSD license.

Supported platforms: Mac OS X, Windows, Linux

# Motivation
The motivation for creating **instl** grow out of frustration with existing installer builder tools for wide spread desktop operating systems such as Mac OS or Windows.

## What's wrong with existing installer builders?

1. **Cross-platform:** Products distributed for both Mac and Windows usually have a lot in common. Using separate installer builders for each platform requires to define and maintain all dependencies twice in different formats.
1. **File formats:** Each installer builder has different format for defining an installer and many times these are not text based formats. Compering Mac and Windows definitions or even to previous versions in the same platform is usually impossible.
1. **Version control:** Developers are accustomed to using version control for all sources required to build a software product. However, the build products (which are the installation sources) themselves also have versions that need to be tracked.
1. **Scalability:** While creating a small installer with conventional tools is easy, managing large or complicated installers is exponentially harder. Other scalability needs are to easily create variations on existing installers or partial installers and propagating changes done in the main installer to it's derivatives.
1. **Discoverability:** Installation builder that create a closed-box binary installers are hard to understand and debug. If something is not working at the use's end, it's virtually impossible to understand what went wrong.
1. **Programming languages:** Installer builders usually provide a proprietary programming language. Such languages are not cross-platform and usually limited in their functionality and not well documented.

##How does instl improves the situation?
1. **Cross-platform:** **instl** uses one database for Mac, Windows and common files. Module content and dependencies between modules can be expressed only once for all platforms, even if the actual files installed are different.
1. **File formats:** **instl** uses YAML as it's file format, this means that all files are plain text and therefor easily searchable and comparable.
1. **Version control:** **instl** uses SubVersion as database for all installable files. This makes updating the installer for new versions very straight forward.
1. **Scalability:** Since **instl** file format is text based, duplicating or making variations is very easy. Full cycle propagation of changes is also a non issue.
1. **Discoverability:**
    * Configuration and index files are written in plain-text format and so are easy to understand and debug.
    * Processing stages are written to intermediate plain-text files and so are easy to understand and debug.
    * Installation sources are kept in their original format under their original name.
1. **Programming languages:** **instl** is implemented in python and any extension can be written in python using almost all of python's echosystem.

# What to expect (and what not to expect)

## **instl** doesn't...
* Create a GUI for the installer. If you need to inquire the user for choices and decisions, you will also need to create your own GUI application wrapper around **instl**.
* Have a GUI for the developer of installers. All work is done in a text editor and on the command line. We think that this is a big advantage, especially for large or complicated projects.
* Interact intimately with the operating system. For example, writting to Windows' registry is done by issuing CMD commands.
* Does not implement all functionality found in full grown installers. Unique or special install steps, such as installing drivers, can be done in conventional installer tools and be triggered by **instl**.

**instl** is...
---------------
* Open source and uses open source tools in it's implementation. **instl** license allows for commercial usage, but you need to check if the **instl** license and the license of the tools used by **instl** are suitable for you.
* Relies on specifc buildin tools of the operting system, e.g. Robocopy on Window or curl on MacOS.
