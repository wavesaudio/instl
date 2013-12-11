#!/usr/bin/env python2.7
from __future__ import print_function
from pyinstl.utils import *

try:
    import networkx as nx
except ImportError as IE:
    raise IE

def create_dependencies_graph(item_map):
    retVal = nx.DiGraph()
    for item in item_map:
        for dependant in item_map[item].depend_list():
            retVal.add_edge(item_map[item].iid, dependant)
    return retVal

def create_inheritItem_graph(item_map):
    retVal = nx.DiGraph()
    for item in item_map:
        for dependant in item_map[item].inherit_list():
            retVal.add_edge(item_map[item].iid, dependant)
    return retVal

def find_cycles(item_graph):
    retVal = nx.simple_cycles(item_graph)
    return retVal

def find_leafs(item_graph):
    retVal = list()
    for node in sorted(item_graph):
        neig = item_graph.neighbors(node)
        if not neig:
            retVal.append(node)
    return retVal

def find_needed_by(item_graph, node):
    retVal = set_with_order()
    if node in item_graph:
        preds = item_graph.predecessors(node)
        for pred in preds:
            if pred not in retVal:
                retVal.append(pred)
                retVal.extend(find_needed_by(item_graph, pred))
    return retVal
