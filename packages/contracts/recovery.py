"""Version 1 recovery wire protocol; no persistence or server dependencies."""

import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit

from packages.contracts.recovery_routes import ROUTES


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def route_policy(method, path):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or path.startswith("/") or "%" in parsed.path:
        raise ValueError("Unsupported recovery path")
    query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if query and (not parsed.path.startswith("custom-fields/") or len(query) != 1 or query[0][0] != "warehouse_id"):
        raise ValueError("Unsupported recovery query")
    for verb, template, mode in ROUTES:
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", template)
        if method == verb and re.fullmatch(pattern, parsed.path):
            return mode, template
    raise ValueError("Unclassified write endpoint")


def request_digest(method, path, body, key):
    return digest([1, method, path, body, str(key)])


def acknowledgement(request_hash, result):
    return digest([1, request_hash, result])
