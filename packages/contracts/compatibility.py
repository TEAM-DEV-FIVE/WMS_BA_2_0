"""Explicit wire capabilities required by the packaged desktop; no DB secrets."""

CLIENT_VERSION = "0.1.0"
API_PROTOCOL = "1"
RECOVERY_PROTOCOL = "lookup-v1,send-v1"
CACHE_READ_MIN = 1
CACHE_READ_MAX = 3


def server_headers():
    return {"X-WMS-API-Protocol": API_PROTOCOL, "X-WMS-Recovery-Protocol": RECOVERY_PROTOCOL}


def compatible(headers):
    return headers.get("X-WMS-API-Protocol") == API_PROTOCOL and {"lookup-v1", "send-v1"} <= set(
        headers.get("X-WMS-Recovery-Protocol", "").split(",")
    )
