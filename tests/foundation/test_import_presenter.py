import csv
import io
import threading
from uuid import uuid4

import pytest
from test_imports_parser import workbook

from apps.desktop.api.client import ApiError
from apps.desktop.api.imports import check_source, save_bytes, source_file
from apps.desktop.presenters.imports import ImportPresenter


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_import_preflight_opening_limit_before_upload_and_exact_hash(tmp_path, extension):
    rows = [["sku", "quantity_base"], *[["SKU", "1"] for _ in range(201)]]
    out = io.StringIO(newline="")
    csv.writer(out).writerows(rows)
    path = tmp_path / ("tồn đầu kỳ." + extension)
    path.write_bytes(out.getvalue().encode("utf-8-sig") if extension == "csv" else workbook(rows, kind="11_opening"))
    with pytest.raises(ApiError, match="200") as error:
        source_file(path, "11_opening", 5 * 1024 * 1024, 200)
    assert error.value.code == "ROW_LIMIT"
    source = source_file(path, "11_opening", 5 * 1024 * 1024, 500)
    assert source.row_count == 201 and len(source.sha256) == 64
    check_source(source)
    path.write_bytes(b"changed")
    with pytest.raises(ApiError) as error:
        check_source(source)
    assert error.value.code == "SOURCE_CHANGED"


def test_import_download_stale_does_not_overwrite_or_leave_temporary(tmp_path):
    path = tmp_path / "lỗi.csv"
    path.write_bytes(b"keep")
    with pytest.raises(ApiError) as error:
        save_bytes(path, b"sensitive", lambda: False)
    assert error.value.code == "STALE_SESSION"
    assert path.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [path]


def test_import_preflight_ignores_formatted_blank_xlsx_rows(tmp_path):
    path = tmp_path / "blank.xlsx"
    path.write_bytes(workbook([["code", "name", "decimal_places"], ["U", "Unit", 0],
                               *[["", " ", ""] for _ in range(250)]], kind="01_uom"))
    assert source_file(path, "01_uom", 5 * 1024 * 1024, 200).row_count == 1


def test_import_presenter_old_scope_and_session_results_never_reach_tk():
    main = threading.get_ident()
    started, release = threading.Event(), threading.Event()

    class Api:
        session_generation = 1

        def in_session(self, generation, fn):
            assert threading.get_ident() != main
            return fn()

    class View:
        def __init__(self):
            self.received = []

        def import_clear(self):
            assert threading.get_ident() == main

        def import_busy(self):
            assert threading.get_ident() == main

        def import_downloaded(self, value):
            assert threading.get_ident() == main
            self.received.append(value)

        def import_error(self, error):
            assert threading.get_ident() == main
            self.received.append(error)

    view, api = View(), Api()
    presenter = ImportPresenter(view, api)

    def slow():
        started.set()
        assert release.wait(5)
        return "old warehouse data"

    try:
        presenter.reset(uuid4(), "11_opening", uuid4())
        presenter.submit("download", slow)
        pending = presenter.pending
        assert started.wait(5)
        presenter.reset(uuid4(), "11_opening", uuid4())
        release.set()
        pending.result(5)
        presenter.drain()
        assert view.received == []
        presenter.submit("download", lambda: "old session data")
        presenter.pending.result(5)
        api.session_generation += 1
        presenter.drain()
        assert "old session data" not in view.received and "Phiên đã đổi" in view.received[-1]
    finally:
        release.set()
        presenter.close()
        presenter.finish()
