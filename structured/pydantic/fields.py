from collections import defaultdict
from typing import Any, Callable, Dict, Generic, TypeVar, Union, List, Type

from django.db import models as django_models
from pydantic import GetJsonSchemaHandler, SerializationInfo
from pydantic_core import core_schema as cs
from pydantic.json_schema import JsonSchemaValue
from structured.utils.options import build_relation_schema_options
from structured.utils.serializer import (
    build_standard_model_serializer,
    minimal_serialization,
    minimal_list_serialization,
)
from structured.utils.typing import get_type
from django.apps import apps


T = TypeVar("T", bound=django_models.Model)


class ForeignKey(Generic[T]):
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: Callable[[Any], cs.CoreSchema]
    ) -> cs.CoreSchema:
        from structured.cache.engine import ValueWithCache

        model_class = get_type(source)
        is_abstract = getattr(model_class._meta, "abstract", False)

        def validate_from_pk(
            pk: Union[int, str], model_class=model_class
        ) -> Type[django_models.Model]:
            if is_abstract:
                raise ValueError(
                    "Cannot retrieve abstract models from primary key only."
                )
            return model_class._default_manager.get(pk=pk)

        int_str_union = cs.union_schema([cs.str_schema(), cs.int_schema()])
        from_pk_schema = cs.chain_schema(
            [
                int_str_union,
                cs.no_info_plain_validator_function(validate_from_pk),
            ]
        )

        def validate_from_dict(
            data: Dict[str, Union[str, int]]
        ) -> Type[django_models.Model]:
            if data is None:
                return None
            if is_abstract:
                model_class = apps.get_model(*data["model"])
            pk_attname = model_class._meta.pk.attname
            return validate_from_pk(data[pk_attname], model_class)

        from_dict_schema = cs.chain_schema(
            [
                # cs.typed_dict_schema({pk_attname: cs.typed_dict_field(int_str_union)}),
                cs.no_info_plain_validator_function(validate_from_dict),
            ]
        )

        from_cache_schema = cs.chain_schema(
            [
                cs.is_instance_schema(ValueWithCache),
                cs.no_info_plain_validator_function(lambda v: v.retrieve()),
            ]
        )

        def serialize_data(instance, info):
            if info.mode == "python":
                serializer = build_standard_model_serializer(model_class, depth=1)
                return serializer(instance=instance).data
            if isinstance(instance, ValueWithCache):
                instance = instance.retrieve()
            return minimal_serialization(instance)

        return cs.json_or_python_schema(
            json_schema=cs.union_schema(
                [from_cache_schema, from_pk_schema, from_dict_schema]
            ),
            python_schema=cs.union_schema(
                [
                    cs.is_instance_schema(model_class),
                    from_cache_schema,
                    from_pk_schema,
                    from_dict_schema,
                ]
            ),
            serialization=cs.plain_serializer_function_ser_schema(
                serialize_data, info_arg=True
            ),
            metadata={"relation": build_relation_schema_options(model_class)},
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: cs.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(cs.str_schema())
        json_schema.update(_core_schema.get("metadata", {}).get("relation", {}))
        return json_schema


class QuerySet(Generic[T]):
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: Callable[[Any], cs.CoreSchema]
    ) -> cs.CoreSchema:
        from structured.cache.engine import ValueWithCache

        def get_mclass() -> Type[django_models.Model]:
            return get_type(source)

        is_abstract = getattr(get_mclass()._meta, "abstract", False)

        def validate_from_pk_list(
            values: List[Union[int, str]]
        ) -> django_models.QuerySet:
            if is_abstract:
                raise ValueError(
                    "Cannot retrieve abstract models from primary key only."
                )
            preserved = django_models.Case(
                *[django_models.When(pk=pk, then=pos) for pos, pk in enumerate(values)]
            )
            return get_mclass()._default_manager.filter(pk__in=values).order_by(
                preserved
            )

        int_str_union = cs.union_schema([cs.str_schema(), cs.int_schema()])
        from_pk_list_schema = cs.chain_schema(
            [
                cs.list_schema(int_str_union),
                cs.no_info_plain_validator_function(validate_from_pk_list),
            ]
        )
        pk_attname = get_mclass()._meta.pk.attname

        def validate_from_dict(
            values: List[Dict[str, Union[str, int]]]
        ) -> django_models.QuerySet:
            if not is_abstract:
                pk_attname = get_mclass()._meta.pk.attname
                return validate_from_pk_list([data[pk_attname] for data in values])
            stack = defaultdict(list)
            for value in values:
                mclass = apps.get_model(*value["model"])
                pk_attname = mclass._meta.pk.attname
                stack[mclass].append(value[pk_attname])
            return django_models.QuerySet.union(
                *[
                    mclass._default_manager.filter(pk__in=stack[mclass])
                    for mclass in stack
                ]
            )

        from_dict_list_schema = cs.chain_schema(
            [
                cs.list_schema(
                    cs.typed_dict_schema(
                        {pk_attname: cs.typed_dict_field(int_str_union)}
                    )
                ),
                cs.no_info_plain_validator_function(validate_from_dict),
            ]
        )
        from_cache_schema = cs.chain_schema(
            [
                cs.is_instance_schema(ValueWithCache),
                cs.no_info_plain_validator_function(lambda v: v.retrieve()),
            ]
        )

        def serialize_data(qs: django_models.QuerySet, info: SerializationInfo):
            if info.mode == "python":
                serializer = build_standard_model_serializer(get_mclass(), depth=1)
                return serializer(instance=qs, many=True).data
            return minimal_list_serialization(qs)

        return cs.json_or_python_schema(
            json_schema=cs.union_schema(
                [from_cache_schema, from_pk_list_schema, from_dict_list_schema]
            ),
            python_schema=cs.union_schema(
                [
                    cs.is_instance_schema(django_models.QuerySet),
                    from_cache_schema,
                    from_pk_list_schema,
                    from_dict_list_schema,
                ]
            ),
            serialization=cs.plain_serializer_function_ser_schema(
                serialize_data, info_arg=True
            ),
            metadata={
                "relation": build_relation_schema_options(get_mclass(), many=True)
            },
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: cs.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(cs.str_schema())
        json_schema.update(_core_schema.get("metadata", {}).get("relation", {}))
        return json_schema
