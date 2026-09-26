"""Write the OpenAPI schema to a file; the frontend generates its API types from it."""

import json
import sys
from pathlib import Path
from typing import Final

from app.core.config import Settings
from app.main import create_app

DEFAULT_OUTPUT: Final = Path("openapi.json")


def main(argv: list[str]) -> None:
    output = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT
    schema = create_app(Settings(environment="test", log_level="WARNING")).openapi()
    output.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
