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

> **Upgrading from an earlier version?**  
> The `qq_id` and `inviter_id` columns changed from `BIGINT` to `VARCHAR(64)`.  
> Run the migration snippet at the bottom of `schema.sql` before starting the server.

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
uvicorn api_server:app --host 127.0.0.1 --port 8000
```

### 3. NoneBot2 Plugin

**Install dependencies — choose your adapter(s):**
```bash
pip install nonebot2 httpx

# OneBot V11 (Lagrange, go-cqhttp, etc.)
pip install nonebot-adapter-onebot

# QQ Official Bot
pip install nonebot-adapter-qq
```

> Both adapters can be installed and loaded simultaneously.  
> The plugin detects which adapter is present at runtime using optional imports.

Place `auth_plugin.py` in your NoneBot2 plugins directory and load it:

```python
# bot.py
import nonebot
nonebot.init()
nonebot.load_plugin("auth_plugin")
```

Set your superusers in `.env`:
```
SUPERUSERS=["123456789"]   # Owner QQ number (OneBot) or openid (QQ Official)
```

Update `API_BASE` in `auth_plugin.py` if the API server runs on a different host/port.

---

## Adapter Notes

| Feature | OneBot V11 | QQ Official Bot |
|---|---|---|
| User ID format | Integer QQ number | String openid |
| Group trigger | All messages | Bot must be @mentioned |
| Private message | `PrivateMessageEvent` | `DirectMessageCreateEvent` / `C2CMessageCreateEvent` |
| @mention segment | `type="at"` | `type="mention_user"` |

**QQ Official Bot group messages:**  
The bot only receives messages in which it is @mentioned. Users must `@Bot [command]` in groups; the plugin automatically strips the leading bot mention before matching commands.

**User IDs:**  
Both adapters call `event.get_user_id()` which returns a string in both cases. The database stores IDs as `VARCHAR(64)`, so traditional QQ numbers and openids work without modification.

---

## Commands

| Command | Description |
|---|---|
| `help` | Show command list |
| `auth [Name] [ID]` | Submit real-name authentication |
| `getauth` | Query your own auth status (masked) |
| `getauth [@user\|ID]` | Query another user's status (Admin only, masked) |
| `admingetauth [@user\|ID]` | Query full unmasked info (Admin/Owner, **private only**) |
| `setauthstats [@user\|ID] [Status]` | Set user's auth status (Admin/Owner) |
| `invite [@user\|ID]` | Invite a user to register |
| `binduid1 [UID]` | Bind primary UID |
| `binduid2 [UID]` | Bind secondary UID |
| `binduid3 [UID]` | Bind tertiary UID |
| `initadmin` | Bootstrap first admin account (Owner only) |

## Auth Statuses & Invitation Quotas

| Status | Invitation Quota |
|---|---|
| Unverified | 0 |
| Pending Review | 0 |
| Verified | 0 |
| Verified Enhanced | 5 |
| Verified Exempt | 5 |
| Banned | 0 |
| Admin | Unlimited |

## Notes
- ID numbers must be exactly 18 characters (17 digits + 1 alphanumeric check digit).
- `getauth` masks name as `***` and ID as `X*******X`.
- `admingetauth` shows full unmasked details and is **restricted to private messages**.
- The NoneBot owner (superuser) bypasses all privilege checks and can set any status even without a DB Admin record.
- Use `initadmin` once after first deployment to grant yourself Admin status in the database.
