#!/usr/bin/env python

# Copyright (c) 2017, DIANA-HEP
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
# 
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# 
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import collections
import json
import sys

import numpy
import numpy.ma

import arrowed.proxy

if sys.version_info[0] <= 2:
    string_types = (unicode, str)
else:
    string_types = (str,)

class ObjectArrayMapping(object):
    def toJsonString(self):
        return json.dumps(self.toJson())

    @staticmethod
    def fromJsonString(string):
        return ObjectArrayMapping.fromJson(json.loads(string))

    @property
    def name(self):
        base = self
        while base.base is not None:
            base = base.base
        return base._name

    def hasbase(self, base):
        obj = self
        while obj is not None:
            if obj is base:
                return True
            obj = obj.base
        return False

    def proxy(self, index):
        raise TypeError("cannot get a proxy for an unresolved ObjectArrayMap; call the resolved method first or pass a source to this method")

    def compile(self, function, paramtypes={}, env={}, numba={"nopython": True, "nogil": True}, debug=False):
        import arrowed.compiler
        paramtypes = paramtypes.copy()
        paramtypes[0] = self

        if not hasattr(self, "_functions"):
            self._functions = {}
        if id(function) not in self._functions:
            self._functions[id(function)] = arrowed.compiler.compile(function, paramtypes, env=env, numbaargs=numba, debug=debug)
        return self._functions[id(function)]

    def run(self, function, paramtypes={}, env={}, numba={"nopython": True, "nogil": True}, debug=False, *args):
        import arrowed.compiler

        if not isinstance(function, arrowed.compiler.Compiled):
            base = self
            while base.base is not None:
                base = base.base
            function = base.compile(function, paramtypes=paramtypes, env=env, numba=numba, debug=debug)

        return function(self, *args)

    @staticmethod
    def _toint64(array):
        if array.dtype != numpy.dtype(numpy.int64):
            if getattr(array, "mask", None) is not None:
                return numpy.ma.MaskedArray(array, dtype=numpy.int64)
            else:
                return numpy.array(array, dtype=numpy.int64)
        else:
            return array

    @staticmethod
    def _resolved_check(array, message, masked, extracheck):
        if masked:
            message = message.format("masked")
            extracheck2 = lambda x: getattr(x, "mask", None) is not None
        else:
            message = message.format("non-masked")
            extracheck2 = lambda x: getattr(x, "mask", None) is None
        assert hasattr(array, "dtype") and not isinstance(array, numpy.recarray) and len(array.shape) == 1 and extracheck(array) and extracheck2(array), message
        return array

    def _resolved(self, obj, source, message, masked, extracheck=lambda x: True):
        if isinstance(obj, numpy.ndarray):
            return ObjectArrayMapping._resolved_check(obj, message, masked, extracheck)

        elif callable(obj):
            if hasattr(obj, "__code__") and obj.__code__.co_argcount == 0:
                return ObjectArrayMapping._resolved_check(obj(), message, masked, extracheck)
            elif hasattr(obj, "__code__") and obj.__code__.co_argcount == 1:
                return ObjectArrayMapping._resolved_check(obj(source), message, masked, extracheck)
            elif hasattr(obj, "__code__") and obj.__code__.co_argcount == 2:
                return ObjectArrayMapping._resolved_check(obj(source, self), message, masked, extracheck)
            else:
                return ObjectArrayMapping._resolved_check(obj(source, self, self.__class__), message, masked, extracheck)

        elif isinstance(obj, collections.Hashable) and obj in source:
            return ObjectArrayMapping._resolved_check(source[obj], message, masked, extracheck)

        else:
            raise ValueError("array cannot be found for key {0}".format(repr(obj)))

    def _recursion_check(self, memo):
        if memo is None:
            memo = {}
        if id(self) in memo:
            raise TypeError("a container type cannot be included more than once in the same nested tree")
        memo[id(self)] = None
        return memo

    @staticmethod
    def _format_array(array, arraywidth):
        if isinstance(array, numpy.ndarray):
            end = ", dtype={0})".format(repr(str(array.dtype)))
            arraywidth -= len(end)
            
            if getattr(array, "mask", None) is not None:
                out = ["masked_array(["]
                arraywidth -= len(out[-1])
                index = 0
                while index < len(array) and arraywidth - 4 > 0:
                    if index != 0:
                        out.append(" ")
                        arraywidth -= 1

                    if array.mask[index]:
                        out.append("--")
                        arraywidth -= 2
                    else:
                        out.append("{0:g}".format(array.data[index]))
                        arraywidth -= len(out[-1])

                    index += 1

            else:
                out = ["array(["]
                arraywidth -= len(out[-1])
                index = 0
                while index < len(array) and arraywidth - 4 > 0:
                    if index != 0:
                        out.append(" ")
                        arraywidth -= 1

                    out.append("{0:g}".format(array[index]))
                    arraywidth -= len(out[-1])

                    index += 1

            if index < len(array):
                out.append("...]")
            else:
                out.append("]")
            out.append(end)

            return "".join(out)

        elif isinstance(array, string_types + (bytes,)):
            out = repr(array)
            if len(out) > arraywidth:
                out = out[:arraywidth - 4] + "...'"
            return out

        else:
            return repr(array)

    def _format_with_preamble(self, preamble, indent, width, refs, memo):
        first = True
        for line in self._format(indent, width, refs, memo):
            if first:
                yield indent + preamble + line[len(indent):]
                first = False
            else:
                yield line
                
    def format(self, indent="", highlight=lambda t: "", width=80):
        ids = {}
        refs = {}
        def recurse(t):
            if id(t) in ids:
                refs[id(t)] = "[{0}] ".format(len(refs))
            else:
                ids[id(t)] = t
                c = getattr(t, "contents", ())
                if isinstance(c, tuple):
                    for ci in c:
                        recurse(ci)
                elif isinstance(c, dict):
                    for ci in c.values():
                        recurse(ci)
                else:
                    recurse(c)
                c = getattr(t, "target", None)
                if c is not None:
                    recurse(c)
        recurse(self)

        return "\n".join(self._format(indent, width, refs, {}))

