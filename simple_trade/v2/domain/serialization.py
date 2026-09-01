"""领域对象的确定性序列化工具。"""

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
import json
from types import MappingProxyType
from typing import Mapping, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} 必须包含时区")


def require_stock_code(value: str) -> str:
    code = value.strip().upper()
    if not code:
        raise ValueError("stock_code 不能为空")
    return code


def freeze_json(value: object) -> JsonValue:
    """把 JSON 兼容数据递归冻结，避免 frozen dataclass 内部仍可变。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime):
        require_aware(value, "datetime")
        return value.isoformat()
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): freeze_json(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    if is_dataclass(value):
        return freeze_json(asdict(value))
    raise TypeError(f"不支持的 JSON 值类型: {type(value).__name__}")


def to_primitive(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        require_aware(value, "datetime")
        return value.isoformat()
    if is_dataclass(value):
        return {k: to_primitive(v) for k, v in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(k): to_primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_primitive(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
