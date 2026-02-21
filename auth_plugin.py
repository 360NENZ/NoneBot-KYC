"""
NoneBot2 实名认证插件
支持 OneBot V11 (nonebot-adapter-onebot) 和 QQ 官方机器人 (nonebot-adapter-qq) 适配器。

Supports both OneBot V11 and QQ Official Bot adapters simultaneously.
"""

import re
import httpx
from nonebot import on_regex, get_driver
from nonebot.typing import T_State

# ── 使用 nonebot.adapters 基类，避免绑定到特定适配器 ─────────────────────────
from nonebot.adapters import Bot, Event, Message

# ── 按需导入各适配器的私聊/DM 事件类型，用于 isinstance 检查 ─────────────────
# OneBot V11
try:
    from nonebot.adapters.onebot.v11 import PrivateMessageEvent as _OBPrivateMsg
    _HAS_ONEBOT = True
except ImportError:
    _OBPrivateMsg = None
    _HAS_ONEBOT = False

# QQ 官方机器人适配器
try:
    from nonebot.adapters.qq import (
        DirectMessageCreateEvent as _QQDirectMsg,   # 频道私信
        C2CMessageCreateEvent as _QQC2CMsg,         # 单聊（好友）消息
    )
    _HAS_QQ = True
except ImportError:
    _QQDirectMsg = None
    _QQC2CMsg = None
    _HAS_QQ = False

# ── 配置 ────────────────────────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"  # 更改为你的 API 服务器地址

driver = get_driver()

# ── 适配器兼容辅助函数 ───────────────────────────────────────────────────────

def is_private_event(event: Event) -> bool:
    """判断事件是否为私聊/单聊（兼容 OneBot V11 和 QQ 官方适配器）"""
    if _HAS_ONEBOT and _OBPrivateMsg and isinstance(event, _OBPrivateMsg):
        return True
    if _HAS_QQ:
        if _QQDirectMsg and isinstance(event, _QQDirectMsg):
            return True
        if _QQC2CMsg and isinstance(event, _QQC2CMsg):
            return True
    return False


def get_sender_id(event: Event) -> str:
    """获取发送者 ID 字符串（OneBot V11 返回 QQ 号，QQ 官方适配器返回 openid）"""
    return event.get_user_id()


def get_plain_text(event: Event) -> str:
    """
    从消息中提取纯文本（忽略 @mention 等非文本 segment）。
    用于 regex 匹配，避免因 CQ 码或 mention_user segment 字符串格式不同导致匹配失败。
    QQ 官方适配器群消息开头的机器人 @ 也会被正确跳过。
    """
    parts = []
    for seg in event.get_message():
        if seg.type == "text":
            parts.append(seg.data.get("text", ""))
    return "".join(parts).strip()


def extract_mention_id(event: Event) -> str | None:
    """
    从消息 segments 中提取被 @ 的用户 ID（返回字符串）。
    - OneBot V11：segment.type == "at"，data["qq"] 为 QQ 号
    - QQ 官方适配器：segment.type == "mention_user"，data["user_id"] 为 openid
    """
    sender_id = get_sender_id(event)
    for seg in event.get_message():
        # OneBot V11
        if seg.type == "at":
            try:
                uid = str(seg.data["qq"])
                # 跳过 @全体成员 和 @机器人自身（OneBot 用 "all" 表示全体）
                if uid not in ("all", "0"):
                    return uid
            except (KeyError, ValueError):
                pass
        # QQ 官方适配器
        elif seg.type == "mention_user":
            try:
                uid = str(seg.data["user_id"])
                # 跳过机器人自身的 mention（QQ 官方群消息第一个 mention 通常是机器人）
                return uid  # 调用方自行过滤机器人 ID（如需要）
            except (KeyError, ValueError):
                pass
    return None


def get_event_key(event: Event) -> str:
    """生成事件唯一键用于去重，兼容两种适配器（不依赖 event.time）"""
    try:
        ts = getattr(event, "time", None) or getattr(event, "timestamp", None) or ""
    except Exception:
        ts = ""
    return f"{event.get_session_id()}_{hash(str(event.get_message()))}_{ts}"

# ── API 辅助函数 ─────────────────────────────────────────────────────────────

async def api_get(path: str) -> httpx.Response | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{API_BASE}{path}")
            return resp
    except Exception as e:
        print(f"[ERROR] API GET 请求失败 ({path}): {e}")
        return None


async def api_post(path: str, json_data: dict) -> httpx.Response | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{API_BASE}{path}", json=json_data)
            return resp
    except Exception as e:
        print(f"[ERROR] API POST 请求失败 ({path}): {e}")
        return None

