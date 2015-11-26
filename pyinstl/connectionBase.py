#!/usr/bin/env python2.7
from __future__ import print_function

import abc
import urllib
import urlparse

have_boto = True
try:
    import boto
except:
    have_boto = False

from configVar import var_stack


class ConnectionBase(object):
    repo_connection = None # global singleton, holding current connection
    def __init__(self):
        pass

    def get_cookie(self, net_loc):
        retVal = None
        cookie_list = var_stack.resolve_var_to_list_if_exists("COOKIE_JAR")
        if cookie_list:
            #print("cookie list:", cookie_list)
            for cookie_line in cookie_list:
                cred_split = cookie_line.split(":", 2)
                if len(cred_split) == 2 and net_loc.lower() == cred_split[0].lower():
                    retVal = cred_split[1]
                    break
        #else:
        #    print("No cookie list")
        return retVal

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
        quoted_results = urlparse.ParseResult(scheme=parsed.scheme, netloc=parsed.netloc, path=urllib.quote(parsed.path, "$()/:%"), params=parsed.params, query=parsed.query, fragment=parsed.fragment)
        retVal = urlparse.urlunparse(quoted_results)
        return retVal

if have_boto:
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


def connection_factory():
    if ConnectionBase.repo_connection is None:
        if "__CREDENTIALS__" in var_stack and have_boto:
            credentials = var_stack.resolve_var("__CREDENTIALS__", default=None)
            cred_split = credentials.split(":")
            if cred_split[0].lower() == "s3":
                ConnectionBase.repo_connection = ConnectionS3(cred_split[1:])
        else:
            ConnectionBase.repo_connection = ConnectionHTTP()
    return ConnectionBase.repo_connection

def translate_url(in_bare_url):
    translated_url = connection_factory().translate_url(in_bare_url)
    parsed = urlparse.urlparse(translated_url)
    cookie = connection_factory().get_cookie(parsed.netloc)
    return translated_url, cookie
