Architecture
############



Server
======
Installation sources are kept on a Subversion server.
Typically this will be a linux server running Apache web server and Subversion server.
Such configuration can done on a dedicated server or one of the svn hosting services available.
Optionally, in order to speed up download times for users, a snapshot of the Subversion repository can be uploaded as static files to http server or cloud hosting services such as Amazon's S3.
The advantage of using a static snapshot is that it can be further optimize by using file caching services such as CloudFront or Akamai.


client
======
User of an installer created with **instl** will have to first download a package consisting of:

    **svn** client - if using direct SVN access

    OR:

    downloading agent such as wget or curl. Such agent may or may not be already installed on the user's computer.

    **instl** client. The python sources of **instl** can be provided, but that would make the installation process depends on the user having the exact python version installed. A better choice would be to pre-compile instl using tool such as Pyinstaller_, and provide the user with a stand alone binary instl client.


.. _Pyinstaller: http://www.pyinstaller.org/
