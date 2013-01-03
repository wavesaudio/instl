# dump the HEAD revision to a dump file
svnadmin dump --revision HEAD repos/V9 > V9-dumpfile

# filter only the Win part to another dump file
svndumpfilter include Win < V9-dumpfile > V9-dumpfile-win

# filter only the Mac part to another dump file
svndumpfilter include Mac < V9-dumpfile > V9-dumpfile-mac

# create the new Win only repository
svnadmin create V9-Win
svnadmin load  V9-Win < V9-dumpfile-win

# create the new Mac only repository
svnadmin create V9-Mac
svnadmin load V9-Mac < V9-dumpfile-mac