################################################################ primitives

class Primitive(ObjectArrayMapping):
    def __init__(self, array, masked=False, base=None):
        self.array = array
        self.masked = masked
        self.base = base

    def accessedby(self, accessor, _memo=None):
        return Primitive(accessor, self.masked, self)

    def findbybase(self, base, _memo=None):
        if self.hasbase(base):
            return self
        else:
            return None

    @property
    def _name(self):
        return self.array

    def resolved(self, source, lazy=False, _memo=None):
        def resolve():
            return self._resolved(self.array, source, "Primitive array must map to a one-dimensional, {0}, non-record array", self.masked)

        if lazy:
            return Primitive(resolve, self.masked, self)
        else:
            return Primitive(resolve(), self.masked, self)

    def proxy(self, index):
        if callable(self.array):
            self.array = self.array()

        if getattr(self.array, "mask", None) is not None and self.array.mask[index]:
            return None
        else:
            return self.array[index]

    def get(self, attr):
        if callable(self.array):
            self.array = self.array()

        if attr == "array":
            return self.array
        else:
            raise NameError("Primitive has no array {0}".format(repr(attr)))

    def members(self, _memo=None):
        return [self]

    def hasany(self, others, _memo=None):
        return any(x is self for x in others)

    def projection(self, required, _memo=None):
        if self.hasany(required):
            return Primitive(self.array, self.masked, self)
        else:
            return None

    def _format_with_preamble(self, preamble, indent, width, refs, memo):
        for line in self._format(indent, width - len(preamble), refs, memo):
            yield indent + preamble + line[len(indent):]

    def _format(self, indent, width, refs, memo):
        self._recursion_check(memo)
        preamble = refs.get(id(self), "")
        yield indent + preamble + self._format_array(self.array, width - len(preamble) - len(indent))

    def __eq__(self, other):
        return isinstance(other, Primitive) and ((isinstance(self.array, ndarray) and isinstance(other.array, ndarray) and numpy.array_equal(self.array, other.array)) or self.array == other.array) and self.base == other.base

    def __ne__(self, other):
        return not self.__eq__(self, other)

################################################################ lists

class List(ObjectArrayMapping):
    def __init__(self, *args, **kwds):
        raise TypeError("List is abstract; use ListCount, ListOffset, or ListStartEnd instead")

    def findbybase(self, base, _memo=None):
        if self.hasbase(base):
            return self
        else:
            if _memo is None:
                _memo = set()
            if id(self.contents) not in _memo:
                _memo.add(id(self.contents))
                return self.contents.findbybase(base, _memo)
            else:
                return None

    def members(self, _memo=None):
        if _memo is None:
            _memo = set()
        out = [self]
        if id(self.contents) not in _memo:
            _memo.add(id(self.contents))
            return out + self.contents.members(_memo)
        else:
            return out

    def hasany(self, others, _memo=None):
        if any(x is self for x in others):
            return True
        if _memo is None:
            _memo = set()
        if id(self.contents) not in _memo:
            _memo.add(id(self.contents))
            return self.contents.hasany(others, _memo)
        else:
            return False

