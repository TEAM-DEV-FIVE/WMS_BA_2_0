"""Lookup uses the original validator and live authorization, never the handler."""

import json
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from apps.server.application.recovery import RecoveryContext, recovery_context
from apps.server.domain.errors import DomainError
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


async def reject_invalid_return_submit(request, exc):
    """Only certify a known pre-handler failure after live authorization/key lookup."""
    context = recovery_context.get()
    parts = request.url.path.split("/")
    if (context is None or request.method != "POST" or len(parts) != 6
            or parts[:4] != ["", "api", "v1", "documents"] or parts[5] != "submit"
            or any(tuple(e["loc"]) != ("body", "reason") for e in exc.errors())):
        return False
    scheme, _, access = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not access:
        return False
    try:
        key = UUID(request.headers["Idempotency-Key"])
        document_id = UUID(parts[4])
        confirmed = await run_in_threadpool(
            request.app.state.orders.can_reject_invalid_return_submit,
            access, key, document_id, exc.body)
    except (KeyError, ValueError, DomainError):
        return False
    if confirmed:
        context.key, context.rejected = str(key), True
    return confirmed


async def reject_invalid_transfer_post(request, exc):
    """Certify only authorized blank reason/evidence transfer posting failures."""
    context = recovery_context.get()
    parts = request.url.path.split("/")
    if (context is None or request.method != "POST" or len(parts) != 6
            or parts[:4] != ["", "api", "v1", "transfers"]
            or parts[5] not in {"dispatch", "receive"}
            or any(tuple(e["loc"]) not in {("body", "reason"), ("body", "evidence_ref")}
                   for e in exc.errors())):
        return False
    scheme, _, access = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not access:
        return False
    try:
        key, doc_id = UUID(request.headers["Idempotency-Key"]), UUID(parts[4])
        confirmed = await run_in_threadpool(
            request.app.state.orders.transfers.can_reject_invalid_post, access, key, doc_id, exc.body,
            "DISPATCH" if parts[5] == "dispatch" else "ARRIVE")
    except (KeyError, ValueError, DomainError):
        return False
    if confirmed:
        context.key, context.rejected = str(key), True
    return confirmed


async def reject_invalid_issue_cancel(request, exc):
    """Keep immutable legacy cancel envelopes recoverable after blank reasons."""
    context = recovery_context.get()
    parts = request.url.path.split("/")
    if (context is None or request.method != "POST" or len(parts) != 6
            or parts[:4] != ["", "api", "v1", "documents"] or parts[5] != "cancel"
            or any(tuple(e["loc"]) != ("body", "reason") for e in exc.errors())):
        return False
    scheme, _, access = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not access:
        return False
    try:
        key, doc_id = UUID(request.headers["Idempotency-Key"]), UUID(parts[4])
        confirmed = await run_in_threadpool(
            request.app.state.orders.can_reject_invalid_issue_cancel,
            access, key, doc_id, exc.body)
    except (KeyError, ValueError, DomainError):
        return False
    if confirmed:
        context.key, context.rejected = str(key), True
    return confirmed
