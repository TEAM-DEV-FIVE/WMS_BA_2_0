"""Small read-only adapter over existing orders/approval storage. No new write policy."""

from sqlalchemy import text

from apps.server.domain.errors import DomainError
from packages.contracts.document_reviews import AssignmentCandidate, DocumentReview


def public_snapshot(snapshot):
    if snapshot is None:
        # Revision 008 deliberately preserves legacy requests without inventing a snapshot.
        return None
    # Explicit allowlists: old snapshots may contain prices and arbitrary attributes.
    header = snapshot.get("header", {})
    result = {
        "header": {k: header.get(k) for k in ("kind", "warehouse_id", "partner_id", "business_date")},
        "assigned_user_ids": sorted(snapshot.get("assigned_user_ids", [])),
        "lines": [],
    }
    plan = header.get("attributes", {}).get("receipt_plan", {})
    if header.get("kind") == "RECEIPT":
        result["source_order_id"] = plan.get("source_order_id")
    for line in snapshot.get("lines", []):
        projected = {k: line.get(k) for k in (
            "line_no", "product_id", "uom_id", "quantity", "factor_snapshot", "base_quantity",
            "owner_id", "consignment_id", "source_line_id", "closed_base_quantity",
        )}
        if header.get("kind") == "RECEIPT":
            spec = plan.get("lines", {}).get(str(line["id"]), {})
            projected["receipt_plan"] = {k: spec.get(k) for k in (
                "destination_location_id", "lot_code", "serial_code", "manufactured_on", "expires_on",
            )}
        result["lines"].append(projected)
    return result


class DocumentReviewService:
    def __init__(self, orders):
        self.orders = orders

    def document(self, auth, document_id):
        doc = self.orders.document(auth, document_id)
        if doc["kind"] not in {"PO", "SO", "RECEIPT"}:
            raise DomainError("NOT_FOUND", "Màn hình này chỉ hỗ trợ PO/SO/phiếu nhận.")
        if doc["kind"] == "RECEIPT":
            self.orders.receipts.source(auth, doc)
        return doc

    def review(self, auth, document_id):
        # Hold a shared document lock for a consistent current version/content projection.
        self.document(auth, document_id)
        auth.connection.execute(text("SELECT id FROM wms.document WHERE id=:id FOR SHARE"), {"id": document_id})
        doc = self.document(auth, document_id)
        snapshots = auth.connection.execute(text("""SELECT id,document_version,status,created_at,content_snapshot
            FROM wms.approval_request WHERE document_id=:id ORDER BY document_version"""),
            {"id": document_id}).mappings()
        return DocumentReview(
            document_id=document_id, current_version=doc["version"],
            current=public_snapshot(self.orders.snapshot(auth.connection, doc)),
            snapshots=[{**{k: row[k] for k in ("id", "document_version", "status", "created_at")},
                        "content": public_snapshot(row["content_snapshot"])} for row in snapshots],
        )

    def candidates(self, auth, document_id, query="", after=None, limit=25):
        doc = self.document(auth, document_id)
        auth.require("document.assign", doc["warehouse_id"])
        rows = list(auth.connection.execute(text("""SELECT u.id,u.username,u.display_name FROM wms.app_user u
            WHERE u.is_active AND (CAST(:after AS uuid) IS NULL OR u.id>:after)
            AND (strpos(lower(u.username),lower(:query))>0 OR strpos(lower(u.display_name),lower(:query))>0)
            AND EXISTS(SELECT 1 FROM wms.user_role_grant g
                JOIN wms.role r ON r.id=g.role_id AND r.is_active
                JOIN wms.role_permission rp ON rp.role_id=r.id
                JOIN wms.permission p ON p.id=rp.permission_id AND p.code='document.read' AND p.scope_kind='WAREHOUSE'
                WHERE g.user_id=u.id AND g.revoked_at IS NULL AND g.valid_from<=:now
                  AND (g.valid_until IS NULL OR g.valid_until>:now)
                  AND (g.scope_kind='ALL_WAREHOUSES' OR (g.scope_kind='WAREHOUSE' AND g.warehouse_id=:warehouse)))
            ORDER BY u.id LIMIT :limit"""),
            {"query": query, "after": after, "now": auth.now, "warehouse": doc["warehouse_id"], "limit": limit + 1}
        ).mappings())
        items = [AssignmentCandidate(**row) for row in rows[:limit]]
        return {"items": items, "next_after": items[-1].id if len(rows) > limit else None}
