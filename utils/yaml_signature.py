"""
Tolerate Encryptor-style trailing signatures on YAML payloads.

Wire format (matches Utilities/Encryptor/signer.py):
  payload + "[" + base64(RSA-PKCS1v15-SHA1(payload)) with newlines at 4/82/160 + "]"

Instl does not verify the signature. It only strips the trailer in memory so
the YAML parser sees the unsigned payload. Verification of helper-visible
``instl doit --in <yaml>`` is performed by InstlHelper.
"""

from __future__ import annotations


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


def strip_encryptor_signature(buffer: str) -> str:
    """
    If *buffer* ends with an Encryptor ``[sig]`` trailer, return the payload.
    Otherwise return *buffer* unchanged. Does not verify the signature.
    """
    parts = split_signed_text(buffer)
    if parts is None:
        return buffer
    return parts[0]
