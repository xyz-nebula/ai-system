"""Export or verify the committed Arena AI OpenAPI contract."""

import argparse
import json
from pathlib import Path

from arena_ai.app import create_app

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "api" / "openapi.json"


def rendered_schema() -> str:
    return json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the committed schema differs from the application",
    )
    args = parser.parse_args()
    rendered = rendered_schema()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != rendered:
            raise SystemExit("docs/api/openapi.json is out of date; run export_openapi.py")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
