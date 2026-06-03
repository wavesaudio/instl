#!/usr/bin/env python3.12

import subprocess
from pathlib import Path, PurePath
import sys
import itertools
import functools
import logging
import os
import re
from packaging.version import Version

log = logging.getLogger()
if sys.platform == 'win32':
    import win32api
from dataclasses import dataclass

import utils
from configVar import config_vars  # √
from . import connectionBase
from pybatch import *

@dataclass
class CurlConfigFile:
    path: Path
    wfd: int = None
    num_urls = 0


@dataclass
class CurlDownloadEntry:
    url: str
    final_path: str
    output_path: str
    size: int = 0
    resume_from_byte: int = 0
    conditional_headers: tuple[str, ...] = ()

    def has_per_transfer_options(self):
        return self.resume_from_byte > 0 or len(self.conditional_headers) > 0

    def is_resume_entry(self):
        return self.resume_from_byte > 0

    def fresh_restart_entry(self):
        return CurlDownloadEntry(
            url=self.url,
            final_path=self.final_path,
            output_path=self.output_path,
            size=self.size,
        )


def _curl_config_quoted_value(value):
    return str(value).replace("\\", "\\\\").replace('"', r'\"')


class CUrlHelper(object, metaclass=abc.ABCMeta):
    """ Create download commands. Each function should be overridden to implement the download
        on specific platform using a specific copying tool. All functions return
        a list of commands, even if there is only one. This will allow to return
        multiple commands if needed.
    """
    curl_output_format_str = r'%{url_effective}, %{size_download} bytes, %{time_total} sec., %{speed_download} bps.\n'
    # for debugging:
    curl_extra_write_out_str = r'    num_connects:%{num_connects}, time_namelookup: %{time_namelookup}, time_connect: %{time_connect}, time_pretransfer: %{time_pretransfer}, time_redirect: %{time_redirect}, time_starttransfer: %{time_starttransfer}\n\n'

    # text for curl config file in case instl is running curl copies in parallel
    external_parallel_header_text = """
insecure
raw
fail
silent
show-error
compressed
create-dirs
connect-timeout = {connect_time_out}
max-time = {max_time}
retry = {retries}
retry-delay = {retry_delay}
{extra_retry_options}
cookie = {cookie_text}
write-out = "Progress: ... of ...; {basename}: {curl_output_format_str}"


"""
    # text for curl config file in case instl running curl with parallel option
    internal_parallel_header_text = """
parallel
progress-bar
insecure
raw
fail
show-error
compressed
create-dirs
connect-timeout = {connect_time_out}
max-time = {max_time}
retry = {retries}
retry-delay = {retry_delay}
{extra_retry_options}
cookie = {cookie_text}
parallel-max = {max_parallel_downloads}


"""
    min_supported_parallel_curl_version = "7.66.0"
    cached_internal_parallel = None  # True means curl knows to parallel download internally, set to None



    def __init__(self) -> None:
        self.urls_to_download = list()
        self.urls_to_download_last = list()
        self.short_win_paths_cache = dict()


    # this is done as lazy load, since the actual "curl" location is known a bit later after the class is created
    # executes and reads the version of the curl if it matches the expected version, returns True, otherwise returns False
    # If we've already computed the value no need to check this again
    def is_internal_parallel_supported(self):
        if CUrlHelper.cached_internal_parallel is None:
            CUrlHelper.cached_internal_parallel = False
            try:
                # The curl --version output is
                # curl 7.79.1 (x86_64-apple-darwin21.0) libcurl/7.79.1 (SecureTransport) LibreSSL/3.3.6 zlib/1.2.11 nghttp2/1.45.1
                # Release-Date: 2021-09-22
                # Protocols: dict file ftp ftps gopher gophers http https imap imaps ldap ldaps mqtt pop3 pop3s rtsp smb smbs smtp smtps telnet tftp
                # Features: alt-svc AsynchDNS GSS-API HSTS HTTP2 HTTPS-proxy IPv6 Kerberos Largefile libz MultiSSL NTLM NTLM_WB SPNEGO SSL UnixSockets
                # So we take the fist line after the "curl" word

                exe_name = config_vars.resolve_str("curl")
                proc = subprocess.Popen(
                        f"{exe_name} --version",
                        shell=True,
                        stderr=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        universal_newlines=True)

                match = re.search(r"curl\s+([0-9.]+)\s", proc.stdout.read())

                if match is not None and len(match.groups()) > 0:
                    curl_version = Version(match.group(1))
                    min_version = Version(CUrlHelper.min_supported_parallel_curl_version)
                    if min_version > curl_version:
                        log.info(f"Detected a legacy curl version {match.group(1)}")
                    else:
                        CUrlHelper.cached_internal_parallel = True
            except Exception:
                log.info(f"Could not parse CURL version, assuming legacy version")
        return CUrlHelper.cached_internal_parallel

    def use_internal_parallel(self):
        return config_vars["PARALLEL_DOWNLOAD_METHOD"].str() == "internal" and self.is_internal_parallel_supported()

    def add_download_url(self, url, path, verbatim=False, size=0, download_last=False, output_path=None, resume_from_byte=0, conditional_headers=()):
        if verbatim:
            translated_url = url
        else:
            translated_url = connectionBase.connection_factory(config_vars).translate_url(url)
        resume_from_byte = int(resume_from_byte or 0)
        if resume_from_byte < 0:
            raise ValueError(f"resume_from_byte must be non-negative, got {resume_from_byte}")
        conditional_headers = tuple(str(header) for header in (conditional_headers or ()))
        if any("\r" in header or "\n" in header for header in conditional_headers):
            raise ValueError("conditional_headers must not contain newlines")
        download_entry = CurlDownloadEntry(
            url=translated_url,
            final_path=os.fspath(path),
            output_path=os.fspath(output_path if output_path is not None else path),
            size=size,
            resume_from_byte=resume_from_byte,
            conditional_headers=conditional_headers,
        )
        if download_last:
            self.urls_to_download_last.append(download_entry)
        else:
            self.urls_to_download.append(download_entry)

    def get_num_urls_to_download(self):
        return len(self.urls_to_download)+len(self.urls_to_download_last)

    def download_from_config_file(self, config_file):
        pass

    def fix_path(self, in_some_path_to_fix):
        """  On Windows: to overcome cUrl inability to handle path with unicode chars, we try to calculate the windows
                short path (DOS style 8.3 chars). The function that does that, win32api.GetShortPathName,
                does not work for paths that do not yet exist so we need to also create the folder.
                However if the creation requires admin permissions - it could fail -
                in which case we revert to using the long path.
        """

        fixed_path = PurePath(in_some_path_to_fix)
        if 'Win' in utils.get_current_os_names():
            # to overcome cUrl inability to handle path with unicode chars, we try to calculate the windows
            # short path (DOS style 8.3 chars). The function that does that, win32api.GetShortPathName,
            # does not work for paths that do not yet exist so we need to also create the folder.
            # However if the creation requires admin permissions - it could fail -
            # in which case we revert to using the long path.
            import win32api
            fixed_path_parent = str(fixed_path.parent)
            fixed_path_name = str(fixed_path.name)
            if fixed_path_parent not in self.short_win_paths_cache:
                try:
                    os.makedirs(fixed_path_parent, exist_ok=True)
                    short_parent_path = win32api.GetShortPathName(fixed_path_parent)
                    self.short_win_paths_cache[fixed_path_parent] = short_parent_path
                except Exception as e:  # failed to mkdir or get the short path? never mind, just use the full path
                    self.short_win_paths_cache[fixed_path_parent] = fixed_path_parent
                    log.warning(f"""warning creating short path failed for {fixed_path}, {e}, using long path""")

            short_file_path = os.path.join(self.short_win_paths_cache[fixed_path_parent], fixed_path_name)
            fixed_path = short_file_path.replace("\\", "\\\\")
        return fixed_path

    def create_config_files(self, curl_config_folder, num_config_files):
        return self._create_config_files_for_entries(
            curl_config_folder,
            num_config_files,
            self.urls_to_download,
            self.urls_to_download_last,
        )

    def _create_config_files_for_entries(
            self,
            curl_config_folder,
            num_config_files,
            urls_to_download,
            urls_to_download_last=(),
            file_name_suffix=""):
        config_file_list = list()
        urls_to_download = list(urls_to_download)
        urls_to_download_last = list(urls_to_download_last)

        if len(urls_to_download) + len(urls_to_download_last) <= 0:
            return config_file_list

        # Offline grace window: on a network drop mid-sync, curl's default
        # retry set does not cover "network unreachable" (exit 7), so the
        # session fails within ~one connect-timeout. retry-connrefused +
        # retry-all-errors make curl keep retrying through a brief outage,
        # bounded by retry-max-time so genuine failures still terminate.
        # retry-all-errors needs curl >= 7.71; it is gated behind a config var
        # so it can be turned off (e.g. for an old bundled curl) without code.
        #
        # IMPORTANT: retry-all-errors is mutually exclusive with the resume
        # fallback. The fallback restarts a transfer from zero when curl exits
        # 33 (range not satisfiable / bad Content-Range); retry-all-errors would
        # instead retry that same request, defeating the fallback. So we only
        # add it when this config batch has NO resume entries (the production
        # default, since resume ships off). Resume batches keep the exit-33
        # fallback and skip retry-all-errors.
        has_resume_entries = any(
            entry.resume_from_byte > 0
            for entry in itertools.chain(urls_to_download, urls_to_download_last)
        )
        retry_max_time = str(config_vars.setdefault("CURL_RETRY_MAX_TIME", "90"))
        extra_retry_lines = ["retry-connrefused", f"retry-max-time = {retry_max_time}"]
        if (not has_resume_entries
                and str(config_vars.setdefault("CURL_RETRY_ALL_ERRORS", "yes")).strip().lower() in ("yes", "true", "1")):
            extra_retry_lines.append("retry-all-errors")

        config_options = {
            "connect_time_out": str(config_vars.setdefault("CURL_CONNECT_TIMEOUT", "16")),
            "max_time": str(config_vars.setdefault("CURL_MAX_TIME", "180")),
            "retries": str(config_vars.setdefault("CURL_RETRIES", "5")),
            "retry_delay": str(config_vars.setdefault("CURL_RETRY_DELAY", "8")),
            "extra_retry_options": "\n".join(extra_retry_lines),
            "cookie_text": str(config_vars.get("COOKIE_FOR_SYNC_URLS", "")),
            "max_parallel_downloads": str(config_vars.get("PARALLEL_SYNC", "50")),
            "curl_output_format_str": self.curl_output_format_str
        }

        if self.use_internal_parallel():
            confi_file_text = self.internal_parallel_header_text
            actual_num_config_files = int(max(0, min(len(urls_to_download), 1)))
        else:
            confi_file_text = self.external_parallel_header_text
            actual_num_config_files = int(max(0, min(len(urls_to_download), num_config_files)))

        if urls_to_download_last:
            actual_num_config_files += 1

        # a list of curl config file and number of urls in each
        file_name_prefix = f"{config_vars['CURL_CONFIG_FILE_NAME']}{file_name_suffix}"
        for file_i in range(actual_num_config_files):
            config_file_path = curl_config_folder.joinpath(f"{file_name_prefix}-{file_i:02}")
            config_file_list.append(CurlConfigFile(config_file_path))

        def write_config_header(a_file):
            config_options["basename"] = a_file.path.name
            curl_config_header = confi_file_text.format(**config_options)
            a_file.wfd.write(curl_config_header)

        # open the files make sure they have r/w permissions and are utf-8
        # write curl config header to each file
        for a_file in config_file_list:
            a_file.wfd = utils.utf8_open_for_write(a_file.path, "w")
            write_config_header(a_file)

        use_isolated_transfer_sections = any(
            download_entry.has_per_transfer_options()
            for download_entry in itertools.chain(self.urls_to_download, self.urls_to_download_last)
        )

        def write_download_entry(file_details, download_entry):
            if use_isolated_transfer_sections and file_details.num_urls > 0:
                file_details.wfd.write("next\n")
                write_config_header(file_details)
            fixed_path = self.fix_path(download_entry.output_path)
            if download_entry.resume_from_byte > 0:
                file_details.wfd.write("no-fail\n")
                file_details.wfd.write(f"continue-at = {download_entry.resume_from_byte}\n")
            for header in download_entry.conditional_headers:
                file_details.wfd.write(f'header = "{_curl_config_quoted_value(header)}"\n')
            file_details.wfd.write(f'''url = "{download_entry.url}"\noutput = "{fixed_path}"\n\n''')
            file_details.num_urls += 1

        last_file = None
        if urls_to_download_last:
            last_file = config_file_list.pop()

        def url_sorter(l, r):
            """ smaller files should be downloaded first so the progress bar gets moving early. """
            return l.size - r.size  # non Info.xml files are sorted by size

        cfig_file_cycler = itertools.cycle(config_file_list)
        total_url_num = 0
        # No sorting for curl's parallel as the progress looks better when there are mixed sizes
        sorted_by_size = urls_to_download if self.use_internal_parallel() else sorted(urls_to_download, key=functools.cmp_to_key(url_sorter))

        for download_entry in sorted_by_size:
            file_details = next(cfig_file_cycler)
            write_download_entry(file_details, download_entry)
            total_url_num += 1

        for a_file in config_file_list:
            a_file.wfd.close()
            a_file.wfd = None

        if last_file:
            # write urls for files that should be downloaded last
            for download_entry in urls_to_download_last:
                write_download_entry(last_file, download_entry)
                total_url_num += 1
            last_file.wfd.close()
            last_file.wfd = None
            # insert None which means "wait" before the config file that downloads urls_to_download_last.
            # but only if there were actually download files other than urls_to_download_last.
            # it might happen that there are only urls_to_download_last - so no need to "wait".
            if not self.use_internal_parallel() and len(config_file_list) > 0:
                config_file_list.append(None)
            config_file_list.append(last_file)

        return config_file_list

    def _config_files_url_count(self, config_file_list):
        return sum(config_file.num_urls for config_file in config_file_list if config_file is not None)

    def _partition_resume_entries(self, entries):
        fresh_entries = list()
        resume_entries = list()
        for entry in entries:
            if entry.is_resume_entry():
                resume_entries.append(entry)
            else:
                fresh_entries.append(entry)
        return fresh_entries, resume_entries

    def _create_download_config_phase(
            self,
            curl_config_folder,
            num_config_files,
            entries,
            file_name_suffix,
            create_fallback=False):
        config_files = self._create_config_files_for_entries(
            curl_config_folder,
            num_config_files,
            entries,
            file_name_suffix=file_name_suffix,
        )
        fallback_config_files = list()
        if create_fallback and config_files:
            fallback_entries = [entry.fresh_restart_entry() for entry in entries]
            fallback_config_files = self._create_config_files_for_entries(
                curl_config_folder,
                num_config_files,
                fallback_entries,
                file_name_suffix=f"{file_name_suffix}-fallback",
            )
        return config_files, fallback_config_files

    def _add_external_parallel_download_commands(
            self,
            dl_commands,
            curl_config_folder,
            config_file_list,
            fallback_config_file_list=()):
        if not config_file_list:
            return

        file_name = config_file_list[0].path.name
        parallel_run_config_file_path = curl_config_folder.joinpath(f"{file_name}.parallel-run")
        self.create_parallel_run_config_file(parallel_run_config_file_path, config_file_list)

        fallback_parallel_run_config_file_path = None
        if fallback_config_file_list:
            fallback_parallel_run_config_file_path = curl_config_folder.joinpath(f"{file_name}.fallback.parallel-run")
            self.create_parallel_run_config_file(fallback_parallel_run_config_file_path, fallback_config_file_list)

        dl_commands += ParallelRun(
            parallel_run_config_file_path,
            shell=False,
            action_name="Downloading",
            fallback_config_file=fallback_parallel_run_config_file_path,
            fallback_exit_codes=(33,),
            own_progress_count=self._config_files_url_count(config_file_list),
            report_own_progress=False,
        )

    def _add_internal_parallel_download_commands(
            self,
            dl_commands,
            config_file_list,
            fallback_config_file_list,
            total_files_to_download,
            total_bytes_to_download,
            previously_downloaded_files):
        fallback_by_path = {}
        for config_file, fallback_config_file in zip(config_file_list, fallback_config_file_list):
            fallback_by_path[config_file.path] = fallback_config_file.path

        for config_file in config_file_list:
            dl_commands += CurlWithInternalParallel(
                curl_path=f"$(DOWNLOAD_TOOL_PATH)",
                config_file_path=config_file.path,
                fallback_config_file_path=fallback_by_path.get(config_file.path),
                fallback_exit_codes=(33,),
                total_files_to_download=total_files_to_download,
                previously_downloaded_files=previously_downloaded_files,
                total_bytes_to_download=total_bytes_to_download,
                action_name="Downloading",
                own_progress_count=config_file.num_urls,
                report_own_progress=False)
            previously_downloaded_files += config_file.num_urls
        return previously_downloaded_files

    def create_download_instructions(self, dl_commands):
        """ Download is done be creating files with instructions for curl - curl config files.
            Another file is created containing invocations of curl with each of the config files
            - the parallel run file.
            curl_config_folder: the folder where curl config files and parallel run file will be placed.
            num_config_files: the maximum number of curl config files.
            actual_num_config_files: actual number of curl config files created. Might be smaller
            than num_config_files, or might be 0 if downloading is not required.
        """

        main_outfile = config_vars["__MAIN_OUT_FILE__"].Path()
        curl_config_folder = main_outfile.parent.joinpath(main_outfile.name+"_curl")
        MakeDir(curl_config_folder, chowner=True, own_progress_count=0, report_own_progress=False)()

        num_config_files = int(config_vars["PARALLEL_SYNC"])
        fresh_downloads, resume_downloads = self._partition_resume_entries(self.urls_to_download)
        fresh_downloads_last, resume_downloads_last = self._partition_resume_entries(self.urls_to_download_last)
        if resume_downloads or resume_downloads_last:
            config_file_groups = list()
            for suffix, entries, create_fallback in (
                    ("-fresh", fresh_downloads, False),
                    ("-resume", resume_downloads, True),
                    ("-fresh-last", fresh_downloads_last, False),
                    ("-resume-last", resume_downloads_last, True),
            ):
                config_files, fallback_config_files = self._create_download_config_phase(
                    curl_config_folder,
                    num_config_files,
                    entries,
                    suffix,
                    create_fallback=create_fallback,
                )
                if config_files:
                    config_file_groups.append((config_files, fallback_config_files))
            config_file_list = [
                config_file
                for config_files, _fallback_config_files in config_file_groups
                for config_file in config_files
            ]
        else:
            # TODO: Move class someplace else
            config_file_list = self.create_config_files(curl_config_folder, num_config_files)
            config_file_groups = [(config_file_list, list())] if config_file_list else list()

        actual_num_config_files = len(config_file_list)
        if actual_num_config_files > 0:
            if num_config_files > 1:
                dl_start_message = f"Downloading with {num_config_files} processes in parallel"
            else:
                dl_start_message = "Downloading with 1 process"
            dl_commands += Progress(dl_start_message)

            total_files_to_download = int(config_vars["__NUM_FILES_TO_DOWNLOAD__"])
            total_bytes_to_download = int(config_vars["__NUM_BYTES_TO_DOWNLOAD__"])

            if self.use_internal_parallel():
                dl_commands += Progress(f"Downloading with curl parallel")
                previously_downloaded_files = 0
                for group_config_files, group_fallback_config_files in config_file_groups:
                    previously_downloaded_files = self._add_internal_parallel_download_commands(
                        dl_commands,
                        group_config_files,
                        group_fallback_config_files,
                        total_files_to_download,
                        total_bytes_to_download,
                        previously_downloaded_files,
                    )
            else:
                if num_config_files > 1:
                    dl_start_message = f"Downloading with {num_config_files} processes in parallel"
                else:
                    dl_start_message = "Downloading with 1 process"
                dl_commands += Progress(dl_start_message)
                for group_config_files, group_fallback_config_files in config_file_groups:
                    self._add_external_parallel_download_commands(
                        dl_commands,
                        curl_config_folder,
                        group_config_files,
                        group_fallback_config_files,
                    )

            if total_files_to_download > 1:
                dl_end_message = f"Downloading {total_files_to_download} files done"
            else:
                dl_end_message = "Downloading 1 file done"

            dl_commands += Progress(dl_end_message)

            return dl_commands

    def create_parallel_run_config_file(self, parallel_run_config_file_path, config_files):
        with utils.utf8_open_for_write(parallel_run_config_file_path, "w") as wfd:
            for config_file in config_files:
                if config_file is None:  # None means to insert a wait
                    wfd.write("wait\n")
                else:
                    if sys.platform == 'win32':
                        # curl on windows has problem with path to config files that have unicode characters
                        normalized_path = win32api.GetShortPathName(str(config_file.path))
                    else:
                        normalized_path = config_file.path
                    wfd.write(config_vars.resolve_str(f'''"$(DOWNLOAD_TOOL_PATH)" --config "{normalized_path}"\n'''))
