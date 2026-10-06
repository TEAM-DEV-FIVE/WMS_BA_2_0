"""Lookup uses the original validator and live authorization, never the handler."""

import json
from uuid import UUID

from apps.server.application.recovery import RecoveryContext, recovery_context
from packages.contracts.recovery import acknowledgement, request_digest, route_policy


def document_recovery(app):
    original = app.openapi

    def schema():
        result = original()
        for path, operations in result["paths"].items():
            for method, operation in operations.items():
                if method not in {"post", "put", "patch", "delete"}:
                    continue
                policy, _ = route_policy(method.upper(), path.removeprefix("/api/v1/"))
                operation["x-wms-recovery"] = {"version": 1, "mode": policy}
                parameters = operation.setdefault("parameters", [])
                if policy == "COMMAND" and not any(p.get("name") == "X-WMS-Recovery" for p in parameters):
                    parameters.append({"name": "X-WMS-Recovery", "in": "header", "required": False,
                        "schema": {"type": "string", "enum": ["lookup-v1", "send-v1"]},
                        "description": "lookup-v1 only authorizes and looks up the exact command key/body; never executes a missing command. X-WMS-ACK binds the committed result to the request. See RECOVERY_ALL.md."})
        return result
    app.openapi = schema


async def recovery_request(request, call_next, error):
    mode = request.headers.get("X-WMS-Recovery")
    if mode is None:
        return await call_next(request)
    try:
        path = request.url.path.removeprefix("/api/v1/")
        if request.url.query:
            path += "?" + request.url.query
        if mode not in {"lookup-v1", "send-v1"} or route_policy(request.method, path)[0] != "COMMAND":
            raise ValueError
        key = str(UUID(request.headers["Idempotency-Key"]))
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 2 * 1024 * 1024:
                return error(request, 413, "FILE_LIMIT", "Lệnh phục hồi vượt 2 MiB.")
        request._body = bytes(data)
        body = json.loads(data)
        if not isinstance(body, dict):
            raise ValueError
        fingerprint = request_digest(request.method, path, body, key)
    except (KeyError, ValueError, RecursionError):
        return error(request, 422, "INVALID_RECOVERY", "Lệnh không hỗ trợ giao thức phục hồi này.")
    context = RecoveryContext(lookup_only=mode == "lookup-v1")
    token = recovery_context.set(context)
    try:
        response = await call_next(request)
        if context.key == key:
            if context.result is not None and 200 <= response.status_code < 300:
                response.headers["X-WMS-ACK"] = acknowledgement(fingerprint, context.result)
            elif context.rejected and 400 <= response.status_code < 500:
                response.headers["X-WMS-Rejected"] = fingerprint
        return response
    finally:
        recovery_context.reset(token)
