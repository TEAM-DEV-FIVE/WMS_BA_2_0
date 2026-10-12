import csv

import pytest
from sqlalchemy import text

from scripts.import_warehouse_source import import_orders, prepare, read_source, verify_archive


def fixture_source(folder):
    def write(name, fields, rows, delimiter=","):
        with (folder / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=delimiter)
            w.writeheader()
            w.writerows(rows)

    refs = [f"REF{i:03d}" for i in range(208)]
    write(
        "Product.csv",
        ["Reference", "ABCCOD", "Sector"],
        [dict(Reference=r, ABCCOD="A", Sector="PF") for r in refs],
        ";",
    )
    write(
        "Storage_Location.csv",
        ["originalLocation", "position", "x", "y", "z"],
        [dict(originalLocation="A-01-01", position="1, 2, 3", x="1", y="2", z="3")],
    )
    write(
        "Random_Storage.csv",
        ["originalLocation"] + [f"col_{i}" for i in range(208)],
        [dict(originalLocation="A-01-01", **{f"col_{i}": r + ";300.0" for i, r in enumerate(refs)})],
    )
    fields = [
        "codCustomer",
        "orderNumber",
        "orderToCollect",
        "Reference",
        "Size (US)",
        "quantity (units)",
        "creationDate",
        "waveNumber",
        "operator",
    ]
    write(
        "Customer_Order.csv",
        fields,
        [
            dict(
                zip(
                    fields, ["C1", "123", "1", refs[0], "105", "4", "19/10/2023 07:18", "43175", "Operator_1"]
                )
            ),
            dict(
                zip(fields, ["C1", "123", "2", refs[0], "9", "2", "19/10/2023 07:18", "43175", "Operator_1"])
            ),
            dict(
                zip(fields, ["C2", "124", "1", refs[1], "9", "0", "19/10/2023 07:18", "43176", "Operator_2"])
            ),
        ],
        ";",
    )


def test_source_checks_reject_bad_checksum_and_unknown_reference(tmp_path):
    fixture_source(tmp_path)
    assert len(read_source(tmp_path)[0]) == 208
    with pytest.raises(ValueError, match="checksum"):
        verify_archive(tmp_path / "Product.csv")
    p = tmp_path / "Customer_Order.csv"
    p.write_text(p.read_text().replace("REF000", "UNKNOWN"))
    with pytest.raises(ValueError, match="Unknown"):
        read_source(tmp_path)


@pytest.mark.integration
def test_dataset_import_and_operations_preserve_source_quantities(iam, tmp_path):
    ident, _ = iam.user("kien", mfa=True)
    iam.grant(ident, "SYSADMIN")
    iam.grant(ident, "MASTER_DATA")
    fixture_source(tmp_path)
    manifest = prepare(iam.engine, iam.service.settings, tmp_path)
    mapping = import_orders(iam.engine, iam.service.settings, tmp_path, manifest)
    assert mapping[0]["units"] == 6
    assert mapping[1]["status"] == "ZERO_QUANTITY"
    with iam.engine.connect() as c:
        assert (
            c.execute(
                text("SELECT sum(base_quantity) FROM wms.document_line WHERE document_id=:id"),
                {"id": mapping[0]["id"]},
            ).scalar_one()
            == 6
        )
        assert c.execute(text("SELECT count(*) FROM wms.product WHERE sku LIKE 'DEMO-%'")).scalar_one() == 0
        assert (
            c.execute(text("SELECT count(*) FROM wms.count_session WHERE status='POSTED'")).scalar_one() == 3
        )
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.app_user WHERE username LIKE 'training_%' AND is_active")
            ).scalar_one()
            == 0
        )
    with pytest.raises(ValueError, match="already exist"):
        import_orders(iam.engine, iam.service.settings, tmp_path, manifest)
    with pytest.raises(ValueError, match="replace"):
        prepare(iam.engine, iam.service.settings, tmp_path)
