from uuid import uuid4

import httpx
import pytest

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient


def token_result(access="access", refresh="refresh"):
    return {"status": "AUTHENTICATED", "access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": 900}


def unauthorized():
    return httpx.Response(401, json={"code": "UNAUTHENTICATED", "message": "Sign in", "request_id": str(uuid4())})


def test_client_refreshes_once_for_get_and_keeps_rotated_tokens_only_in_ram():
    calls = []
    def serve(request):
        calls.append((request.method, request.url.path, request.headers.get("Authorization")))
        if request.url.path.endswith("login"):
            return httpx.Response(200, json=token_result())
        if request.url.path.endswith("refresh"):
            return httpx.Response(200, json=token_result("new-access", "new-refresh"))
        if request.headers.get("Authorization") == "Bearer new-access":
            return httpx.Response(200, json=[])
        return unauthorized()
    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(serve))
    try:
        api.login("operator", "password")
        assert api.warehouses() == []
        assert [path for _, path, _ in calls] == ["/api/v1/auth/login", "/api/v1/warehouses", "/api/v1/auth/refresh", "/api/v1/warehouses"]
        assert api._tokens.refresh_token == "new-refresh"
        assert "new-refresh" not in repr(api._tokens)
    finally:
        api.close()
    assert api._tokens is None


def test_refresh_timeout_drops_uncertain_tokens_without_retry():
    refresh_calls = []
    def serve(request):
        if request.url.path.endswith("login"):
            return httpx.Response(200, json=token_result())
        if request.url.path.endswith("refresh"):
            refresh_calls.append(request)
            raise httpx.ReadTimeout("timeout after commit")
        return unauthorized()
    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(serve))
    try:
        api.login("operator", "password")
        with pytest.raises(ApiError) as error:
            api.warehouses()
        assert error.value.code == "TIMEOUT"
        assert api._tokens is None
        assert len(refresh_calls) == 1
    finally:
        api.close()


def test_logout_network_error_still_drops_local_credentials():
    def serve(request):
        if request.url.path.endswith("login"):
            return httpx.Response(200, json=token_result())
        raise httpx.ConnectError("disconnected")
    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(serve))
    try:
        api.login("operator", "password")
        with pytest.raises(ApiError):
            api.logout()
        assert api._tokens is None and api._challenge is None
    finally:
        api.close()
