"""Bounded, repeatable-read reports. Snapshots contain no bearer credentials."""

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from apps.server.application.commands import CommandBus, CommandResult
from apps.server.application.master_data import one
from apps.server.application.report_queries import QUERIES
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.database import PostgresUnitOfWork
from packages.contracts.reports import ReportSnapshot

MAX_ROWS = 20000
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_ACTIVE = 10


def encode(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(type(value).__name__)


def serialized(value):
    return json.dumps(value, default=encode, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def serialize_actor(auth):
    # A real row version write makes concurrent REPEATABLE READ writers retry
    # with a fresh snapshot; advisory locks alone cannot refresh an old snapshot.
    auth.connection.execute(
        text("""INSERT INTO wms.report_request_guard(user_id) VALUES (:actor)
        ON CONFLICT(user_id) DO UPDATE SET version=wms.report_request_guard.version+1"""),
        {"actor": auth.principal.user_id},
    )


def permissions(code, criteria):
    result = ["report.read", "ownership.read"]
    if code in {"R01", "R03", "R05", "R06", "R07"}:
        result.append("serial.read")
    if code == "R07":
        result.append("count.snapshot.read")
    if criteria["include_price"]:
        result.append("price.read")
    return result


class ReportService:
    def __init__(self, identity):
        self.identity = identity
        self.bus = CommandBus(
            lambda: PostgresUnitOfWork(identity.engine.execution_options(isolation_level="REPEATABLE READ"))
        )

    def command(self, access, key, command, resource, body, authorize, handler):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        return self.bus.execute(
            actor_id=actor,
            key=key,
            command=command,
            resource_id=resource,
            payload=body,
            authorize=lambda uow: authorize(self.identity.authorization(uow.connection, access)),
            handle=lambda uow: handler(self.identity.authorization(uow.connection, access)),
        )

    @staticmethod
    def authorize(auth, code, criteria, warehouses=None, export=False):
        for warehouse in warehouses or [criteria["warehouse_id"]]:
            for permission in permissions(code, criteria) + (["report.export"] if export else []):
                auth.require(permission, warehouse)

    def snapshot(self, auth, snapshot_id, *, export=False):
        snapshot = one(
            auth.connection,
            """SELECT * FROM wms.report_snapshot
            WHERE id=:id AND requested_by=:actor""",
            id=snapshot_id,
            actor=auth.principal.user_id,
        )
        if not snapshot:
            raise DomainError("NOT_FOUND", "Không tìm thấy snapshot của bạn.")
        self.authorize(
            auth, snapshot["report_code"], snapshot["criteria"], snapshot["required_warehouses"], export
        )
        if snapshot["expires_at"] <= self.identity.clock():
            raise DomainError("REPORT_EXPIRED", "Snapshot hết hạn; tạo báo cáo mới.")
        if snapshot["report_code"] == "R07" and one(
            auth.connection,
            """SELECT ca.id
            FROM wms.report_snapshot_row r JOIN wms.count_assignment ca
            ON ca.session_id=CAST(r.payload->>'session_id' AS uuid)
            WHERE r.snapshot_id=:id AND ca.user_id=:actor LIMIT 1""",
            id=snapshot_id,
            actor=auth.principal.user_id,
        ):
            raise DomainError("FORBIDDEN", "Người được phân công đếm không được đọc snapshot kiểm kê.")
        return snapshot

    @staticmethod
    def view(snapshot):
        return ReportSnapshot.model_validate(
            {k: snapshot[k] for k in ReportSnapshot.model_fields}
        ).model_dump(mode="json")

    def page(self, auth, snapshot_id, after, limit):
        snapshot = self.snapshot(auth, snapshot_id)
        rows = (
            auth.connection.execute(
                text("""SELECT ordinal,payload FROM wms.report_snapshot_row
            WHERE snapshot_id=:id AND ordinal>:after ORDER BY ordinal LIMIT :limit"""),
                dict(id=snapshot_id, after=after, limit=limit + 1),
            )
            .mappings()
            .all()
        )
        return dict(
            snapshot=self.view(snapshot),
            items=[r["payload"] for r in rows[:limit]],
            next_after=rows[limit - 1]["ordinal"] if len(rows) > limit else None,
        )

    def create(self, access, key, code, criteria, request_id):
        body = criteria.model_dump(mode="json")
        if code != "R08" and (criteria.include_price or criteria.effective_on):
            raise DomainError("INVALID_FILTER", "Giá tham chiếu chỉ có ở R08.")
        if code == "R03" and (criteria.sort_by != "default" or criteria.descending):
            raise DomainError("INVALID_FILTER", "R03 cố định thứ tự posted_at, transaction id, move id.")
        if code in {"R01", "R06"} and any(
            [criteria.business_from, criteria.business_to, criteria.posted_from, criteria.posted_to]
        ):
            raise DomainError("INVALID_FILTER", "R01/R06 là tồn hiện tại; dùng R02/R03 để lọc lịch sử.")
        if code in {"R04", "R07"} and (criteria.posted_from or criteria.posted_to):
            raise DomainError("INVALID_FILTER", "R04/R07 lọc theo ngày nghiệp vụ.")
        if code == "R05" and criteria.location_ids:
            raise DomainError("INVALID_FILTER", "R05 đối chiếu toàn phiếu chuyển giữa hai kho.")

        def create(auth):
            c, now = auth.connection, self.identity.clock()
            # Serialize per-user quota, including concurrent independent command keys.
            serialize_actor(auth)
            count = c.execute(
                text("""SELECT count(*) FROM wms.report_snapshot
                WHERE requested_by=:actor AND expires_at>:now"""),
                dict(actor=auth.principal.user_id, now=now),
            ).scalar_one()
            if count >= MAX_ACTIVE:
                raise DomainError(
                    "REPORT_LIMIT", "Tối đa 10 snapshot còn hạn mỗi người; chờ snapshot hết hạn."
                )
            locations = (
                c.execute(
                    text("""SELECT id FROM wms.location WHERE warehouse_id=:warehouse
                AND kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING')"""),
                    {"warehouse": criteria.warehouse_id},
                )
                .scalars()
                .all()
            )
            if not set(criteria.location_ids).issubset(locations):
                raise DomainError("INVALID_SCOPE", "Ranh giới chỉ chứa vị trí lá trong kho được chọn.")
            warehouse_ids = c.execute(text("SELECT id FROM wms.warehouse ORDER BY id")).scalars().all()
            allowed = [w for w in warehouse_ids if all(auth.allows(p, w) for p in permissions(code, body))]
            today = now.astimezone(ZoneInfo(self.identity.settings.business_timezone)).date()
            params = dict(
                warehouse=criteria.warehouse_id,
                locations=criteria.location_ids,
                owner=criteria.owner_id,
                actor=auth.principal.user_id,
                product=criteria.product_id,
                warehouses=allowed,
                today=today,
                timezone=self.identity.settings.business_timezone,
                **{
                    k: getattr(criteria, k)
                    for k in ["business_from", "business_to", "posted_from", "posted_to"]
                },
            )
            result = c.execute(
                text(QUERIES[code] + " LIMIT :row_limit"), {**params, "row_limit": MAX_ROWS + 1}
            )
            columns = list(result.keys())
            rows = [dict(r) for r in result.mappings()]
            if len(rows) > MAX_ROWS:
                raise DomainError("REPORT_LIMIT", "Báo cáo vượt 20.000 dòng; thu hẹp bộ lọc.")
            if code == "R08" and criteria.include_price:
                effective = criteria.effective_on or today
                prices = {
                    r["product_id"]: dict(r)
                    for r in c.execute(
                        text("""SELECT DISTINCT ON (product_id)
                    product_id,amount,currency,effective_on FROM wms.reference_price
                    WHERE effective_on<=:effective ORDER BY product_id,effective_on DESC"""),
                        dict(effective=effective),
                    ).mappings()
                }
                columns += [
                    "reference_price",
                    "currency",
                    "price_effective_on",
                    "valuation_label",
                    "inbound_reference_value",
                    "outbound_reference_value",
                ]
                for r in rows:
                    price = prices.get(r["id"])
                    r.update(
                        reference_price=price["amount"] if price else None,
                        currency=price["currency"] if price else None,
                        price_effective_on=price["effective_on"] if price else None,
                        valuation_label="Giá tham chiếu quản trị",
                        inbound_reference_value=r["inbound"] * price["amount"] if price else None,
                        outbound_reference_value=r["outbound"] * price["amount"] if price else None,
                    )
            if criteria.sort_by != "default":
                if criteria.sort_by not in columns:
                    raise DomainError("INVALID_FILTER", "Báo cáo không có cột sắp xếp đã chọn.")
                rows.sort(
                    key=lambda r: (str(r.get(criteria.sort_by) or ""), serialized(r)),
                    reverse=criteria.descending,
                )
            elif criteria.descending:
                rows.reverse()
            raw = serialized(rows)
            if len(raw.encode()) > MAX_SNAPSHOT_BYTES:
                raise DomainError("REPORT_LIMIT", "Snapshot vượt 16 MiB; thu hẹp bộ lọc.")
            # Cross-warehouse reports/transit require the original permissions at every read/download.
            required = {criteria.warehouse_id}
            if code == "R05":
                for r in rows:
                    required.update([r["source_warehouse_id"], r["destination_warehouse_id"]])
            if code in {"R01", "R06"}:
                transit = [r["location_id"] for r in rows if r["location_kind"] == "TRANSIT"]
                for r in c.execute(
                    text("""SELECT warehouse_id,destination_warehouse_id FROM wms.document
                    WHERE transit_location_id=ANY(CAST(:locations AS uuid[]))"""),
                    {"locations": transit},
                ).mappings():
                    required.update([r["warehouse_id"], r["destination_warehouse_id"]])
            snapshot = dict(
                id=uuid4(),
                requested_by=auth.principal.user_id,
                report_code=code,
                criteria=body,
                required_warehouses=sorted(required, key=str),
                created_at=now,
                expires_at=now + timedelta(hours=1),
                row_count=len(rows),
                columns=columns,
                sha256=hashlib.sha256(raw.encode()).hexdigest(),
            )
            c.execute(
                text("""INSERT INTO wms.report_snapshot
                (id,requested_by,report_code,criteria,required_warehouses,created_at,expires_at,row_count,columns,sha256)
                VALUES (:id,:requested_by,:report_code,CAST(:criteria AS jsonb),:required_warehouses,
                  :created_at,:expires_at,:row_count,CAST(:columns AS jsonb),:sha256)"""),
                {**snapshot, "criteria": serialized(body), "columns": serialized(columns)},
            )
            if rows:
                c.execute(
                    text("""INSERT INTO wms.report_snapshot_row(snapshot_id,ordinal,payload)
                    VALUES (:id,:ordinal,CAST(:payload AS jsonb))"""),
                    [
                        dict(id=snapshot["id"], ordinal=n, payload=serialized(r))
                        for n, r in enumerate(rows, 1)
                    ],
                )
            c.execute(
                text("""INSERT INTO wms.audit_event
                (id,actor_id,action,entity_type,entity_id,request_id,occurred_at)
                VALUES (:id,:actor,'report.snapshot.created','report',:target,:request,:now)"""),
                dict(
                    id=uuid4(),
                    actor=auth.principal.user_id,
                    target=snapshot["id"],
                    request=request_id,
                    now=now,
                ),
            )
            return CommandResult(self.view(snapshot), 201)

        return self.command(
            access,
            key,
            "report.snapshot." + code,
            criteria.warehouse_id,
            body,
            lambda auth: self.authorize(auth, code, body),
            create,
        )
