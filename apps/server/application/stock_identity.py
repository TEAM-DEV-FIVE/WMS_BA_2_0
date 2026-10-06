from uuid import uuid4

from sqlalchemy import text

from apps.server.application.master_data import active_reference, invalid, one


def validate_ownership(connection, *, owner_id, warehouse_id, business_date, consignment_id=None):
    """Validate current owner/agreement without creating an inventory identity."""
    owner = active_reference(connection, "stock_owner", owner_id, "owner_id")
    if owner["kind"] == "UNCLASSIFIED":
        invalid("owner_id", "Dữ liệu cũ chưa phân loại; cần đối soát chủ sở hữu.", "OWNERSHIP_UNRESOLVED")
    if (owner["kind"] == "CONSIGNOR") != (consignment_id is not None):
        invalid("consignment_id", "Hàng ký gửi cần hợp đồng; hàng doanh nghiệp không gắn hợp đồng ký gửi.")
    if consignment_id:
        agreement = active_reference(connection, "consignment_agreement", consignment_id, "consignment_id")
        active_reference(connection, "partner", owner["partner_id"], "owner_id")
        if (
            agreement["owner_id"] != owner_id
            or agreement["warehouse_id"] != warehouse_id
            or not agreement["valid_from"] <= business_date <= agreement["valid_until"]
        ):
            invalid("consignment_id", "Hợp đồng không đúng chủ hàng/kho/ngày hiệu lực.", "INVALID_AGREEMENT")
    return owner


def resolve_stock_identity(
    connection,
    *,
    product_id,
    owner_id,
    warehouse_id,
    business_date,
    lot_id=None,
    serial_id=None,
    consignment_id=None,
):
    """Transaction primitive; caller authorizes and locks documents/locations. Owner is permanent."""
    product = active_reference(connection, "product", product_id, "product_id")
    validate_ownership(
        connection,
        owner_id=owner_id,
        warehouse_id=warehouse_id,
        business_date=business_date,
        consignment_id=consignment_id,
    )
    tracking = product["tracking"]
    if (
        (tracking == "NONE" and (lot_id or serial_id))
        or (tracking == "LOT" and (lot_id is None or serial_id is not None))
        or (tracking == "SERIAL" and (serial_id is None or lot_id is not None))
    ):
        invalid("product_id", "Danh tính lô/serial không đúng tracking SKU.", "TRACKING_MISMATCH")
    for table, value in [("lot", lot_id), ("serial", serial_id)]:
        if value:
            related = one(connection, f"SELECT product_id FROM wms.{table} WHERE id=:id FOR UPDATE", id=value)
            if not related or related["product_id"] != product_id:
                invalid(table + "_id", "Lô/serial không thuộc SKU.", "TRACKING_MISMATCH")
    params = {
        "id": uuid4(),
        "product": product_id,
        "lot": lot_id,
        "serial": serial_id,
        "owner": owner_id,
        "agreement": consignment_id,
    }
    connection.execute(
        text("""INSERT INTO wms.stock_item(id,product_id,lot_id,serial_id,owner_id,consignment_id)
        VALUES (:id,:product,:lot,:serial,:owner,:agreement) ON CONFLICT DO NOTHING"""),
        params,
    )
    return connection.execute(
        text("""SELECT id FROM wms.stock_item WHERE product_id=:product AND owner_id=:owner
        AND lot_id IS NOT DISTINCT FROM CAST(:lot AS uuid) AND serial_id IS NOT DISTINCT FROM CAST(:serial AS uuid)
        AND consignment_id IS NOT DISTINCT FROM CAST(:agreement AS uuid) FOR UPDATE"""),
        params,
    ).scalar_one()


def is_consignment_receipt(c, doc_id):
    return bool(one(c, "SELECT document_id FROM wms.consignment_receipt WHERE document_id=:id", id=doc_id))


def ownership_snapshot(c, lines):
    """Business evidence copied into approval, never recomputed as historical truth."""
    ids = sorted({r["consignment_id"] for r in lines if r["consignment_id"]})
    if not ids:
        return {}
    agreements = [one(c, "SELECT * FROM wms.consignment_agreement WHERE id=:id", id=value) for value in ids]
    owners = [
        one(c, "SELECT * FROM wms.stock_owner WHERE id=:id", id=value)
        for value in sorted({r["owner_id"] for r in lines})
    ]
    return {"ownership": {"owners": owners, "agreements": agreements}}
