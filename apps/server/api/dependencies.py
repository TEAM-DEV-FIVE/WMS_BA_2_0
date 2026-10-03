from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from apps.server.domain.errors import DomainError


def identity_dependencies(service):
    bearer = HTTPBearer(auto_error=False)

    def token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not credentials or credentials.scheme.lower() != "bearer":
            raise DomainError("UNAUTHENTICATED", "Cần đăng nhập.")
        return credentials.credentials

    def authorization(access: Annotated[str, Depends(token)]):
        with service.engine.begin() as connection:
            yield service.authorization(connection, access)

    return token, authorization
