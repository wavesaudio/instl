import unittest
from utils import *

class TestStrUtils(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_quoteme_by_type(self):
        to_quote_in = (True, False, 0.001, 'bazu"ka',"shuki", 123, [123, "mama"], {"artizan": "vodka", "price": 19.19} )
        quoted_expected = ("True", "False", "0.001", """r'bazu"ka'""",'''r"shuki"''', "123", '''[123,r"mama"]''', '''{r"artizan":r"vodka",r"price":19.19}''')

        for in_, expected_ in zip(to_quote_in, quoted_expected):
            quoted_out = quoteme_raw_by_type(in_)
            self.assertEqual(expected_, quoted_out, f"quoteme_raw_by_type({in_}) should return {expected_} not {quoted_out}")
