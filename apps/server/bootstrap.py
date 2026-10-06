"""Provision initial administrators locally, using hidden interactive passwords."""

import argparse
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from apps.server.application.identity import IdentityService
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from packages.contracts.identity import UserCreate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    engine = None
    try:
        password = getpass("Mật khẩu (12–128 ký tự): ")
        if password != getpass("Nhập lại mật khẩu: "):
            raise SystemExit("Hai mật khẩu không khớp.")
        user = UserCreate(username=args.username, display_name=args.display_name, password=password)
        settings = Settings()
        engine = make_engine(settings)
        IdentityService(engine, settings).bootstrap(user.username, user.display_name, user.password.get_secret_value())
        print("Đã tạo SYSADMIN. Đăng nhập và bật MFA trước khi quản trị; tài khoản chưa có quyền kho.")
    except (ValidationError, ValueError):
        raise SystemExit("Dữ liệu hoặc cấu hình không hợp lệ. Kiểm tra username, mật khẩu, DB và khóa MFA.") from None
    except DomainError as exc:
        raise SystemExit(exc.message) from None
    except SQLAlchemyError:
        raise SystemExit("Không tạo được tài khoản. Kiểm tra DB/migration; giao dịch đã rollback.") from None
    finally:
        if engine:
            engine.dispose()


if __name__ == "__main__":
    main()
