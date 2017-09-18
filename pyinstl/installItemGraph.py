#!/usr/bin/env python3

import utils
from configVar import var_stack

try:
    import networkx as nx
except ImportError as IE:
    raise IE


def create_dependencies_graph(items_table):
    retVal = nx.DiGraph()
    for iid in items_table.get_all_iids():
        for dependant in items_table.get_resolved_details_for_iid(iid, "depends"):
            retVal.add_edge(iid, dependant)
    return retVal


def create_inheritItem_graph(items_table):
    retVal = nx.DiGraph()
    for iid in items_table.get_all_iids():
        for dependant in items_table.get_resolved_details_for_iid(iid, "inherit"):
                retVal.add_edge(iid, dependant)
    return retVal


def find_cycles(item_graph):
    retVal = nx.simple_cycles(item_graph)
    return retVal


def find_leafs(item_graph):
    retVal = list()
    for node in sorted(item_graph):
        the_neighbors = item_graph.neighbors(node)
        if not the_neighbors:
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
