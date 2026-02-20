"""
Real-Name Authentication API Server
FastAPI + MariaDB (via aiomysql)
"""

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import aiomysql
import os
from contextlib import asynccontextmanager
from datetime import datetime
import logging
import sys

# ── Configure logging ─────────────────────────────────────────────────────────
def setup_logging():
    # Clear all existing handlers
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    # Set up root logger with custom format that includes timestamps
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

setup_logging()

# ── Config ────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "auth_user"),
    "password": os.getenv("DB_PASSWORD", "auth_pass"),
    "db": os.getenv("DB_NAME", "auth_db"),
    "autocommit": True,
}

# Verification status list
AUTH_STATUSES = [
    "Unverified",
    "Pending Review", 
    "Verified",
    "Verified Enhanced",
    "Verified Exempt",
    "Banned",
    "Admin",
]
# Quotas: Unverified/Pending/Review/Verified/VerifiedEnhanced/VerifiedExempt/Banned/Admin
STATUS_QUOTA = {
    "Unverified": 0,
    "Pending Review": 0,
    "Verified": 0,
    "Verified Enhanced": 5,
    "Verified Exempt": 5,
    "Banned": 0,
    "Admin": -1,  # unlimited
}

# ── DB pool ───────────────────────────────────────────────────────────────────
pool: aiomysql.Pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await aiomysql.create_pool(**DB_CONFIG)
    yield
    pool.close()
    await pool.wait_closed()

app = FastAPI(title="Auth API", lifespan=lifespan)

