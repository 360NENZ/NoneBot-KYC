"""
NoneBot2 Real-Name Authentication Plugin
Requires: nonebot2, nonebot-adapter-onebot, httpx
"""

import re
import httpx
from nonebot import get_driver, on_command, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    PrivateMessageEvent,
    MessageSegment,
    Message,
)
from nonebot.params import CommandArg, ArgPlainText
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State
from nonebot.rule import to_me

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"  # Change to your API server address

driver = get_driver()

# ── Helpers ───────────────────────────────────────────────────────────────────
async def api_get(path: str, **kwargs):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}{path}", **kwargs)
        return resp

async def api_post(path: str, json: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_BASE}{path}", json=json)
        return resp

def mask_name(name: str) -> str:
    """Replace each character of name with *"""
    return "*" * len(name)

def mask_id(id_number: str) -> str:
    """Keep first and last digit, replace rest with *"""
    if not id_number or len(id_number) < 2:
        return id_number
    return id_number[0] + "*" * (len(id_number) - 2) + id_number[-1]

def format_user_info(user: dict, mask: bool = True) -> str:
    name = user.get("real_name") or "N/A"
    id_num = user.get("id_number") or "N/A"
    if mask and name != "N/A":
        name = mask_name(name)
    if mask and id_num != "N/A":
        id_num = mask_id(id_num)
    uid1 = user.get("uid1") or "none"
    uid2 = user.get("uid2") or "none"
    uid3 = user.get("uid3") or "none"
    inviter = user.get("inviter_id") or "none"
    invite_count = user.get("invite_count", 0)
    quota = user.get("invite_quota", 0)
    quota_str = "Unlimited" if quota == -1 else str(quota)
    status = user.get("auth_status", "Unverified")

    return (
        f"Your authentication status is: {status}\n"
        f"Your authentication details are:\n"
        f"Name: {name}\n"
        f"ID Number: {id_num}\n"
        f"Bound UID1: {uid1}\n"
        f"Bound UID2: {uid2}\n"
        f"Bound UID3: {uid3}\n"
        f"Number of Invites: {invite_count}\n"
        f"Inviter: {inviter}\n"
        f"Invitation Quota: {quota_str}"
    )

def extract_at_or_id(args: Message, event: Event) -> int | None:
    """Extract QQ ID from @mention or plain text argument."""
    for seg in args:
        if seg.type == "at":
            return int(seg.data["qq"])
    text = args.extract_plain_text().strip()
    if text.isdigit():
        return int(text)
    return None

# ── Commands ──────────────────────────────────────────────────────────────────

# help
help_cmd = on_command("help", aliases={"帮助"}, priority=10)

@help_cmd.handle()
async def handle_help(event: Event):
    msg = (
        "The following commands are available:\n"
        "getauth: Query your authentication status\n"
        "auth [Name] [ID Number]: Submit your authentication information\n"
        "binduid1 [UID]: Bind your primary UID\n"
        "binduid2 [UID]: Bind your secondary UID\n"
        "binduid3 [UID]: Bind your tertiary UID"
    )
    await help_cmd.finish(msg)


# getauth
getauth_cmd = on_command("getauth", priority=10)

@getauth_cmd.handle()
async def handle_getauth(bot: Bot, event: Event, args: Message = CommandArg()):
    sender_id = event.get_user_id()

    # Check if a target ID was provided
    target_id_raw = extract_at_or_id(args, event)
    if target_id_raw:
        # Only admins can query others
        sender_user_resp = await api_get(f"/user/{sender_id}")
        if sender_user_resp.status_code == 404:
            await getauth_cmd.finish("You have no record in the system.")
            return
        sender_user = sender_user_resp.json()
        is_superuser = str(sender_id) in driver.config.superusers
        if sender_user.get("auth_status") != "Admin" and not is_superuser:
            await getauth_cmd.finish("Insufficient privileges to query other users.")
            return
        target_id = target_id_raw
    else:
        target_id = int(sender_id)

    resp = await api_get(f"/user/{target_id}")
    if resp.status_code == 404:
        await getauth_cmd.finish("No record found for the specified user.")
        return

    user = resp.json()
    await getauth_cmd.finish(format_user_info(user, mask=True))


# auth
auth_cmd = on_command("auth", priority=10)

@auth_cmd.handle()
async def handle_auth(bot: Bot, event: Event, args: Message = CommandArg()):
    parts = args.extract_plain_text().strip().split()
    if len(parts) < 2:
        await auth_cmd.finish("Usage: auth [Name] [ID Number]")
        return

    name = parts[0]
    id_number = parts[1]

    if len(id_number) != 18 or not id_number[:17].isdigit():
        await auth_cmd.finish("Invalid ID number. Must be 18 digits.")
        return

    qq_id = int(event.get_user_id())

    # Check if user has an inviter set in the system
    user_resp = await api_get(f"/user/{qq_id}")
    inviter_id = None
    if user_resp.status_code == 200:
        inviter_id = user_resp.json().get("inviter_id")

    await auth_cmd.send("Submitting your authentication credentials...")

    payload = {
        "qq_id": qq_id,
        "real_name": name,
        "id_number": id_number,
        "inviter_id": inviter_id,
    }
    resp = await api_post("/auth/submit", payload)
    data = resp.json()

    if data.get("success"):
        await auth_cmd.finish("Submission successful! Please await administrator review.")
    else:
        await auth_cmd.finish(f"Submission failed! Error message: {data.get('message')}")


