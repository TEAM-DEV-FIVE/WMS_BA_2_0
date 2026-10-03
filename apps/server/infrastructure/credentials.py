import hashlib
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12–128 characters")
    return hasher.hash(password)


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    return hasher.hash(secrets.token_urlsafe(32))


def verify_password(stored: str | None, password: str) -> bool:
    try:
        valid = hasher.verify(stored or dummy_hash(), password)
        return bool(stored) and valid
    except (VerificationError, InvalidHashError):
        return False


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)
