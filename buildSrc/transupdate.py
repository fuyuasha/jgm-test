#!/usr/bin/env python

"""
Description:
Utility to upload (English) resource files and download (translated) resource files from Transifex (www.transifex.com).

Dependency:
Onshape forked version of python-transifex (https://github.com/onshape/python-transifex/tree/onshape-master).
"""

import argparse
import errno
import fnmatch
import hashlib
import json
import os
import re
import sys

from transifex.api import TransifexAPI
from transifex.util import slugify

class TransUpdateError(Exception):
    pass

class _Const(object):
    ALL = 'all'
    MODE_UP = 'up'
    MODE_DOWN = 'down'
    MODE_CKSUMFILE = 'cksumfile'
    TRANSIFEX_PROJ_PREFIX = 'onshape-'
    EXIT_OK = 0
    EXIT_ERROR = 1
    EXIT_OK_NOCHANGES = 100
    def __setattr__(self, attr, value):
        if hasattr(self, attr):
            raise ValueError, 'Attribute %s already has a value and so cannot be written to' % attr
        self.__dict__[attr] = value

def create_path(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise ValueError, 'ERROR: creating folder %s' % path

class OnTransifexAPI(TransifexAPI):
    def __init__(self, transuser, transpass, url):
        TransifexAPI.__init__(self, transuser, transpass, url)

class ResourceInfo(object):
    """
    Manage access to the .json info that describes a repo's localizable files.
    The 'resources' file spec isn't fully generalized but is sufficient to handle the newton, ios and android repos.
    There are two main forms of file spec:
    1) newton: wildcards allowed, lang expected to be file base name suffix ex: 'project/translations/*.po'
    2) android, ios: no wildcards, lang specified in path by '%s', ex: 'belcad/belcad/%s.lproj/Localizable.strings'
    """

    def __init__(self, src_folder, json_file):
        self._src_folder = src_folder
        full_path = os.path.join(src_folder, json_file)
        with open(full_path, "r") as fp:
            self._res_spec = json.load(fp)
        self._lang_exclude = ["pig_latin"]
        for lang in self._res_spec['langs']:
            self._lang_exclude.append(lang.items()[0][0])

    def get(self, english_mode=True):
        file_list = []
        tx_res_list = []
        tx_lang_list = []
        for item in self._res_spec['resources']:
            path, filename = os.path.split(item[0])
            filename_only, ext = os.path.splitext(filename)
            if "%s" in path:
                # typically an ios/android resource
                if english_mode:
                    english_file = os.path.join(self._src_folder, item[0] % item[2])
                    file_list.append(english_file)
                else:
                    # Convert English filenames to lang filenames
                    for lang in self._res_spec['langs']:
                        tx_lang = lang.items()[0][0]
                        native_lang = lang.items()[0][1] if lang.items()[0][1] else tx_lang
                        native_lang_with_prefix = item[1] + native_lang
                        file_list.append(os.path.join(self._src_folder, item[0] % native_lang_with_prefix))
                        tx_res_list.append(filename)
                        tx_lang_list.append(tx_lang)
            else:
                # typically a newton resource
                if item[2]:
                    filename_english = filename_only + item[1] + item[2] + ext
                else:
                    filename_english = filename_only + ext
                full_filespec = os.path.join(self._src_folder, os.path.join(path, filename_english))
                english_files = self._get_english_files(full_filespec, item[1])
                if english_mode:
                    file_list.extend(english_files)
                else:
                    # Convert English filenames to lang filenames
                    for lang in self._res_spec['langs']:
                        tx_lang = lang.items()[0][0]
                        native_lang = lang.items()[0][1] if lang.items()[0][1] else tx_lang
                        for english_file in english_files:
                            path, filename = os.path.split(english_file)
                            filename_only, ext = os.path.splitext(filename)
                            if item[2]:
                                lang_file = os.path.join(path, filename_only[:-len(item[2])] + native_lang + ext)
                            else:
                                lang_file = os.path.join(path, filename_only + item[1] + native_lang + ext)
                            file_list.append(lang_file)
                            tx_res_list.append(filename)
                            tx_lang_list.append(tx_lang)
        return file_list, tx_res_list, tx_lang_list

    def _get_english_files(self, full_filespec, lang_prefix):
        """
        :param full_filespec: typically includes a filename wildcard
        ex: "/media/disk1/jenkins/jobs/current-l10n-upload/workspace/project/core/src/main/resources/com/belmonttech/util/l10n/*.properties"
        :param lang_prefix: lang separator associated with this resource (specified in args.repolocalizeinfo)
        ex: "_"
        :return: a list of English-only full filenames
        """
        pattern = ".*" + lang_prefix + "(" + '|'.join(lang for lang in self._lang_exclude) + ")$"
        foreign_lang = re.compile(pattern)
        english_files = []
        path, filespec = os.path.split(full_filespec)
        for filename in os.listdir(path):
            if fnmatch.fnmatch(filename, filespec):
                if not foreign_lang.match(os.path.splitext(filename)[0]):
                    english_files.append(os.path.join(path, filename))
        return english_files

class TransUpdate(object):
    """
    Update translation info (upload English resources or download translated resources)
    """

    def __init__(self, transuser, transpass, reponame, noprojprefix, clonepath, repolocalizeinfo):
        self._transifex = OnTransifexAPI(transuser, transpass, 'http://www.transifex.com')
        self._reponame = reponame
        self._noprojprefix = noprojprefix
        self._clonepath = clonepath
        self._res_info = ResourceInfo(clonepath, repolocalizeinfo)
        self._transifex_i18n_type = {
            "po": "PO",
            "properties": "UNICODEPROPERTIES",
            "html": "HTML",
            "strings": "STRINGS",
            "xml": "ANDROID",
            "json": "CHROME",
            "ts": "QT"
            }

    def _get_i18n_type(self, full_filename):
        """ Derive the Transifex format type from the resource file extension """
        _, file_extension = os.path.splitext(full_filename)
        file_extension = file_extension.split(".")[1]
        if file_extension in self._transifex_i18n_type:
            return self._transifex_i18n_type[file_extension]
        else:
            raise TransUpdateError("ERROR: unrecognised extension in filename: '%s'" % full_filename)

    def _get_proj_slug(self):
        """ Get the Transifex project slug """
        if self._noprojprefix:
            proj_name = self._reponame
        else:
            proj_name = "%s%s" % (_Const.TRANSIFEX_PROJ_PREFIX, self._reponame)
        project_slug = slugify(proj_name)
        if not self._transifex.project_exists(project_slug):
            raise TransUpdateError("ERROR: project does not exist: '%s'" % project_slug)
        return project_slug

    def _get_filtered_upload_list(self, filelist):
        """ Scan a repo change list for resource files """
        res_filelist = []
        all_res_files, __, __ = self._res_info.get()
        if filelist == _Const.ALL:
            res_filelist.extend(all_res_files)
            msg = "About to upload all resources (%d)" % len(res_filelist)
        else:
            total = 0
            with open(filelist) as f:
                for line in f:
                    total += 1
                    test_file = os.path.join(self._clonepath, line.rstrip("\n\r"))
                    if test_file in all_res_files:
                        res_filelist.append(test_file)
            msg = "%d resource(s) found in %d changed files" % (len(res_filelist), total)
        return res_filelist, msg

    def _get_filtered_upload_list_by_cksum_compare(self, cksum_folder, git_branch, download_path, cksum_file_suffix):
        """ Check all English resource hashes against previous values """
        file_list, __, __ = self._res_info.get()
        changed_files = self._get_changed_and_new_resources(cksum_folder, git_branch, download_path, file_list, cksum_file_suffix)
        res_filelist = [os.path.join(download_path, change_file) for change_file in changed_files]
        msg = "%d changed/new resource(s) out of %d total" % (len(res_filelist), len(file_list))
        return res_filelist, msg

    def upload_source_files(self, filelist, filehash, cksum_folder, git_branch, download_path):
        """ Upload English resource files to Transifex """
        project_slug = self._get_proj_slug()

        curr_res_names = []
        curr_res_info = self._transifex.list_resources(project_slug)
        if curr_res_info:
            curr_res_names = [item['name'] for item in curr_res_info]

        cksum_file_suffix = "english"
        if filehash:
            res_files, msg = self._get_filtered_upload_list_by_cksum_compare(cksum_folder, git_branch, download_path, cksum_file_suffix)
        else:
            res_files, msg = self._get_filtered_upload_list(filelist)

        print msg
        for res_file in res_files:
            filename = os.path.basename(res_file)
            i18n_type = self._get_i18n_type(res_file)
            print "Uploading %s" % res_file
            if filename in curr_res_names:
                # update resource strings
                self._transifex.update_source_translation(project_slug, res_file, i18n_type=i18n_type)
            else:
                # create resource
                self._transifex.new_resource(project_slug, res_file, resource_name=filename, i18n_type=i18n_type)
                #for lang in self._res_info['langs']:
                #    self._transifex.new_language(project_slug, lang, ["buildmaster"])

        if filehash and len(res_files) > 0:
            # update English resource hashes
            self.write_cksumfile(cksum_folder, git_branch, download_path, cksum_file_suffix=cksum_file_suffix, english_mode=True)

        return _Const.EXIT_OK

    def _compute_file_hash(self, filename, nBufferSize=8192):
        if not os.path.exists(filename):
            raise TransUpdateError("ERROR: file does not exist: '%s'" % filename)
        with open(filename) as fp:
            m = hashlib.md5()
            fp.seek(0)
            s = fp.read(nBufferSize)
            while s:
                m.update(s)
                s = fp.read(nBufferSize)
        return m.hexdigest()

    def _download_from_transifex(self, download_path, file_list, tx_res_list, tx_lang_list):
        """ Download translated resource files and return completion stats"""
        stats_all = {}
        project_slug = self._get_proj_slug()
        for i, file in enumerate(file_list):
            lang = tx_lang_list[i]
            resource_slug = slugify(tx_res_list[i])
            create_path(os.path.dirname(file))
            print "Downloading %s" % file
            self._transifex.get_translation(project_slug, resource_slug, lang, file)
            stats = self._transifex.get_statistics(project_slug, resource_slug, lang)
            stats_all[file[len(download_path)+1:]] = stats
        return stats_all

    def _compute_current_hashinfo(self, download_path, file_list):
        hashinfo = {}
        for file in file_list:
            filename = file[len(download_path)+1:]
            hashinfo[filename] = self._compute_file_hash(file)
        return hashinfo

    def _get_hash_filename(self, cksum_folder, git_branch, repo_name, suffix):
        underscore_suffix = "_" + suffix if suffix else suffix
        return os.path.join(cksum_folder, "%s_%s%s.json" % (git_branch, repo_name, underscore_suffix))

    def _read_previous_hashinfo(self, cksum_folder, git_branch, suffix):
        hashinfo = {}
        hash_filename = self._get_hash_filename(cksum_folder, git_branch, self._reponame, suffix)
        try:
            with open(hash_filename, "r") as fp:
                hashinfo = json.load(fp)
        except Exception as e:
            hashinfo = {}
        return hashinfo

    def _get_changed_and_new_resources(self, cksum_folder, git_branch, download_path, file_list, suffix=""):
        """ Check if there are any changes to resource files compared to last successful download """
        changed_items = []
        if cksum_folder:
            latest_hashinfo = self._compute_current_hashinfo(download_path, file_list)
            previous_hashinfo = self._read_previous_hashinfo(cksum_folder, git_branch, suffix)
            for item, hash in latest_hashinfo.iteritems():
                if item in previous_hashinfo:
                    if hash != previous_hashinfo[item]:
                        changed_items.append(item)
                else:
                    changed_items.append(item)
            changed_items.sort()
        return changed_items

    def write_download_list_file(self, download_list_file, download_path, file_list):
        if download_list_file:
            with open(download_list_file, "w") as fp:
                for file in file_list:
                    fp.write("%s\n" % file[len(download_path)+1:])

    def _display_results(self, stats_all, cksum_folder, git_branch, download_path, file_list):
        """ Show results and return number of changed/new items """
        changed = self._get_changed_and_new_resources(cksum_folder, git_branch, download_path, file_list)
        num_changed = len(changed)
        print "\nNumber of changed/new files (***): %d" % num_changed
        line_format = "%-12s%-115s%-16s%-12s%-15s%s"
        print line_format % ("Completed", "Resource", "Words", "Entities", "Commiter", "Updated")
        for file in file_list:
            filename_lang = file[len(download_path)+1:]
            if filename_lang in stats_all:
                stats = stats_all[filename_lang]
            else:
                raise TransUpdateError("ERROR: no stats for %s" % filename_lang)
            word_total = int(stats['translated_words']) + int(stats['untranslated_words'])
            word_item = "%s/%d" % (stats['translated_words'], word_total)
            entity_total = int(stats['translated_entities']) + int(stats['untranslated_entities'])
            entity_item = "%s/%d" % (stats['translated_entities'], entity_total)
            completed_item = "*** %s" % stats['completed'] if filename_lang in changed else stats['completed']
            line = line_format % (completed_item, filename_lang, word_item, entity_item, stats['last_commiter'], stats['last_update'])
            print line
        return num_changed

    def process_translated_files(self, cksum_folder, git_branch, download_path, download_list_file):
        """ Process resources files from Transifex """
        file_list, tx_res_list, tx_lang_list = self._res_info.get(english_mode=False)
        stats = self._download_from_transifex(download_path, file_list, tx_res_list, tx_lang_list)
        self.write_download_list_file(download_list_file, download_path, file_list)
        num_changed = self._display_results(stats, cksum_folder, git_branch, download_path, file_list)
        exit_val = _Const.EXIT_OK if num_changed else _Const.EXIT_OK_NOCHANGES
        return exit_val

    def write_cksumfile(self, cksum_folder, git_branch, download_path, cksum_file_suffix="", english_mode=False):
        """ Write resource file checksum info """
        file_list, __, __ = self._res_info.get(english_mode)
        latest_hashinfo = self._compute_current_hashinfo(download_path, file_list)
        hash_filename = self._get_hash_filename(cksum_folder, git_branch, self._reponame, cksum_file_suffix)
        with open(hash_filename, "w") as fp:
            json.dump(latest_hashinfo, fp, sort_keys=True)
        return _Const.EXIT_OK


def args_check(args):
    # Transifex credentials
    transcred = os.path.expandvars(os.path.expanduser(args.transcred))
    with open(transcred, "r") as fp:
        transcred = json.load(fp)
    args.transuser = transcred['username']
    args.transpass = transcred['password']
    # Mode
    if args.mode == _Const.MODE_UP:
        if (not args.filelist and not args.filehash) or (args.filelist and args.filehash):
            raise TransUpdateError("ERROR: must supply one of either -fl or -fh")
        if args.filehash:
            if not args.cksumfolder:
                raise TransUpdateError("ERROR: must supply -ckf")
            if not args.gitbranch:
                raise TransUpdateError("ERROR: must supply -gitbranch")
    else:
        # _Const.MODE_UP and _Const.MODE_CKSUMFILE
        if not args.cksumfolder:
            raise TransUpdateError("ERROR: must supply -ckf")
        if not args.gitbranch:
            raise TransUpdateError("ERROR: missing parameter -gb")
    if not args.downloadpath:
        args.downloadpath = args.clonepath
    if args.cksumfolder:
        args.cksumfolder = os.path.expandvars(os.path.expanduser(args.cksumfolder))
        if not os.path.isdir(args.cksumfolder):
            raise TransUpdateError("ERROR: -ckf folder does not exist: %s" % args.cksumfolder)


def args_get():
    parser = argparse.ArgumentParser()
    parser.add_argument('-m', '--mode', choices=[_Const.MODE_UP, _Const.MODE_DOWN, _Const.MODE_CKSUMFILE], help=r'"up"=upload English source file to Transifex, "down"=download translated files from Transifex', required=True)
    parser.add_argument('-fl', '--filelist', help=r'One of -fl or -fh required for -m up: file list to filter for English resources or "all" to choose all resources, ex: gitdiff.txt')
    parser.add_argument('-fh', '--filehash', help=r'One of -fl or -fh required for -m up: determine English resource changes by comparing with previous file hashes', action='store_true')
    parser.add_argument('-tc', '--transcred', help=r'Transifex credentials file (JSON) ex: ~/.transifex.json', required=True)
    parser.add_argument('-rl', '--repolocalizeinfo', help=r'Repo localization info file ex: localize_info.json', required=True)
    parser.add_argument('-rn', '--reponame', help=r'Repo name, ex: android, ios, newton', required=True)
    parser.add_argument('-c', '--clonepath', help=r'Repo clone path, ex: <Jenkins job workspace>', required=True)
    parser.add_argument('-ckf', '--cksumfolder', help=r'Used by -m down: checksum folder - where files with checksums on last downloaded filenames are kept')
    parser.add_argument('-gb', '--gitbranch', help=r'Required for -m down: the git branch name, ex: rel-1.43')
    # optional
    parser.add_argument('-dlf', '--download_list_file', help=r'Filename to contain downloaded file list relative to -c')
    parser.add_argument('-d', '--downloadpath', help=r'[Testing use] Optional for -m down (else -clonepath will be used) ex: <Jenkins job workspace>/stage/tmp')
    parser.add_argument('-npp', '--noprojprefix', help=r'[Testing use] No project name prefix (i.e. same as repo name)', action='store_true')
    args = parser.parse_args()
    return args


def main():
    args = args_get()
    args_check(args)

    trans_update = TransUpdate(args.transuser, args.transpass, args.reponame, args.noprojprefix, args.clonepath, args.repolocalizeinfo)
    if args.mode == _Const.MODE_UP:
        exit_val = trans_update.upload_source_files(args.filelist, args.filehash, args.cksumfolder, args.gitbranch, args.downloadpath)
    elif args.mode == _Const.MODE_DOWN:
        exit_val = trans_update.process_translated_files(args.cksumfolder, args.gitbranch, args.downloadpath, args.download_list_file)
    else:
        exit_val = trans_update.write_cksumfile(args.cksumfolder, args.gitbranch, args.downloadpath)
    return exit_val


if __name__ == "__main__":
    try:
        exit_val = main()
    except Exception as e:
        print "%s exception: %s" % (os.path.basename(__file__), e)
        exit_val = _Const.EXIT_ERROR
    sys.exit(exit_val)
