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
    ACME_IDD:
        name: Acme 1.0
        Mac:
            install_sources:
                - Acme.app/
        Win:
            install_sources:
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
The different from basic installation is that the user now can choose to install all, some or none of the plugins.
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
    ACME_IDD:
        name: Acme 2.0
        Mac:
            install_sources:
                - Acme.app/
            install_folders: $(APPLICATIONS_FOLDER)
        Win:
            install_sources:
                - !file Acme.exe
                - !file Acme.ico
                - !file Acme.pdf
            install_folders: $(APPLICATIONS_FOLDER)/Acme
    PLUGIN_DEFAULT_IDD:
        name: Acme 2.0 plugins
        depends: ACME_IDD
        install_folders: "$(APPLICATIONS_FOLDER)/Acme Plugins"
    SING_A_SONG_IDD:
        name: Sing a song Acme plugin
        Mac:
            install_sources:
                - !file sing_a_song.dylib
        Win:
            install_sources:
                - !file sing_a_song.dll
    RING_A_BELL_IDD:
        name: Ring a bell Acme plugin
        Mac:
            install_sources:
                - !file ring_a_bell.dylib
        Win:
            install_sources:
                - !file ring_a_bell.dll
    SET_THE_TONE_IDD:
        name: Set the tone Acme plugin
        Mac:
            install_sources:
                - !file set_the_tone.dylib
        Win:
            install_sources:
                - !file set_the_tone.dll

Bundling
========
Acme management has decided to bundle together two plugins and sell them as the *Art of Noise* bundle.
All needs to be done is to add the following to the index.txt file:
::
    ART_OF_NOISE_BUNDLE_IDD:
        depends:
              - SING_A_SONG_IDD
              - RING_A_BELL_IDD

Users choosing to install *Art of Noise* bundle will get the Acme application together with the two plugins.

