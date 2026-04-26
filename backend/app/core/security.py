import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


def generate_token() -> bytes:
    """Génère 32 octets cryptographiquement aléatoires."""
    return secrets.token_bytes(32)


def hash_token(token: bytes) -> bytes:
    """SHA-256 du token brut → 32 octets stockés en bytea."""
    return hashlib.sha256(token).digest()


def verify_token(token: bytes, stored_hash: bytes) -> bool:
    """Comparaison time-safe entre hash(token) et stored_hash."""
    return hmac.compare_digest(hash_token(token), stored_hash)


def token_to_cookie(token: bytes) -> str:
    """Encode le token brut en hex pour le cookie."""
    return token.hex()


def cookie_to_token(value: str) -> bytes | None:
    """Décode le cookie hex en bytes. Retourne None si invalide."""
    try:
        raw = bytes.fromhex(value)
        if len(raw) != 32:
            return None
        return raw
    except ValueError:
        return None
