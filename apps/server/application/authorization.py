from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, text

from apps.server.domain.errors import DomainError


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    session_id: UUID
    username: str
    display_name: str
    mfa_verified_at: datetime | None


class Authorization:
    """Each row is a permission AND its own grant scope. No cross product of grants."""

    def __init__(self, connection: Connection, principal: Principal, now: datetime):
        self.connection = connection
        self.principal = principal
        self.now = now

    def grants(self, permission: str, warehouse_id: UUID | None = None) -> list[dict]:
        return list(self.connection.execute(text("""
            SELECT r.code AS role_code, g.id FROM wms.user_role_grant g
            JOIN wms.role r ON r.id=g.role_id AND r.is_active
            JOIN wms.role_permission rp ON rp.role_id=r.id
            JOIN wms.permission p ON p.id=rp.permission_id
            WHERE g.user_id=:user AND g.revoked_at IS NULL AND g.valid_from<=:now
              AND (g.valid_until IS NULL OR g.valid_until>:now) AND p.code=:permission
              AND ((p.scope_kind='GLOBAL' AND g.scope_kind='GLOBAL' AND CAST(:warehouse AS uuid) IS NULL)
                OR (p.scope_kind='WAREHOUSE' AND CAST(:warehouse AS uuid) IS NOT NULL
                    AND (g.scope_kind='ALL_WAREHOUSES' OR
                        (g.scope_kind='WAREHOUSE' AND g.warehouse_id=CAST(:warehouse AS uuid)))))
        """), {"user": self.principal.user_id, "now": self.now,
               "permission": permission, "warehouse": warehouse_id}).mappings())

    def allows(self, permission: str, warehouse_id: UUID | None = None) -> bool:
        return bool(self.grants(permission, warehouse_id))

    def require(self, permission: str, warehouse_id: UUID | None = None, *, hidden: bool = False) -> None:
        if not self.allows(permission, warehouse_id):
            raise DomainError("NOT_FOUND" if hidden else "FORBIDDEN", "Không có quyền truy cập tài nguyên.")
        if permission in {"iam.manage", "role.manage", "config.manage", "period.reopen", "backup.operate"}:
            if self.principal.mfa_verified_at is None:
                raise DomainError("MFA_REQUIRED", "Cần xác thực MFA để thực hiện thao tác này.")

    def global_permissions(self) -> list[str]:
        codes = self.connection.execute(text("SELECT code FROM wms.permission WHERE scope_kind='GLOBAL' ORDER BY code")).scalars()
        return [code for code in codes if self.allows(code)]

    def document(self, document_id: UUID) -> dict:
        row = self.connection.execute(text("SELECT * FROM wms.document WHERE id=:id"), {"id": document_id}).mappings().one_or_none()
        if row is None:
            raise DomainError("NOT_FOUND", "Không tìm thấy chứng từ.")
        grants = self.grants("document.read", row["warehouse_id"])
        broad = any(grant["role_code"] not in {"RECEIVER", "PICKER"} for grant in grants)
        owned = row["created_by"] == self.principal.user_id
        assigned = self.connection.execute(text("""
            SELECT EXISTS(SELECT 1 FROM wms.document_assignment WHERE document_id=:doc AND user_id=:user)
        """), {"doc": document_id, "user": self.principal.user_id}).scalar_one()
        if not grants or not (broad or owned or assigned):
            raise DomainError("NOT_FOUND", "Không tìm thấy chứng từ.")
        # Until transfer DTO field filtering is implemented, require visibility in both warehouses.
        if row["destination_warehouse_id"]:
            self.require("document.read", row["destination_warehouse_id"], hidden=True)
        return dict(row)

    def require_approval(self, document: dict, *, requester_id: UUID | None = None,
                         previous_approvers: tuple[UUID, ...] = (), counters: tuple[UUID, ...] = ()) -> None:
        permission = {"OPENING": "opening.approve", "ADJUSTMENT": "adjustment.approve"}.get(document["kind"], "document.approve")
        self.require(permission, document["warehouse_id"])
        if self.principal.user_id in {document["created_by"], requester_id, *previous_approvers, *counters}:
            raise DomainError("SELF_APPROVAL", "Người lập/gửi/đếm hoặc đã duyệt bước trước không được duyệt.")
        if document["destination_warehouse_id"]:
            self.require(permission, document["destination_warehouse_id"])
