"""DB-operator provisioning of the FIRST stock period for a warehouse.

Uses local server DB credentials, like administrator bootstrap. Does not reopen,
close, extend or replace existing periods; those need the period-control workflow.
"""

import argparse
import json
from datetime import date
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from apps.server.application.master_data import one
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine


def provision(engine, warehouse_code, starts_on, ends_on, reason):
    if ends_on < starts_on or not reason.strip() or len(reason) > 1000:
        raise ValueError("Ngày/lý do không hợp lệ.")
    with engine.begin() as c:
        warehouse = one(
            c, "SELECT * FROM wms.warehouse WHERE code=:code AND is_active FOR UPDATE", code=warehouse_code
        )
        if not warehouse:
            raise DomainError("NOT_FOUND", "Kho không tồn tại hoặc đã ngừng dùng.")
        if one(c, "SELECT id FROM wms.stock_period WHERE warehouse_id=:id LIMIT 1", id=warehouse["id"]):
            raise DomainError("PERIOD_EXISTS", "Kho đã có kỳ; bootstrap không được đổi hoặc mở lại kỳ.")
        if one(
            c,
            """SELECT t.id FROM wms.inventory_transaction t JOIN wms.document d ON d.id=t.document_id
            WHERE d.warehouse_id=:id OR d.destination_warehouse_id=:id LIMIT 1""",
            id=warehouse["id"],
        ):
            raise DomainError("ALREADY_POSTED", "Kho có lịch sử ghi sổ; cần đối soát trước khi thiết lập kỳ.")
        period_id, request_id = uuid4(), uuid4()
        c.execute(
            text("""INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status)
            VALUES (:id,:warehouse,:start,:end,'OPEN')"""),
            {"id": period_id, "warehouse": warehouse["id"], "start": starts_on, "end": ends_on},
        )
        data = json.dumps(
            dict(
                starts_on=str(starts_on),
                ends_on=str(ends_on),
                status="OPEN",
                database_operator=c.execute(text("SELECT current_user")).scalar_one(),
            )
        )
        c.execute(
            text("""INSERT INTO wms.audit_event(id,warehouse_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
            VALUES (:id,:warehouse,'period.bootstrap','stock_period',:period,:request,clock_timestamp(),CAST(:data AS jsonb),:reason)"""),
            {
                "id": uuid4(),
                "warehouse": warehouse["id"],
                "period": period_id,
                "request": request_id,
                "data": data,
                "reason": reason,
            },
        )
        return period_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse-code", required=True)
    parser.add_argument("--starts-on", required=True, type=date.fromisoformat)
    parser.add_argument("--ends-on", required=True, type=date.fromisoformat)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    engine = None
    try:
        engine = make_engine(Settings())
        period = provision(engine, args.warehouse_code, args.starts_on, args.ends_on, args.reason)
        print(f"Đã tạo kỳ đầu tiên {period}. Có audit của tài khoản DB vận hành.")
    except DomainError as exc:
        raise SystemExit(exc.message) from None
    except ValueError:
        raise SystemExit("Ngày, lý do hoặc cấu hình không hợp lệ.") from None
    except SQLAlchemyError:
        raise SystemExit("Không tạo được kỳ; kiểm tra kết nối/migration. Giao dịch đã rollback.") from None
    finally:
        if engine:
            engine.dispose()


if __name__ == "__main__":
    main()
