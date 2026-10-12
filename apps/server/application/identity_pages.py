"""Paginated projections of the existing global IAM lists, without secret columns."""
from uuid import UUID

from sqlalchemy import text

from apps.server.application.pagination import counted_rows
from apps.server.domain.errors import DomainError

QUERIES = {
    'users': ('iam.manage', 'username', 'SELECT id,username,display_name,is_active FROM wms.app_user\n            WHERE (CAST(:after AS text) IS NULL OR username>:after) ORDER BY username LIMIT :limit'),
    'roles': ('role.manage', 'code', 'SELECT code,name FROM wms.role WHERE is_active AND (CAST(:after AS text) IS NULL OR code>:after) ORDER BY code LIMIT :limit'),
    'grants': ('role.manage', 'id', 'SELECT g.id,g.user_id,r.code AS role_code,g.scope_kind,g.warehouse_id,\n            g.valid_from,g.valid_until,g.revoked_at FROM wms.user_role_grant g JOIN wms.role r ON r.id=g.role_id\n            WHERE CAST(:after AS uuid) IS NULL OR g.id>CAST(:after AS uuid) ORDER BY g.id LIMIT :limit'),
    'grant-requests': ('role.manage', 'id', 'SELECT q.id,q.user_id,r.code AS role_code,q.scope_kind,q.warehouse_id,\n            q.valid_until,q.reason,q.requested_by,q.requested_at FROM wms.grant_request q JOIN wms.role r ON r.id=q.role_id\n            WHERE q.grant_id IS NULL AND (CAST(:after AS uuid) IS NULL OR q.id>CAST(:after AS uuid))\n            ORDER BY q.id LIMIT :limit'),
    'lookup-users': ('role.manage', 'username', 'SELECT id,username,display_name,is_active FROM wms.app_user\n            WHERE is_active AND (CAST(:after AS text) IS NULL OR username>:after) AND (strpos(lower(username),lower(:q))>0 OR strpos(lower(display_name),lower(:q))>0)\n            ORDER BY username LIMIT :limit'),
    'lookup-warehouses': ('role.manage', 'code', 'SELECT id,code,name FROM wms.warehouse\n            WHERE is_active AND (CAST(:after AS text) IS NULL OR code>:after) AND (strpos(lower(code),lower(:q))>0 OR strpos(lower(name),lower(:q))>0)\n            ORDER BY code LIMIT :limit'),
    'sessions': ('iam.manage', 'id', 'SELECT s.id,s.user_id,u.username,s.device_id,\n            (SELECT min(t.created_at) FROM wms.auth_token t WHERE t.session_id=s.id) AS created_at,\n            s.expires_at,s.revoked_at,s.mfa_verified_at,\n            (u.is_active AND u.auth_version=s.auth_version AND s.revoked_at IS NULL AND s.expires_at>:now) AS is_active\n            FROM wms.auth_session s JOIN wms.app_user u ON u.id=s.user_id\n            WHERE (CAST(:user AS uuid) IS NULL OR s.user_id=:user)\n              AND (CAST(:after AS uuid) IS NULL OR s.id>:after)\n            ORDER BY s.id LIMIT :limit'),
    'events': ('audit.security.read', 'id', "SELECT e.id,e.actor_id,u.username AS actor_name,\n            e.action,e.entity_id,e.occurred_at,e.request_id,e.reason\n            FROM wms.audit_event e LEFT JOIN wms.app_user u ON u.id=e.actor_id\n            WHERE e.entity_type='identity' AND (CAST(:after AS uuid) IS NULL OR e.id>:after)\n            ORDER BY e.id LIMIT :limit"),
}


def identity_page(auth, resource, after, query, limit, now):
    resource = "users" if resource == "password-resets" else resource
    if resource not in QUERIES:
        raise DomainError("NOT_FOUND", "Không tìm thấy danh sách")
    permission, cursor, sql = QUERIES[resource]
    auth.require(permission)
    if auth.principal.mfa_verified_at is None:
        raise DomainError("MFA_REQUIRED", "Cần xác thực MFA để quản trị")
    if after and cursor == "id":
        try:
            after = UUID(after)
        except ValueError:
            raise DomainError("INVALID_FILTER", "Con trỏ trang không hợp lệ") from None
    rows, total = counted_rows(auth.connection, text(sql),
                              dict(after=after, q=query, user=None, now=now, limit=limit + 1))
    return dict(items=[dict(row) for row in rows[:limit]], total=total,
                next_after=str(rows[limit - 1][cursor]) if len(rows) > limit else None)
