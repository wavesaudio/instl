Example
#######

Basic
=======

*Acme* is and application with versions for Mac and Windows.
For version 1.0 the svn server structure would look like this:
::
    Acme_Installer/
    index.txt
    |_  Mac/
       |_ Acme.app/
          |_ Contents/
             Info.plist
             |_ MacOS/
                   Acme
             |_ Resources/
                   Acme.icns
                   ....
    |_ Win/
        Acme/
            Acme.exe
            Acme.ico
        ....

The index.txt file would be:
::
    ACME_GUID:
        name: Acme 1.0
        mac:
            install_from:
                - Acme.app/
        win:
            install_from:
                - Acme/
        install_folders: $(APPLICATIONS_FOLDER)

Adding a file
===============

Later a pdf of documentation was added.
In order for the extra file to be installed at the user's machine the file should be added to svn, and the server would looks like:
::
    Acme_Installer/
    index.txt
    |_  Mac/
       |_ Acme.app/
          |_ Contents/
             Info.plist
             |_ MacOS/
                   Acme
             |_ Resources/
                   Acme.icns
                   Acme.pdf
                   ....
    |_ Win/
        Acme/
            Acme.exe
            Acme.ico
            Acme.pdf
        ....

There is not need to change the index.txt file. The next time the user will run **instl** svn would detect the missing files and add them to the user's disk.

Going complicated
=================

Acme software decided to add choice of some plugins that the user can add to the product.
The different from basic installation is that the user now can choose to install all, some or nine of the plugins.
Acme is now at version 2.0, and the extra file were added to svn repository:
::
    Acme_Installer/
    index.txt
    |_  Mac/
       |_ Acme.app/
          |_ Contents/
             Info.plist
             |_ MacOS/
                   Acme
             |_ Resources/
                   Acme.icns
                   Acme.pdf
                   ....
       |_ Acme Plugins
            sing_a_song.dylib
            ring_a_bell.dylib
            set_the_tone.dylib

    |_ Win/
        Acme/
            Acme.exe
            Acme.ico
            Acme.pdf
            |_ Acme Plugins
                sing_a_song.dylib
                ring_a_bell.dylib
                set_the_tone.dylib


The index file would need to be expanded to allow for the various options and dependencies:
::
    ACME_GUID:
        name: Acme 2.0
        mac:
            install_from:
                - Acme.app/
            install_folders: $(APPLICATIONS_FOLDER)
        win:
            install_from:
                - !file Acme.exe
                - !file Acme.ico
                - !file Acme.pdf
            install_folders: $(APPLICATIONS_FOLDER)/Acme
    PLUGIN_DEFAULT_GUID:
        name: Acme 2.0 plugins
        depends: ACME_GUID
        install_folders: "$(APPLICATIONS_FOLDER)/Acme Plugins"
    SING_A_SONG_GUID:
        name: Sing a song Acme plugin
        mac:
            install_from:
                - !file sing_a_song.dylib
        win:
            install_from:
                - !file sing_a_song.dll
    RING_A_BELL_GUID:
        name: Ring a bell Acme plugin
        mac:
            install_from:
                - !file ring_a_bell.dylib
        win:
            install_from:
                - !file ring_a_bell.dll
    SET_THE_TONE_GUID:
        name: Set the tone Acme plugin
        mac:
            install_from:
                - !file set_the_tone.dylib
        win:
            install_from:
                - !file set_the_tone.dll

Bundling
========
Acme management has decided to bundle together two plugins and sell them as the *Art of Noise* bundle.
All needs to be done is to add the following to the index.txt file:
::
    ART_OF_NOISE_BUNDLE_GUID:
        depends:
              - SING_A_SONG_GUID
              - RING_A_BELL_GUID

Users choosing to install *Art of Noise* bundle will get the Acme application together with the two plugins.

