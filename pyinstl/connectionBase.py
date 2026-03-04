#!/usr/bin/env python3.12


import abc
import json
import ssl
import urllib.error
import urllib.parse

import requests
from requests.adapters import HTTPAdapter

import logging

log = logging.getLogger()

from typing import Dict


class SSLContextAdapter(HTTPAdapter):
    """Custom HTTPAdapter with a maximally permissive SSL context.

    See https://wavesaudio.atlassian.net/browse/CEN2-3633 - customers
    from Serbia had installed their own governments' certificates
    instead of Windows default ones.
    The issue may take place with any such corporate CAs.

    Python 3.12 / OpenSSL 3.x enforces strict DER/ASN.1 parsing during the
    TLS handshake.  The '[ASN1] nested asn1 error' (_ssl.c) is NOT a
    certificate-verification error — it is a certificate-parsing error that
    occurs even when verify=False, because OpenSSL still parses the server
    certificate to extract the public key for the key exchange.

    Common triggers on Windows:
      - A corporate SSL-inspection proxy whose certificate generator emits
        BER-encoded (not strict DER-encoded) RSA keys.
      - A malformed CA certificate in the Windows system cert store being
        loaded by ssl.create_default_context() (which calls load_default_certs).

    What this adapter does:
      1. Loads CAs from certifi's well-formed bundle instead of the Windows
         system cert store (avoids [ASN1] errors from malformed system CAs).
      2. Disables certificate verification (CERT_NONE / check_hostname=False).
      3. Sets @SECLEVEL=0 on the cipher list, making OpenSSL as permissive as
         possible about algorithm and encoding requirements.
      4. Sets OP_LEGACY_SERVER_CONNECT (re-enables pre-OpenSSL-3 renegotiation
         behaviour — helps with servers that don't advertise RI).

    Note: none of the above fully fixes the SSL-inspection-proxy case where the
    *server's* certificate has malformed ASN.1.  For that, the only reliable
    remedy is to use the OS-native TLS stack (Schannel on Windows) via the
    optional `truststore` package — see inject_truststore() below.
    """

    @staticmethod
    def _make_ssl_context() -> ssl.SSLContext:
        try:
            import certifi
            # create_default_context(cafile=...) loads certifi's CAs only —
            # it does NOT call load_default_certs(), so the Windows cert store
            # (which may contain malformed certs) is never touched.
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # SECLEVEL=0 makes OpenSSL accept any algorithm / encoding regardless
        # of age or strength.  Only set it; ignore errors on exotic builds.
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        except ssl.SSLError:
            pass

        # OP_LEGACY_SERVER_CONNECT re-enables pre-3.x renegotiation behaviour.
        if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT

        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._make_ssl_context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["ssl_context"] = self._make_ssl_context()
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def inject_truststore():
    """Optionally replace OpenSSL with the OS-native TLS stack (Schannel on
    Windows, SecureTransport on macOS).  This is the *only* reliable fix when
    the problem is a corporate SSL-inspection proxy that presents a certificate
    with non-conformant ASN.1 encoding, because the OS-native stacks parse
    certificates far more leniently than OpenSSL 3.x.

    The `truststore` package is an optional dependency.  When not installed
    this function is a silent no-op so that the rest of the SSL hardening
    still applies.
    """
    try:
        import truststore
        truststore.inject_into_ssl()
        log.debug("truststore: injected OS-native TLS (Schannel/SecureTransport)")
    except ImportError:
        pass  # truststore not installed — OpenSSL path is used

have_boto = False
# try:
#     import boto3
#     have_boto = True
# except Exception:
#     pass


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
        parsed = urllib.parse.urlparse(in_bare_url, allow_fragments=False)
        quoted_path = urllib.parse.quote(parsed.path, "$()/:%")
        quoted_results = urllib.parse.ParseResult(scheme=parsed.scheme, netloc=parsed.netloc,
                                                  path=quoted_path, params=parsed.params,
                                                  query=parsed.query, fragment=parsed.fragment)
        retVal = urllib.parse.urlunparse(quoted_results)
        return retVal

    def get_session(self, url):
        netloc = urllib.parse.urlparse(url).netloc
        session = self.sessions.get(netloc, None)
        if session is None:
            session = requests.Session()
            session.verify = False
            adapter = SSLContextAdapter()
            session.mount("https://", adapter)
            session.mount("http://", adapter)
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
