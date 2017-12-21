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

import numpy

import oamap.proxy

# array cache, so that arrays are only loaded once (might be an expensive network operation)
class Cache(object):
    def __init__(self, cachelen):
        self.arraylist = [None] * cachelen
        self.ptr = numpy.zeros(cachelen, dtype=numpy.intp)   # these arrays are only set and used in compiled code
        self.len = numpy.zeros(cachelen, dtype=numpy.intp)

    def entercompiled(self):
        for i, x in enumerate(self.arraylist):
            if x is None:
                self.ptr[i] = 0
                self.len[i] = 0
            else:
                if not isinstance(x, numpy.ndarray):
                    raise TypeError("all arrays must have numpy.ndarray type for use in compiled code")
                self.ptr[i] = x.ctypes.data
                self.len[i] = x.shape[0]
        return self.ptr.ctypes.data, self.len.ctypes.data

# base class of all runtime-object generators (one for each type)
class Generator(object):
    @staticmethod
    def _getarray(arrays, name, cache, cacheidx, dtype, dims=()):
        if cache.arraylist[cacheidx] is None:
            cache.arraylist[cacheidx] = arrays[name]
            if getattr(cache.arraylist[cacheidx], "dtype", dtype) != dtype:
                raise TypeError("arrays[{0}].dtype is {1} but expected {2}".format(repr(name), cache.arraylist[cacheidx].dtype, dtype))
            if getattr(cache.arraylist[cacheidx], "shape", (0,) + dims)[1:] != dims:
                raise TypeError("arrays[{0}].shape[1:] is {1} but expected {2}".format(repr(name), cache.arraylist[cacheidx].shape[1:], dims))
        return cache.arraylist[cacheidx]

    def __init__(self, name):
        self.name = name

    def __call__(self, arrays):
        return self._generate(arrays, 0, Cache(self._cachelen))

# mix-in for all generators of nullable types
class Masked(object):
    dtype = numpy.dtype(numpy.bool_)

    def __init__(self, mask, maskidx):
        self.mask = mask
        self.maskidx = maskidx

    def _generate(self, arrays, index, cache):
        if self._getarray(arrays, self.mask, cache, self.maskidx, Masked.dtype)[index]:
            return None
        else:
            return self.__class__.__bases__[1]._generate(self, arrays, index, cache)

################################################################ Primitives

class PrimitiveGenerator(Generator):
    def __init__(self, data, dataidx, dtype, dims, name):
        self.data = data
        self.dataidx = dataidx
        self.dtype = dtype
        self.dims = dims
        Generator.__init__(self, name)

    def _generate(self, arrays, index, cache):
        return self._getarray(arrays, self.data, cache, self.dataidx, self.dtype, self.dims)[index]

class MaskedPrimitiveGenerator(Masked, PrimitiveGenerator):
    def __init__(self, mask, maskidx, data, dataidx, dtype, dims, name):
        Masked.__init__(self, mask, maskidx)
        PrimitiveGenerator.__init__(self, data, dataidx, dtype, dims, name)

################################################################ Lists

class ListGenerator(Generator):
    dtype = numpy.dtype(numpy.int32)

    def __init__(self, starts, startsidx, stops, stopsidx, content, name):
        self.starts = starts
        self.startsidx = startsidx
        self.stops = stops
        self.stopsidx = stopsidx
        self.content = content
        Generator.__init__(self, name)

    def _generate(self, arrays, index, cache):
        starts = self._getarray(arrays, self.starts, cache, self.startsidx, ListGenerator.dtype)
        stops  = self._getarray(arrays, self.stops,  cache, self.stopsidx,  ListGenerator.dtype)
        return oamap.proxy.ListProxy(self, arrays, cache, starts[index], stops[index], 1)

class MaskedListGenerator(Masked, ListGenerator):
    def __init__(self, mask, maskidx, starts, startsidx, stops, stopsidx, content, name):
        Masked.__init__(self, mask, maskidx)
        ListGenerator.__init__(self, starts, startsidx, stops, stopsidx, content, name)