# ── 数据格式化辅助函数 ────────────────────────────────────────────────────────

def mask_name(name: str) -> str:
    return "*" * len(name)


def mask_id(id_number: str) -> str:
    if not id_number or len(id_number) < 2:
        return id_number
    return id_number[0] + "*" * (len(id_number) - 2) + id_number[-1]


def format_auth_status(status: str) -> str:
    status_map = {
        "Unverified": "未认证",
        "Pending Review": "待审核",
        "Verified": "已认证",
        "Verified Enhanced": "已认证 加强版",
        "Verified Exempt": "已认证 豁免",
        "Banned": "已封禁",
        "Admin": "管理员",
    }
    return status_map.get(status, status)


def format_user_info(user: dict, mask: bool = True) -> str:
    name = user.get("real_name") or "N/A"
    id_num = user.get("id_number") or "N/A"
    if mask and name != "N/A":
        name = mask_name(name)
    if mask and id_num != "N/A":
        id_num = mask_id(id_num)
    uid1 = user.get("uid1") or "None"
    uid2 = user.get("uid2") or "None"
    uid3 = user.get("uid3") or "None"
    inviter = user.get("inviter_id") or "None"
    invite_count = user.get("invite_count", 0)
    quota = user.get("invite_quota", 0)
    quota_str = "无限制" if quota == -1 else str(quota)
    status = user.get("auth_status", "Unverified")
    return (
        f"身份认证状态：{format_auth_status(status)}\n"
        f"认证信息：\n"
        f"姓名：{name}\n"
        f"身份证号：{id_num}\n"
        f"绑定的UID1：{uid1}\n"
        f"绑定的UID2：{uid2}\n"
        f"绑定的UID3：{uid3}\n"
        f"已邀请人数：{invite_count}\n"
        f"邀请人: {inviter}\n"
        f"邀请最大限额: {quota_str}"
    )

# ── 去重缓存 ─────────────────────────────────────────────────────────────────
_processed_events: set[str] = set()

# ── 命令：help ───────────────────────────────────────────────────────────────
help_handler = on_regex(r"^(help|帮助)$", priority=1, block=True)

@help_handler.handle()
async def handle_help(bot: Bot, event: Event):
    key = get_event_key(event)
    if key in _processed_events:
        return
    _processed_events.add(key)
    try:
        await bot.send(event, (
            "以下是可用的命令：\n"
            "getauth: 查询您的身份认证状态\n"
            "auth [姓名] [身份证号]: 提交您的身份认证信息\n"
            "binduid1 [UID]: 绑定您的一号UID\n"
            "binduid2 [UID]: 绑定您的二号UID\n"
            "binduid3 [UID]: 绑定您的三号UID\n"
            "invite [@用户|ID]: 邀请用户注册\n"
            "setauthstats [@用户|ID] [状态]: 设置用户认证状态（管理员专用）\n"
            "admingetauth [@用户|ID]: 查询完整未脱敏信息（管理员专用，私聊）\n"
            "initadmin: 初始化管理员账户（超级用户专用）"
        ))
    finally:
        _processed_events.discard(key)

# ── 命令：initadmin ──────────────────────────────────────────────────────────
initadmin_handler = on_regex(r"^initadmin$", priority=1, block=True)

@initadmin_handler.handle()
async def handle_initadmin(bot: Bot, event: Event):
    key = get_event_key(event)
    if key in _processed_events:
        return
    _processed_events.add(key)
    try:
        sender_id = get_sender_id(event)
        if sender_id not in driver.config.superusers:
            await bot.send(event, "只有超级用户可以初始化管理员账户。")
            return
        resp = await api_post("/auth/initadmin", {"qq_id": sender_id})
        if not resp:
            await bot.send(event, "无法连接到认证服务器。")
            return
        if resp.status_code == 200:
            await bot.send(event, resp.json().get("message", "管理员账户初始化成功。"))
        else:
            detail = _extract_detail(resp)
            await bot.send(event, f"初始化失败: {detail}")
    finally:
        _processed_events.discard(key)

# ── 命令：getauth ─────────────────────────────────────────────────────────────
getauth_handler = on_regex(r"^getauth(\s+\S+)?$", priority=1, block=True)

