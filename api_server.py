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

# ── Config ────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "auth_user"),
    "password": os.getenv("DB_PASSWORD", "auth_pass"),
    "db": os.getenv("DB_NAME", "auth_db"),
    "autocommit": True,
}

# Verification status list (index maps to quota list below)
AUTH_STATUSES = [
    "Unverified",
    "Pending Review",
    "Verified",
    "Verified Enhanced",
    "Verified Exempt",
    "Banned",
    "Admin",
]
# Quotas: Unverified/Pending/Verified/VerifiedEnhanced/VerifiedExempt/Banned/Admin
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
    # Ensure table exists
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    qq_id BIGINT PRIMARY KEY,
                    real_name VARCHAR(64),
                    id_number CHAR(18),
                    uid1 VARCHAR(64),
                    uid2 VARCHAR(64),
                    uid3 VARCHAR(64),
                    auth_status VARCHAR(32) DEFAULT 'Unverified',
                    inviter_id BIGINT DEFAULT NULL,
                    invite_count INT DEFAULT 0
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
    yield
    pool.close()
    await pool.wait_closed()

app = FastAPI(title="Auth API", lifespan=lifespan)

# ── Helpers ───────────────────────────────────────────────────────────────────
async def get_user(qq_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM users WHERE qq_id=%s", (qq_id,))
            return await cur.fetchone()

async def ensure_user(qq_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT IGNORE INTO users (qq_id) VALUES (%s)", (qq_id,)
            )

# ── Models ────────────────────────────────────────────────────────────────────
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

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/user/{qq_id}")
async def get_user_info(qq_id: int):
    user = await get_user(qq_id)
    if not user:
        raise HTTPException(404, "User not found")
    user["invite_quota"] = STATUS_QUOTA.get(user["auth_status"], 0)
    return user


@app.post("/auth/submit")
async def submit_auth(data: AuthSubmit):
    # Validate ID number (18 digits)
    if not (len(data.id_number) == 18 and data.id_number[:17].isdigit()):
        raise HTTPException(400, "ID number must be 18 characters")

    await ensure_user(data.qq_id)

    # Check inviter
    if data.inviter_id is None:
        return {"success": False, "message": "You are not an invited user and cannot register at this time."}

    inviter = await get_user(data.inviter_id)
    if not inviter:
        return {"success": False, "message": "You are not an invited user and cannot register at this time."}

    quota = STATUS_QUOTA.get(inviter["auth_status"], 0)
    if quota == 0:
        return {"success": False, "message": "You are not an invited user and cannot register at this time."}
    if quota != -1 and inviter["invite_count"] >= quota:
        return {"success": False, "message": "Inviter has reached their invitation quota."}

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
    return {"success": True, "message": "Submission successful! Please await administrator review."}


@app.post("/auth/setstatus")
async def set_status(data: SetStatus):
    if data.status not in AUTH_STATUSES:
        raise HTTPException(400, f"Invalid status. Valid: {AUTH_STATUSES}")

    operator = await get_user(data.operator_id)
    if not operator or operator["auth_status"] not in ("Admin",):
        raise HTTPException(403, "Insufficient privileges")

    await ensure_user(data.target_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE users SET auth_status=%s WHERE qq_id=%s",
                (data.status, data.target_id),
            )
    return {"success": True}


@app.post("/auth/binduid")
async def bind_uid(data: BindUID):
    if data.slot not in (1, 2, 3):
        raise HTTPException(400, "Slot must be 1, 2, or 3")
    col = f"uid{data.slot}"
    await ensure_user(data.qq_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE users SET {col}=%s WHERE qq_id=%s",
                (data.uid, data.qq_id),
            )
    return {"success": True}


@app.post("/auth/invite")
async def invite_user(data: InviteRequest):
    inviter = await get_user(data.inviter_id)
    if not inviter:
        raise HTTPException(404, "Inviter not found")

    quota = STATUS_QUOTA.get(inviter["auth_status"], 0)
    if quota == 0:
        raise HTTPException(403, "You do not have invitation privileges.")
    if quota != -1 and inviter["invite_count"] >= quota:
        raise HTTPException(403, "You have reached your invitation quota.")

    target = await get_user(data.target_id)
    if target and target["inviter_id"] is not None:
        raise HTTPException(400, "Target user already has an inviter.")

    await ensure_user(data.target_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE users SET inviter_id=%s WHERE qq_id=%s AND inviter_id IS NULL",
                (data.inviter_id, data.target_id),
            )
    return {"success": True}
