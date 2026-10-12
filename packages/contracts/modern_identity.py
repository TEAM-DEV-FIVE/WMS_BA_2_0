from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from packages.contracts import Contract
from packages.contracts.identity import Reauthentication


class ContactInput(Reauthentication):
    kind: Literal['email', 'sms']
    value: str = Field(min_length=3, max_length=254)


class ContactConfirm(Contract):
    challenge_id: UUID
    code: SecretStr = Field(min_length=6, max_length=6)


class ForgotInput(Contract):
    kind: Literal['email', 'sms']
    value: str = Field(min_length=3, max_length=254)
    purpose: Literal['account', 'password']


class GoogleStart(Contract):
    port: int = Field(ge=1024, le=65535)
    device_id: UUID
    link: bool = False
    password: SecretStr | None = None
    code: SecretStr | None = None


class GoogleComplete(Contract):
    state: SecretStr = Field(min_length=40, max_length=100)
    code: SecretStr = Field(min_length=1, max_length=4096)


class AuthOptions(Contract):
    email: bool
    sms: bool
    google: bool


class AuthMessage(Contract):
    message: str


class VerifiedContact(Contract):
    kind: Literal['email', 'sms']
    value: str


class ContactChallenge(AuthMessage):
    challenge_id: UUID


class GoogleFlow(Contract):
    url: str
    state: str


class SignedOut(Contract):
    status: Literal['SIGNED_OUT']