# binduid1 / binduid2 / binduid3
for slot in (1, 2, 3):
    _slot = slot  # closure capture

    cmd = on_command(f"binduid{slot}", priority=10)

    @cmd.handle()
    async def handle_binduid(bot: Bot, event: Event, args: Message = CommandArg(), _s=_slot, _cmd=cmd):
        uid = args.extract_plain_text().strip()
        if not uid:
            await _cmd.finish(f"Usage: binduid{_s} [UID]")
            return
        qq_id = int(event.get_user_id())
        resp = await api_post("/auth/binduid", {"qq_id": qq_id, "slot": _s, "uid": uid})
        if resp.status_code == 200:
            await _cmd.finish(f"UID{_s} bound successfully.")
        else:
            await _cmd.finish("Failed to bind UID.")


# setauthstats (Admin / Superuser only)
setauthstats_cmd = on_command("setauthstats", priority=10)

@setauthstats_cmd.handle()
async def handle_setauthstats(bot: Bot, event: Event, args: Message = CommandArg()):
    sender_id = int(event.get_user_id())
    is_superuser = str(sender_id) in driver.config.superusers

    if not is_superuser:
        # Check DB admin status
        resp = await api_get(f"/user/{sender_id}")
        if resp.status_code != 200 or resp.json().get("auth_status") != "Admin":
            await setauthstats_cmd.finish("Insufficient privileges.")
            return

    parts = args.extract_plain_text().strip().split()
    # Support: setauthstats [target_id_or_@] [status]
    # Or with @: segments contain at + text
    target_id = extract_at_or_id(args, event)
    if target_id:
        # Status is the plain text part
        text = args.extract_plain_text().strip()
        status = text.strip() if text else None
    else:
        if len(parts) < 2:
            await setauthstats_cmd.finish("Usage: setauthstats [@user or ID] [Status]")
            return
        target_id = int(parts[0]) if parts[0].isdigit() else None
        status = " ".join(parts[1:]) if target_id else None

    if not target_id or not status:
        await setauthstats_cmd.finish("Usage: setauthstats [@user or ID] [Status]")
        return

    payload = {"operator_id": sender_id, "target_id": target_id, "status": status}
    # Superusers bypass operator check – temporarily set operator as a known admin
    # For superusers, we allow directly via a special override flag
    if is_superuser:
        # Create/promote sender as admin first if needed
        await api_post("/auth/binduid", {"qq_id": sender_id, "slot": 1, "uid": ""})
        async with httpx.AsyncClient() as client:
            await client.post(f"{API_BASE}/auth/setstatus", json={
                "operator_id": sender_id,
                "target_id": sender_id,
                "status": "Admin",
            })
        # Now retry
        resp = await api_post("/auth/setstatus", payload)
    else:
        resp = await api_post("/auth/setstatus", payload)

    if resp.status_code == 200:
        await setauthstats_cmd.finish(f"Status updated successfully.")
    else:
        detail = resp.json().get("detail", "Unknown error")
        await setauthstats_cmd.finish(f"Failed: {detail}")


# invite
invite_cmd = on_command("invite", priority=10)

@invite_cmd.handle()
async def handle_invite(bot: Bot, event: Event, args: Message = CommandArg()):
    inviter_id = int(event.get_user_id())
    target_id = extract_at_or_id(args, event)
    if not target_id:
        await invite_cmd.finish("Usage: invite [@user or ID]")
        return

    resp = await api_post("/auth/invite", {"inviter_id": inviter_id, "target_id": target_id})
    if resp.status_code == 200:
        await invite_cmd.finish(f"Invitation sent to {target_id} successfully.")
    else:
        detail = resp.json().get("detail", "Unknown error")
        await invite_cmd.finish(f"Invitation failed: {detail}")


# admingetauth (private message only, Admin/Superuser)
admingetauth_cmd = on_command("admingetauth", priority=10)

@admingetauth_cmd.handle()
async def handle_admingetauth(bot: Bot, event: Event, args: Message = CommandArg()):
    # Must be private message
    if not isinstance(event, PrivateMessageEvent):
        await admingetauth_cmd.finish("This command can only be used in private messages.")
        return

    sender_id = int(event.get_user_id())
    is_superuser = str(sender_id) in driver.config.superusers

    if not is_superuser:
        resp = await api_get(f"/user/{sender_id}")
        if resp.status_code != 200 or resp.json().get("auth_status") != "Admin":
            await admingetauth_cmd.finish("Insufficient privileges.")
            return

    target_id = extract_at_or_id(args, event)
    if not target_id:
        text = args.extract_plain_text().strip()
        target_id = int(text) if text.isdigit() else None

    if not target_id:
        await admingetauth_cmd.finish("Usage: admingetauth [@user or ID]")
        return

    resp = await api_get(f"/user/{target_id}")
    if resp.status_code == 404:
        await admingetauth_cmd.finish("No record found for the specified user.")
        return

    user = resp.json()
    await admingetauth_cmd.finish(format_user_info(user, mask=False))