class ListCount(List):
    def __init__(self, countarray, contents, masked=False, base=None):
        self.countarray = countarray
        self.contents = contents
        self.masked = masked
        self.base = base
        assert isinstance(self.contents, ObjectArrayMapping), "contents must be an ObjectArrayMapping"

    def accessedby(self, accessor, _memo=None):
        if _memo is None:
            _memo = {}
        if id(self.contents) not in _memo:
            _memo[id(self.contents)] = None
            _memo[id(self.contents)] = self.contents.accessedby(accessor)
        contents = _memo[id(self.contents)]
        return ListCount(accessor, contents, self.masked, self)

    @property
    def _name(self):
        return self.countarray

    def resolved(self, source, lazy=False, _memo=None):
        def resolve():
            countarray = self._resolved(self.countarray, source, "ListCount countarray must map to a one-dimensional, {0}, non-record array of integers", self.masked, lambda x: issubclass(x.dtype.type, numpy.integer))
            offsetarray = numpy.empty(len(countarray) + 1, dtype=numpy.int64)   # new allocation
            countarray.cumsum(out=offsetarray[1:])                              # fill with offsets
            offsetarray[0] = 0
            startarray = offsetarray[:-1]  # overlapping views
            endarray = offsetarray[1:]     # overlapping views

            if getattr(countarray, "mask", None) is not None:
                startarray = numpy.ma.MaskedArray(startarray, mask=countarray.mask)

            return startarray, endarray

        _memo = self._recursion_check(_memo)
        if lazy:
            _memo[id(self)] = ListStartEnd(resolve, None, self.contents.resolved(source, lazy, _memo), self.masked, self)
        else:
            startarray, endarray = resolve()
            _memo[id(self)] = ListStartEnd(startarray, endarray, self.contents.resolved(source, lazy, _memo), self.masked, self)
        return _memo[id(self)]

    def get(self, attr):
        if callable(self.countarray):
            self.countarray = self.countarray()

        if attr == "countarray":
            return self.countarray
        else:
            raise NameError("ListCount has no array {0}".format(repr(attr)))

    def projection(self, required, _memo=None):
        if self.hasany(required):
            if _memo is None:
                _memo = {}
            if id(self.contents) not in _memo:
                _memo[id(self.contents)] = None
                _memo[id(self.contents)] = self.contents.projection(required, _memo)
            contents = _memo[id(self.contents)]
            if contents is None:
                contents = Primitive(self.countarray, self.masked)
            return ListCount(self.countarray, contents, self.masked, self)
        else:
            return None

    def _format(self, indent, width, refs, memo):
        self._recursion_check(memo)
        yield indent + refs.get(id(self), "") + "List ["
        indent += "  "
        preamble = "countarray = "
        yield indent + preamble + self._format_array(self.countarray, width - len(preamble) - len(indent))
        for line in self.contents._format(indent, width, refs, memo):
            yield line
        yield indent + "]"

    def __eq__(self, other):
        return isinstance(other, ListCount) and ((isinstance(self.countarray, ndarray) and isinstance(other.countarray, ndarray) and numpy.array_equal(self.countarray, other.countarray)) or self.countarray == other.countarray) and self.contents == other.contents and self.base == other.base

    def __ne__(self, other):
        return not self.__eq__(self, other)

class ListOffset(List):
    def __init__(self, offsetarray, contents, masked=False, base=None):
        self.offsetarray = offsetarray
        self.contents = contents
        self.masked = masked
        self.base = base
        assert isinstance(self.contents, ObjectArrayMapping), "contents must be an ObjectArrayMapping"

    def accessedby(self, accessor, _memo=None):
        if _memo is None:
            _memo = {}
        if id(self.contents) not in _memo:
            _memo[id(self.contents)] = None
            _memo[id(self.contents)] = self.contents.accessedby(accessor)
        contents = _memo[id(self.contents)]
        return ListOffset(accessor, contents, self.masked, self)

    @property
    def _name(self):
        return self.offsetarray

    def resolved(self, source, lazy=False, _memo=None):
        def resolve():
            offsetarray = self._toint64(self._resolved(self.offsetarray, source, "ListOffset offsetarray must map to a one-dimensional, {0}, non-record array of integers", self.masked, lambda x: issubclass(x.dtype.type, numpy.integer)))
            startarray = offsetarray[:-1]  # overlapping views
            endarray = offsetarray[1:]     # overlapping views
            return startarray, endarray

        _memo = self._recursion_check(_memo)
        if lazy:
            _memo[id(self)] = ListStartEnd(resolve, None, self.contents.resolved(source, lazy, _memo), self.masked, self)
        else:
            startarray, endarray = resolve()
            _memo[id(self)] = ListStartEnd(startarray, endarray, self.contents.resolved(source, lazy, _memo), self.masked, self)
        return _memo[id(self)]

    def get(self, attr):
        if callable(self.offsetarray):
            self.offsetarray = self.offsetarray()

        if attr == "offsetarray":
            return self.offsetarray
        else:
            raise NameError("ListOffset has no array {0}".format(repr(attr)))

    def projection(self, required, _memo=None):
        if self.hasany(required):
            if _memo is None:
                _memo = {}
            if id(self.contents) not in _memo:
                _memo[id(self.contents)] = None
                _memo[id(self.contents)] = self.contents.projection(required, _memo)
            contents = _memo[id(self.contents)]
            if contents is None:
                contents = Primitive(self.offsetarray, self.masked)
            return ListOffset(self.offsetarray, contents, self.masked, self)
        else:
            return None

    def _format(self, indent, width, refs, memo):
        self._recursion_check(memo)
        yield indent + refs.get(id(self), "") + "List ["
        indent += "  "
        preamble = "offsetarray = "
        yield indent + preamble + self._format_array(self.offsetarray, width - len(preamble) - len(indent))
        for line in self.contents._format(indent, width, refs, memo):
            yield line
        yield indent + "]"

    def __eq__(self, other):
        return isinstance(other, ListOffset) and ((isinstance(self.offsetarray, ndarray) and isinstance(other.offsetarray, ndarray) and numpy.array_equal(self.offsetarray, other.offsetarray)) or self.offsetarray == other.offsetarray) and self.contents == other.contents and self.base == other.base

    def __ne__(self, other):
        return not self.__eq__(self, other)
        