################################################################ Unions

class UnionGenerator(Generator):
    dtype = numpy.dtype(numpy.int32)

    def __init__(self, tags, tagsidx, offsets, offsetsidx, possibilities, name):
        self.tags = tags
        self.tagsidx = tagsidx
        self.offsets = offsets
        self.offsetsidx = offsetsidx
        self.possibilities = possibilities
        Generator.__init__(self, name)

    def _generate(self, arrays, index, cache):
        tags    = self._getarray(arrays, self.tags,    cache, self.tagsidx,    UnionGenerator.dtype)
        offsets = self._getarray(arrays, self.offsets, cache, self.offsetsidx, UnionGenerator.dtype)
        return self.possibilities[tags[index]]._generate(arrays, offsets[index], cache)

class MaskedUnionGenerator(Masked, UnionGenerator):
    def __init__(self, mask, maskidx, tags, tagsidx, offsets, offsetsidx, possibilities, name):
        Masked.__init__(self, mask, maskidx)
        UnionGenerator.__init__(self, tags, tagsidx, offsets, offsetsidx, possibilities, name)

################################################################ Records

class RecordGenerator(Generator):
    def __init__(self, fields, name):
        self.fields = fields
        Generator.__init__(self, name)

    def _generate(self, arrays, index, cache):
        return oamap.proxy.RecordProxy(self, arrays, cache, index)

class MaskedRecordGenerator(Masked, RecordGenerator):
    def __init__(self, mask, maskidx, fields, name):
        Masked.__init__(self, mask, maskidx)
        RecordGenerator.__init__(self, fields, name)

################################################################ Tuples

class TupleGenerator(Generator):
    def __init__(self, types, name):
        self.types = types
        Generator.__init__(self, name)

    def _generate(self, arrays, index, cache):
        return oamap.proxy.TupleProxy(self, arrays, cache, index)

class MaskedTupleGenerator(Masked, TupleGenerator):
    def __init__(self, mask, maskidx, types, name):
        Masked.__init__(self, mask, maskidx)
        TupleGenerator.__init__(self, types, name)

################################################################ Pointers

class PointerGenerator(Generator):
    dtype = numpy.dtype(numpy.int32)

    def __init__(self, positions, positionsidx, target, name):
        self.positions = positions
        self.positionsidx = positionsidx
        self.target = target
        Generator.__init__(self, name)

    def _generate(self, arrays, index, cache):
        positions = self._getarray(arrays, self.positions, cache, self.positionsidx, PointerGenerator.dtype)
        return self.target._generate(arrays, positions[index], cache)

class MaskedPointerGenerator(Masked, PointerGenerator):
    def __init__(self, mask, maskidx, positions, positionsidx, target, name):
        Masked.__init__(self, mask, maskidx)
        PointerGenerator.__init__(self, positions, positionsidx, target, name)

################################################################ for assigning unique strings to types (used to distinguish Numba types)

def _firstindex(generator):
    if isinstance(generator, Masked):
        return generator.maskidx
    elif isinstance(generator, PrimitiveGenerator):
        return generator.dataidx
    elif isinstance(generator, ListGenerator):
        return generator.startsidx
    elif isinstance(generator, UnionGenerator):
        return generator.tagsidx
    elif isinstance(generator, RecordGenerator):
        for g in generator.fields.values():
            return _firstindex(g)
        return -1
    elif isinstance(generator, TupleGenerator):
        for g in generator.types:
            return _firstindex(g)
        return -1
    elif isinstance(generator, PointerGenerator):
        return generator.positionsidx
    else:
        raise AssertionError("unrecognized generator type: {0}".format(generator))

