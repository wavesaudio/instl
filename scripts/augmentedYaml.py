#!/usr/local/bin/python

import yaml

if __name__ == "__main__":
    import sys
    sys.path.append("..")

# patch yaml.Node derivatives to identify themselves
yaml.ScalarNode.isScalar = lambda self: True
yaml.SequenceNode.isScalar = lambda self: False
yaml.MappingNode.isScalar = lambda self: False

yaml.ScalarNode.isSequence = lambda self: False
yaml.SequenceNode.isSequence = lambda self: True
yaml.MappingNode.isSequence = lambda self: False

yaml.ScalarNode.isMapping = lambda self: False
yaml.SequenceNode.isMapping = lambda self: False
yaml.MappingNode.isMapping = lambda self: True

# patch yaml.Node derivatives to return their length
yaml.ScalarNode.__len__ = lambda self: 1
yaml.MappingNode.__len__ = lambda self: len(self.value)
yaml.SequenceNode.__len__ = lambda self: len(self.value)

# patch yaml.Node derivatives to iterate themselves
def iter_scalar(self):
    """ iterator for scalar will yield once - it's own value """
    yield self

def iter_mapping(self):
    """ iterator for mapping will yield two values
        the key as a string & the value. The assumption
        is that mapping key is a scalar
    """
    for map_tuple in self.value:
        yield str(map_tuple[0].value), map_tuple[1]

def iter_mapping_keys(self):
    """ iterator for mapping keys will yield
        the key as a string. The assumption
        is that mapping key is a scalar
    """
    for map_tuple in self.value:
        yield str(map_tuple[0].value)

def iter_sequence(self):
    """ iterator for sequence just iterates over the values """
    for item in self.value:
        yield item

yaml.ScalarNode.__iter__ = iter_scalar
yaml.MappingNode.__iter__ = iter_mapping
yaml.MappingNode.iterkeys = iter_mapping_keys
yaml.SequenceNode.__iter__ = iter_sequence

# patch yaml.Node derivatives to support []
def get_scalar_item(self, index):
    """ operator[] for scalar will return the value for index 0
        and throw an exception otherwise. """
    if index == 0 or index == -1:
        return self
    raise  IndexError
def get_mapping_item(self, key):
    """ operator[] for mapping will look for a key whose
        value as a string equal to the key argument. """
    key_as_str = str(key)
    for item in self.value: # for mapping each item is a tuple of (key, value)
        if str(item[0].value) == key_as_str:
            return item[1]
    raise  IndexError
def get_sequence_item(self, index):
    """ operator[] for sequence, support both positive and negative indexes """
    if index < len(self.value) and index >=  -len(self.value):
        return self.value[index]
    raise  IndexError

yaml.ScalarNode.__getitem__ = get_scalar_item
yaml.MappingNode.__getitem__ = get_mapping_item
yaml.SequenceNode.__getitem__ = get_sequence_item


def mappaing_containes(self, key):
    """ support 'if x in y:...' """
    try:
        self.__getitem__(key)
        return True
    except:
        return False
yaml.MappingNode.__contains__ = mappaing_containes


if __name__ == "__main__":
    print (yaml.__file__)
