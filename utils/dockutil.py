#!/usr/bin/python

#   Copyright 2008 Kyle Crawford

#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

#   Send bug reports and comments to kcrwfrd at gmail

# Possible future enhancements
# tie in with application identifier codes for locating apps and replacing them in the dock with newer versions?

import sys, plistlib, subprocess, os, getopt, re, pipes, tempfile, pwd, logging
import platform

import utils

log = logging.getLogger()

# default verbose printing to off
verbose = False
version = '2.0.2'


def usage(e=None):
    """Displays usage information and error if one occurred"""

    print("""usage:     %(progname)s -h
usage:     %(progname)s --add <path to item> | <url> [--label <label>] [ folder_options ] [ position_options ] [ plist_location_specification ] [--no-restart]
usage:     %(progname)s --remove <dock item label> | all [ plist_location_specification ] [--no-restart]
usage:     %(progname)s --move <dock item label>  position_options [ plist_location_specification ]
usage:     %(progname)s --find <dock item label> [ plist_location_specification ]
usage:     %(progname)s --list [ plist_location_specification ]
usage:     %(progname)s --restart
usage:     %(progname)s --version

position_options:
  --replacing <dock item label name>                            replaces the item with the given dock label or adds the item to the end if item to replace is not found
  --position [ index_number | beginning | end | middle ]        inserts the item at a fixed position: can be an position by index number or keyword
  --after <dock item label name>                                inserts the item immediately after the given dock label or at the end if the item is not found
  --before <dock item label name>                               inserts the item immediately before the given dock label or at the end if the item is not found
  --section [ apps | others ]                                   specifies whether the item should be added to the apps or others section

plist_location_specifications:
  <path to a specific plist>                                    default is the dock plist for current user
  <path to a home directory>
  --allhomes                                                    attempts to locate all home directories and perform the operation on each of them
  --homeloc                                                     overrides the default /Users location for home directories

folder_options:
  --view [grid|fan|list|automatic]                              stack view option
  --display [folder|stack]                                      how to display a folder's icon
  --sort [name|dateadded|datemodified|datecreated|kind]         sets sorting option for a folder view

Examples:
  The following adds TextEdit.app to the end of the current user's dock:
           %(progname)s --add /Applications/TextEdit.app

  The following replaces Time Machine with TextEdit.app in the current user's dock:
           %(progname)s --add /Applications/TextEdit.app --replacing 'Time Machine'

  The following adds TextEdit.app after the item Time Machine in every user's dock on that machine:
           %(progname)s --add /Applications/TextEdit.app --after 'Time Machine' --allhomes

  The following adds ~/Downloads as a grid stack displayed as a folder for every user's dock on that machine:
           %(progname)s --add '~/Downloads' --view grid --display folder --allhomes

  The following adds a url dock item after the Downloads dock item for every user's dock on that machine:
           %(progname)s --add vnc://miniserver.local --label 'Mini VNC' --after Downloads --allhomes

  The following removes System Preferences from every user's dock on that machine:
           %(progname)s --remove 'System Preferences' --allhomes

  The following moves System Preferences to the second slot on every user's dock on that machine:
           %(progname)s --move 'System Preferences' --position 2 --allhomes

  The following finds any instance of iTunes in the specified home directory's dock:
           %(progname)s --find iTunes /Users/jsmith

  The following lists all dock items for all home directories at homeloc in the form: item<tab>path<tab><section>tab<plist>
           %(progname)s --list --homeloc /Volumes/RAID/Homes --allhomes

  The following adds Firefox after Safari in the Default User Template without restarting the Dock
           %(progname)s --add /Applications/Firefox.app --after Safari --no-restart '/System/Library/User Template/English.lproj'

  The following restarts the dock, usefull after calling multiple --add/remove with --on-restart
            %(progname)s --restart


Notes:
  When specifying a relative path like ~/Documents with the --allhomes option, ~/Documents must be quoted like '~/Documents' to get the item relative to each home

Bugs:
  Names containing special characters like accent marks will fail


Contact:
  Send bug reports and comments to kcrwfrd at gmail.
""" % dict(progname = os.path.basename(sys.argv[0])))
    if e:
        print("")
        print('Error processing options:', e)
        return 1
    return 0


