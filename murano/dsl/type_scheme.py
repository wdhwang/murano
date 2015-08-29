#    Copyright (c) 2014 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import sys
import types
import uuid

from yaql.language import specs
from yaql.language import utils
from yaql.language import yaqltypes

from murano.dsl import dsl
from murano.dsl import dsl_types
from murano.dsl import exceptions
from murano.dsl import helpers


class TypeScheme(object):
    class ObjRef(object):
        def __init__(self, object_id):
            self.object_id = object_id

    def __init__(self, spec):
        self._spec = spec

    @staticmethod
    def prepare_context(root_context, this, owner, default):
        @specs.parameter('value', nullable=True)
        @specs.method
        def int_(value):
            if value is dsl.NO_VALUE:
                value = default
            if value is None:
                return None
            try:
                return int(value)
            except Exception:
                raise exceptions.ContractViolationException(
                    'Value {0} violates int() contract'.format(value))

        @specs.parameter('value', nullable=True)
        @specs.method
        def string(value):
            if value is dsl.NO_VALUE:
                value = default
            if value is None:
                return None
            try:
                return unicode(value)
            except Exception:
                raise exceptions.ContractViolationException(
                    'Value {0} violates string() contract'.format(value))

        @specs.parameter('value', nullable=True)
        @specs.method
        def bool_(value):
            if value is dsl.NO_VALUE:
                value = default
            if value is None:
                return None
            return True if value else False

        @specs.parameter('value', nullable=True)
        @specs.method
        def not_null(value):
            if isinstance(value, TypeScheme.ObjRef):
                return value

            if value is None:
                raise exceptions.ContractViolationException(
                    'null value violates notNull() contract')
            return value

        @specs.parameter('value', nullable=True)
        @specs.method
        def error(value):
            raise exceptions.ContractViolationException('error() contract')

        @specs.parameter('value', nullable=True)
        @specs.parameter('predicate', yaqltypes.Lambda(with_context=True))
        @specs.method
        def check(value, predicate):
            if isinstance(value, TypeScheme.ObjRef) or predicate(
                    root_context.create_child_context(), value):
                return value
            else:
                raise exceptions.ContractViolationException(
                    "Value {0} doesn't match predicate".format(value))

        @specs.parameter('obj', TypeScheme.ObjRef, nullable=True)
        @specs.name('owned')
        @specs.method
        def owned_ref(obj):
            if obj is None:
                return None
            if isinstance(obj, TypeScheme.ObjRef):
                return obj

        @specs.parameter('obj', dsl_types.MuranoObject)
        @specs.method
        def owned(obj):
            p = obj.owner
            while p is not None:
                if p is this:
                    return obj
                p = p.owner

            raise exceptions.ContractViolationException(
                'Object {0} violates owned() contract'.format(
                    obj.object_id))

        @specs.parameter('obj', TypeScheme.ObjRef, nullable=True)
        @specs.name('not_owned')
        @specs.method
        def not_owned_ref(obj):
            if isinstance(obj, TypeScheme.ObjRef):
                return obj

            if obj is None:
                return None

        @specs.parameter('obj', dsl_types.MuranoObject)
        @specs.method
        def not_owned(obj):
            try:
                owned(obj)
            except exceptions.ContractViolationException:
                return obj
            else:
                raise exceptions.ContractViolationException(
                    'Object {0} violates notOwned() contract'.format(
                        obj.object_id))

        @specs.parameter('name', dsl.MuranoTypeName(
            False, root_context))
        @specs.parameter('default_name', dsl.MuranoTypeName(
            True, root_context))
        @specs.parameter('value', nullable=True)
        @specs.parameter('version_spec', yaqltypes.String(True))
        @specs.method
        def class_(value, name, default_name=None, version_spec=None):
            object_store = this.object_store
            if not default_name:
                default_name = name
            murano_class = name.murano_class
            if value is None:
                return None
            if isinstance(value, dsl_types.MuranoObject):
                obj = value
            elif isinstance(value, dsl_types.MuranoObjectInterface):
                obj = value.object
            elif isinstance(value, utils.MappingType):
                if '?' not in value:
                    new_value = {'?': {
                        'id': uuid.uuid4().hex,
                        'type': default_name.murano_class.name,
                        'classVersion': str(default_name.murano_class.version)
                    }}
                    new_value.update(value)
                    value = new_value

                obj = object_store.load(
                    value, owner, root_context, defaults=default)
            elif isinstance(value, types.StringTypes):
                obj = object_store.get(value)
                if obj is None:
                    if not object_store.initializing:
                        raise exceptions.NoObjectFoundError(value)
                    else:
                        return TypeScheme.ObjRef(value)
            else:
                raise exceptions.ContractViolationException(
                    'Value {0} cannot be represented as class {1}'.format(
                        value, name))
            if not helpers.is_instance_of(
                    obj, murano_class.name,
                    version_spec or helpers.get_type(root_context)):
                raise exceptions.ContractViolationException(
                    'Object of type {0} is not compatible with '
                    'requested type {1}'.format(obj.type.name, name))
            return obj

        context = root_context.create_child_context()
        context.register_function(int_)
        context.register_function(string)
        context.register_function(bool_)
        context.register_function(check)
        context.register_function(not_null)
        context.register_function(error)
        context.register_function(class_)
        context.register_function(owned_ref)
        context.register_function(owned)
        context.register_function(not_owned_ref)
        context.register_function(not_owned)
        return context

    def _map_dict(self, data, spec, context):
        if data is None or data is dsl.NO_VALUE:
            data = {}
        if not isinstance(data, utils.MappingType):
            raise exceptions.ContractViolationException(
                'Supplied is not of a dictionary type')
        if not spec:
            return data
        result = {}
        yaql_key = None
        for key, value in spec.iteritems():
            if isinstance(key, dsl_types.YaqlExpression):
                if yaql_key is not None:
                    raise exceptions.DslContractSyntaxError(
                        'Dictionary contract '
                        'cannot have more than one expression keys')
                else:
                    yaql_key = key
            else:
                result[key] = self._map(data.get(key), value, context)

        if yaql_key is not None:
            yaql_value = spec[yaql_key]
            for key, value in data.iteritems():
                if key in result:
                    continue
                result[self._map(key, yaql_key, context)] = self._map(
                    value, yaql_value, context)

        return utils.FrozenDict(result)

    def _map_list(self, data, spec, context):
        if not utils.is_sequence(data):
            if data is None or data is dsl.NO_VALUE:
                data = []
            else:
                data = [data]
        if len(spec) < 1:
            return data
        shift = 0
        max_length = sys.maxint
        min_length = 0
        if isinstance(spec[-1], types.IntType):
            min_length = spec[-1]
            shift += 1
        if len(spec) >= 2 and isinstance(spec[-2], types.IntType):
            max_length = min_length
            min_length = spec[-2]
            shift += 1

        if not min_length <= len(data) <= max_length:
            raise exceptions.ContractViolationException(
                'Array length {0} is not within [{1}..{2}] range'.format(
                    len(data), min_length, max_length))

        def map_func():
            for index, item in enumerate(data):
                spec_item = (
                    spec[-1 - shift]
                    if index >= len(spec) - shift
                    else spec[index]
                )
                yield self._map(item, spec_item, context)

        return tuple(map_func())

    def _map_scalar(self, data, spec):
        if data != spec:
            raise exceptions.ContractViolationException(
                'Value {0} is not equal to {1}'.format(data, spec))
        else:
            return data

    def _map(self, data, spec, context):
        child_context = context.create_child_context()
        if isinstance(spec, dsl_types.YaqlExpression):
            child_context[''] = data
            return spec(context=child_context)
        elif isinstance(spec, utils.MappingType):
            return self._map_dict(data, spec, child_context)
        elif utils.is_sequence(spec):
            return self._map_list(data, spec, child_context)
        else:
            return self._map_scalar(data, spec)

    def __call__(self, data, context, this, owner, default):
        # TODO(ativelkov, slagun): temporary fix, need a better way of handling
        # composite defaults
        # A bug (#1313694) has been filed

        if data is dsl.NO_VALUE:
            data = helpers.evaluate(default, context)

        context = self.prepare_context(context, this, owner, default)
        return self._map(data, self._spec, context)
