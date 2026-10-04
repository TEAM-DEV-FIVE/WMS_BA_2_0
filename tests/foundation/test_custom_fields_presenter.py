from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.desktop.api.client import ApiError
from apps.desktop.presenters.custom_fields import CustomFieldPresenter, run_request


@pytest.mark.parametrize("wrong", ["id", "version", "revision_id"])
def test_custom_ack_requires_exact_object_revision_and_version(wrong):
    target, revision = str(uuid4()), str(uuid4())
    data = dict(id=target, version=2, revision_id=revision, request_id=str(uuid4()))
    data[wrong] = 9 if wrong == "version" else str(uuid4())
    class Api:
        session_generation = 1
        def in_session(self, generation, action):
            return action()
        def me(self):
            return SimpleNamespace(global_permissions=[])
        def command(self, *args):
            return data
    result = run_request(Api(), 1, Event(), "PUT", "custom-fields/documents/"+target,
                         dict(expected_version=1, revision_id=revision), uuid4(), str(uuid4()))
    assert result[2][0] == "INVALID_RESPONSE"


def test_uncertain_metadata_command_is_copied_and_partitioned_by_user_scope():
    class View:
        def workflow_clear(self):
            pass
        def workflow_error(self, message):
            self.error = message
    class Presenter(CustomFieldPresenter):
        def submit(self, *args, **kwargs):
            return True
    view = View()
    presenter = Presenter(view, SimpleNamespace(session_generation=1))
    try:
        presenter.reset("user-a", "warehouse-a")
        payload = {"values": {"note": "original"}}
        assert presenter.command("PUT", "custom-fields/documents/target", payload)
        command = presenter.uncertain
        payload["values"]["note"] = "mutated"
        assert command[2]["values"]["note"] == "original"
        assert not presenter.command("PUT", "different", payload)
        presenter.reset("user-b", "warehouse-a")
        assert presenter.uncertain is None
        presenter.reset("user-a", "warehouse-a")
        assert presenter.uncertain == command
        presenter.reset("admin")
        assert presenter.scope == ("admin", "global")
    finally:
        presenter.close()
        presenter.finish()


def test_worker_permission_failure_does_not_issue_write():
    class Api:
        session_generation = 1
        def in_session(self, generation, action):
            return action()
        def me(self):
            raise ApiError("UNAUTHENTICATED", "Expired")
        def command(self, *args):
            raise AssertionError("No write without current session")
    result = run_request(Api(), 1, Event(), "PUT", "custom-fields/schemas/PO", {}, uuid4(), "global")
    assert result[2][0] == "UNAUTHENTICATED"
