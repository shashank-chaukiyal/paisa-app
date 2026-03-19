"""
app/api/v1/auth.py

Fixes applied:
  - Fix #4:  enroll_biometric now uses Depends(get_current_user) — was
             Depends(lambda: None) which ALWAYS injected None, causing
             AttributeError on every enrollment attempt.
  - Fix #10: Login timing attack fixed — bcrypt always runs even for
             non-existent phone numbers using a dummy hash constant.
             Previously, short-circuit evaluation skipped bcrypt for
             unknown phones, leaking valid phone numbers via response time.
  - Fix #20: Removed __import__("sqlalchemy") anti-pattern — replaced with
             proper top-level import and ORM attribute access.
  - Fix #20: biometric_public_key now accessed via ORM (added to User model)
             instead of raw SQL via dynamic import.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature
from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.transaction import User, RefreshToken

log = structlog.get_logger(__name__)
router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# Fix #10: Pre-computed dummy hash for constant-time comparison on unknown phones.
# This ensures bcrypt always runs regardless of whether the phone exists,
# preventing timing-based phone number enumeration attacks.
_DUMMY_HASH: str = pwd_ctx.hash("__paisa_dummy_sentinel__")


# ─── Schemas ──────────────────────────────────────────────────────────

class PhoneLoginRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    pin: str = Field(..., min_length=4, max_length=8)
    device_id: str = Field(..., min_length=1, max_length=255)
    fcm_token: Optional[str] = Field(None, max_length=512)


class RegisterRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    pin: str = Field(..., min_length=4, max_length=8)
    display_name: Optional[str] = Field(None, max_length=100)


class BiometricEnrollRequest(BaseModel):
    public_key: str  # Base64 PEM-encoded ECDSA P-256 public key from device Secure Enclave


class BiometricLoginRequest(BaseModel):
    user_id: str
    payload: str        # "{user_id}:{timestamp_ms}" — the signed string
    signature: str      # Base64 ECDSA signature
    device_id: str
    fcm_token: Optional[str] = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


class RefreshRequest(BaseModel):
    refresh_token: str
    device_id: str


# ─── Token helpers ────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": exp, "iat": datetime.utcnow()},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _issue_refresh_token(user: User, device_id: str, db: AsyncSession) -> str:
    raw = secrets.token_urlsafe(48)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(raw),
        device_id=device_id,
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)
    await db.flush()
    return raw


async def _get_user_by_phone(phone: str, db: AsyncSession) -> Optional[User]:
    result = await db.execute(
        select(User).where(User.phone == phone, User.is_active == True)
    )
    return result.scalar_one_or_none()


# ─── Routes ───────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await _get_user_by_phone(body.phone, db)
    if existing:
        raise HTTPException(status_code=409, detail="Phone number already registered")

    user = User(
        id=uuid.uuid4(),
        phone=body.phone,
        pin_hash=pwd_ctx.hash(body.pin),
        display_name=body.display_name,
    )
    db.add(user)
    await db.flush()

    access = create_access_token(str(user.id))
    refresh = await _issue_refresh_token(user, "registration", db)
    await db.commit()

    log.info("auth.registered", user_id=str(user.id), phone=body.phone[-4:])
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenPair)
async def login(body: PhoneLoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Fix #10: Timing-attack-safe login.

    BEFORE (vulnerable):
        if not user or not user.pin_hash or not pwd_ctx.verify(...):
        Short-circuit meant bcrypt was SKIPPED for unknown phone numbers.
        Response time: ~1ms for unknown phone, ~300ms for known phone.
        An attacker could enumerate valid phone numbers by measuring latency.

    AFTER (fixed):
        bcrypt ALWAYS runs — using a dummy hash when the user doesn't exist.
        Response time is consistently ~300ms regardless of phone validity.
    """
    user = await _get_user_by_phone(body.phone, db)

    # Always run bcrypt — use dummy hash for non-existent users
    hash_to_check = user.pin_hash if (user and user.pin_hash) else _DUMMY_HASH
    pin_valid = pwd_ctx.verify(body.pin, hash_to_check)

    # Only succeed if BOTH the user exists AND the pin is correct
    if not user or not pin_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if body.fcm_token:
        user.fcm_token = body.fcm_token
        await db.flush()

    access = create_access_token(str(user.id))
    refresh = await _issue_refresh_token(user, body.device_id, db)
    await db.commit()

    log.info("auth.login_success", user_id=str(user.id))
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Rotate refresh token — old token is revoked, new pair issued."""
    token_hash = _hash_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at == None,
            RefreshToken.expires_at > datetime.utcnow(),
        )
    )
    rt = result.scalar_one_or_none()

    if not rt:
        log.warning("auth.refresh_invalid", device_id=body.device_id)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    rt.revoked_at = datetime.utcnow()
    await db.flush()

    user_result = await db.execute(
        select(User).where(User.id == rt.user_id, User.is_active == True)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    access = create_access_token(str(user.id))
    new_refresh = await _issue_refresh_token(user, body.device_id, db)
    await db.commit()

    log.info("auth.token_rotated", user_id=str(user.id))
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/biometric/enroll")
async def enroll_biometric(
    body: BiometricEnrollRequest,
    db: AsyncSession = Depends(get_db),
    # Fix #4: was Depends(lambda db=Depends(get_db): None)
    # which ALWAYS returned None, causing AttributeError on every call.
    user: User = Depends(get_current_user),
):
    """Store device ECDSA public key for signature-based auth."""
    # Validate it's a real PEM public key before storing
    try:
        pem = base64.b64decode(body.public_key)
        serialization.load_pem_public_key(pem)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid public key format")

    # Fix #20: Use ORM attribute instead of raw SQL via __import__
    user.biometric_enabled = True
    user.biometric_public_key = body.public_key   # column added to User model
    await db.commit()

    log.info("auth.biometric_enrolled", user_id=str(user.id))
    return {"status": "enrolled"}


@router.post("/biometric/login", response_model=TokenPair)
async def biometric_login(body: BiometricLoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate via ECDSA signature.
    1. Load user's stored public key
    2. Verify signature of payload
    3. Verify payload contains recent timestamp (replay protection, 60s window)
    """
    try:
        user_uuid = uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    # Fix #20: Use ORM query instead of __import__("sqlalchemy").text(...)
    result = await db.execute(
        select(User).where(User.id == user_uuid, User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if not user or not user.biometric_enabled or not user.biometric_public_key:
        raise HTTPException(status_code=401, detail="Biometric not enrolled")

    # Replay protection: payload must be "{user_id}:{timestamp_ms}" within 60s
    try:
        parts = body.payload.split(":")
        ts_ms = int(parts[-1])
        age_s = (datetime.utcnow().timestamp() * 1000 - ts_ms) / 1000
        if abs(age_s) > 60:
            raise ValueError(f"Payload too old: {age_s:.0f}s")
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid payload: {exc}")

    # Verify ECDSA signature
    try:
        pem = base64.b64decode(user.biometric_public_key)
        pub_key = serialization.load_pem_public_key(pem)
        sig = base64.b64decode(body.signature)
        pub_key.verify(sig, body.payload.encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        log.warning("auth.biometric_invalid_signature", user_id=body.user_id)
        raise HTTPException(status_code=401, detail="Invalid biometric signature")
    except Exception as exc:
        log.error("auth.biometric_verify_error", error=str(exc))
        raise HTTPException(status_code=401, detail="Biometric verification failed")

    access = create_access_token(str(user_uuid))
    refresh = await _issue_refresh_token(user, body.device_id, db)
    await db.commit()

    log.info("auth.biometric_login_success", user_id=body.user_id)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/logout")
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_hash = _hash_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()
    if rt:
        rt.revoked_at = datetime.utcnow()
        await db.commit()
    return {"status": "logged_out"}
