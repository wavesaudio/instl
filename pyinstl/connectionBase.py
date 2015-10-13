#!/usr/bin/env python2.7
from __future__ import print_function

import abc
import urllib
import urlparse

import boto

from configVar import var_stack


class ConnectionBase(object):
    repo_connection = None # global singleton, holding current connection
    def __init__(self):
        self.cookies = dict()
        self.read_cookies()

    def read_cookies(self):
        cookie_list = var_stack.resolve_var_to_list_if_exists("COOKIE_JAR")
        if cookie_list:
            for cookie_line in cookie_list:
                cred_split = cookie_line.split(":", 2)
                if len(cred_split) == 2:
                    self.cookies[cred_split[0]] = cred_split[1]

    def cookie_for_url(self, in_netloc):
        cookie = self.cookies.get(in_netloc)
        return cookie

    @abc.abstractmethod
    def open_connection(self, credentials):
        pass

    @abc.abstractmethod
    def translate_url(self, in_bare_url):
        pass

class ConnectionHTTP(ConnectionBase):
    def __init__(self):
        super(ConnectionHTTP, self).__init__()

    def open_connection(self, credentials):
        pass

    @abc.abstractmethod
    def translate_url(self, in_bare_url):
        parsed = urlparse.urlparse(in_bare_url)
        quated_results = urlparse.ParseResult(scheme=parsed.scheme, netloc=parsed.netloc, path=urllib.quote(parsed.path, "$()/:%"), params=parsed.params, query=parsed.query, fragment=parsed.fragment)
        self.quote = urlparse.urlunparse(quated_results)
        retVal = self.quote
        return retVal


class ConnectionS3(ConnectionHTTP):
    def __init__(self, credentials):
        super(ConnectionS3, self).__init__()
        self.boto_conn = None
        self.open_bucket = None
        default_expiration_str = var_stack.resolve("$(S3_SECURE_URL_EXPIRATION)", default=str(60*60*24))
        self.default_expiration =  int(default_expiration_str)# in seconds
        self.open_connection(credentials)

    def open_connection(self, credentials):
        in_access_key, in_secret_key, in_bucket = credentials
        self.boto_conn = boto.connect_s3(in_access_key, in_secret_key)
        self.open_bucket = self.boto_conn.get_bucket(in_bucket, validate=False)
        var_stack.set_var("S3_BUCKET_NAME", "from command line options").append(in_bucket)

    def translate_url(self, in_bare_url):
        parseResult = urlparse.urlparse(in_bare_url)
        if parseResult.netloc.startswith(self.open_bucket.name):
            the_key = self.open_bucket.get_key(parseResult.path, validate=False)
            retVal = the_key.generate_url(self.default_expiration)
        else:
            retVal = super(ConnectionS3, self).translate_url(in_bare_url)
        return retVal


def connection_factory(credentials=None):
    if ConnectionBase.repo_connection is None:
        if credentials is None:
            ConnectionBase.repo_connection = ConnectionHTTP()
        else:
            cred_split = credentials.split(":")
            if cred_split[0].lower() == "s3":
                ConnectionBase.repo_connection = ConnectionS3(cred_split[1:])
    return ConnectionBase.repo_connection

def translate_url(in_bare_url):
    translated_url = connection_factory().translate_url(in_bare_url)
    parsed = urlparse.urlparse(translated_url)
    cookie = connection_factory().cookie_for_url(parsed.netloc)
    return translated_url, cookie
