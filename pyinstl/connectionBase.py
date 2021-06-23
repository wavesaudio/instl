#!/usr/bin/env python3.9


import abc
import urllib.request, urllib.parse, urllib.error
import urllib.parse
import requests
import json
import urllib3
urllib3.disable_warnings()
import logging
log = logging.getLogger()

from typing import Dict

have_boto = True
try:
    import boto3
except Exception:
    have_boto = False


class ConnectionBase(object):
    repo_connection = None # global singleton, holding current connection
    def __init__(self, config_vars) -> None:
        self.config_vars = config_vars

    def get_cookie(self, net_loc):
        retVal = None
        cookie_list = list(self.config_vars.get("COOKIE_JAR", []))
        if cookie_list:
            for cookie_line in cookie_list:
                cred_split = cookie_line.split(":", 2)
                if len(cred_split) == 2 and net_loc.lower() == cred_split[0].lower():
                    retVal = 'Cookie', cred_split[1]
                    break

        return retVal

    def get_custom_headers(self, net_loc):
        retVal = list()
        cookie = self.get_cookie(net_loc)
        if cookie is not None:
            retVal.append(cookie)
        custom_headers = list(self.config_vars.get("CUSTOM_HEADERS", []))
        if custom_headers:
            for custom_header in custom_headers:
                custom_header_split = custom_header.split(":", 1)
                header_net_loc, header_values = custom_header_split[0], custom_header_split[1]
                if header_net_loc.lower() == net_loc.lower():
                    try:
                        header_values = json.loads(header_values)
                    except Exception as ex:
                        log.warning(f"""CUSTOM_HEADERS not valid json {custom_headers}, {ex}""")
                    else:
                        retVal.extend(list(header_values.items()))
        return retVal

    @abc.abstractmethod
    def open_connection(self, credentials):
        pass

    @abc.abstractmethod
    def translate_url(self, in_bare_url):
        pass


class ConnectionHTTP(ConnectionBase):
    def __init__(self, config_vars) -> None:
        super().__init__(config_vars)
        self.sessions: Dict[str, requests.Session] = dict()

    def open_connection(self, credentials):
        pass

    @abc.abstractmethod
    def translate_url(self, in_bare_url):
        parsed = urllib.parse.urlparse(in_bare_url)
        quoted_results = urllib.parse.ParseResult(scheme=parsed.scheme, netloc=parsed.netloc, path=urllib.parse.quote(parsed.path, "$()/:%"), params=parsed.params, query=parsed.query, fragment=parsed.fragment)
        retVal = urllib.parse.urlunparse(quoted_results)
        return retVal

    def get_session(self, url):
        netloc = urllib.parse.urlparse(url).netloc
        session = self.sessions.get(netloc, None)
        if session is None:
            session = requests.Session()
            session.verify=False
            self.sessions[netloc] = session
            headers = self.get_custom_headers(netloc)
            session.headers.update(headers)
        return session


if have_boto:
    class ConnectionS3(ConnectionHTTP):
        def __init__(self, credentials, config_vars) -> None:
            super().__init__(config_vars)
            self.boto_conn = None
            self.open_bucket = None
            self.default_expiration = int(self.config_vars.get("S3_SECURE_URL_EXPIRATION", str(60*60*24)))  # in seconds
            self.open_connection(credentials)

        def open_connection(self, credentials):
            in_access_key, in_secret_key, in_bucket = credentials
            self.boto_conn = boto3.connect_s3(in_access_key, in_secret_key)
            self.open_bucket = self.boto_conn.get_bucket(in_bucket, validate=False)
            self.config_vars["S3_BUCKET_NAME"] = in_bucket

        def translate_url(self, in_bare_url):
            parseResult = urllib.parse.urlparse(in_bare_url)
            if parseResult.netloc.startswith(self.open_bucket.name):
                the_key = self.open_bucket.get_key(parseResult.path, validate=False)
                retVal = the_key.generate_url(self.default_expiration)
            else:
                retVal = super().translate_url(in_bare_url)
            return retVal


def connection_factory(config_vars):
    if ConnectionBase.repo_connection is None:
        if "__CREDENTIALS__" in config_vars and have_boto:
            credentials = config_vars["__CREDENTIALS__"].str()
            cred_split = credentials.split(":")
            if cred_split[0].lower() == "s3":
                ConnectionBase.repo_connection = ConnectionS3(cred_split[1:], config_vars)
        else:
            ConnectionBase.repo_connection = ConnectionHTTP(config_vars)
    return ConnectionBase.repo_connection


def translate_url(in_bare_url, config_vars):
    translated_url = connection_factory(config_vars).translate_url(in_bare_url)
    parsed = urllib.parse.urlparse(translated_url)
    cookie = connection_factory(config_vars).get_custom_headers(parsed.netloc)
    return translated_url, cookie
