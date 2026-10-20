"""Write the OpenAPI document used to generate the frontend's typed client."""

import json
import sys
from pathlib import Path

from societytwin.api.app import create_app
from societytwin.config import load_settings


def openapi_document() -> dict:
    # The schema does not depend on local paths or settings values; no lifespan runs here.
    return create_app(load_settings(), start_worker=False).openapi()


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("frontend/openapi.json")
    target.write_text(json.dumps(openapi_document(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
