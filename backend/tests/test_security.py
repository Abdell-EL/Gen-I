from __future__ import annotations

import builtins
from datetime import timedelta
import importlib
import sys
import unittest
from unittest.mock import patch

import jwt

from app.security import (
    ACCESS_TOKEN_ALGORITHM,
    MAX_PASSWORD_BYTES,
    AccessTokenAlgorithmError,
    AccessTokenClaimsError,
    AccessTokenExpiredError,
    AccessTokenSignatureError,
    PasswordTooLongError,
    create_access_token,
    decode_and_validate_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)


SIGNING_KEY = "test-primary-signing-key-0123456789abcdef0123456789abcdef0123456789abcdef"
ISSUER = "security-test-suite"
AUDIENCE = "security-test-client"


def _create_token(**overrides):
    arguments = {
        "signing_key": SIGNING_KEY,
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "lifetime": timedelta(minutes=5),
        "subject": "user-123",
    }
    arguments.update(overrides)
    return create_access_token(**arguments)


def _replace_claims(token: str, **updates) -> str:
    claims = jwt.decode(
        token,
        SIGNING_KEY,
        algorithms=[ACCESS_TOKEN_ALGORITHM],
        options={
            "verify_signature": True,
            "verify_aud": False,
            "verify_iss": False,
        },
    )
    claims.update(updates)
    return jwt.encode(claims, SIGNING_KEY, algorithm=ACCESS_TOKEN_ALGORITHM)


def test_password_verification_accepts_correct_password():
    encoded = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", encoded)


def test_password_verification_rejects_incorrect_password():
    encoded = hash_password("correct horse battery staple")

    assert not verify_password("incorrect password", encoded)


def test_password_hashes_use_different_salts():
    first = hash_password("same password")
    second = hash_password("same password")

    assert first != second
    assert first.startswith("$argon2id$")
    assert second.startswith("$argon2id$")


def test_current_password_hash_does_not_need_rehash():
    assert not password_needs_rehash(hash_password("current parameters"))


def test_hash_with_old_parameters_needs_rehash():
    from argon2 import PasswordHasher

    old_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(
        "old parameters"
    )

    assert password_needs_rehash(old_hash)


def test_oversized_password_is_rejected_before_hashing():
    oversized = "é" * ((MAX_PASSWORD_BYTES // 2) + 1)

    with unittest.TestCase().assertRaises(PasswordTooLongError):
        hash_password(oversized)


def test_valid_access_token_round_trip():
    claims = decode_and_validate_access_token(
        _create_token(),
        signing_key=SIGNING_KEY,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    assert claims["sub"] == "user-123"
    assert claims["iss"] == ISSUER
    assert claims["aud"] == AUDIENCE
    assert claims["typ"] == "access"
    assert claims["ver"] == 0
    assert claims["jti"]


def test_access_token_embeds_supplied_version():
    claims = decode_and_validate_access_token(
        _create_token(version=9),
        signing_key=SIGNING_KEY,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    assert claims["ver"] == 9


def test_access_token_rejects_invalid_version_values():
    for value in (-1, True, "1"):
        with unittest.TestCase().assertRaises(ValueError):
            _create_token(version=value)


def test_expired_token_is_rejected():
    token = _create_token(lifetime=timedelta(seconds=-1))

    with unittest.TestCase().assertRaises(AccessTokenExpiredError):
        decode_and_validate_access_token(
            token,
            signing_key=SIGNING_KEY,
            issuer=ISSUER,
            audience=AUDIENCE,
        )


def test_wrong_signature_is_rejected():
    with unittest.TestCase().assertRaises(AccessTokenSignatureError):
        decode_and_validate_access_token(
            _create_token(),
            signing_key="test-alternate-signing-key-fedcba9876543210fedcba9876543210fedcba9876543210",
            issuer=ISSUER,
            audience=AUDIENCE,
        )


def test_wrong_issuer_or_audience_is_rejected():
    cases = [
        ({"issuer": "wrong-issuer"}, {"issuer": ISSUER, "audience": AUDIENCE}),
        ({"audience": "wrong-audience"}, {"issuer": ISSUER, "audience": AUDIENCE}),
    ]

    for arguments, validation in cases:
        with unittest.TestCase().assertRaises(AccessTokenClaimsError):
            decode_and_validate_access_token(
                _create_token(**arguments),
                signing_key=SIGNING_KEY,
                **validation,
            )


def test_wrong_token_type_is_rejected():
    token = _replace_claims(_create_token(), typ="refresh")

    with unittest.TestCase().assertRaises(AccessTokenClaimsError):
        decode_and_validate_access_token(
            token,
            signing_key=SIGNING_KEY,
            issuer=ISSUER,
            audience=AUDIENCE,
        )


def test_missing_required_claim_is_rejected():
    token = _create_token()
    claims = jwt.decode(
        token,
        SIGNING_KEY,
        algorithms=[ACCESS_TOKEN_ALGORITHM],
        audience=AUDIENCE,
        issuer=ISSUER,
    )
    del claims["jti"]
    token = jwt.encode(claims, SIGNING_KEY, algorithm=ACCESS_TOKEN_ALGORITHM)

    with unittest.TestCase().assertRaises(AccessTokenClaimsError):
        decode_and_validate_access_token(
            token,
            signing_key=SIGNING_KEY,
            issuer=ISSUER,
            audience=AUDIENCE,
        )


def test_unexpected_algorithm_is_rejected():
    token = jwt.encode(
        {
            "sub": "user-123",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": 1,
            "nbf": 1,
            "exp": 4_102_444_800,
            "jti": "test-id",
            "typ": "access",
        },
        SIGNING_KEY,
        algorithm="HS384",
    )

    with unittest.TestCase().assertRaises(AccessTokenAlgorithmError):
        decode_and_validate_access_token(
            token,
            signing_key=SIGNING_KEY,
            issuer=ISSUER,
            audience=AUDIENCE,
        )


def test_security_import_has_no_application_or_external_service_dependencies():
    blocked_roots = {
        "dotenv",
        "pymilvus",
        "requests",
        "sentence_transformers",
        "sqlalchemy",
    }
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".", 1)[0] in blocked_roots:
            raise AssertionError(f"Unexpected external dependency import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    sys.modules.pop("app.security", None)
    with patch("builtins.__import__", side_effect=guarded_import):
        imported = importlib.import_module("app.security")

    assert imported.ACCESS_TOKEN_ALGORITHM == "HS256"


def load_tests(loader, tests, pattern):
    """Expose the preserved function-style cases to unittest discovery."""

    suite = unittest.TestSuite()
    for name, test_case in sorted(globals().items()):
        if name.startswith("test_") and callable(test_case):
            suite.addTest(unittest.FunctionTestCase(test_case))
    return suite


if __name__ == "__main__":
    unittest.main()