def verboseOutput(*args):
    """Used by verbose option (-v) to send more output to stdout"""
    if verbose:
        try:
            log.debug("verbose:", args)
        except Exception:
            pass


def dock_util(args):
    """Parses options and arguments and performs functions"""
    # setup our getoput opts and args
    try:
        (optargs, args) = getopt.getopt(args, 'hv', ["help", "version",
            "section=", "list", "find=", "add=", "move=", "replacing=",
            "remove=", "after=", "before=", "position=", "display=", "view=",
            "sort=", "label=", "type=", "allhomes", "homeloc=", "no-restart", "restart", "hupdock="])
    except getopt.GetoptError as e:  # if parsing of options fails, display usage and parse error
        return usage(e)

    # setup default values
    global verbose
    add_path = None
    remove_labels = []
    find_label = None
    move_label = None
    after_item = None
    before_item = None
    position = None
    add_path = None
    plist_path = None
    list = False
    all_homes = False
    replace_label = None
    section = None
    display_as = None
    show_as = None
    arrangement = None
    tile_type = None
    label_name = None
    home_directories_loc = '/Users'
    restart_dock = True
    explicit_restart = False

    for opt, arg in optargs:
        if opt in ("-h", "--help"):
            usage()
        elif opt == "-v":
            verbose = True
        elif opt == "--version":
            print(version)
            return 0
        elif opt == "--add":
            add_path = arg
        elif opt == "--replacing":
            replace_label = arg
        elif opt == "--move":
            move_label = arg
        elif opt == "--find":
            find_label = arg
        elif opt == "--remove":
            remove_labels.append(arg)
        elif opt == "--after":
            after_item = arg
        elif opt == "--before":
            before_item = arg
        elif opt == "--position":
            position = arg
        elif opt == "--label":
            label_name = arg
        elif opt == '--sort':
            if arg == 'name':
                arrangement = 1
            elif arg == 'dateadded':
                arrangement = 2
            elif arg == 'datemodified':
                arrangement = 3
            elif arg == 'datecreated':
                arrangement = 4
            elif arg == 'kind':
                arrangement = 5
            else:
                usage('unsupported --sort argument')
        elif opt == '--view':
            if arg == 'fan':
                show_as = 1
            elif arg == 'grid':
                show_as = 2
            elif arg == 'list':
                show_as = 3
            elif arg == 'auto':
                show_as = 0
            else:
                usage('unsupported --view argument')
        elif opt == '--display':
            if arg == 'stack':
                display_as = 0
            elif arg == 'folder':
                display_as = 1
            else:
                usage('unsupported --display argument')
        elif opt == '--type':
            tile_type = arg+'-tile'
        elif opt == '--section':
            section = 'persistent-'+arg
        elif opt == '--list':
            list = True
        elif opt == '--allhomes':
            all_homes = True
        elif opt == '--homeloc':
            home_directories_loc = arg
        elif opt == '--no-restart':
            restart_dock = False
        elif opt == '--restart':
            explicit_restart = True
        # for legacy compatibility only
        elif opt == '--hupdock':
            if arg.lower() in ("false", "no", "off", "0"):
                restart_dock = False

    # check for an action
    if add_path is None and not remove_labels and move_label is None and find_label is None and list == False and explicit_restart == False:
        usage('no action was specified')

    if explicit_restart:
        restart_the_dock()
        return 0

    # get the list of plists to process
    # if allhomes option was set, get a list of home directories in the homedirectory location
    if all_homes:
        possible_homes = os.listdir(home_directories_loc)
        plist_paths = [ home_directories_loc+'/'+home+'/Library/Preferences/com.apple.dock.plist' for home in possible_homes if os.path.exists(home_directories_loc+'/'+home+'/Library/Preferences/com.apple.dock.plist') and os.path.exists(home_directories_loc+'/'+home+'/Desktop')]
    else: # allhomes was not specified
        # if no plist argument, then use the user's home directory dock plist, otherwise use the arguments provided
        if not args:
            plist_paths = [ os.path.expanduser('~/Library/Preferences/com.apple.dock.plist') ]
        else:
            plist_paths = args
    # exit if we couldn't find any plists to process
    if len(plist_paths) < 1:
        print('no dock plists were found')
        return 1

    # loop over plist paths
    for plist_path in plist_paths:

        verboseOutput('processing', plist_path)
        # a home directory is allowed as an argument, so if the plist_path is a
        # directory, we append the relative path to the plist
        if os.path.isdir(plist_path):
            plist_path = os.path.join(plist_path,'Library/Preferences/com.apple.dock.plist')

        # verify that the plist exists at the given path
        # and expand and quote it for use when shelling out
        if os.path.exists(os.path.expanduser(plist_path)):
            plist_path = os.path.expanduser(plist_path)
            plist_path = os.path.abspath(plist_path)
            plist_path = pipes.quote(plist_path)
        else:
            print(plist_path, 'does not seem to be a home directory or a dock plist')
            return 1

        # check for each action and process accordingly
        if remove_labels: # --remove action(s)
            pl = readPlist(plist_path)
            changed = False
            for remove_label in remove_labels:
                if removeItem(pl, remove_label):
                    changed = True
                else:
                    print('item', remove_label, 'was not found in', plist_path)
            if changed:
                commitPlist(pl, plist_path, restart_dock)
        elif list: # --list action
            pl = readPlist(plist_path)
            # print a tab separated line for each item in the plist
            # for each section
            for section in ['persistent-apps', 'persistent-others']:
                # for item in section
                for item in pl[section]:
                    try:
                        # join and print relevant data into a string separated by tabs
                        print('\t'.join((item['tile-data']['file-label'], item['tile-data']['file-data']['_CFURLString'], section, plist_path)))
                    except Exception:
                        pass

        elif find_label is not None: # --find action
            # since we are only reading the plist, make a copy before converting it to be read
            pl = readPlist(plist_path)
            # set found state
            item_found = False
            # loop through dock items looking for a match with provided find_label
            for section in ['persistent-apps', 'persistent-others']:
                for item_offset in range(len(pl[section])):
                    try:
                        if pl[section][item_offset]['tile-data']['file-label'] == find_label:
                            item_found = True
                            print(find_label, "was found in", section, "at slot", item_offset+1, "in", plist_path)
                    except Exception:
                        pass
            if not item_found:
                print(find_label, "was not found in", plist_path)
                if not all_homes:  # only exit non-zero if we aren't processing all homes, because for allhomes, exit status for find would be irrelevant
                    return 1

        elif move_label is not None: # --move action
            pl = readPlist(plist_path)
            # check for a position option before processing
            if position is None and before_item is None and after_item is None:
                usage('move action requires a position destination')
            # perform the move and save the plist if it was successful
            if moveItem(pl, move_label, position, before_item, after_item):
                commitPlist(pl, plist_path, restart_dock)
            else:
                print('move failed for', move_label, 'in', plist_path)

        elif add_path is not None:  # --add action
            if add_path.startswith('~'): # we've got a relative path and relative paths need to be processed by using a path relative to this home directory
                real_add_path = re.sub('^~', plist_path.replace('/Library/Preferences/com.apple.dock.plist',''), add_path) # swap out the full home path for the ~
            else:
                real_add_path = add_path
            # determine smart default values where possible
            if section is None:
                if real_add_path.endswith('.app') or real_add_path.endswith('.app/'): # we've got an application
                    section = 'persistent-apps'
                elif display_as is not None or show_as is not None or arrangement is not None: # we've got a folder
                    section = 'persistent-others'

            if tile_type is None:  # if type was not specified, we try to figure that out using the filesystem
                if os.path.isdir(real_add_path) and section != 'persistent-apps': # app bundles are directories too
                    tile_type = 'directory-tile'
                elif re.match(r'\w*://', real_add_path): # regex to determine a url in the form xyz://abcdef.adsf.com/adsf
                    tile_type = 'url-tile'
                    section = 'persistent-others'
                else:
                    tile_type = 'file-tile'

            if section is None:
                section = 'persistent-others'

            if tile_type != 'url-tile': # paths can't be relative in dock items
                real_add_path = os.path.realpath(real_add_path)

            pl = readPlist(plist_path)
            verboseOutput('adding', real_add_path)
            # perform the add save the plist if it was successful
            if addItem(pl, real_add_path, replace_label, position, before_item, after_item, section, display_as, show_as, arrangement, tile_type, label_name):
                commitPlist(pl, plist_path, restart_dock)
            else:
                print('item', add_path, 'was not added to Dock')
                if not all_homes:  # only exit non-zero if we aren't processing all homes, because for allhomes, exit status for add would be irrelevant
                    return 1
    return 0

