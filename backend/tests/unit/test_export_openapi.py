import json
from pathlib import Path

from app.export_openapi import main


def test_the_schema_file_describes_the_api(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"

    main(["export_openapi", str(output)])

    schema = json.loads(output.read_text(encoding="utf-8"))
    assert "/api/v1/health/ready" in schema["paths"]
    assert "ReadinessResponse" in schema["components"]["schemas"]
