import logging

import uvicorn
from pydantic import ValidationError

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings


def main() -> None:
    try:
        settings = Settings()
    except ValidationError:
        raise SystemExit("Cấu hình không hợp lệ: cần WMS_DATABASE_URL PostgreSQL; kiểm tra port/timeout.") from None
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # Access logs would include arbitrary query strings. Our middleware logs IDs/status only.
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