class ListStartEnd(List):
    def __init__(self, startarray, endarray, contents, masked=False, base=None):
        self.startarray = startarray
        self.endarray = endarray
        self.contents = contents
        self.masked = masked
        self.base = base
        assert isinstance(self.contents, ObjectArrayMapping), "contents must be an ObjectArrayMapping"

    def accessedby(self, accessor, _memo=None):
        if _memo is None:
            _memo = {}
        if id(self.contents) not in _memo:
            _memo[id(self.contents)] = None
            _memo[id(self.contents)] = self.contents.accessedby(accessor)
        contents = _memo[id(self.contents)]
        return ListStartEnd(accessor, None, contents, self.masked, self)

    @property
    def _name(self):
        return self.startarray

    def resolved(self, source, lazy=False, _memo=None):
        def resolve():
            startarray = self._toint64(self._resolved(self.startarray, source, "ListStartEnd startarray must map to a one-dimensional, {0}, non-record array of integers", self.masked, lambda x: issubclass(x.dtype.type, numpy.integer)))
            endarray = self._toint64(self._resolved(self.startarray, source, "ListStartEnd endarray must map to a one-dimensional, {0}, non-record array of integers", self.masked, lambda x: issubclass(x.dtype.type, numpy.integer)))
            return startarray, endarray

        _memo = self._recursion_check(_memo)
        if lazy:
            _memo[id(self)] = ListStartEnd(resolve, None, self.contents.resolved(source, lazy, _memo), self.masked, self)
        else:
            startarray, endarray = resolve()
            _memo[id(self)] = ListStartEnd(startarray, endarray, self.contents.resolved(source, lazy, _memo), self.masked, self)
        return _memo[id(self)]

    def proxy(self, index):
        if callable(self.startarray):
            self.startarray, self.endarray = self.startarray()

        if getattr(self.startarray, "mask", None) is not None and self.startarray.mask[index]:
            return None
        else:
            return arrowed.proxy.ListProxy(self, index)

    def get(self, attr):
        if callable(self.startarray):
            self.startarray, self.endarray = self.startarray()

        if attr == "startarray":
            return self.startarray
        elif attr == "endarray":
            return self.endarray
        else:
            raise NameError("ListStartEnd has no array {0}".format(repr(attr)))

    def projection(self, required, _memo=None):
        if self.hasany(required):
            if _memo is None:
                _memo = {}
            if id(self.contents) not in _memo:
                _memo[id(self.contents)] = None
                _memo[id(self.contents)] = self.contents.projection(required, _memo)
            contents = _memo[id(self.contents)]
            if contents is None:
                contents = Primitive(self.startarray, self.masked)
            return ListStartEnd(self.startarray, self.endarray, contents, self.masked, self)
        else:
            return None

    def _format(self, indent, width, refs, memo):
        self._recursion_check(memo)
        yield indent + refs.get(id(self), "") + "List ["
        indent += "  "
        preamble = "startarray = "
        yield indent + preamble + self._format_array(self.startarray, width - len(preamble) - len(indent))
        preamble = "endarray   = "
        yield indent + preamble + self._format_array(self.endarray, width - len(preamble) - len(indent))
        for line in self.contents._format(indent, width, refs, memo):
            yield line
        yield indent + "]"

    def __eq__(self, other):
        return isinstance(other, ListStartEnd) and ((isinstance(self.startarray, ndarray) and isinstance(other.startarray, ndarray) and numpy.array_equal(self.startarray, other.startarray)) or self.startarray == other.startarray) and ((isinstance(self.endarray, ndarray) and isinstance(other.endarray, ndarray) and numpy.array_equal(self.endarray, other.endarray)) or self.endarray == other.endarray) and self.contents == other.contents and self.base == other.base

    def __ne__(self, other):
        return not self.__eq__(self, other)

################################################################ records and tuples

