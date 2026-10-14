"""Service-to-service auth: only VCB_BE may call /api, using a shared static secret."""
import os
import secrets

from fastapi import Header, HTTPException

HEADER = "X-Assistant-Secret"


def require_internal_secret(x_assistant_secret: str = Header(default="", alias=HEADER)) -> None:
    expected = os.environ.get("ASSISTANT_INTERNAL_SECRET", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ASSISTANT_INTERNAL_SECRET chưa cấu hình trên AI service")
    if not secrets.compare_digest(x_assistant_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid assistant secret")
