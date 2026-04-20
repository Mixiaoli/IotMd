from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

SECRET = os.getenv("IOTMD_AUTH_SECRET", "change-this-secret")
TOKEN_EXPIRE_SECONDS = int(os.getenv("IOTMD_TOKEN_EXPIRE_SECONDS", "86400"))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return base64.urlsafe_b64encode(salt + digest).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = base64.urlsafe_b64decode(password_hash.encode("utf-8"))
    salt, digest = raw[:16], raw[16:]
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(digest, check)


def create_token(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + TOKEN_EXPIRE_SECONDS
    encoded = base64.urlsafe_b64encode(json.dumps(body, ensure_ascii=False).encode("utf-8")).decode("utf-8")
    sign = hmac.new(SECRET.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{encoded}.{sign}"


def parse_token(token: str) -> dict[str, Any] | None:
    try:
        encoded, sign = token.split(".", 1)
        expected = hmac.new(SECRET.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sign, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("utf-8")))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