class Record(ObjectArrayMapping):
    __nameindex = 0

    def __init__(self, contents, base=None, name=None):
        self.contents = contents
        self.base = base
        if name is None:
            self._name = "Record-{0}".format(self.__nameindex)
            self.__nameindex += 1
        else:
            self._name = name

        assert isinstance(self.contents, dict)
        assert all(isinstance(x, string_types) for x in self.contents.keys()), "contents must be a dict from strings to ObjectArrayMappings"
        assert all(isinstance(x, ObjectArrayMapping) for x in self.contents.values()), "contents must be a dict from strings to ObjectArrayMappings"

        if self.base is None:
            superclasses = (arrowed.proxy.RecordProxy,)
        else:
            superclasses = self.base.proxyclass.__bases__

        def makeproperty(n, c):
            return property(lambda self: c.proxy(self._index))

        self.proxyclass = type(str(self.name), superclasses, dict((n, makeproperty(n, c)) for n, c in self.contents.items()))
        self.proxyclass.__slots__ = ["_schema", "_index"]

    def accessedby(self, accessor, _memo=None):
        if _memo is None:
            _memo = {}
        contents = collections.OrderedDict()
        for n, c in self.contents.items():
            if id(c) not in _memo:
                _memo[id(c)] = None
                _memo[id(c)] = c.accessedby(accessor)
            contents[n] = _memo[id(c)]
        return Record(contents, self)

    def findbybase(self, base, _memo=None):
        if self.hasbase(base):
            return self
        else:
            if _memo is None:
                _memo = set()
            for x in self.contents.values():
                if id(x) not in _memo:
                    _memo.add(id(x))
                    out = x.findbybase(base, _memo)
                    if out is not None:
                        return out
            return None

    def resolved(self, source, lazy=False, _memo=None):
        # a record is a purely organizational type; it has no arrays of its own, so just pass on the dereferencing request
        _memo = self._recursion_check(_memo)
        _memo[id(self)] = Record(collections.OrderedDict((k, v.resolved(source, lazy, _memo)) for k, v in self.contents.items()), self)
        return _memo[id(self)]

    def proxy(self, index):
        return self.proxyclass(self, index)

    def get(self, attr):
        raise NameError("Record has no array {0}".format(repr(attr)))

    def members(self, _memo=None):
        if _memo is None:
            _memo = set()
        out = [self]
        for x in self.contents.values():
            if id(x) not in _memo:
                _memo.add(id(x))
                out.extend(x.members(_memo))
        return out

    def hasany(self, others, _memo=None):
        if any(x is self for x in others):
            return True
        if _memo is None:
            _memo = set()
        for x in self.contents.values():
            if id(x) not in _memo:
                _memo.add(id(x))
                return x.hasany(others, _memo)
        return False

    def projection(self, required, _memo=None):
        if self.hasany(required):
            if _memo is None:
                _memo = {}
            contents = collections.OrderedDict()
            for n, x in self.contents.items():
                if id(x) not in _memo:
                    _memo[id(x)] = None
                    _memo[id(x)] = x.projection(required, _memo)
                content = _memo[id(x)]
                if content is not None:
                    contents[n] = content
            if len(contents) > 0:
                return Record(contents, self)
            else:
                return None
        else:
            return None

    def _format(self, indent, width, refs, memo):
        self._recursion_check(memo)
        yield indent + refs.get(id(self), "") + "Record {"
        indent += "  "
        yield indent + "name = {0}".format(repr(self.name))

        for key, contents in self.contents.items():
            for line in contents._format_with_preamble("{0}: ".format(key), indent, width, refs, memo):
                yield line
        yield indent + "}"

    def __eq__(self, other):
        return isinstance(other, Record) and self.contents == other.contents and self.base == other.base and self._name == other._name

    def __ne__(self, other):
        return not self.__eq__(self, other)