@getauth_handler.handle()
async def handle_getauth(bot: Bot, event: Event):
    key = get_event_key(event)
    if key in _processed_events:
        return
    _processed_events.add(key)
    try:
        sender_id = get_sender_id(event)
        plain = get_plain_text(event)

        # 尝试提取目标：先检查 @mention，再检查文本参数
        target_id = extract_mention_id(event)
        if target_id is None:
            m = re.match(r"^getauth\s+(\S+)$", plain)
            if m:
                target_id = m.group(1)

        # 查询他人时需要管理员权限
        if target_id and target_id != sender_id:
            is_superuser = sender_id in driver.config.superusers
            if not is_superuser:
                sr = await api_get(f"/user/{sender_id}")
                if not sr or sr.status_code != 200 or sr.json().get("auth_status") != "Admin":
                    await bot.send(event, "权限不足。")
                    return
        else:
            target_id = sender_id

        resp = await api_get(f"/user/{target_id}")
        if not resp or resp.status_code == 404:
            await bot.send(event, "未找到该用户的认证信息。")
            return
        user = resp.json()
        await bot.send(event, format_user_info(user, mask=True))
    finally:
        _processed_events.discard(key)

# ── 命令：auth ───────────────────────────────────────────────────────────────
auth_handler = on_regex(r"^auth(\s+\S+.*)?$", priority=1, block=True)

@auth_handler.handle()
async def handle_auth(bot: Bot, event: Event):
    key = get_event_key(event)
    if key in _processed_events:
        return
    _processed_events.add(key)
    try:
        plain = get_plain_text(event)
        m = re.match(r"^auth\s+(\S+)\s+(\S+)$", plain)
        if not m:
            await bot.send(event, "用法: auth [姓名] [身份证号]")
            return
        name, id_number = m.group(1), m.group(2)
        if len(id_number) != 18 or not (id_number[:17].isdigit() and id_number[17].isalnum()):
            await bot.send(event, "身份证号格式错误：需为18位（前17位数字，最后一位字母或数字）。")
            return

        sender_id = get_sender_id(event)
        # 查询是否已有邀请人
        ur = await api_get(f"/user/{sender_id}")
        inviter_id = None
        if ur and ur.status_code == 200:
            inviter_id = ur.json().get("inviter_id")

        await bot.send(event, "正在提交您的实名认证信息...")
        resp = await api_post("/auth/submit", {
            "qq_id": sender_id,
            "real_name": name,
            "id_number": id_number,
            "inviter_id": inviter_id,
        })
        if not resp:
            await bot.send(event, "无法连接到认证服务器。")
            return
        data = resp.json()
        if resp.status_code == 200 and data.get("success"):
            await bot.send(event, "提交成功！请等待管理员审核。")
        else:
            detail = data.get("detail") or data.get("message") or "未知错误"
            await bot.send(event, f"提交失败！错误信息：{detail}")
    finally:
        _processed_events.discard(key)

# ── 命令：binduid1 / binduid2 / binduid3 ────────────────────────────────────
def _make_binduid_handler(slot: int):
    handler = on_regex(rf"^binduid{slot}(\s+\S+)?$", priority=1, block=True)

    @handler.handle()
    async def _handle(bot: Bot, event: Event, _slot: int = slot):
        key = get_event_key(event)
        if key in _processed_events:
            return
        _processed_events.add(key)
        try:
            plain = get_plain_text(event)
            m = re.match(rf"^binduid{_slot}\s+(\S+)$", plain)
            if not m:
                await bot.send(event, f"用法: binduid{_slot} [UID]")
                return
            uid = m.group(1)
            sender_id = get_sender_id(event)
            resp = await api_post("/auth/binduid", {"qq_id": sender_id, "slot": _slot, "uid": uid})
            if resp and resp.status_code == 200:
                await bot.send(event, f"UID{_slot} 绑定成功。")
            else:
                detail = _extract_detail(resp)
                await bot.send(event, f"绑定失败: {detail}")
        finally:
            _processed_events.discard(key)

    return handler

binduid1_handler = _make_binduid_handler(1)
binduid2_handler = _make_binduid_handler(2)
binduid3_handler = _make_binduid_handler(3)

# ── 命令：invite ─────────────────────────────────────────────────────────────
invite_handler = on_regex(r"^invite(\s+\S+)?$", priority=1, block=True)

