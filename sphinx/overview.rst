Overview
########

    Creating an installer
    ---------------------
    Creating an installer require the following steps:
        #.  Create SubVersion repository containing the files to be installed.
        #.  Create an index of the repository by writing an index file, documenting information
            about the components to be installed and dependencies between them.
        #.  Make the SVN repository public on the internet

            OR:
        #.  Export the repository as static files via http or by using services such as Amazon S3.

    Using an installer
    ----------------------
    The user of an instl installer will need to:
        # Create a file describing what needs to be installed and providing locations for various folders and tools needed for installing.
        # Run the instl tool providing the file described above as input and creating a file with installation actions as output.
        # Run the output of the instl command.

    These actions need not be done manually be the user, as most users are not comfortable with using command line tools.
    Typically a GUI application will perform these steps for the user, letting the user choose what and where to install.
    Such GUI is beyond the scope of instl.