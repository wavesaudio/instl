#!/usr/bin/env python3

import utils
from configVar import var_stack

try:
    import networkx as nx
except ImportError as IE:
    raise IE


def create_dependencies_graph(item_map):
    retVal = nx.DiGraph()
    for item in item_map:
        with item_map[item].push_var_stack_scope():
            for dependant in var_stack.ResolveVarToList("iid_depend_list"):
                retVal.add_edge(var_stack.ResolveVarToStr("iid_iid"), dependant)
    return retVal


def create_inheritItem_graph(item_map):
    retVal = nx.DiGraph()
    for item in item_map:
        with item_map[item].push_var_stack_scope():
            for dependant in var_stack.ResolveVarToList("iid_inherit"):
                retVal.add_edge(var_stack.ResolveVarToStr("iid_iid"), dependant)
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
    retVal = utils.set_with_order()
    if node in item_graph:
        predecessors = item_graph.predecessors(node)
        for predecessor in predecessors:
            if predecessor not in retVal:
                retVal.append(predecessor)
                retVal.extend(find_needed_by(item_graph, predecessor))
    return retVal