class Tuple(ObjectArrayMapping):
    def __init__(self, contents, base=None):
        self.contents = tuple(contents)
        self.base = base
        assert all(isinstance(x, ObjectArrayMapping) for x in self.contents), "contents must be a tuple of ObjectArrayMappings"

    def accessedby(self, accessor, _memo=None):
        if _memo is None:
            _memo = {}
        contents = []
        for c in self.contents:
            if id(c) not in _memo:
                _memo[id(c)] = None
                _memo[id(c)] = c.accessedby(accessor)
            contents.append(_memo[id(c)])
        return Tuple(contents, self)

    def findbybase(self, base, _memo=None):
        if self.hasbase(base):
            return self
        else:
            if _memo is None:
                _memo = set()
            for x in self.contents:
                if id(x) not in _memo:
                    _memo.add(id(x))
                    out = x.findbybase(base, _memo)
                    if out is not None:
                        return out
            return None

    @property
    def _name(self):
        return "tuple{0}".format(len(self.contents))

    def resolved(self, source, lazy=False, _memo=None):
        # a tuple is a purely organizational type; it has no arrays of its own, so just pass on the dereferencing request
        _memo = self._recursion_check(_memo)
        _memo[id(self)] = Tuple(tuple(x.resolved(source, lazy, _memo) for x in self.contents), self)
        return _memo[id(self)]

    def proxy(self, index):
        return arrowed.proxy.TupleProxy(self, index)

    def get(self, attr):
        raise NameError("Tuple has no array {0}".format(repr(attr)))

    def members(self, _memo=None):
        if _memo is None:
            _memo = set()
        out = [self]
        for x in self.contents:
            if id(x) not in _memo:
                _memo.add(id(x))
                out.extend(x.members(_memo))
        return out

    def hasany(self, others, _memo=None):
        if any(x is self for x in others):
            return True
        if _memo is None:
            _memo = set()
        for x in self.contents:
            if id(x) not in _memo:
                _memo.add(id(x))
                return x.hasany(others, _memo)
        return False

    def projection(self, required, _memo=None):
        if self.hasany(required):
            if _memo is None:
                _memo = {}
            contents = []
            for x in self.contents:
                if id(x) not in _memo:
                    _memo[id(x)] = None
                    _memo[id(x)] = x.projection(required, _memo)
                content = _memo[id(x)]
                if content is not None:
                    contents.append(content)
            if len(contents) > 0:
                return Tuple(contents, self)
            else:
                return None
        else:
            return None

    def _format(self, indent, width, refs, memo):
        self._recursion_check(memo)
        if isinstance(self.contents, tuple):
            yield indent + refs.get(id(self), "") + "Tuple ("
            indent += "  "
            for index, contents in enumerate(self.contents):
                for line in contents._format_with_preamble("{0}: ".format(index), indent, width, refs, memo):
                    yield line
            yield indent + ")"

    def __eq__(self, other):
        return isinstance(other, Tuple) and self.contents == other.contents and self.base == other.base

    def __ne__(self, other):
        return not self.__eq__(self, other)

################################################################ unions

class Union(ObjectArrayMapping):
    def __init__(self, *args, **kwds):
        raise TypeError("Union is abstract; use UnionSparse or UnionSparseOffset instead")

    def findbybase(self, base, _memo=None):
        if self.hasbase(base):
            return self
        else:
            if _memo is None:
                _memo = set()
            for x in self.contents:
                if id(x) not in _memo:
                    _memo.add(id(x))
                    out = x.findbybase(base, _memo)
                    if out is not None:
                        return out
            return None

    def members(self, _memo=None):
        if _memo is None:
            _memo = set()
        out = [self]
        for x in self.contents:
            if id(x) not in _memo:
                _memo.add(id(x))
                out.extend(x.members(_memo))
        return out

    def hasany(self, others, _memo=None):
        if any(x is self for x in others):
            return True
        if _memo is None:
            _memo = set()
        for x in self.contents:
            if id(x) not in _memo:
                _memo.add(id(x))
                return x.hasany(others, _memo)
        return False

class UnionSparse(Union):
    def __init__(self, tagarray, contents, masked=False, base=None):
        self.tagarray = tagarray
        self.contents = tuple(contents)
        self.masked = masked
        self.base = base
        if isinstance(self.contents, tuple):
            assert all(isinstance(x, ObjectArrayMapping) for x in self.contents), "contents must be a tuple of ObjectArrayMappings"
        else:
            raise AssertionError("contents must be a tuple")

    def accessedby(self, accessor, _memo=None):
        if _memo is None:
            _memo = {}
        contents = []
        for c in self.contents:
            if id(c) not in _memo:
                _memo[id(c)] = None
                _memo[id(c)] = c.accessedby(accessor)
            contents.append(_memo[id(c)])
        return UnionSparse(accessor, contents, self.masked, self)

    @property
    def _name(self):
        return self.tagarray

    def resolved(self, source, lazy=False, _memo=None):
        def resolve():
            tagarray = self._toint64(self._resolved(self.tagarray, source, "UnionSparse tagarray must map to a one-dimensional, {0}, non-record array of integers", self.masked, lambda x: issubclass(x.dtype.type, numpy.integer)))

            offsetarray = numpy.empty(len(tagarray), dtype=numpy.int64)
            for tag in range(len(self.contents)):    # for each possible tag
                matches = (tagarray == tag)          # find the elements of tagarray that match this tag
                nummatches = matches.sum()
                offsetarray[matches] = numpy.linspace(0, nummatches - 1, nummatches, dtype=numpy.int64)
                                                     # offsets corresponding to matching tags should be increasing integers
            return tagarray, offsetarray
        
        _memo = self._recursion_check(_memo)
        if lazy:
            _memo[id(self)] = UnionSparseOffset(resolve, None, [x.resolved(source, lazy, _memo) for x in self.contents], self.masked, self)
        else:
            tagarray, offsetarray = resolve()
            _memo[id(self)] = UnionSparseOffset(tagarray, offsetarray, [x.resolved(source, lazy, _memo) for x in self.contents], self.masked, self)
        return _memo[id(self)]

    def get(self, attr):
        if callable(self.tagarray):
            self.tagarray = self.tagarray()

        if attr == "tagarray":
            return self.tagarray
        else:
            raise NameError("UnionSparse has no array {0}".format(repr(attr)))

    def projection(self, required, _memo=None):
        if self.hasany(required):
            if _memo is None:
                _memo = {}
            contents = []
            for x in self.contents:
                if id(x) not in _memo:
                    _memo[id(x)] = None
                    _memo[id(x)] = x.projection(required, _memo)
                content = _memo[id(x)]
                if content is not None:
                    contents.append(content)
            if len(contents) > 0:
                return UnionSparse(self.tagarray, contents, self.masked, self)
            else:
                return None
        else:
            return None

    def _format(self, indent, width, refs, memo):
        self._recursion_check(memo)
        yield indent + refs.get(id(self), "") + "Union <"
        indent += "  "
        preamble = "tagarray = "
        yield indent + preamble + self._format_array(self.tagarray, width - len(preamble) - len(indent))
        for index, contents in enumerate(self.contents):
            for line in contents._format_with_preamble("{0}: ".format(index), indent, width, refs, memo):
                yield line
        yield indent + ">"

    def __eq__(self, other):
        return isinstance(other, UnionSparse) and ((isinstance(self.tagarray, ndarray) and isinstance(other.tagarray, ndarray) and numpy.array_equal(self.tagarray, other.tagarray)) or self.tagarray == other.tagarray) and self.contents == other.contents and self.base == other.base

    def __ne__(self, other):
        return not self.__eq__(self, other)

