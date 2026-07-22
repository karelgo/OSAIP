"""Weak ETags on heavy GETs (§6.6): hash of the serialized payload, If-None-Match → 304."""

import hashlib
import json
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse


def etag_json_response(request: Request, payload: Any) -> Response:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    etag = f'W/"{hashlib.sha256(body.encode()).hexdigest()[:32]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response = JSONResponse(content=payload)
    response.headers["ETag"] = etag
    return response
