Motivation
##########

The motivation for creating **instl** grow out of frustration with existing installer builder tools for wide spread desktop operating systems such as Mac OS or Windows.
    
What's wrong with existing installer builders?
---------------------------------------------- 
#. Cross-platform: No high quality tools exist for creating cross-platform installers. Products distributed for both Mac and Windows usually have a lot in common. Using separate installer builders for each platform requires, for example, to define and maintain all dependencies twice in different formats. 
#. File formats: Each installer builder has different format for defining an installer and many times these are not text based formats. Compering Mac and Windows definitions or even to previous versions in the same platform is usually impossible.
#. Version control: Developers are accustomed to using version control for all sources required to build a software product. However, the build products themselves also have versions that need to be tracked. 
#. Scalability: While creating a small installer with conventional tools is easy, managing large or complicated installers is exponentially harder. Other scalability needs are to easily create variations on existing installers or partial installers and propagating changes done in the main installer to it's derivatives.
#. Programming languages: Installer builders usually provide a programming language. Such languages are never cross-platform and usually are limited in their functionality and not well documented.
    
How does **instl** improves the situation?
------------------------------------------ 
#. Cross platform: **instl** uses one database for Mac only, Windows only and common files. Online users activate the same installer for mac or Windows and get only the subset suitable for their platform. Offline users can download one installer use it for both Mac and Windows installations.
#. File formats: **instl** uses YAML as it's file format, this means that all files are easily searchable and comparable.
#. Version control: **instl** uses SubVersion as database for all installables. This makes updating the installer for new versions very straight forward and gives users the ability to mix and match different versions of the same product. If you do not want users to have a choice about which version to install - this can also ne achieved easily.
#. Scalability: Since **instl** is text based duplicating or making variations is very easy. Full cycle propagation of changes is also a non issue. 
#. Programming languages: **instl** is implemented in python, but since it mainly deals with text files - any programming language can be used to implement advanced features and modifications.