class UnionSparseOffset(Union):
    def __init__(self, tagarray, offsetarray, contents, masked=False, base=None):
        self.tagarray = tagarray
        self.offsetarray = offsetarray
        self.contents = tuple(contents)
        self.masked = masked
        self.base = base
        if isinstance(self.contents, tuple):
            assert all(isinstance(x, ObjectArrayMapping) for x in self.contents), "contents must be a tuple of ObjectArrayMappings"
        else:
            raise AssertionError("contents must be a tuple")

    def accessedby(self, accessor, _memo=None):
        if _memo is None:
            _memo = {}
        contents = []
        for c in self.contents:
            if id(c) not in _memo:
                _memo[id(c)] = None
                _memo[id(c)] = c.accessedby(accessor)
            contents.append(_memo[id(c)])
        return UnionSparseOffset(accessor, None, contents, self.masked, self)

    @property
    def _name(self):
        return self.tagarray

    def resolved(self, source, lazy=False, _memo=None):
        def resolve():
            tagarray = self._toint64(self._resolved(self.tagarray, source, "UnionSparseOffset tagarray must map to a one-dimensional, {0}, non-record array of integers", self.masked, lambda x: issubclass(x.dtype.type, numpy.integer)))
            offsetarray = self._toint64(self._resolved(self.offsetarray, source, "UnionSparseOffset offsetarray must map to a one-dimensional, {0}, non-record array of integers", self.masked, lambda x: issubclass(x.dtype.type, numpy.integer)))
            return tagarray, offsetarray

        _memo = self._recursion_check(_memo)
        if lazy:
            _memo[id(self)] = UnionSparseOffset(resolve, None, [x.resolved(source, lazy, _memo) for x in self.contents], self.masked, self)
        else:
            tagarray, offsetarray = resolve()
            _memo[id(self)] = UnionSparseOffset(tagarray, offsetarray, [x.resolved(source, lazy, _memo) for x in self.contents], self.masked, self)
        return _memo[id(self)]

    def proxy(self, index):
        if callable(self.tagarray):
            self.tagarray, self.offsetarray = self.tagarray()

        if getattr(self.tagarray, "mask", None) is not None and self.tagarray.mask[index]:
            return None
        else:
            tag = self.tagarray[index]
            offset = self.offsetarray[index]
            return self.contents[tag].proxy(offset)

    def get(self, attr):
        if callable(self.tagarray):
            self.tagarray, self.offsetarray = self.tagarray()

        if attr == "tagarray":
            return self.tagarray
        elif attr == "offsetarray":
            return self.offsetarray
        else:
            raise NameError("UnionSparseOffset has no array {0}".format(repr(attr)))

    def projection(self, required, _memo=None):
        if self.hasany(required):
            if _memo is None:
                _memo = {}
            contents = []
            for x in self.contents:
                if id(x) not in _memo:
                    _memo[id(x)] = None
                    _memo[id(x)] = x.projection(required, _memo)
                content = _memo[id(x)]
                if content is not None:
                    contents.append(content)
            if len(contents) > 0:
                return UnionSparseOffset(self.tagarray, self.offsetarray, contents, self.masked, self)
            else:
                return None
        else:
            return None

    def _format(self, indent, width, refs, memo):
        self._recursion_check(memo)
        yield indent + refs.get(id(self), "") + "Union <"
        indent += "  "
        preamble = "tagarray    = "
        yield indent + preamble + self._format_array(self.tagarray, width - len(preamble) - len(indent))
        preamble = "offsetarray = "
        yield indent + preamble + self._format_array(self.offsetarray, width - len(preamble) - len(indent))
        for index, contents in enumerate(self.contents):
            for line in contents._format_with_preamble("{0}: ".format(index), indent, width, refs, memo):
                yield line
        yield indent + ">"

    def __eq__(self, other):
        return isinstance(other, UnionSparseOffset) and ((isinstance(self.tagarray, ndarray) and isinstance(other.tagarray, ndarray) and numpy.array_equal(self.tagarray, other.tagarray)) or self.tagarray == other.tagarray) and ((isinstance(self.offsetarray, ndarray) and isinstance(other.offsetarray, ndarray) and numpy.array_equal(self.offsetarray, other.offsetarray)) or self.offsetarray == other.offsetarray) and self.contents == other.contents and self.base == other.base

    def __ne__(self, other):
        return not self.__eq__(self, other)

