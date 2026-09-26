"""Exact finite JSON numbers for the v2 wire boundary, without float conversion."""

import json
from decimal import Decimal


def loads(data: str | bytes | bytearray) -> object:
    def invalid_constant(value: str) -> None:
        raise ValueError(f"Nonfinite JSON number: {value}")

    return json.loads(data, parse_float=Decimal, parse_constant=invalid_constant)


def dumps(data: object, *, indent: int | None = None, ensure_ascii: bool = False) -> str:
    """Encode a model's Python tree, retaining Decimal as JSON numeric tokens."""

    def render(value: object, depth: int) -> str:
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("Nonfinite JSON number")
            return str(value)
        if isinstance(value, dict):
            parts = []
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("JSON object keys must be strings")
                parts.append(
                    json.dumps(key, ensure_ascii=ensure_ascii)
                    + (": " if indent is not None else ":")
                    + render(item, depth + 1)
                )
            opening, closing = "{", "}"
        elif isinstance(value, list):
            parts = [render(item, depth + 1) for item in value]
            opening, closing = "[", "]"
        else:
            return json.dumps(value, ensure_ascii=ensure_ascii, allow_nan=False)
        if indent is None or not parts:
            return opening + ",".join(parts) + closing
        padding = " " * (indent * (depth + 1))
        return (
            opening
            + "\n"
            + padding
            + (",\n" + padding).join(parts)
            + "\n"
            + (" " * (indent * depth))
            + closing
        )

    return render(data, 0)
