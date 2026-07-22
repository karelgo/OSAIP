"""RFC 9116 security.txt (CP-12). Served at the root, outside /api/v1."""

import datetime

from fastapi import APIRouter, Response

router = APIRouter(include_in_schema=False)

_SECURITY_TXT_TEMPLATE = """\
Contact: mailto:security@osaip.dev
Expires: {expires}
Preferred-Languages: en, nl
Policy: https://github.com/osaip/osaip/blob/main/SECURITY.md
"""


@router.get("/.well-known/security.txt")
async def security_txt() -> Response:
    expires = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)).strftime(
        "%Y-%m-%dT00:00:00Z"
    )
    return Response(
        content=_SECURITY_TXT_TEMPLATE.format(expires=expires),
        media_type="text/plain; charset=utf-8",
    )
