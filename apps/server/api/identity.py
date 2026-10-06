from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

from apps.server.api.dependencies import identity_dependencies
from apps.server.application.identity import IdentityService, audit, row
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.credentials import hash_password
from packages.contracts import Error
from packages.contracts.identity import (
    CurrentUser,
    Enrollment,
    EnrollmentConfirmation,
    GrantCreate,
    IdentityEvent,
    LoginInput,
    MfaChallenge,
    MfaInput,
    PasswordChange,
    PasswordConfirmation,
    PasswordResetComplete,
    PasswordResetIssue,
    PasswordResetToken,
    Reauthentication,
    RecoveryCodes,
    RecoveryInput,
    RefreshInput,
    RevokeInput,
    SessionSummary,
    SessionTokens,
    UserActivation,
    UserCreate,
    UserSummary,
    WarehouseSummary,
)


def identity_router(service: IdentityService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["identity"],
                       responses={code: {"model": Error} for code in (401, 403, 404, 409, 422, 429, 503)})
    token, authorization = identity_dependencies(service)

    @router.post("/auth/login", response_model=SessionTokens | MfaChallenge)
    def login(payload: LoginInput, request: Request):
        return service.login(payload.username, payload.password.get_secret_value(), payload.device_id, request.state.request_id)

    @router.post("/auth/mfa", response_model=SessionTokens)
    def mfa(payload: MfaInput, request: Request):
        return service.complete_mfa(payload.challenge_token.get_secret_value(), payload.code.get_secret_value(), request.state.request_id)

    @router.post("/auth/refresh", response_model=SessionTokens)
    def refresh(payload: RefreshInput, request: Request):
        return service.refresh(payload.refresh_token.get_secret_value(), payload.device_id, request.state.request_id)

    @router.post("/auth/logout")
    def logout(request: Request, access: Annotated[str, Depends(token)]):
        service.logout(access, request.state.request_id)
        return {"status": "SIGNED_OUT"}

    @router.get("/auth/me", response_model=CurrentUser)
    def me(auth=Depends(authorization)):
        actor = auth.principal
        return CurrentUser(id=actor.user_id, username=actor.username, display_name=actor.display_name,
                           is_active=True, mfa_verified=actor.mfa_verified_at is not None,
                           global_permissions=auth.global_permissions())

    @router.post("/auth/mfa/enroll", response_model=Enrollment)
    def enroll(payload: PasswordConfirmation, request: Request, access: Annotated[str, Depends(token)]):
        return service.enroll(access, payload.password.get_secret_value(), request.state.request_id)

    @router.post("/auth/mfa/confirm")
    def confirm(payload: EnrollmentConfirmation, request: Request, access: Annotated[str, Depends(token)]):
        service.confirm_enrollment(access, payload.factor_id, payload.code.get_secret_value(), request.state.request_id)
        return {"status": "MFA_ENABLED"}

    @router.get("/warehouses", response_model=list[WarehouseSummary])
    def warehouses(auth=Depends(authorization)):
        candidates = auth.connection.execute(text("SELECT id,code,name FROM wms.warehouse WHERE is_active ORDER BY code,id")).mappings()
        return [dict(warehouse) for warehouse in candidates
                if auth.allows("stock.read", warehouse["id"]) or auth.allows("document.read", warehouse["id"])]

    @router.get("/warehouses/{warehouse_id}/permissions", response_model=list[str])
    def warehouse_permissions(warehouse_id: UUID, auth=Depends(authorization)):
        warehouse = row(auth.connection, "SELECT id FROM wms.warehouse WHERE id=:id AND is_active", id=warehouse_id)
        if not warehouse or not (auth.allows("stock.read", warehouse_id) or auth.allows("document.read", warehouse_id)):
            raise DomainError("NOT_FOUND", "Không tìm thấy kho.")
        codes = auth.connection.execute(text("SELECT code FROM wms.permission WHERE scope_kind='WAREHOUSE' ORDER BY code")).scalars()
        return [code for code in codes if auth.allows(code, warehouse_id)]

    @router.get("/documents/{document_id}")
    def document(document_id: UUID, auth=Depends(authorization)):
        document = auth.document(document_id)
        result = {key: document[key] for key in ["id", "number", "kind", "status", "warehouse_id", "version"]}
        has_price = auth.allows("price.read", document["warehouse_id"])
        lines = auth.connection.execute(text("""SELECT id,line_no,product_id,quantity,base_quantity,reference_unit_price
            FROM wms.document_line WHERE document_id=:id ORDER BY line_no,id"""), {"id": document_id}).mappings()
        result["lines"] = []
        for line in lines:
            value = {key: line[key] for key in ["id", "line_no", "product_id"]}
            value.update(quantity=str(line["quantity"]), base_quantity=str(line["base_quantity"]))
            if has_price:
                value["reference_unit_price"] = str(line["reference_unit_price"]) if line["reference_unit_price"] is not None else None
            result["lines"].append(value)
        return result

    @router.get("/users", response_model=list[UserSummary])
    def users(auth=Depends(authorization), limit: int = Query(default=100, ge=1, le=200), after: str = ""):
        auth.require("iam.manage")
        return auth.connection.execute(text("""SELECT id,username,display_name,is_active FROM wms.app_user
            WHERE username>:after ORDER BY username LIMIT :limit"""), {"after": after, "limit": limit}).mappings().all()

    @router.post("/users", response_model=UserSummary, status_code=201)
    def create_user(payload: UserCreate, request: Request, auth=Depends(authorization)):
        auth.require("iam.manage")
        user_id = uuid4()
        if row(auth.connection, "SELECT id FROM wms.app_user WHERE username=:name", name=payload.username):
            raise DomainError("USER_EXISTS", "Tên tài khoản đã tồn tại.")
        auth.connection.execute(text("""INSERT INTO wms.app_user(id,username,display_name,password_hash,is_active,auth_version,created_at)
            VALUES (:id,:name,:display,:password,true,0,:now)"""),
                                {"id": user_id, "name": payload.username, "display": payload.display_name,
                                 "password": hash_password(payload.password.get_secret_value()), "now": service.clock()})
        audit(auth.connection, auth.principal.user_id, "iam.user.created", user_id, request.state.request_id, service.clock())
        return UserSummary(id=user_id, username=payload.username, display_name=payload.display_name, is_active=True)

    @router.patch("/users/{user_id}/active", response_model=UserSummary)
    def set_active(user_id: UUID, payload: UserActivation, request: Request, auth=Depends(authorization)):
        auth.require("iam.manage")
        if user_id == auth.principal.user_id:
            raise DomainError("SELF_MODIFICATION", "Không thay đổi trạng thái tài khoản đang đăng nhập.")
        user = row(auth.connection, """UPDATE wms.app_user SET is_active=:active,auth_version=auth_version+1 WHERE id=:id
            RETURNING id,username,display_name,is_active""", id=user_id, active=payload.is_active)
        if not user:
            raise DomainError("NOT_FOUND", "Không tìm thấy tài khoản.")
        audit(auth.connection, auth.principal.user_id, "iam.user.activation_changed", user_id, request.state.request_id, service.clock(), payload.reason)
        return dict(user)

    @router.post("/users/{user_id}/revoke-sessions")
    def revoke_sessions(user_id: UUID, payload: RevokeInput, request: Request, auth=Depends(authorization)):
        auth.require("iam.manage")
        user = row(auth.connection, "UPDATE wms.app_user SET auth_version=auth_version+1 WHERE id=:id RETURNING id", id=user_id)
        if not user:
            raise DomainError("NOT_FOUND", "Không tìm thấy tài khoản.")
        audit(auth.connection, auth.principal.user_id, "iam.sessions.revoked", user_id, request.state.request_id, service.clock(), payload.reason)
        return {"status": "REVOKED"}

    @router.get("/roles")
    def roles(auth=Depends(authorization)):
        auth.require("role.manage")
        return auth.connection.execute(text("SELECT code,name FROM wms.role WHERE is_active ORDER BY code")).mappings().all()

    @router.get("/grants")
    def grants(auth=Depends(authorization), limit: int = Query(default=100, ge=1, le=200), after: UUID | None = None):
        auth.require("role.manage")
        return auth.connection.execute(text("""SELECT g.id,g.user_id,r.code AS role_code,g.scope_kind,g.warehouse_id,
            g.valid_from,g.valid_until,g.revoked_at FROM wms.user_role_grant g JOIN wms.role r ON r.id=g.role_id
            WHERE CAST(:after AS uuid) IS NULL OR g.id>CAST(:after AS uuid) ORDER BY g.id LIMIT :limit"""),
                                       {"after": after, "limit": limit}).mappings().all()

    @router.post("/grant-requests", status_code=201)
    def request_grant(payload: GrantCreate, request: Request, auth=Depends(authorization)):
        auth.require("role.manage")
        if payload.user_id == auth.principal.user_id:
            raise DomainError("SELF_APPROVAL", "Không được tự yêu cầu cấp quyền cho chính mình.")
        if (payload.scope_kind == "WAREHOUSE") != (payload.warehouse_id is not None):
            raise DomainError("INVALID_SCOPE", "Phạm vi kho không hợp lệ.")
        role = row(auth.connection, "SELECT id FROM wms.role WHERE code=:code AND is_active", code=payload.role_code)
        user = row(auth.connection, "SELECT id FROM wms.app_user WHERE id=:id AND is_active", id=payload.user_id)
        if not role or not user:
            raise DomainError("NOT_FOUND", "Không tìm thấy user hoặc role hợp lệ.")
        if payload.warehouse_id and not row(auth.connection, "SELECT id FROM wms.warehouse WHERE id=:id AND is_active", id=payload.warehouse_id):
            raise DomainError("NOT_FOUND", "Không tìm thấy kho.")
        now = service.clock()
        if payload.valid_until and payload.valid_until <= now:
            raise DomainError("INVALID_SCOPE", "Thời hạn grant phải ở tương lai.")
        request_id = uuid4()
        auth.connection.execute(text("""INSERT INTO wms.grant_request
            (id,user_id,role_id,scope_kind,warehouse_id,valid_until,reason,requested_by,requested_at)
            VALUES (:id,:user,:role,:scope,:warehouse,:until,:reason,:actor,:now)"""),
                                {"id": request_id, "user": payload.user_id, "role": role["id"], "scope": payload.scope_kind,
                                 "warehouse": payload.warehouse_id, "until": payload.valid_until, "reason": payload.reason,
                                 "actor": auth.principal.user_id, "now": now})
        audit(auth.connection, auth.principal.user_id, "iam.grant.requested", request_id, request.state.request_id, now, payload.reason)
        return {"id": request_id, "status": "PENDING"}

    @router.get("/grant-requests")
    def grant_requests(auth=Depends(authorization), limit: int = Query(default=100, ge=1, le=200), after: UUID | None = None):
        auth.require("role.manage")
        return auth.connection.execute(text("""SELECT q.id,q.user_id,r.code AS role_code,q.scope_kind,q.warehouse_id,
            q.valid_until,q.reason,q.requested_by,q.requested_at FROM wms.grant_request q JOIN wms.role r ON r.id=q.role_id
            WHERE q.grant_id IS NULL AND (CAST(:after AS uuid) IS NULL OR q.id>CAST(:after AS uuid))
            ORDER BY q.id LIMIT :limit"""), {"after": after, "limit": limit}).mappings().all()

    @router.post("/grant-requests/{grant_request_id}/approve")
    def approve_grant(grant_request_id: UUID, request: Request, auth=Depends(authorization)):
        auth.require("role.manage")
        pending = row(auth.connection, "SELECT * FROM wms.grant_request WHERE id=:id FOR UPDATE", id=grant_request_id)
        if not pending:
            raise DomainError("NOT_FOUND", "Không tìm thấy yêu cầu cấp quyền.")
        if auth.principal.user_id in {pending["requested_by"], pending["user_id"]}:
            raise DomainError("SELF_APPROVAL", "Cần quản trị viên thứ hai, không phải người nhận quyền.")
        if pending["grant_id"]:
            return {"id": pending["grant_id"], "status": "APPROVED"}
        now = service.clock()
        if pending["valid_until"] and pending["valid_until"] <= now:
            raise DomainError("INVALID_SCOPE", "Yêu cầu cấp quyền đã hết hạn.")
        valid = row(auth.connection, """SELECT u.id FROM wms.app_user u JOIN wms.role r ON r.id=:role
            WHERE u.id=:user AND u.is_active AND r.is_active""", user=pending["user_id"], role=pending["role_id"])
        requester_valid = row(auth.connection, """SELECT u.id FROM wms.app_user u WHERE u.id=:user AND u.is_active
            AND EXISTS(SELECT 1 FROM wms.user_role_grant g JOIN wms.role r ON r.id=g.role_id AND r.is_active
              JOIN wms.role_permission rp ON rp.role_id=r.id JOIN wms.permission p ON p.id=rp.permission_id
              WHERE g.user_id=u.id AND p.code='role.manage' AND g.scope_kind='GLOBAL' AND g.revoked_at IS NULL
                AND g.valid_from<=:now AND (g.valid_until IS NULL OR g.valid_until>:now))""", user=pending["requested_by"], now=now)
        warehouse_valid = not pending["warehouse_id"] or row(auth.connection, "SELECT id FROM wms.warehouse WHERE id=:id AND is_active", id=pending["warehouse_id"])
        if not valid or not requester_valid or not warehouse_valid:
            raise DomainError("INVALID_SCOPE", "User/role/kho hoặc quyền người yêu cầu không còn hợp lệ.")
        grant_id = uuid4()
        auth.connection.execute(text("""INSERT INTO wms.user_role_grant
            (id,user_id,role_id,scope_kind,warehouse_id,valid_from,valid_until,granted_by)
            VALUES (:id,:user,:role,:scope,:warehouse,:now,:until,:actor)"""),
                                {"id": grant_id, "user": pending["user_id"], "role": pending["role_id"],
                                 "scope": pending["scope_kind"], "warehouse": pending["warehouse_id"],
                                 "until": pending["valid_until"], "now": now, "actor": auth.principal.user_id})
        auth.connection.execute(text("UPDATE wms.grant_request SET approved_by=:actor,grant_id=:grant WHERE id=:id"),
                                {"actor": auth.principal.user_id, "grant": grant_id, "id": grant_request_id})
        audit(auth.connection, auth.principal.user_id, "iam.grant.approved", grant_id, request.state.request_id, now, pending["reason"])
        return {"id": grant_id, "status": "APPROVED"}

    @router.post("/grants/{grant_id}/revoke")
    def revoke_grant(grant_id: UUID, payload: RevokeInput, request: Request, auth=Depends(authorization)):
        auth.require("role.manage")
        grant = row(auth.connection, "UPDATE wms.user_role_grant SET revoked_at=COALESCE(revoked_at,:now) WHERE id=:id RETURNING id", id=grant_id, now=service.clock())
        if not grant:
            raise DomainError("NOT_FOUND", "Không tìm thấy grant.")
        audit(auth.connection, auth.principal.user_id, "iam.grant.revoked", grant_id, request.state.request_id, service.clock(), payload.reason)
        return {"status": "REVOKED"}

    @router.post("/auth/password/change")
    def change_password(payload: PasswordChange, request: Request, access: Annotated[str, Depends(token)]):
        service.change_password(access, payload.password.get_secret_value(),
                                payload.code.get_secret_value() if payload.code else None,
                                payload.new_password.get_secret_value(), request.state.request_id)
        return {"status": "SIGNED_OUT"}

    @router.post("/auth/password/reset")
    def complete_reset(payload: PasswordResetComplete, request: Request):
        service.complete_password_reset(payload.username, payload.reset_token.get_secret_value(),
                                        payload.new_password.get_secret_value(), request.state.request_id)
        return {"status": "SIGNED_OUT"}

    @router.post("/users/{user_id}/password-reset", response_model=PasswordResetToken)
    def issue_reset(user_id: UUID, payload: PasswordResetIssue, request: Request, access: Annotated[str, Depends(token)]):
        return service.issue_password_reset(access, user_id, payload.password.get_secret_value(),
                                            payload.code.get_secret_value() if payload.code else None,
                                            payload.reason, request.state.request_id)

    @router.post("/auth/mfa/reset")
    def reset_mfa(payload: Reauthentication, request: Request, access: Annotated[str, Depends(token)]):
        service.reset_mfa(access, payload.password.get_secret_value(),
                          payload.code.get_secret_value() if payload.code else None, request.state.request_id)
        return {"status": "SIGNED_OUT"}

    @router.post("/auth/mfa/recovery-codes", response_model=RecoveryCodes)
    def recovery_codes(payload: Reauthentication, request: Request, access: Annotated[str, Depends(token)]):
        return service.recovery_codes(access, payload.password.get_secret_value(),
                                      payload.code.get_secret_value() if payload.code else None, request.state.request_id)

    @router.post("/auth/mfa/recover")
    def recover(payload: RecoveryInput, request: Request):
        service.recover_mfa(payload.challenge_token.get_secret_value(), payload.recovery_code.get_secret_value(), request.state.request_id)
        return {"status": "SIGNED_OUT"}

    @router.get("/iam/lookup/users", response_model=list[UserSummary])
    def lookup_users(auth=Depends(authorization), q: str = Query(default="", max_length=100),
                     after: str = "", limit: int = Query(default=100, ge=1, le=200)):
        auth.require("role.manage")
        return auth.connection.execute(text("""SELECT id,username,display_name,is_active FROM wms.app_user
            WHERE is_active AND username>:after AND (strpos(lower(username),lower(:q))>0 OR strpos(lower(display_name),lower(:q))>0)
            ORDER BY username LIMIT :limit"""), {"after": after, "q": q, "limit": limit}).mappings().all()

    @router.get("/iam/lookup/warehouses", response_model=list[WarehouseSummary])
    def lookup_warehouses(auth=Depends(authorization), q: str = Query(default="", max_length=100),
                          after: str = "", limit: int = Query(default=100, ge=1, le=200)):
        # Identity lookup conveys no stock/document access.
        auth.require("role.manage")
        return auth.connection.execute(text("""SELECT id,code,name FROM wms.warehouse
            WHERE is_active AND code>:after AND (strpos(lower(code),lower(:q))>0 OR strpos(lower(name),lower(:q))>0)
            ORDER BY code LIMIT :limit"""), {"after": after, "q": q, "limit": limit}).mappings().all()

    @router.get("/iam/sessions", response_model=list[SessionSummary])
    def sessions(auth=Depends(authorization), user_id: UUID | None = None,
                 after: UUID | None = None, limit: int = Query(default=100, ge=1, le=200)):
        auth.require("iam.manage")
        return auth.connection.execute(text("""SELECT s.id,s.user_id,u.username,s.device_id,
            (SELECT min(t.created_at) FROM wms.auth_token t WHERE t.session_id=s.id) AS created_at,
            s.expires_at,s.revoked_at,s.mfa_verified_at,
            (u.is_active AND u.auth_version=s.auth_version AND s.revoked_at IS NULL AND s.expires_at>:now) AS is_active
            FROM wms.auth_session s JOIN wms.app_user u ON u.id=s.user_id
            WHERE (CAST(:user AS uuid) IS NULL OR s.user_id=:user)
              AND (CAST(:after AS uuid) IS NULL OR s.id>:after)
            ORDER BY s.id LIMIT :limit"""),
            {"user": user_id, "after": after, "limit": limit, "now": service.clock()}).mappings().all()

    @router.get("/iam/events", response_model=list[IdentityEvent])
    def events(auth=Depends(authorization), after: UUID | None = None,
               limit: int = Query(default=100, ge=1, le=200)):
        auth.require("audit.security.read")
        if auth.principal.mfa_verified_at is None:
            raise DomainError("MFA_REQUIRED", "Cần MFA để đọc lịch sử tài khoản/quyền.")
        # Deliberate allowlist: never project before_data/after_data or auth rows.
        return auth.connection.execute(text("""SELECT e.id,e.actor_id,u.username AS actor_name,
            e.action,e.entity_id,e.occurred_at,e.request_id,e.reason
            FROM wms.audit_event e LEFT JOIN wms.app_user u ON u.id=e.actor_id
            WHERE e.entity_type='identity' AND (CAST(:after AS uuid) IS NULL OR e.id>:after)
            ORDER BY e.id LIMIT :limit"""), {"after": after, "limit": limit}).mappings().all()

    return router
