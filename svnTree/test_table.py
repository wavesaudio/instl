#!/usr/bin/env python2.7
from __future__ import print_function

import os
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy import update, select
from sqlalchemy import or_
from sqlalchemy import Column, Integer, String, BOOLEAN
from sqlalchemy.ext.declarative import declarative_base

import utils

from svnRow import SVNRow
from svnTable import SVNTable

alchemy_base = declarative_base()


comment_line_re = re.compile(r"""
            ^
            \s*\#\s*
            (?P<the_comment>.*)
            $
            """, re.X)
flags_and_revision_re = re.compile(r"""
                ^
                \s*
                (?P<flags>[fdxs]+)
                \s*
                (?P<revision>\d+)
                (\s*
                (?P<checksum>[\da-f]+))? # 5985e53ba61348d78a067b944f1e57c67f865162
                $
                """, re.X)
wtar_file_re = re.compile(r""".+\.wtar(\...)?$""")
wtar_first_file_re = re.compile(r""".+\.wtar(\.aa)?$""")


def print_items(item_list):
    for item in item_list:
        print(item.__repr__())

sources = (('Mac/Plugins/Enigma.bundle', '!dir', 'common'),
    ('Mac/Shells/WaveShell-VST 9.6.vst', '!dir', 'Mac'),
    ('Mac/Icons', '!dir', 'common'),
    ('Mac/Utilities/uninstallikb', '!dir', 'Mac'),
    ('instl/uninstallException.json', '!file', 'common'),
    ('Mac/Shells/WaveShell-VST3 9.6.vst3', '!dir', 'Mac'),
    ('Mac/Shells/WaveShell-DAE 9.6.dpm', '!dir', 'Mac'),
    ('Mac/Shells/WaveShell-AU 9.6.component', '!dir', 'Mac'),
    ('Mac/Shells/Waves AU Reg Utility 9.6.app', '!dir', 'Mac'),
    ('Mac/Shells/WaveShell-AAX 9.6.aaxplugin', '!dir', 'common'),
    ('Mac/Shells/WaveShell-WPAPI_1 9.6.bundle', '!dir', 'common'),
    ('Mac/Shells/WaveShell-WPAPI_2 9.6.bundle', '!dir', 'common'),
    ('Mac/Plugins/WavesLib_9.6.framework', '!dir', 'Mac'),
    ('Mac/Modules/InnerProcessDictionary.dylib', '!file', 'Mac'),
    ('Mac/Modules/WavesLicenseEngine.bundle', '!dir', 'common'),
    ('Common/Plugins/Documents/Waves System Guide.pdf', '!file', 'common'),
    ('Common/SoundGrid/Firmware/SGS/SGS_9.7.wfi', '!file', 'common'),
    ('Common/Data/IR1Impulses/Basic', '!files', 'common'),
           )

if __name__ == "__main__":
    t = SVNTable()
    t.read_info_map_from_file("/Users/shai/Library/Caches/Waves Audio/instl/instl/V9/bookkeeping/58/remote_info_map.txt")
    #t.write_as_text("/Users/shai/Library/Caches/Waves Audio/instl/instl/V9/bookkeeping/58/remote_info_map.txt.out")
    #items = t.get_items()
    #t.print_items(items)

    #items = t.get_ancestry("Common/Data/IR1Impulses/Basic/Studio1_xcg.wir")
    #t.print_items(items)
    print("------------ 1")
    #t.mark_required_for_source(('Common/SoundGrid/Firmware/SGS/SGS_9.7.wfi', '!file', 'common'))
    #t.mark_required_for_source(('Common/Plugins/Documents/Waves System Guide.pdf', '!file', 'common'))
    #t.mark_required_for_source(('Common/Data/WavesGTR', '!dir_cont', 'common'))
    for source in sources:
        t.mark_required_for_source(source)
    t.mark_required_completion()
    print("------------ 2")
    items = t.get_required()
    print_items(items)
    print("------------ 3")
    #items = t.get_required()
    #t.print_items(items)
    print(len(items), "required items")