# NOTE on use of defaults
# We use defaults because it knows how to handle cfpreferences caching even when given a path rather than a domain
# This allows us to keep using path-based plist specifications rather than domains
# Preserving path based plists are important for people needing to run this on a non boot volume
# However if Apple stops using plists or moves the plist path, all of this will break
# So at that point we will have to change the API so users pass in a defaults domain or user rather than a plist path
def writePlist(pl, plist_path):
    """writes a plist object down to a file"""
    # get the unescaped path
    ###plist_path = path_as_string(plist_path)
    # get a tempfile path for writing our plist
    plist_import_path = tempfile.mktemp()
    # Write the plist to our temporary plist for importing because defaults can't import from a pipe (yet)
    plistlib.writePlist(pl, plist_import_path)
    # get original permissions
    plist_stat = os.stat(plist_path)
    # If we are running as root, ensure we run as the correct user to update cfprefsd
    if os.geteuid() == 0:
        # Running defaults as the user only works if the user exists
        if valid_uid(plist_stat.st_uid):
            subprocess.Popen(['sudo', '-u', '#%d' % plist_stat.st_uid, '-g', '#%d' % plist_stat.st_gid, 'defaults', 'import', plist_path, plist_import_path])
        else:
            subprocess.Popen(['defaults', 'import', plist_path, plist_import_path])
            os.chown(plist_path, plist_stat.st_uid, plist_stat.st_gid)
            os.chmod(plist_path, plist_stat.st_mode)
    else:
        subprocess.Popen(['defaults', 'import', plist_path, plist_import_path])


