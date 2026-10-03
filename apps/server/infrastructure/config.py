from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WMS_", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    pool_size: int = Field(default=5, ge=1, le=30)
    database_timeout_seconds: int = Field(default=5, ge=1, le=60)
    mfa_encryption_key: SecretStr | None = None
    access_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    session_ttl_seconds: int = Field(default=28800, ge=3600, le=604800)
    auth_failure_limit: int = Field(default=5, ge=3, le=10)
    auth_lock_seconds: int = Field(default=300, ge=60, le=3600)
    business_timezone: str = "Asia/Ho_Chi_Minh"

    @field_validator("business_timezone")
    @classmethod
    def valid_timezone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("WMS_BUSINESS_TIMEZONE must be an IANA timezone") from None
        return value

    @field_validator("mfa_encryption_key")
    @classmethod
    def valid_encryption_key(cls, value):
        if value is not None:
            from cryptography.fernet import Fernet
            try:
                Fernet(value.get_secret_value().encode("ascii"))
            except (ValueError, UnicodeError):
                raise ValueError("WMS_MFA_ENCRYPTION_KEY must be a Fernet key") from None
        return value

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername == "postgresql+psycopg" and bool(url.database)
        except Exception:
            valid = False
        if not valid:
            raise ValueError("WMS_DATABASE_URL must use postgresql+psycopg:// and name a database")
        return value