def _uniquestr(generator, memo):
    if id(generator) not in memo:
        memo.add(id(generator))
        givenname = "nil" if generator.name is None else repr(generator.name)

        if isinstance(generator, PrimitiveGenerator):
            generator._uniquestr = "(P {0} {1} ({2}) {3} {4})".format(givenname, repr(str(generator.dtype)), " ".join(map(repr, generator.dims)), generator.dataidx, repr(generator.data))

        elif isinstance(generator, MaskedPrimitiveGenerator):
            generator._uniquestr = "(P {0} {1} ({2}) {3} {4} {5} {6})".format(givenname, repr(str(generator.dtype)), " ".join(map(repr, generator.dims)), generator.maskidx, repr(generator.mask), generator.dataidx, repr(generator.data))

        elif isinstance(generator, ListGenerator):
            _uniquestr(generator.content, memo)
            generator._uniquestr = "(L {0} {1} {2} {3} {4} {5})".format(givenname, generator.startsidx, repr(generator.starts), generator.stopsidx, repr(generator.stops), generator.content._uniquestr)

        elif isinstance(generator, MaskedListGenerator):
            _uniquestr(generator.content, memo)
            generator._uniquestr = "(L {0} {1} {2} {3} {4} {5} {6} {7})".format(givenname, generator.maskidx, repr(generator.mask), generator.startsidx, repr(generator.starts), generator.stopsidx, repr(generator.stops), generator.content._uniquestr)

        elif isinstance(generator, UnionGenerator):
            for t in generator.possibilities:
                _uniquestr(t, memo)
            generator._uniquestr = "(U {0} {1} {2} {3} {4} ({5}))".format(givenname, generator.tagsidx, repr(generator.tags), generator.offsetsidx, repr(generator.offsets), " ".join(x._uniquestr for x in generator.possibilities))

        elif isinstance(generator, MaskedUnionGenerator):
            for t in generator.possibilities:
                _uniquestr(t, memo)
            generator._uniquestr = "(U {0} {1} {2} {3} {4} {5} {6} ({7}))".format(givenname, generator.maskidx, repr(generator.mask), generator.tagsidx, repr(generator.tags), generator.offsetsidx, repr(generator.offsets), " ".join(x._uniquestr for x in generator.possibilities))

        elif isinstance(generator, RecordGenerator):
            for t in generator.fields.values():
                _uniquestr(t, memo)
            generator._uniquestr = "(R {0} ({1}))".format(givenname, " ".join("({0} . {1})".format(repr(n), t._uniquestr) for n, t in generator.fields.items()))

        elif isinstance(generator, MaskedRecordGenerator):
            for t in generator.fields.values():
                _uniquestr(t, memo)
            generator._uniquestr = "(R {0} {1} {2} ({3}))".format(givenname, generator.maskidx, repr(generator.mask), " ".join("({0} . {1})".format(repr(n), t._uniquestr) for n, t in generator.fields.items()))

        elif isinstance(generator, TupleGenerator):
            for t in generator.types:
                _uniquestr(t, memo)
            generator._uniquestr = "(T {0} ({1}))".format(givenname, " ".join(t._uniquestr for t in generator.types))

        elif isinstance(generator, MaskedTupleGenerator):
            for t in generator.types:
                _uniquestr(t, memo)
            generator._uniquestr = "(T {0} {1} {2} ({3}))".format(givenname, generator.maskidx, repr(generator.mask), " ".join(t._uniquestr for t in generator.types))

        elif isinstance(generator, PointerGenerator):
            _uniquestr(generator.target, memo)
            if generator._referenceonly:
                target = _firstindex(generator.target)
            else:
                target = generator.target._uniquestr
            generator._uniquestr = "(X {0} {1} {2} {3})".format(givenname, generator.positionsidx, repr(generator.positions), target)

        elif isinstance(generator, MaskedPointerGenerator):
            _uniquestr(generator.target, memo)
            if generator._referenceonly:
                target = _firstindex(generator.target)
            else:
                target = generator.target._uniquestr
            generator._uniquestr = "(X {0} {1} {2} {3} {4} {5})".format(givenname, generator.maskidx, repr(generator.mask), generator.positionsidx, repr(generator.positions), target)

        else:
            raise AssertionError("unrecognized generator type: {0}".format(generator))