def valid_uid(uid):
    """returns bool of whether uid can be resolved to a user"""
    try:
        pwd.getpwuid(uid)
        return True
    except Exception:
        return False


def getOsxVersion():
    """returns a tuple with the (major,minor,revision) numbers"""
    # OS X Yosemite return 10.10, so we will be happy with len(...) == 2, then add 0 for last number
    try:
        mac_ver = tuple(int(n) for n in platform.mac_ver()[0].split('.'))
        assert 2 <= len(mac_ver) <= 3, f"Bac mac_ver format {mac_ver}"
    except Exception as e:
        raise e
    if len(mac_ver) == 2:
      mac_ver = mac_ver + (0, )
    return mac_ver


def readPlist(plist_path):
    """returns a plist object read from a file path"""
    # get the unescaped path
    ###plist_path = path_as_string(plist_path)
    # get a tempfile path for exporting our defaults data
    export_fifo = tempfile.mktemp()
    # make a fifo for defaults export in a temp file
    os.mkfifo(export_fifo)
    # export to the fifo
    osx_version = getOsxVersion()
    if osx_version[1] >= 9:
        subprocess.Popen(['defaults', 'export', plist_path, export_fifo]).communicate()
        # convert the export to xml
        plist_string = subprocess.Popen(['plutil', '-convert', 'xml1', export_fifo, '-o', '-'], stdout=subprocess.PIPE).stdout.read()
    else:
        try:
            cmd = ['/usr/libexec/PlistBuddy','-x','-c', 'print',plist_path]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (plist_string,err) = proc.communicate()
        except Exception as e:
            raise e
    # parse the xml into a dictionary
    pl = plistlib.readPlistFromBytes(plist_string)
    return pl


def path_as_string(path):
    """returns an unescaped string of the path"""
    return subprocess.Popen('ls -d '+path, shell=True, stdout=subprocess.PIPE).stdout.read().rstrip('\n')


