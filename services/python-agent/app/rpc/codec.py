"""Lossless Protobuf values, including IDs beyond JavaScript's safe integer range."""
import math
from fastapi.encoders import jsonable_encoder
from .generated import easyjob_rpc_pb2 as pb


def encode(value, depth=0):
    if depth > 32:
        raise ValueError('RPC value nesting is too deep')
    result = pb.Value()
    if value is None:
        result.null_value = True
    elif isinstance(value, bool):
        result.boolean = value
    elif isinstance(value, int):
        result.integer = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Non-finite RPC number')
        result.decimal = value
    elif isinstance(value, str):
        result.text = value
    elif isinstance(value, dict):
        result.object.SetInParent()
        for key, item in value.items():
            result.object.fields[str(key)].CopyFrom(encode(item, depth + 1))
    elif isinstance(value, (list, tuple)):
        result.array.SetInParent()
        for item in value:
            result.array.items.add().CopyFrom(encode(item, depth + 1))
    else:
        return encode(jsonable_encoder(value, by_alias=True), depth)
    return result


def decode(value, depth=0):
    if depth > 32:
        raise ValueError('RPC value nesting is too deep')
    kind = value.WhichOneof('kind')
    if kind in (None, 'null_value'):
        return None
    if kind == 'object':
        return {key: decode(item, depth + 1) for key, item in value.object.fields.items()}
    if kind == 'array':
        return [decode(item, depth + 1) for item in value.array.items]
    return getattr(value, kind)


def decode_object(value):
    return {key: decode(item) for key, item in value.fields.items()}
