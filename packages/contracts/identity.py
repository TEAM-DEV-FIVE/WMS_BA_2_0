from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SecretStr, StringConstraints, field_validator, model_validator

from packages.contracts import Contract

Username = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3,
                                           max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")]


class LoginInput(Contract):
    username: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3,
        max_length=254, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.@_+\-]*$")]
    password: SecretStr = Field(min_length=1, max_length=128)
    device_id: UUID


class RefreshInput(Contract):
    refresh_token: SecretStr = Field(min_length=40, max_length=100)
    device_id: UUID


class MfaInput(Contract):
    challenge_token: SecretStr = Field(min_length=40, max_length=100)
    code: SecretStr = Field(min_length=6, max_length=6)


class SessionTokens(Contract):
    status: Literal["AUTHENTICATED"] = "AUTHENTICATED"
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class MfaChallenge(Contract):
    status: Literal["MFA_REQUIRED"] = "MFA_REQUIRED"
    challenge_token: str = Field(repr=False)
    expires_in: int = 300


class PasswordConfirmation(Contract):
    password: SecretStr = Field(min_length=1, max_length=128)


class Enrollment(Contract):
    factor_id: UUID
    provisioning_uri: str = Field(repr=False)
    secret: str = Field(repr=False)
    expires_in: int = 300


class EnrollmentConfirmation(Contract):
    factor_id: UUID
    code: SecretStr = Field(min_length=6, max_length=6)


class UserSummary(Contract):
    id: UUID
    username: str
    display_name: str
    is_active: bool


class CurrentUser(UserSummary):
    mfa_verified: bool
    global_permissions: list[str]
    avatar_base64: str | None = Field(default=None, max_length=350000, repr=False)
    avatar_version: int = 0


class UserCreate(Contract):
    username: Username
    display_name: str = Field(min_length=1, max_length=200)
    password: SecretStr = Field(min_length=12, max_length=128)


class ProfileUpdate(Contract):
    display_name: str = Field(min_length=1, max_length=200, pattern=r"^\S(?:[^\r\n\t]*\S)?$")
    expected_display_name: str = Field(min_length=1, max_length=200)
    avatar_base64: str | None = Field(default=None, max_length=350000, repr=False)
    expected_avatar_version: int | None = Field(default=None, ge=0)


    @model_validator(mode="after")
    def avatar_has_version(self):
        if "avatar_base64" in self.model_fields_set and self.expected_avatar_version is None:
            raise ValueError("Ảnh đại diện cần phiên bản hiện tại")
        return self


class UserActivation(Contract):
    is_active: bool = Field(strict=True)
    reason: str = Field(min_length=3, max_length=2000)


class RevokeInput(Contract):
    reason: str = Field(min_length=3, max_length=2000)


class WarehouseSummary(Contract):
    id: UUID
    code: str
    name: str


class GrantCreate(Contract):
    user_id: UUID
    role_code: str = Field(min_length=1, max_length=60)
    scope_kind: Literal["GLOBAL", "WAREHOUSE", "ALL_WAREHOUSES"]
    warehouse_id: UUID | None = None
    valid_until: datetime | None = None
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("valid_until")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value


class Reauthentication(PasswordConfirmation):
    code: SecretStr | None = Field(default=None, min_length=6, max_length=6)


class PasswordChange(Reauthentication):
    new_password: SecretStr = Field(min_length=12, max_length=128)


class PasswordResetIssue(Reauthentication):
    reason: str = Field(min_length=3, max_length=2000)


class PasswordResetComplete(Contract):
    username: Username
    reset_token: SecretStr = Field(min_length=40, max_length=100)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class RecoveryInput(Contract):
    challenge_token: SecretStr = Field(min_length=40, max_length=100)
    recovery_code: SecretStr = Field(min_length=20, max_length=100)


class RecoveryCodes(Contract):
    codes: list[str] = Field(repr=False)


class PasswordResetToken(Contract):
    reset_token: str = Field(repr=False)
    expires_in: int = 900


class SessionSummary(Contract):
    id: UUID
    user_id: UUID
    username: str
    device_id: UUID
    created_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
    mfa_verified_at: datetime | None
    is_active: bool


class IdentityEvent(Contract):
    id: UUID
    actor_id: UUID | None
    actor_name: str | None
    action: str
    entity_id: UUID | None
    occurred_at: datetime
    request_id: UUID
    reason: str | None
