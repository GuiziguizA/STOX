"""Tests unitaires — app/core/security.py"""
import pytest

from app.core.security import (
    cookie_to_token,
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    token_to_cookie,
    verify_password,
    verify_token,
)


# ── Argon2id ──────────────────────────────────────────────────────────────────

def test_hash_password_returns_string():
    h = hash_password("mysecret")
    assert isinstance(h, str)
    assert h.startswith("$argon2id$")


def test_verify_password_correct():
    h = hash_password("correcthorse")
    assert verify_password("correcthorse", h) is True


def test_verify_password_wrong():
    h = hash_password("correcthorse")
    assert verify_password("wrongpassword", h) is False


def test_verify_password_empty():
    h = hash_password("nonempty")
    assert verify_password("", h) is False


def test_password_needs_rehash_fresh():
    h = hash_password("test")
    assert password_needs_rehash(h) is False


# ── Token generation ──────────────────────────────────────────────────────────

def test_generate_token_length():
    t = generate_token()
    assert len(t) == 32


def test_generate_token_is_random():
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100


# ── Token hash ────────────────────────────────────────────────────────────────

def test_hash_token_length():
    t = generate_token()
    h = hash_token(t)
    assert len(h) == 32


def test_hash_token_deterministic():
    t = generate_token()
    assert hash_token(t) == hash_token(t)


def test_hash_token_different_inputs():
    t1, t2 = generate_token(), generate_token()
    assert hash_token(t1) != hash_token(t2)


# ── verify_token (time-safe) ──────────────────────────────────────────────────

def test_verify_token_correct():
    t = generate_token()
    h = hash_token(t)
    assert verify_token(t, h) is True


def test_verify_token_wrong():
    t1 = generate_token()
    t2 = generate_token()
    h = hash_token(t1)
    assert verify_token(t2, h) is False


def test_verify_token_tampered_hash():
    t = generate_token()
    h = bytearray(hash_token(t))
    h[0] ^= 0xFF  # flip premier octet
    assert verify_token(t, bytes(h)) is False


# ── Cookie encode/decode ──────────────────────────────────────────────────────

def test_cookie_roundtrip():
    t = generate_token()
    cookie_val = token_to_cookie(t)
    recovered = cookie_to_token(cookie_val)
    assert recovered == t


def test_cookie_to_token_invalid_hex():
    assert cookie_to_token("not_hex_!@#") is None


def test_cookie_to_token_wrong_length():
    # 31 octets en hex = 62 chars
    assert cookie_to_token("ab" * 31) is None


def test_cookie_to_token_empty():
    assert cookie_to_token("") is None
