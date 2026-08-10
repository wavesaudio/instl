"""
Verify Encryptor-style signatures on MAIN_DOIT_ITEMS YAML payloads.

Wire format (matches Utilities/Encryptor/signer.py):
  payload + "[" + base64(RSA-PKCS1v15-SHA1(payload)) with newlines at 4/82/160 + "]"

Verification uses an embedded PKCS#1 public key so Instl does not need Azure credentials.
"""

from __future__ import annotations

import base64
import re

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

MAIN_DOIT_MARKER = "MAIN_DOIT_ITEMS"
# Section/key declaration only — not variable refs like $(MAIN_DOIT_ITEMS).
_MAIN_DOIT_SECTION_RE = re.compile(rf"(?m)^\s*{MAIN_DOIT_MARKER}\s*:")


def declares_main_doit_items(text: str) -> bool:
    """True when *text* defines a MAIN_DOIT_ITEMS YAML key/section."""
    return _MAIN_DOIT_SECTION_RE.search(text) is not None

# PKCS#1 DER public key (Base64), from Encryptor export_public_key_pkcs1_b64()
# for certificate_key central-urlsign-pfx.
_DOIT_PUBLIC_KEY_PKCS1_B64 = (
    "MIGJAoGBANITmJV5OLukVGB+sr+XlwlyDKXsxV7b/qdih72UX7+UAgtedsMXCHBx"
    "WUBRe60d6+z21+VJocswm0jJPlFrNjtESdH8SmPMk4Eu+suaOPTZbXQ1Mk/kPlCt"
    "q3Oom2XaRupGlGouJur1ncz2PR+h1j/nQXVitRxOs7COYMPwit/JAgMBAAE="
)

_public_key: RSAPublicKey | None = None


def _get_public_key() -> RSAPublicKey:
    global _public_key
    if _public_key is None:
        der = base64.b64decode(_DOIT_PUBLIC_KEY_PKCS1_B64)
        key = serialization.load_der_public_key(der)
        if not isinstance(key, RSAPublicKey):
            raise TypeError("Embedded doit public key is not an RSA public key")
        _public_key = key
    return _public_key


def split_signed_text(signed_text: str) -> tuple[str, str] | None:
    """
    Split ``payload[sig]`` into (payload, sig_field).
    Returns None if the trailing signature bracket is missing/malformed.
    """
    signed_text = signed_text.rstrip()
    bracket_pos = signed_text.rfind("[")
    if bracket_pos == -1 or not signed_text.endswith("]"):
        return None

    text = signed_text[:bracket_pos]
    sig_field = signed_text[bracket_pos + 1 : -1]
    if not sig_field:
        return None
    return text, sig_field


def verify_signed_text(signed_text: str) -> bool:
    """Return True if *signed_text* has a valid Encryptor trailing signature."""
    parts = split_signed_text(signed_text)
    if parts is None:
        return False

    text, sig_field = parts
    sig_clean = sig_field.replace("\n", "")
    try:
        sig_bytes = base64.b64decode(sig_clean)
    except Exception:
        return False

    try:
        _get_public_key().verify(
            sig_bytes,
            text.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        return True
    except Exception:
        return False


def prepare_yaml_buffer_for_doit(buffer: str, path_for_error: str = "") -> str:
    """
    If *buffer* declares a MAIN_DOIT_ITEMS section (``MAIN_DOIT_ITEMS:``), require a
    valid Encryptor signature and return the unsigned payload for YAML parsing.
    Variable references such as ``$(MAIN_DOIT_ITEMS)`` do not require a signature.
    Otherwise return *buffer* unchanged.
    """
    if not declares_main_doit_items(buffer):
        return buffer

    where = f" ({path_for_error})" if path_for_error else ""
    parts = split_signed_text(buffer)
    if parts is None:
        raise ValueError(
            f"YAML contains {MAIN_DOIT_MARKER} but has no Encryptor signature{where}"
        )

    text, _sig = parts
    if not declares_main_doit_items(text):
        raise ValueError(
            f"YAML contains {MAIN_DOIT_MARKER} but signature payload is missing the marker{where}"
        )

    # Verify against the rstrip'd form used by split_signed_text.
    if not verify_signed_text(buffer.rstrip()):
        raise ValueError(
            f"Invalid Encryptor signature for MAIN_DOIT_ITEMS YAML{where}"
        )

    return text