def moveItem(pl, move_label=None, position=None, before_item=None, after_item=None):
    """locates an existing dock item and moves it to a new position"""
    for section in ['persistent-apps', 'persistent-others']:
        item_to_move = None
        # loop over the items looking for the item label
        for item_offset in range(len(pl[section])):
            if pl[section][item_offset]['tile-data']['file-label'] == move_label:
                item_found = True
                verboseOutput('found', move_label)
                # make a copy of the found dock entry
                item_to_move = pl[section][item_offset]
                found_offset = item_offset
                break
            else:
                verboseOutput('no match for', pl[section][item_offset]['tile-data']['file-label'])
        # if the item wasn't found, continue to next section loop iteration
        if item_to_move is None:
            continue
        # we are still inside the section for loop
        # remove the found item
        pl[section].remove(pl[section][item_offset])

        # figure out where to re-insert the original dock item back into the plist
        if position is not None:
            if position in [ 'beginning', 'begin', 'first' ]:
                pl[section].insert(0, item_to_move)
                return True
            elif position in [ 'end', 'last' ]:
                pl[section].append(item_to_move)
                return True
            elif position in [ 'middle', 'center' ]:
                midpoint = int(len(pl[section])/2)
                pl[section].insert(midpoint, item_to_move)
                return True
            else:
                # if the position integer starts with a + or - , then add or subtract from its current position respectively
                if position.startswith('-') or position.startswith('+'):
                    new_position = int(position) + found_offset
                    if new_position > len(pl[section]):
                        pl[section].append(item_to_move)
                    elif new_position < 0:
                        pl[section].insert(0, item_to_move)
                    else:
                        pl[section].insert(int(position) + found_offset, item_to_move)
                    return True

                try:
                    int(position)
                except Exception:
                    print('Invalid position', position)
                    return False
                pl[section].insert(int(position)-1, item_to_move)
                return True
        elif after_item is not None or before_item is not None:
            # if after or before is set, find the offset of that item and do the insert relative to that offset
            for item_offset in range(len(pl[section])):
                try:
                    if after_item is not None:
                        if pl[section][item_offset]['tile-data']['file-label'] == after_item:
                            pl[section].insert(item_offset+1, item_to_move)
                            return True
                    if before_item is not None:
                        if pl[section][item_offset]['tile-data']['file-label'] == before_item:
                            pl[section].insert(item_offset, item_to_move)
                            return True
                except KeyError:
                    pass

    return False


def generate_guid():
    """returns guid string"""
    return subprocess.Popen(['/usr/bin/uuidgen'],stdout=subprocess.PIPE).communicate()[0].rstrip()


def addItem(pl, add_path, replace_label=None, position=None, before_item=None, after_item=None, section='persistent-apps', display_as=1, show_as=1, arrangement=2, tile_type='file-tile',label_name=None):
    """adds an item to an existing dock plist object"""
    if display_as is None:
        display_as = 1
    if show_as is None:
        show_as = 0
    if arrangement is None:
        arrangement = 2

    # fix problems with unicode file names
    enc = (sys.stdin.encoding if sys.stdin.encoding else 'utf-8')
    add_path = utils.unicodify(add_path, enc)

    # set a dock label if one isn't provided
    if label_name is None:
        if tile_type == 'url-tile':
            label_name = add_path
            section = 'persistent-others'
        else:
            base_name = re.sub('/$', '', add_path).split('/')[-1]
            label_name = re.sub('.app$', '', base_name)


    # only add if item label isn't already there

    if replace_label != label_name:
        for existing_dock_item in (pl[section]):
            for label_key in ['file-label','label']:
                if label_key in existing_dock_item['tile-data']:
                    if existing_dock_item['tile-data'][label_key] == label_name:
                        print("%s already exists in dock. Use --replacing '%s' to update an existing item" % (label_name, label_name))
                        return False



    if replace_label is not None:
        for item_offset in range(len(pl[section])):
            tile_replace_candidate = pl[section][item_offset]['tile-data']
            if tile_replace_candidate[label_key_for_tile(tile_replace_candidate)] == replace_label:
                verboseOutput('found', replace_label)
                del pl[section][item_offset]
                position = item_offset + 1
                break

    new_guid = generate_guid()
    if tile_type == 'file-tile':
        new_item = {'GUID': new_guid, 'tile-data': {'file-data': {'_CFURLString': add_path, '_CFURLStringType': 0},'file-label': label_name, 'file-type': 32}, 'tile-type': tile_type}
    elif tile_type == 'directory-tile':
        if subprocess.Popen(['/usr/bin/sw_vers', '-productVersion'],
                stdout=subprocess.PIPE).stdout.read().rstrip().split('.')[1] == '4': # gets the decimal after 10 in sw_vers; 10.4 does not use 10.5 options for stacks
            new_item = {'GUID': new_guid, 'tile-data': {'directory': 1, 'file-data': {'_CFURLString': add_path, '_CFURLStringType': 0}, 'file-label': label_name, 'file-type': 2 }, 'tile-type': tile_type}
        else:
            new_item = {'GUID': new_guid, 'tile-data': {'arrangement': arrangement, 'directory': 1, 'display_as': display_as, 'file-data': {'_CFURLString': add_path, '_CFURLStringType': 0}, 'file-label': label_name, 'file-type': 2, 'show_as': show_as}, 'tile-type': tile_type}

    elif tile_type == 'url-tile':
        new_item = {'GUID': new_guid, 'tile-data': {'label': label_name, 'url': {'_CFURLString': add_path, '_CFURLStringType': 15}}, 'tile-type': tile_type}
    else:
        print('unknown type:', tile_type)
        return False

    verboseOutput('adding', new_item)

    if position is not None:
        if position in [ 'beginning', 'begin', 'first' ]:
            pl[section].insert(0, new_item)
            return True
        elif position in [ 'end', 'last' ]:
            pl[section].append(new_item)
            return True
        elif position in [ 'middle', 'center' ]:
            midpoint = int(len(pl[section])/2)
            pl[section].insert(midpoint, new_item)
            return True
        else:
            try:
                int(position)
            except Exception:
                print('Invalid position', position)
                return False
            if int(position) == 0:
                pl[section].insert(int(position), new_item)
            elif int(position) > 0:
                pl[section].insert(int(position)-1, new_item)
            else:
                pl[section].insert(int(position)+len(pl[section])+1, new_item)
            return True
    elif after_item is not None or before_item is not None:
        for item_offset in range(len(pl[section])):
            try:
                if after_item is not None:
                    if pl[section][item_offset]['tile-data']['file-label'] == after_item:
                        pl[section].insert(item_offset+1, new_item)
                        return True
                if before_item is not None:
                    if pl[section][item_offset]['tile-data']['file-label'] == before_item:
                        pl[section].insert(item_offset, new_item)
                        return True
            except KeyError:
                pass
    pl[section].append(new_item)
    verboseOutput('item added at end')
    return True


