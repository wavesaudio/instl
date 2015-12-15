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


alchemy_base = declarative_base()


comment_line_re = re.compile(r"""
            ^
            \s*\#\s*
            (?P<the_comment>.*)
            $
            """, re.X)
text_line_re = re.compile(r"""
            ^
            (?P<path>.+)
            ,\s+
            (?P<flags>[dfsx]+)
            ,\s+
            (?P<revision>\d+)
            (,\s+
            (?P<checksum>[\da-f]+))?    # 5985e53ba61348d78a067b944f1e57c67f865162
            (,\s+
            (?P<size>[\d]+))?       # 356985
            (,\s+
            (?P<url>(http(s)?|ftp)://.+))?    # http://....
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

class Row(alchemy_base):
    __tablename__ = 'svnitem'
    path = Column(String, primary_key=True)
    name = Column(String)
    #parent = Column(String, index=True)
    fileFlag = Column(BOOLEAN, default=False)
    execFlag = Column(BOOLEAN, default=False)
    symlinkFlag = Column(BOOLEAN, default=False)
    wtar_file = Column(BOOLEAN, default=False) # any .wtar or .wtar.?? file
    wtar_first_file = Column(BOOLEAN, default=False) # .wtar or wtar.aa file
    revision_remote = Column(Integer)
    revision_local = Column(Integer)
    checksum = Column(String)
    size = Column(Integer, default=-1)
    url = Column(String, default=None)
    required = Column(BOOLEAN, default=False)
    need_download = Column(BOOLEAN, default=False)
    level = Column(Integer, default=0)

    def __repr__(self):
        return ("<{self.level}, {self.path},f:{self.fileFlag}"
                ",x:{self.execFlag},s:{self.symlinkFlag}"
                ",w:{self.wtar_file},fw:{self.wtar_first_file}"
                ",rev-remote:{self.revision_remote},rev-local:{self.revision_local}"
                ",checksum:{self.checksum},size:{self.size}"
                ",url:{self.checksum},size:{self.size}"
                ",required:{self.required},need_download:{self.need_download}>"
                ).format(**locals())

    def get_ancestry(self):
        ancestry = list()
        split_path = self.path.split("/")
        for i in range(1, len(split_path)+1):
            ancestry.append("/".join(split_path[:i]))
        return ancestry

class Table(object):
    def __init__(self):
        self.engine = create_engine('sqlite:///:memory:', echo=False)
        alchemy_base.metadata.create_all(self.engine)
        self.session_maker = sessionmaker(bind=self.engine)
        self.session = self.session_maker()
        self.path_to_file = None
        self.comments = list()

    @staticmethod
    def item_dict_from_str_re(the_str):
        """ create a new a sub-item from string description.
            If create_folders is True, non existing intermediate folders
            will be created, with the same revision. create_folders is False,
            and some part of the path does not exist KeyError will be raised.
            This is the regular expression version.
        """
        item_details = None
        match = text_line_re.match(the_str)
        if match:
            item_details = {'path': match.group('path'),
                            'revision_remote': match.group('revision')}
            path_parts = match.group('path').split("/")
            item_details['level'] = len(path_parts)
            item_details['name'] = path_parts[-1]
            #item_details['parent'] = "/".join(path_parts[:-1])+"/"
            flags = match.group('flags')
            if 'f' in flags:
                item_details['fileFlag'] = True
                item_details['wtar_file'], item_details['wtar_first_file'] = Table.get_wtar_file_status(item_details['name'])
            if 's' in flags:
                item_details['symlinkFlag'] = True
            if 'x' in flags:
                item_details['execFlag'] = True
            if match.group('checksum') is not None:
                item_details['checksum'] = match.group('checksum')
            if match.group('url') is not None:
                item_details['url'] = match.group('url')
            if match.group('size') is not None:
                item_details['size'] = match.group('size')
        return item_details

    @staticmethod
    def get_wtar_file_status(file_name):
        is_wtar_file = wtar_file_re.match(file_name) is not None
        is_wtar_first_file = is_wtar_file and wtar_first_file_re.match(file_name) is not None
        return is_wtar_file, is_wtar_first_file

    @utils.timing
    def write_as_text(self, in_path):
        with open(in_path, "w") as wfd:

            the_query = self.session.query(Row)

            for item in the_query.all():
                wfd.write(str(item) + "\n")

    @utils.timing
    def read_from_text(self, in_path):
        self.path_to_file = in_path
        with open(in_path, "r") as rfd:
            insert_dicts = list()
            for line in rfd:
                line = line.strip()
                item_dict = Table.item_dict_from_str_re(line)
                if item_dict:
                    insert_dicts.append(item_dict)
                else:
                    match = comment_line_re.match(line)
                    if match:
                        self.comments.append(match.group("the_comment"))
            self.session.bulk_insert_mappings(Row, insert_dicts)

    @utils.timing
    def get_items(self, in_parent="", in_level=700, get_files=True, get_dirs=False):
        if not in_parent:
            the_query = self.session.query(Row).filter(Row.fileFlag==True)
        else:
            parent_item = self.session.query(Row).filter(Row.path==in_parent).one()
            get_dirs = not get_dirs
            the_query = self.session.query(Row).filter(or_(Row.fileFlag==get_files, Row.fileFlag==get_dirs))\
                                                .filter(Row.path.like(parent_item.path+"/%"))\
                                                .filter(Row.level > parent_item.level, Row.level < parent_item.level+in_level+1)

        return the_query.all()

    @utils.timing
    def get_ancestry(self, in_path):
        item = self.session.query(Row).filter(Row.path==in_path).one()
        ancestry = item.get_ancestry()
        the_query = self.session.query(Row).filter(Row.path.in_(ancestry))

        return the_query.all()

    def mark_required_for_item(self, item):
        ancestry = item.get_ancestry()
        update_statement = update(Row)\
                .where(Row.path.in_(ancestry))\
                .values(required=True)
        self.session.execute(update_statement)

    @utils.timing
    def mark_required_for_file(self, item_path):
        file_items = self.session.query(Row).filter(or_(Row.path.like(item_path), Row.path.like(item_path+".wtar%"))).all()
        paths_to_mark = [file_item.path for file_item in file_items]
        paths_to_mark.extend(file_items[0].get_ancestry()) # all share the same ancestry
        update_statement = update(Row)\
                .where(Row.path.in_(paths_to_mark))\
                .values(required=True)
        self.session.execute(update_statement)

    @utils.timing
    def mark_required_for_files(self, parent_path):
        parent_item = self.session.query(Row).filter(Row.path == parent_path, Row.fileFlag==False).one()
        self.mark_required_for_item(parent_item)
        update_statement = update(Row)\
                .where(Row.level == parent_item.level+1)\
                .where(Row.fileFlag == True)\
                .where(Row.path.like(parent_item.path+"/%"))\
                .values(required=True)
        self.session.execute(update_statement)

    @utils.timing
    def mark_required_for_dir(self, dir_path):
        dir_item = self.session.query(Row).filter(Row.path == dir_path, Row.fileFlag==False).one()
        self.mark_required_for_item(dir_item)
        update_statement = update(Row)\
                .where(Row.level > dir_item.level)\
                .where(Row.path.like(dir_item.path+"/%"))\
                .values(required=True)
        self.session.execute(update_statement)

    def get_required(self):
        the_query = self.session.query(Row).filter(Row.required==True)
        return the_query.all()

    def mark_required_for_source(self, source):
        """
        :param source: a tuple (source_folder, tag), where tag is either !file or !dir
        :return: None
        """
        if source[1] == '!file':
            self.mark_required_for_file(source[0])
        elif source[1] == '!files':
            self.mark_required_for_files(source[0])
        elif source[1] == '!dir' or source[1] == '!dir_cont':  # !dir and !dir_cont are only different when copying
            self.mark_required_for_dir(source[0])


    @staticmethod
    def print_items(item_list):
        for item in item_list:
            print(item)

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
    t = Table()
    t.read_from_text("/Users/shai/Library/Caches/Waves Audio/instl/instl/V9/bookkeeping/58/remote_info_map.txt")
    #t.write_as_text("/Users/shai/Library/Caches/Waves Audio/instl/instl/V9/bookkeeping/58/remote_info_map.txt.out")
    #items = t.get_items(in_parent="Mac/Apps/WavesQtLibs_4.7.3/Frameworks/QtDBus.framework", in_level=6, get_dirs=True)
    #t.print_items(items)
    #items = t.get_ancestry("Common/Data/IR1Impulses/Basic/Studio1_xcg.wir")
    #t.print_items(items)
    print("------------ 1")
    #t.mark_required_for_source(('Common/SoundGrid/Firmware/SGS/SGS_9.7.wfi', '!file', 'common'))
    #t.mark_required_for_source(('Common/Plugins/Documents/Waves System Guide.pdf', '!file', 'common'))
    #t.mark_required_for_source(('Common/Data/WavesGTR', '!dir_cont', 'common'))
    for source in sources:
        t.mark_required_for_source(source)
    print("------------ 2")
    items = t.get_required()
    print("------------ 3")
    t.print_items(items)
    print(len(items), "required items")
