"""
Real-Name Authentication API Server
FastAPI + MariaDB (via aiomysql)

user IDs are stored as VARCHAR(64) to support both:
  - OneBot V11: traditional integer QQ numbers (stored as strings)
  - QQ Official Bot: openid strings (alphanumeric, non-integer)
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import aiomysql
import os
from contextlib import asynccontextmanager
import logging
import sys

# ── Configure logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "auth_user"),
    "password": os.getenv("DB_PASSWORD", "auth_pass"),
    "db": os.getenv("DB_NAME", "auth_db"),
    "autocommit": True,
}

AUTH_STATUSES = [
    "Unverified",
    "Pending Review",
    "Verified",
    "Verified Enhanced",
    "Verified Exempt",
    "Banned",
    "Admin",
]

STATUS_QUOTA: dict[str, int] = {
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
    logger.info("Database pool created.")
    yield
    pool.close()
    await pool.wait_closed()
    logger.info("Database pool closed.")


app = FastAPI(title="Auth API", lifespan=lifespan)

# ── DB helpers ────────────────────────────────────────────────────────────────

async def get_user(qq_id: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM users WHERE qq_id=%s", (qq_id,))
            row = await cur.fetchone()
            if row:
                # Decode any byte values (charset safety)
                return {k: (v.decode("utf-8") if isinstance(v, bytes) else v) for k, v in row.items()}
            return None


async def ensure_user(qq_id: str) -> None:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT IGNORE INTO users (qq_id) VALUES (%s)", (qq_id,))

# ── Request models ────────────────────────────────────────────────────────────

class AuthSubmit(BaseModel):
    qq_id: str
    real_name: str
    id_number: str
    inviter_id: Optional[str] = None


class SetStatus(BaseModel):
    operator_id: str
    target_id: str
    status: str
    force: bool = False   # True → superuser bypass (no DB admin check needed)


class BindUID(BaseModel):
    qq_id: str
    slot: int   # 1, 2, or 3
    uid: str


class InviteRequest(BaseModel):
    inviter_id: str
    target_id: str


class InitAdminRequest(BaseModel):
    qq_id: str
    real_name: str = "System Admin"
    id_number: str = "123456789012345678"

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/user/{qq_id}")
async def get_user_info(qq_id: str):
    logger.info(f"GET /user/{qq_id}")
    user = await get_user(qq_id)
    if not user:
        raise HTTPException(404, "User not found")
    user["invite_quota"] = STATUS_QUOTA.get(user["auth_status"], 0)
    return user


@app.post("/auth/submit")
async def submit_auth(data: AuthSubmit):
    logger.info(f"POST /auth/submit for {data.qq_id}")

    # Validate ID number: 18 chars, first 17 digits, last alphanumeric
    if not (len(data.id_number) == 18
            and data.id_number[:17].isdigit()
            and data.id_number[17].isalnum()):
        raise HTTPException(400, "ID number must be 18 characters (17 digits + 1 alphanumeric)")

    await ensure_user(data.qq_id)

    current = await get_user(data.qq_id)
    if current and current["auth_status"] != "Unverified":
        raise HTTPException(400, "You have already submitted authentication information.")

    # Invitation is required
    if not data.inviter_id:
        raise HTTPException(
            400,
            "You are not an invited user and cannot register at this time.",
        )

    inviter = await get_user(data.inviter_id)
    if not inviter:
        raise HTTPException(
            400,
            "You are not an invited user and cannot register at this time.",
        )

    quota = STATUS_QUOTA.get(inviter["auth_status"], 0)
    if quota == 0:
        raise HTTPException(
            400,
            "You are not an invited user and cannot register at this time.",
        )
    if quota != -1 and inviter["invite_count"] >= quota:
        raise HTTPException(400, "Inviter has reached their invitation quota.")

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE users
                   SET real_name=%s, id_number=%s, auth_status='Pending Review', inviter_id=%s
                   WHERE qq_id=%s""",
                (data.real_name, data.id_number, data.inviter_id, data.qq_id),
            )
            await cur.execute(
                "UPDATE users SET invite_count = invite_count + 1 WHERE qq_id=%s",
                (data.inviter_id,),
            )

    logger.info(f"Auth submission successful for {data.qq_id}")
    return {"success": True, "message": "Submission successful! Please await administrator review."}


@app.post("/auth/setstatus")
async def set_status(data: SetStatus):
    logger.info(f"POST /auth/setstatus: {data.operator_id} -> {data.target_id} as '{data.status}' (force={data.force})")

    if data.status not in AUTH_STATUSES:
        raise HTTPException(400, f"Invalid status. Valid values: {AUTH_STATUSES}")

    # force=True is used by NoneBot superusers and bypasses the DB admin check
    if not data.force:
        operator = await get_user(data.operator_id)
        if not operator or operator["auth_status"] != "Admin":
            raise HTTPException(403, "Insufficient privileges")

    await ensure_user(data.target_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE users SET auth_status=%s WHERE qq_id=%s",
                (data.status, data.target_id),
            )

    logger.info(f"Status updated for {data.target_id}: {data.status}")
    return {"success": True}


@app.post("/auth/binduid")
async def bind_uid(data: BindUID):
    logger.info(f"POST /auth/binduid: {data.qq_id} slot={data.slot} uid={data.uid}")
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
    logger.info(f"POST /auth/invite: {data.inviter_id} -> {data.target_id}")

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

    logger.info(f"Invite successful: {data.inviter_id} -> {data.target_id}")
    return {"success": True}


@app.post("/auth/initadmin")
async def init_admin(data: InitAdminRequest):
    """
    Bootstrap endpoint: creates the very first admin account.
    Bypasses invitation requirements intentionally.
    Should be called once by the NoneBot superuser via the `initadmin` command.
    """
    logger.info(f"POST /auth/initadmin: {data.qq_id}")
    await ensure_user(data.qq_id)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE users
                   SET real_name=%s, id_number=%s, auth_status='Admin', inviter_id=%s
                   WHERE qq_id=%s""",
                (data.real_name, data.id_number, data.qq_id, data.qq_id),
            )
    return {"success": True, "message": "Admin account initialised successfully."}


if __name__ == "__main__":
    import uvicorn
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
            },
        },
    )
