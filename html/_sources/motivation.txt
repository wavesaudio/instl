Moivation
##########

The motivation for creating **instl** grow out of frustration with existing installer builder tools for wide spread desktop operating systems such as Mac OS or Windows.

What's wrong with existing installer builders?
----------------------------------------------
#. **Cross-platform:** Products distributed for both Mac and Windows usually have a lot in common. Using separate installer builders for each platform requires to define and maintain all dependencies twice in different formats.
#. **File formats:** Each installer builder has different format for defining an installer and many times these are not text based formats. Compering Mac and Windows definitions or even to previous versions in the same platform is usually impossible.
#. **Version control:** Developers are accustomed to using version control for all sources required to build a software product. However, the build products (which are the installation sources) themselves also have versions that need to be tracked.
#. **Scalability:** While creating a small installer with conventional tools is easy, managing large or complicated installers is exponentially harder. Other scalability needs are to easily create variations on existing installers or partial installers and propagating changes done in the main installer to it's derivatives.
#. **Discoverability:** INstallation builder that create a closed-box binary installers are hard to understand and debug. If something is not working at the use's end, it's virtually impossible to understand what went wrong.
#. **Programming languages:** Installer builders usually provide a programming language. Such languages are never cross-platform and usually are limited in their functionality and are not well documented.

How does **instl** improves the situation?
------------------------------------------
#. **Cross-platform:** **instl** uses one database for Mac, Windows and common files. Module content adn dependencies between modules can be expressed only once for all platforms, even if the actual files installed are different.
#. **File formats:** **instl** uses YAML as it's file format, this means that all files are plain text and therefor easily searchable and comparable.
#. **Version control:** **instl** uses SubVersion as database for all installable files. This makes updating the installer for new versions very straight forward.
#. **Scalability:** Since **instl** file format is text based, duplicating or making variations is very easy. Full cycle propagation of changes is also a non issue.
#. **Discoverability:**
            * All configuration and index files are written in plain-text format and so are easy to understand and debug.

            * All processing stages are written to intermediate plain-text files and so are easy to understand and debug.

            * Installation sources are kept in their original format under their original name.
#. **Programming languages:** **instl** is implemented in python, but since it mainly deals with text files - any programming language can be used to implement advanced features and modifications.
