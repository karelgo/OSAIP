"""Export the OpenAPI document (deterministic) for client generation.

Usage: uv run python -m osaip_api.export_openapi > packages/api-client/openapi.json
The output is byte-stable for unchanged routes so the CI drift gate can diff it.
"""

import json
import sys

from osaip_api.app import create_app
from osaip_api.config import Settings


def main() -> None:
    # dev=True so dev-only routes (e.g. /dev/emit-test-event) are part of the schema;
    # they exist only in dev deployments but the client needs their types for e2e.
    app = create_app(Settings(dev=True))
    document = app.openapi()
    json.dump(document, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
