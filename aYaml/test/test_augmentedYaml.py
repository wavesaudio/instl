#!/usr/bin/env python2.7
from __future__ import print_function

import sys
import os
import unittest
import StringIO 

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
import yaml
from augmentedYaml import *

class TestAugmentedYaml(unittest.TestCase):

    def setUp(self):
        """ .
        """
    def tearDown(self):
        pass

    def test_single_scalar_iteration(self):
        """ iterate over a single scalar """
        someYamlScalar = """
a
"""
        fd = StringIO.StringIO(someYamlScalar)
        num_nodes = 0
        for a_node in yaml.compose_all(fd):
            self.assertIsInstance(a_node, yaml.nodes.ScalarNode)
            num_nodes += 1
            num_scalars = 0
            for something in a_node: # iterate over a scalar as if it was a sequence
                self.assertIsInstance(something, yaml.nodes.ScalarNode)
                self.assertIsInstance(something.value, basestring)
                num_scalars += 1
                self.assertEqual(something.value, "a")
            self.assertEqual(num_scalars, 1)
        self.assertEqual(num_nodes, 1)

    def test_sequence_of_scalar_iteration(self):
        """ iterate over sequence of scalars """
        someYamlSeq = """
- a
- b
- c
"""
        fd = StringIO.StringIO(someYamlSeq)
        num_nodes = 0
        for a_node in yaml.compose_all(fd):
            self.assertIsInstance(a_node, yaml.nodes.SequenceNode)
            num_nodes += 1
            num_scalars = 0
            scalars = list()
            for something in a_node:
                self.assertIsInstance(something, yaml.nodes.ScalarNode)
                self.assertIsInstance(something.value, basestring)
                num_scalars += 1
                scalars.append(something.value)
            self.assertEqual(scalars, ["a", "b", "c"])
            self.assertEqual(num_scalars, 3)
        self.assertEqual(num_nodes, 1)

    def test_sequence_of_sequence_of_scalar_iteration(self):
        """ iterate over sequence of sequence of scalars """
        someYamlSeqSeq = """
-
    - a
    - aa
    - aaa
-
    - b
    - bb
    - bbb
-
    - c
    - cc
    - ccc
"""
        fd = StringIO.StringIO(someYamlSeqSeq)
        num_nodes = 0
        for a_node in yaml.compose_all(fd):
            self.assertIsInstance(a_node, yaml.nodes.SequenceNode)
            num_nodes += 1
            num_sub_seq = 0
            list_of_scalars = list()
            for a_seq in a_node:
                self.assertIsInstance(a_seq, yaml.nodes.SequenceNode)
                num_sub_seq += 1
                scalars = list()
                for something in a_seq:
                    self.assertIsInstance(something, yaml.nodes.ScalarNode)
                    self.assertIsInstance(something.value, basestring)
                    scalars.append(something.value)
                list_of_scalars.append(scalars)
            self.assertEqual(list_of_scalars, [["a", "aa", "aaa"], ["b", "bb", "bbb"], ["c", "cc", "ccc"]])
            self.assertEqual(num_sub_seq, 3)
        self.assertEqual(num_nodes, 1)

    def test_map_iteration(self):
        """ iterate over map of sequence of scalars """
        someYamlMap = """
A:
    - a
    - aa
    - aaa
B: b
C: 
    c
"""
        fd = StringIO.StringIO(someYamlMap)
        num_nodes = 0
        for a_node in yaml.compose_all(fd):
            self.assertIsInstance(a_node, yaml.nodes.MappingNode)
            num_nodes += 1
            num_map_items = 0
            self.assertTrue("A" in a_node)
            self.assertTrue("B" in a_node)
            self.assertTrue("C" in a_node)
            self.assertFalse("D" in a_node)
            
            # iterate with key/value pair
            list_of_scalars1 = list()
            for name, a_seq in a_node:
                self.assertIsInstance(name, basestring)
                self.assertIsInstance(a_seq, yaml.nodes.Node)
                num_map_items += 1
                for something in a_seq:
                    list_of_scalars1.append(something.value)
            self.assertEqual(sorted(list_of_scalars1), sorted(["a", "aa", "aaa", "b", "c"]))

            # iterate with iterkeys
            list_of_scalars2 = list()
            for name in a_node.iterkeys():
                for something in a_node[name]:
                    list_of_scalars2.append(something.value)
            self.assertEqual(sorted(list_of_scalars1), sorted(list_of_scalars2))
            
            # test "if ... in ..." functionality
            list_of_scalars3 = list()
            for name in ("A", "B", "D", "C"):
                if name in a_node:
                    for something in a_node[name]:
                        list_of_scalars3.append(something.value)
            self.assertEqual(sorted(list_of_scalars1), sorted(list_of_scalars3))
            
            self.assertEqual(num_map_items, 3)
        self.assertEqual(num_nodes, 1)