# ── Helpers ───────────────────────────────────────────────────────────────────
async def get_user(qq_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM users WHERE qq_id=%s", (qq_id,))
            result = await cur.fetchone()
            if result:
                # Convert any byte strings to regular strings
                for key, value in result.items():
                    if isinstance(value, bytes):
                        result[key] = value.decode('utf-8')
            return result

async def ensure_user(qq_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT IGNORE INTO users (qq_id) VALUES (%s)", (qq_id,)
            )

# ── Models ───────────────────────────────────────────────────────────────────
class AuthSubmit(BaseModel):
    qq_id: int
    real_name: str
    id_number: str
    inviter_id: Optional[int] = None

class SetStatus(BaseModel):
    operator_id: int
    target_id: int
    status: str

class BindUID(BaseModel):
    qq_id: int
    slot: int  # 1, 2, or 3
    uid: str

class InviteRequest(BaseModel):
    inviter_id: int
    target_id: int

class InitAdminRequest(BaseModel):
    qq_id: int
    real_name: str = "System Admin"
    id_number: str = "123456789012345678"

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/user/{qq_id}")
async def get_user_info(qq_id: int):
    logging.info(f"GET /user/{qq_id}")
    user = await get_user(qq_id)
    if not user:
        logging.warning(f"User {qq_id} not found")
        raise HTTPException(404, "User not found")
    user["invite_quota"] = STATUS_QUOTA.get(user["auth_status"], 0)
    logging.info(f"Retrieved user {qq_id} info")
    return user


@app.post("/auth/submit")
async def submit_auth(data: AuthSubmit):
    logging.info(f"POST /auth/submit for QQ {data.qq_id}")
    
    # Validate ID number (18 chars, first 17 digits, last alphanumeric)
    if not (len(data.id_number) == 18 and data.id_number[:17].replace(' ', '').isdigit() and data.id_number[17].isalnum()):
        logging.warning(f"Invalid ID number for QQ {data.qq_id}")
        raise HTTPException(400, "ID number must be 18 characters with first 17 digits and last alphanumeric")

    await ensure_user(data.qq_id)

    # Check if user already has submitted info
    current_user = await get_user(data.qq_id)
    if current_user and current_user['auth_status'] != 'Unverified':
        logging.warning(f"User {data.qq_id} already submitted auth info")
        raise HTTPException(400, "You have already submitted authentication information.")

    # Check if user has an inviter (required for registration)
    if data.inviter_id is None:
        logging.warning(f"No inviter provided for QQ {data.qq_id}")
        raise HTTPException(400, "You must be invited by an existing user to register.")

    inviter = await get_user(data.inviter_id)
    if not inviter:
        logging.warning(f"Inviter {data.inviter_id} not found for QQ {data.qq_id}")
        raise HTTPException(400, "You are not an invited user and cannot register at this time.")

    quota = STATUS_QUOTA.get(inviter["auth_status"], 0)
    if quota == 0:
        logging.warning(f"Inviter {data.inviter_id} has no invitation privileges")
        raise HTTPException(400, "You are not an invited user and cannot register at this time.")
    if quota != -1 and inviter["invite_count"] >= quota:
        logging.warning(f"Inviter {data.inviter_id} reached invitation quota")
        raise HTTPException(400, "Inviter has reached their invitation quota.")

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE users SET real_name=%s, id_number=%s,
                   auth_status='Pending Review', inviter_id=%s
                   WHERE qq_id=%s""",
                (data.real_name, data.id_number, data.inviter_id, data.qq_id),
            )
            # Increment inviter count
            await cur.execute(
                "UPDATE users SET invite_count=invite_count+1 WHERE qq_id=%s",
                (data.inviter_id,),
            )
    logging.info(f"Auth submission successful for QQ {data.qq_id}")
    return {"success": True, "message": "Submission successful! Please await administrator review."}


@app.post("/auth/setstatus")
async def set_status(data: SetStatus):
    logging.info(f"POST /auth/setstatus: {data.operator_id} -> {data.target_id} as {data.status}")
    
    if data.status not in AUTH_STATUSES:
        logging.warning(f"Invalid status requested: {data.status}")
        raise HTTPException(400, f"Invalid status. Valid: {AUTH_STATUSES}")

    operator = await get_user(data.operator_id)
    if not operator or operator["auth_status"] not in ("Admin",):
        logging.warning(f"Insufficient privileges for operator {data.operator_id}")
        raise HTTPException(403, "Insufficient privileges")

    await ensure_user(data.target_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE users SET auth_status=%s WHERE qq_id=%s",
                (data.status, data.target_id),
            )
    logging.info(f"Status set successfully for QQ {data.target_id}")
    return {"success": True}


@app.post("/auth/binduid")
async def bind_uid(data: BindUID):
    logging.info(f"POST /auth/binduid: QQ {data.qq_id}, slot {data.slot}, UID {data.uid}")
    
    if data.slot not in (1, 2, 3):
        logging.warning(f"Invalid slot {data.slot} for QQ {data.qq_id}")
        raise HTTPException(400, "Slot must be 1, 2, or 3")
    col = f"uid{data.slot}"
    await ensure_user(data.qq_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE users SET {col}=%s WHERE qq_id=%s",
                (data.uid, data.qq_id),
            )
    logging.info(f"UID bound successfully for QQ {data.qq_id}")
    return {"success": True}


@app.post("/auth/invite")
async def invite_user(data: InviteRequest):
    logging.info(f"POST /auth/invite: {data.inviter_id} -> {data.target_id}")
    
    inviter = await get_user(data.inviter_id)
    if not inviter:
        logging.warning(f"Inviter {data.inviter_id} not found")
        raise HTTPException(404, "Inviter not found")

    quota = STATUS_QUOTA.get(inviter["auth_status"], 0)
    if quota == 0:
        logging.warning(f"Inviter {data.inviter_id} has no invitation privileges")
        raise HTTPException(403, "You do not have invitation privileges.")
    if quota != -1 and inviter["invite_count"] >= quota:
        logging.warning(f"Inviter {data.inviter_id} reached invitation quota")
        raise HTTPException(403, "You have reached your invitation quota.")

    target = await get_user(data.target_id)
    if target and target["inviter_id"] is not None:
        logging.warning(f"Target {data.target_id} already has an inviter")
        raise HTTPException(400, "Target user already has an inviter.")

    await ensure_user(data.target_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE users SET inviter_id=%s WHERE qq_id=%s AND inviter_id IS NULL",
                (data.inviter_id, data.target_id),
            )
    logging.info(f"Invite successful: {data.inviter_id} -> {data.target_id}")
    return {"success": True}


@app.post("/auth/initadmin")
async def init_admin(data: InitAdminRequest):
    """
    Special endpoint to initialize the first admin account.
    This bypasses normal invitation requirements.
    """
    logging.info(f"POST /auth/initadmin: QQ {data.qq_id}")
    
    # Ensure the user exists
    await ensure_user(data.qq_id)
    
    # Update user details including setting them as admin
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE users SET real_name=%s, id_number=%s, 
                   auth_status='Admin', inviter_id=%s
                   WHERE qq_id=%s""",
                (data.real_name, data.id_number, data.qq_id, data.qq_id),  # Self-invite
            )
    
    logging.info(f"Initialized admin account for QQ {data.qq_id}")
    return {"success": True, "message": "Admin account initialized successfully"}

if __name__ == "__main__":
    import uvicorn
    
    # Configure uvicorn to use our logging settings
    uvicorn.run(
        app, 
        host="127.0.0.1", 
        port=8000,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "()": "uvicorn.logging.DefaultFormatter",
                    "fmt": "%(asctime)s %(levelname)s | %(levelprefix)s %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": "INFO"},
                "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            }
        }
    )
