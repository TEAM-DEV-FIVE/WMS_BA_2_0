import csv
import io
import zipfile
from xml.etree import ElementTree

import pytest

from apps.server.application.export_files import render
from apps.server.domain.errors import DomainError
from packages.contracts.reports import ReportCriteria


def test_reports_exports_formula_injection_exact_decimal_unicode_and_determinism():
    values = [
        '=HYPERLINK("https://example.test")',
        " +1",
        "-2",
        "@SUM(A1)",
        "\t=1",
        "\r=1",
        "\n=1",
        "\ufeff=1",
        "\u2003=1",
        "99999999999999.123456",
        "Tiếng Việt & <ghi chú>",
        "một\nhai",
        None,
    ]
    snapshot = dict(
        id="fixture",
        created_at="2026-10-02",
        criteria={"include_price": False},
        sha256="abc",
        columns=["value"],
    )
    rows = [dict(value=v) for v in values]
    csv_data = render(snapshot, rows, "csv")
    parsed = list(csv.reader(io.StringIO(csv_data.decode("utf-8-sig"))))
    assert all(row[-1].startswith("'") for row in parsed[1:10])
    assert parsed[10][-1] == values[9] and parsed[11][-1] == values[10]
    xlsx = render(snapshot, rows, "xlsx")
    assert xlsx == render(snapshot, rows, "xlsx")
    with zipfile.ZipFile(io.BytesIO(xlsx)) as archive:
        assert len(archive.namelist()) == 5
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert not sheet.findall(".//{*}f")
        assert all(c.attrib["t"] == "inlineStr" for c in sheet.findall(".//{*}c"))
        assert values[9] in list(sheet.itertext())
    with pytest.raises(DomainError, match="hạn mức"):
        render(snapshot, rows, "csv", max_bytes=50)
    with pytest.raises(DomainError, match="32.767"):
        render(snapshot, [dict(value="a" * 32768)], "xlsx")


def test_reports_filters_reject_timezone_less_reversed_and_duplicate_locations():
    from uuid import uuid4

    warehouse, location = uuid4(), uuid4()
    for fields in [
        dict(posted_from="2026-10-02T12:00:00"),
        dict(business_from="2026-10-03", business_to="2026-10-02"),
        dict(location_ids=[location, location]),
    ]:
        with pytest.raises(ValueError):
            ReportCriteria(warehouse_id=warehouse, **fields)


def test_reports_presenter_read_error_does_not_discard_uncertain_command():
    from concurrent.futures import Future
    from types import SimpleNamespace

    from apps.desktop.api.client import ApiError
    from apps.desktop.presenters.reports import ReportPresenter

    errors = []
    view = SimpleNamespace(report_clear=lambda: None, report_error=errors.append)
    presenter = ReportPresenter(view, SimpleNamespace(session_generation=0))
    try:
        presenter.user_id, presenter.warehouse = "actor", "warehouse"
        command = ("exports", "{}", "same-key", "job")
        presenter.commands[presenter.scope] = command
        future = Future()
        future.set_exception(ApiError("FILE_HASH_MISMATCH", "Download failed"))
        presenter.results.put((0, 0, "download", future))
        presenter.drain()
        assert presenter.uncertain == command and errors
        presenter.snapshot = {"id": "snapshot"}
        presenter.pending = Future()
        presenter.export("xlsx")
        assert presenter.uncertain == command
    finally:
        presenter.close()
        presenter.finish()


def test_reports_presenter_session_generation_change_clears_visible_data():
    from concurrent.futures import Future
    from types import SimpleNamespace

    from apps.desktop.presenters.reports import ReportPresenter

    cleared = []
    presenter = ReportPresenter(SimpleNamespace(report_clear=lambda: cleared.append(True)),
                                SimpleNamespace(session_generation=2))
    try:
        presenter.snapshot, presenter.job = {"id": "old"}, {"id": "old-job"}
        future = Future()
        future.set_result({})
        presenter.pending = future
        presenter.results.put((0, 1, "page", future))
        presenter.drain()
        assert presenter.snapshot is None and presenter.job is None and presenter.pending is None
        assert cleared
    finally:
        presenter.close()
        presenter.finish()