def removeItem(pl, item_name):
    removal_succeeded = False
    if item_name == "all":
        verboseOutput('Removing all items')
        pl['persistent-apps'] = []
        pl['persistent-others'] = []
        return True
    for dock_item in pl['persistent-apps']:
        if dock_item['tile-data'].get('file-label') == item_name:
            verboseOutput('found', item_name)
            pl['persistent-apps'].remove(dock_item)
            removal_succeeded = True
    for dock_item in pl['persistent-others']:
        if dock_item['tile-type'] == "url-tile":
            if dock_item['tile-data'].get('label') == item_name:
                verboseOutput('found', item_name)
                pl['persistent-others'].remove(dock_item)
                removal_succeeded = True
        else:
            if dock_item['tile-data'].get('file-label') == item_name:
                verboseOutput('found', item_name)
                pl['persistent-others'].remove(dock_item)
                removal_succeeded = True
    return removal_succeeded


def restart_the_dock():
    os.system('/usr/bin/killall -HUP Dock >/dev/null 2>&1')


def commitPlist(pl, plist_path, restart_dock):
    writePlist(pl, plist_path)
    if restart_dock:
        restart_the_dock()
#def commitPlistLegacy(pl, plist_path, restart_dock):
#    plist_string_path = path_as_string(plist_path)
#    pl = removeLongs(pl)
#    plist_stat = os.stat(plist_string_path)
#    writePlist(pl, plist_path)
#    convertPlist(plist_path, 'binary1')
#    os.chown(plist_string_path, plist_stat.st_uid, plist_stat.st_gid)
#    os.chmod(plist_string_path, plist_stat.st_mode)
#    if restart_dock:
#        os.system('/usr/bin/killall -HUP cfprefsd >/dev/null 2>&1')
#        os.system('/usr/bin/killall -HUP Dock >/dev/null 2>&1')
#


def label_key_for_tile(item):
    for label_key in ['file-label','label']:
        if label_key in item:
            return label_key


def main():
    retVal = dock_util(sys.argv[1:])
    sys.exit(retVal)


if __name__ == "__main__":
    main()