@invite_handler.handle()
async def handle_invite(bot: Bot, event: Event):
    key = get_event_key(event)
    if key in _processed_events:
        return
    _processed_events.add(key)
    try:
        plain = get_plain_text(event)

        # 从 @mention 提取，或从文本参数提取
        target_id = extract_mention_id(event)
        if target_id is None:
            m = re.match(r"^invite\s+(\S+)$", plain)
            if m:
                target_id = m.group(1)

        if not target_id:
            await bot.send(event, "用法: invite [@用户 或 ID]")
            return

        inviter_id = get_sender_id(event)
        resp = await api_post("/auth/invite", {"inviter_id": inviter_id, "target_id": target_id})
        if resp and resp.status_code == 200:
            await bot.send(event, f"已成功邀请用户 {target_id}。")
        else:
            detail = _extract_detail(resp)
            await bot.send(event, f"邀请失败: {detail}")
    finally:
        _processed_events.discard(key)

# ── 命令：setauthstats ────────────────────────────────────────────────────────
#
# 用法：setauthstats [@用户|ID] [状态]
# 状态名称可能含空格（如 "Verified Enhanced"），必须小心解析。
# 解析策略：
#   1. 若消息中有 @mention segment → target_id 取自 mention，剩余纯文本全为状态
#   2. 若无 mention → 纯文本第一个词为 target_id，剩余全为状态
#
setauthstats_handler = on_regex(r"^setauthstats(\s+.*)?$", priority=1, block=True)

@setauthstats_handler.handle()
async def handle_setauthstats(bot: Bot, event: Event):
    key = get_event_key(event)
    if key in _processed_events:
        return
    _processed_events.add(key)
    try:
        sender_id = get_sender_id(event)
        is_superuser = sender_id in driver.config.superusers

        if not is_superuser:
            sr = await api_get(f"/user/{sender_id}")
            if not sr or sr.status_code != 200 or sr.json().get("auth_status") != "Admin":
                await bot.send(event, "权限不足。")
                return

        plain = get_plain_text(event)
        # 去掉命令词本身
        args_text = re.sub(r"^setauthstats\s*", "", plain).strip()

        target_id = extract_mention_id(event)
        if target_id:
            # 有 @mention → 纯文本参数即为状态
            status = args_text.strip()
        else:
            # 无 @mention → 第一词为 ID，其余为状态
            parts = args_text.split(maxsplit=1)
            if len(parts) < 2:
                await bot.send(event, "用法: setauthstats [@用户 或 ID] [状态]")
                return
            target_id, status = parts[0], parts[1]

        if not target_id or not status:
            await bot.send(event, "用法: setauthstats [@用户 或 ID] [状态]")
            return

        resp = await api_post("/auth/setstatus", {
            "operator_id": sender_id,
            "target_id": target_id,
            "status": status,
            "force": is_superuser,   # 超级用户直接强制设置，无需 operator 在 DB 中为 Admin
        })
        if resp and resp.status_code == 200:
            await bot.send(event, "认证状态更新成功。")
        else:
            detail = _extract_detail(resp)
            await bot.send(event, f"操作失败: {detail}")
    finally:
        _processed_events.discard(key)

# ── 命令：admingetauth ────────────────────────────────────────────────────────
admingetauth_handler = on_regex(r"^admingetauth(\s+\S+)?$", priority=1, block=True)

@admingetauth_handler.handle()
async def handle_admingetauth(bot: Bot, event: Event):
    key = get_event_key(event)
    if key in _processed_events:
        return
    _processed_events.add(key)
    try:
        # 仅允许私聊（兼容两种适配器）
        if not is_private_event(event):
            await bot.send(event, "此命令只能在私聊中使用。")
            return

        sender_id = get_sender_id(event)
        is_superuser = sender_id in driver.config.superusers

        if not is_superuser:
            sr = await api_get(f"/user/{sender_id}")
            if not sr or sr.status_code != 200 or sr.json().get("auth_status") != "Admin":
                await bot.send(event, "权限不足。")
                return

        plain = get_plain_text(event)
        target_id = extract_mention_id(event)
        if target_id is None:
            m = re.match(r"^admingetauth\s+(\S+)$", plain)
            if m:
                target_id = m.group(1)

        if not target_id:
            await bot.send(event, "用法: admingetauth [@用户 或 ID]")
            return

        resp = await api_get(f"/user/{target_id}")
        if not resp or resp.status_code == 404:
            await bot.send(event, "未找到该用户的认证信息。")
            return
        user = resp.json()
        await bot.send(event, format_user_info(user, mask=False))
    finally:
        _processed_events.discard(key)

# ── 内部辅助 ─────────────────────────────────────────────────────────────────

def _extract_detail(resp: httpx.Response | None) -> str:
    if resp is None:
        return "无法连接到认证服务器"
    try:
        return resp.json().get("detail") or resp.json().get("message") or f"HTTP {resp.status_code}"
    except Exception:
        return f"HTTP {resp.status_code}: {resp.text[:80]}"
