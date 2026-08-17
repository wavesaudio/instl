import unittest

from utils.yaml_signature import split_signed_text, strip_encryptor_signature


class TestYamlSignature(unittest.TestCase):
    def test_unsigned_unchanged(self):
        text = "MAIN_DOIT_ITEMS:\n  - foo\n"
        self.assertEqual(strip_encryptor_signature(text), text)
        self.assertIsNone(split_signed_text(text))

    def test_trailer_stripped(self):
        payload = "MAIN_DOIT_ITEMS:\n  - foo\n"
        signed = payload + "[abc\ndef]"
        self.assertEqual(strip_encryptor_signature(signed), payload)
        self.assertEqual(split_signed_text(signed), (payload, "abc\ndef"))

    def test_trailing_whitespace_after_bracket(self):
        payload = "key: value\n"
        signed = payload + "[sigvalue]\n\n"
        self.assertEqual(strip_encryptor_signature(signed), payload)
        self.assertEqual(split_signed_text(signed), (payload, "sigvalue"))

    def test_empty_signature_not_stripped(self):
        text = "key: value\n[]"
        self.assertEqual(strip_encryptor_signature(text), text)
        self.assertIsNone(split_signed_text(text))

    def test_no_closing_bracket(self):
        text = "key: value\n[not-a-sig"
        self.assertEqual(strip_encryptor_signature(text), text)
        self.assertIsNone(split_signed_text(text))

    def test_uses_last_open_bracket(self):
        payload = "list: [1, 2]\n"
        signed = payload + "[sig]"
        self.assertEqual(strip_encryptor_signature(signed), payload)


if __name__ == "__main__":
    unittest.main()
