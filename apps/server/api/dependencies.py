from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from apps.server.application.authorization import Authorization
from apps.server.domain.errors import DomainError


def identity_dependencies(service):
    bearer = HTTPBearer(auto_error=False)

    def token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not credentials or credentials.scheme.lower() != "bearer":
            raise DomainError("UNAUTHENTICATED", "Cần đăng nhập.")
        return credentials.credentials

    def transaction(access: Annotated[str, Depends(token)]):
        with service.engine.begin() as connection:
            yield service.authorization(connection, access)

    def authorization(auth: Annotated[Authorization, Depends(transaction, scope="function")]):
        # Finish the transaction before response transmission. Request-scoped yield
        # teardown can otherwise acknowledge a write before its commit completes.
        return auth

    return token, authorization
