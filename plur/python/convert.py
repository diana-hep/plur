#!/usr/bin/env python

# Copyright 2017 DIANA-HEP
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import numpy

from plur.util import *
from plur.types import *
from plur.types.columns import type2columns
from plur.types.arrayname import ArrayName
from plur.python.types import infertype
from plur.python.fillmemory import FillableInMemory

def toarrays(prefix, obj, tpe=None, fillable=FillableInMemory, delimiter="-", indextype=numpy.dtype(numpy.uint64), **fillableOptions):
    if tpe is None:
        tpe = infertype(obj)

    dtypes = type2columns(tpe, prefix, delimiter=delimiter, indextype=indextype)
    fillables = dict((ArrayName.parse(n, prefix, delimiter=delimiter), fillable(n, d, **fillableOptions)) for n, d in dtypes.items())

    last_list_offset = {}
    last_union_offset = {}

    def recurse(obj, tpe, name):
        if isinstance(tpe, Primitive):
            if not obj in tpe:
                raise TypeError("cannot fill {0} where an object of type {1} is expected".format(obj, tpe))
            fillables[name].fill(obj)

        elif isinstance(tpe, List):
            try:
                iter(obj)
                if isinstance(obj, dict) or (isinstance(obj, tuple) and hasattr(obj, "_fields")):
                    raise TypeError
            except TypeError:
                raise TypeError("cannot fill {0} where an object of type {1} is expected".format(obj, tpe))

            nameoffset = name.toListOffset()
            namedata = name.toListData()

            if nameoffset not in last_list_offset:
                last_list_offset[nameoffset] = 0
            last_list_offset[nameoffset] += len(obj)

            fillables[nameoffset].fill(last_list_offset[nameoffset])
            
            for x in obj:
                recurse(x, tpe.of, namedata)

        elif isinstance(tpe, Union):
            t = infertype(obj)   # can be expensive!
            tag = None
            for i, possibility in enumerate(tpe.of):
                if t.issubtype(possibility):
                    tag = i
                    break
            if tag is None:
                raise TypeError("cannot fill {0} where an object of type {1} is expected".format(obj, tpe))

            nametag = name.toUnionTag()
            nameoffset = name.toUnionOffset()
            namedata = name.toUnionData(tag)

            if namedata not in last_union_offset:
                last_union_offset[namedata] = 0

            fillables[nametag].fill(tag)
            fillables[nameoffset].fill(last_union_offset[namedata])

            last_union_offset[namedata] += 1

            recurse(obj, tpe.of[tag], namedata)

        elif isinstance(tpe, Record):
            if isinstance(obj, dict):
                for fn, ft in tpe.of:
                    if fn not in obj:
                        raise TypeError("cannot fill {0} (missing field \"{1}\") where an object of type {2} is expected".format(obj, fn, tpe))
                    recurse(obj[fn], ft, name.toRecord(fn))

            else:
                for fn, ft in tpe.of:
                    if not hasattr(obj, fn):
                        raise TypeError("cannot fill {0} (missing field \"{1}\") where an object of type {2} is expected".format(obj, fn, tpe))
                    recurse(getattr(obj, fn), ft, name.toRecord(fn))

        else:
            assert False, "unexpected type object: {0}".format(tpe)

    recurse(obj, tpe, ArrayName(prefix, delimiter=delimiter))

    return dict((n.str(), f.finalize()) for n, f in fillables.items())