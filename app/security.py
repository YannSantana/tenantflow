from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

hasher = PasswordHasher()
dummy_hash = hasher.hash("senha-ficticia-para-comparacao")


def verify_password(password, stored_hash):
    try:
        return hasher.verify(stored_hash or dummy_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def token_for(user, settings):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user.id, "tenant": user.tenant_id, "iat": now,
                       "exp": now + timedelta(minutes=settings.token_minutes),
                       "iss": "tenantflow", "aud": "tenantflow-api"}, settings.jwt_secret, algorithm="HS256")


def decode_token(token, settings):
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"],
                      issuer="tenantflow", audience="tenantflow-api",
                      options={"require": ["sub", "tenant", "exp", "iat"]})