################################################################ pointers

class Pointer(ObjectArrayMapping):
    def __init__(self, indexarray, target, masked=False, base=None):
        self.indexarray = indexarray
        self.target = target
        self.masked = masked
        self.base = base
        assert isinstance(self.target, ObjectArrayMapping), "target must be an ObjectArrayMapping"
        assert self.target is not self, "pointer's target may contain the pointer, but it must not be the pointer itself"

    def accessedby(self, accessor, _memo=None):
        if _memo is None:
            _memo = {}
        if id(self.target) not in _memo:
            _memo[id(self.target)] = None
            _memo[id(self.target)] = self.target.accessedby(accessor)
        target = _memo[id(self.target)]
        return Pointer(accessor, target, self.masked, self)

    def findbybase(self, base, _memo=None):
        if self.hasbase(base):
            return self
        else:
            if _memo is None:
                _memo = set()
            if id(self.target) not in _memo:
                _memo.add(id(self.target))
                return self.target.findbybase(base, _memo)
            else:
                return None

    @property
    def _name(self):
        return self.indexarray

    def resolved(self, source, lazy=False, _memo=None):
        def resolve():
            return self._toint64(self._resolved(self.indexarray, source, "Pointer indexarray must map to a one-dimensional, {0}, non-record array of integers", self.masked, lambda x: issubclass(x.dtype.type, numpy.integer)))

        # (only) pointers are allowed to reference themselves, but don't resolve the same pointer more than once
        if _memo is None:
            _memo = {}
        if id(self.target) not in _memo:
            self.target.resolved(source, lazy, _memo)

        if lazy:
            _memo[id(self)] = Pointer(resolve, _memo[id(self.target)], self.masked, self)
        else:
            _memo[id(self)] = Pointer(resolve(), _memo[id(self.target)], self.masked, self)
        return _memo[id(self)]

    def proxy(self, index):
        if callable(self.indexarray):
            self.indexarray = self.indexarray()

        if getattr(self.indexarray, "mask", None) is not None and self.indexarray.mask[index]:
            return None
        else:
            offset = self.indexarray[index]
            return self.target.proxy(offset)

    def get(self, attr):
        if callable(self.indexarray):
            self.indexarray = self.indexarray()

        if attr == "indexarray":
            return self.indexarray
        else:
            raise NameError("Pointer has no array {0}".format(repr(attr)))

    def members(self, _memo=None):
        if _memo is None:
            _memo = set()
        out = [self]
        if id(self.target) not in _memo:
            _memo.add(id(self.target))
            return out + self.target.members(_memo)
        else:
            return out

    def hasany(self, others, _memo=None):
        if any(x is self for x in others):
            return True
        if _memo is None:
            _memo = set()
        if id(self.target) not in _memo:
            _memo.add(id(self.target))
            return self.target.hasany(others, _memo)
        else:
            return False

    def projection(self, required, _memo=None):
        if self.hasany(required):
            if _memo is None:
                _memo = {}
            if id(self.target) not in _memo:
                _memo[id(self.target)] = None
                _memo[id(self.target)] = self.target.projection(required, _memo)
            target = _memo[id(self.target)]
            if target is None:
                target = Primitive(self.indexarray, self.masked)
            return Pointer(self.indexarray, target, self.masked, self)
        else:
            return None

    def _format(self, indent, width, refs, memo):
        yield indent + refs.get(id(self), "") + "Pointer (*"
        indent += "  "
        preamble = "indexarray = "
        yield indent + preamble + self._format_array(self.indexarray, width - len(preamble) - len(indent))
        if id(self.target) in refs:
            yield indent + "target: " + refs[id(self.target)].strip()
        else:
            for line in self.target._format(indent, width, refs, {}):
                yield line
        yield indent + "*)"

    def __eq__(self, other):
        return isinstance(other, Pointer) and ((isinstance(self.indexarray, ndarray) and isinstance(other.indexarray, ndarray) and numpy.array_equal(self.indexarray, other.indexarray)) or self.indexarray == other.indexarray) and self.target is other.target and self.base == other.base

    def __ne__(self, other):
        return not self.__eq__(self, other)
