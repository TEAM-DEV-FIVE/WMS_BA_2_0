from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text

from apps.server.domain.errors import DomainError
from packages.contracts.identity import ProfileUpdate

pytestmark = pytest.mark.integration


def test_profile_requires_mfa_is_self_only_and_retry_safe(iam):
    user, secret = iam.user(mfa=True)
    other, _ = iam.user("other")
    headers = iam.headers(iam.login(secret=secret))
    route = "/api/v1/auth/profile"
    body = {"display_name": "Trần Trung Kiên", "expected_display_name": "operator"}
    assert iam.client.patch(route, json=body).status_code == 401
    for invalid in ({**body, "id": str(other)}, {**body, "display_name": "  "},
                    {**body, "display_name": "Tên\nkhác"}, {**body, "is_active": False}):
        assert iam.client.patch(route, headers=headers, json=invalid).status_code == 422
    for _ in range(2):
        result = iam.client.patch(route, headers=headers, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["display_name"] == body["display_name"]
    assert iam.client.get("/api/v1/auth/me", headers=headers).json()["display_name"] == body["display_name"]
    stale = iam.client.patch(route, headers=headers, json={**body, "display_name": "Tên khác"})
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_VERSION"
    with iam.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='iam.profile.updated' AND actor_id=:id"), {"id": user}).scalar_one() == 1
        assert c.execute(text("SELECT display_name FROM wms.app_user WHERE id=:id"), {"id": other}).scalar_one() == "other"
    plain = iam.headers(iam.login("other"))
    assert iam.client.patch(route, headers=plain, json={"display_name": "Other", "expected_display_name": "other"}).status_code == 403
    iam.client.post("/api/v1/auth/logout", headers=headers)
    assert iam.client.patch(route, headers=headers, json=body).status_code == 401


def test_concurrent_profile_updates_do_not_overwrite(iam):
    _, secret = iam.user("concurrent", mfa=True)
    token = iam.login("concurrent", secret)["access_token"]
    def update(name):
        try:
            return iam.service.update_profile(token, ProfileUpdate(display_name=name, expected_display_name="concurrent"), uuid4())
        except DomainError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(update, ["Tên một", "Tên hai"]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert "STALE_VERSION" in results
