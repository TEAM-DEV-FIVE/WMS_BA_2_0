from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from apps.server.api.dependencies import identity_dependencies
from apps.server.domain.errors import DomainError
from packages.contracts import Error
from packages.contracts.identity import MfaChallenge, PasswordResetComplete, SessionTokens
from packages.contracts.modern_identity import (
    AuthMessage,
    AuthOptions,
    ContactChallenge,
    ContactConfirm,
    ContactInput,
    ForgotInput,
    GoogleComplete,
    GoogleFlow,
    GoogleStart,
    SignedOut,
    VerifiedContact,
)


def modern_identity_router(service):
    router = APIRouter(prefix='/api/v1/auth', tags=['identity'],
                       responses={status: {'model': Error} for status in (401, 403, 404, 409, 422, 429, 503)})
    token, _ = identity_dependencies(service.identity)
    def optional_token(authorization: Annotated[str | None, Header()] = None):
        # Public Google login; link=True separately requires the live bearer.
        scheme, _, value = (authorization or '').partition(' ')
        return value.strip() if scheme.lower() == 'bearer' else ''

    @router.get('/options', response_model=AuthOptions)
    def options():
        return service.settings.capabilities()

    @router.get('/contacts', response_model=list[VerifiedContact])
    def contacts(access: Annotated[str, Depends(token)]):
        return service.contacts(access)

    @router.post('/contacts/start', response_model=ContactChallenge)
    def start(payload: ContactInput, request: Request, access: Annotated[str, Depends(token)]):
        return service.contact_start(access, payload, request.state.request_id)

    @router.post('/contacts/confirm', response_model=AuthMessage)
    def confirm(payload: ContactConfirm, request: Request, access: Annotated[str, Depends(token)]):
        return service.contact_confirm(access, payload.challenge_id, payload.code.get_secret_value(), request.state.request_id)

    @router.post('/forgot', response_model=AuthMessage)
    def forgot(payload: ForgotInput, request: Request):
        return service.forgot(payload, request.client.host if request.client else 'unknown', request.state.request_id)

    @router.post('/self-reset', response_model=SignedOut)
    def reset(payload: PasswordResetComplete, request: Request):
        service.reset(payload.username, payload.reset_token.get_secret_value(), payload.new_password.get_secret_value(), request.state.request_id)
        return dict(status='SIGNED_OUT')

    @router.post('/google/start', response_model=GoogleFlow)
    def google_start(payload: GoogleStart, request: Request, access: Annotated[str, Depends(optional_token)]):
        with service.identity.engine.begin() as c:
            now = service.identity.clock()
            key = service.identity.throttle(c, 'GOOGLE_PEER', request.client.host if request.client else 'unknown', now)
            service.identity.failed_attempt(c, key, now)
        return service.google_start(payload, access, request.state.request_id)

    @router.post('/google/complete', response_model=SessionTokens | MfaChallenge | AuthMessage)
    def google_complete(payload: GoogleComplete, request: Request, access: Annotated[str, Depends(optional_token)]):
        if not payload.code.get_secret_value():
            raise DomainError('UNAUTHENTICATED', 'Google chưa được xác nhận.')
        return service.google_complete(payload.state.get_secret_value(), payload.code.get_secret_value(), access, request.state.request_id)

    return router
