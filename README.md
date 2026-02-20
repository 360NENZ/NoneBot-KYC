# Real-Name Authentication System

[English](README.md) | [简体中文](README_zh-CN.md)

## Files
- `api_server.py` — FastAPI backend (connects to MariaDB)
- `auth_plugin.py` — NoneBot2 plugin
- `schema.sql` — MariaDB schema

---

## Setup

### 1. Database
```bash
mysql -u root -p < schema.sql
```

### 2. API Server

**Install dependencies:**
```bash
pip install fastapi uvicorn aiomysql httpx
```

**Configure via environment variables:**
```bash
export DB_HOST=127.0.0.1
export DB_PORT=3306
export DB_USER=auth_user
export DB_PASSWORD=auth_pass
export DB_NAME=auth_db
```

**Run:**
```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

### 3. NoneBot2 Plugin

**Install dependencies:**
```bash
pip install nonebot2 nonebot-adapter-onebot httpx
```

Place `auth_plugin.py` in your NoneBot2 plugins directory and add it to `pyproject.toml` or `bot.py`:

```python
# bot.py
import nonebot
nonebot.init()
nonebot.load_plugin("auth_plugin")  # or use plugins directory
```

Set your superusers in `.env`:
```
SUPERUSERS=["123456789"]  # Owner QQ ID(s)
```

Update `API_BASE` in `auth_plugin.py` to point to your API server if it runs on a different host/port.

---

## Commands

| Command | Description |
|---|---|
| `help` | Show command list |
| `auth [Name] [ID]` | Submit real-name authentication |
| `getauth` | Query your own auth status (masked) |
| `getauth [@user\|ID]` | Query another user's status (Admin only, masked) |
| `admingetauth [@user\|ID]` | Query full unmasked info (Admin/Owner, private only) |
| `setauthstats [@user\|ID] [Status]` | Set user's auth status (Admin/Owner) |
| `invite [@user\|ID]` | Invite a user to register |
| `binduid1 [UID]` | Bind primary UID |
| `binduid2 [UID]` | Bind secondary UID |
| `binduid3 [UID]` | Bind tertiary UID |

## Auth Statuses & Invitation Quotas

| Status | Quota |
|---|---|
| Unverified | 0 |
| Pending Review | 0 |
| Verified | 0 |
| Verified Enhanced | 5 |
| Verified Exempt | 5 |
| Banned | 0 |
| Admin | Unlimited |

## Notes
- ID numbers must be exactly 18 characters (17 digits + 1 alphanumeric check digit)
- `getauth` masks name as `***` and ID as `X*******X`
- `admingetauth` shows full details and is restricted to private messages
- The NoneBot owner (superuser) has the highest privileges and bypasses all checks
