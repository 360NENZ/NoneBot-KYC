"""
NoneBot2 实名认证插件（完整版）
要求：nonebot2, nonebot-adapter-onebot, httpx
"""

import re
import httpx
from nonebot import on_regex, get_driver
from nonebot.typing import T_State
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    PrivateMessageEvent,
    Message,
)
import json

# ── 配置 ───────────────────────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"  # 更改为你的API服务器地址

driver = get_driver()

# ── 辅助函数 ───────────────────────────────────────────────────────────────────
async def api_get(path: str, **kwargs):
    try:
        print(f"[DEBUG] 正在发起GET请求到: {API_BASE}{path}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{API_BASE}{path}", **kwargs)
            print(f"[DEBUG] GET响应状态码: {resp.status_code}, 内容: {resp.text}")
            return resp
    except Exception as e:
        print(f"[ERROR] API GET请求失败: {e}")
        return None

async def api_post(path: str, json_data: dict):
    try:
        print(f"[DEBUG] 正在发起POST请求到: {API_BASE}{path}")
        print(f"[DEBUG] POST数据: {json_data}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{API_BASE}{path}", json=json_data)
            print(f"[DEBUG] POST响应状态码: {resp.status_code}, 内容: {resp.text}")
            return resp
    except Exception as e:
        print(f"[ERROR] API POST请求失败: {e}")
        return None

def mask_name(name: str) -> str:
    """将姓名中的每个字符替换为*"""
    return "*" * len(name)

def mask_id(id_number: str) -> str:
    """保留首尾数字，中间替换为*"""
    if not id_number or len(id_number) < 2:
        return id_number
    return id_number[0] + "*" * (len(id_number) - 2) + id_number[-1]

def format_auth_status(status: str) -> str:
    """将英文认证状态转换为中文"""
    status_map = {
        "Unverified": "未认证",
        "Pending Review": "待审核",
        "Verified": "已认证",
        "Verified Enhanced": "已认证 加强版",
        "Verified Exempt": "已认证 豁免",
        "Banned": "已封禁",
        "Admin": "管理员"
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

def extract_qq_id_from_message(message: Message) -> int | None:
    """从消息中的@提取QQ号"""
    for seg in message:
        if seg.type == "at":
            return int(seg.data["qq"])
    return None

def extract_plain_text(message: Message) -> str:
    """从消息中提取纯文本"""
    text = ""
    for seg in message:
        if seg.type == "text":
            text += seg.data["text"]
    return text.strip()

def validate_id_number(id_number: str) -> bool:
    """验证身份证号格式：18位，前17位为数字，最后一位为字母或数字"""
    if len(id_number) != 18:
        return False
    if not (id_number[:17].replace(' ', '').isdigit() and id_number[17].isalnum()):
        return False
    return True

# ── 命令处理器 ──────────────────────────────────────────────────────────────────

# 全局缓存，防止重复处理
processed_events = set()

def get_event_key(event: Event) -> str:
    """生成事件的唯一键以防止重复处理"""
    return f"{event.get_session_id()}_{hash(str(event.get_message()))}_{event.time}"

# help命令
help_regex = r'^(help|帮助)$'
help_handler = on_regex(help_regex, priority=1, block=True)

@help_handler.handle()
async def handle_help(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        msg = (
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
        )
        await bot.send(event, msg)
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# initadmin命令 - 超级用户初始化管理员账户
initadmin_regex = r'^initadmin$'
initadmin_handler = on_regex(initadmin_regex, priority=1, block=True)

@initadmin_handler.handle()
async def handle_initadmin(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        sender_id = int(event.get_user_id())
        is_superuser = str(sender_id) in driver.config.superusers
        
        if not is_superuser:
            await bot.send(event, "只有超级用户可以初始化管理员账户。")
            return
        
        # 尝试使用新的initadmin端点
        init_payload = {
            "qq_id": sender_id,
            "real_name": "系统管理员",
            "id_number": "123456789012345678"
        }
        
        print(f"[DEBUG] 尝试通过新端点初始化管理员: {init_payload}")
        
        init_resp = await api_post("/auth/initadmin", init_payload)
        
        if not init_resp:
            await bot.send(event, "无法连接到认证服务器。")
            return
        
        if init_resp.status_code in [200, 201]:
            try:
                response_data = init_resp.json()
                print(f"[DEBUG] 初始化管理员响应: {response_data}")
                success_msg = response_data.get("message", "管理员账户初始化成功")
                await bot.send(event, success_msg)
            except Exception as e:
                print(f"[ERROR] 解析初始化管理员响应失败: {e}")
                await bot.send(event, "管理员账户初始化成功")
        else:
            detail = "未知错误"
            try:
                detail = init_resp.json().get("detail", "未知错误")
            except:
                detail = f"HTTP {init_resp.status_code}: {init_resp.text}"
            print(f"[DEBUG] 初始化管理员失败: {detail}")
            await bot.send(event, f"初始化管理员账户失败: {detail}")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# getauth命令
getauth_regex = r'^getauth(?:\s+(.+))?$'
getauth_handler = on_regex(getauth_regex, priority=1, block=True)

@getauth_handler.handle()
async def handle_getauth(bot: Bot, event: Event, state: T_State):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        sender_id = int(event.get_user_id())
        
        # 获取原始消息并手动解析
        raw_message = str(event.get_message()).strip()
        parts = raw_message.split(maxsplit=1)
        target_part = parts[1] if len(parts) > 1 else None
        
        # 如果未提供目标，则显示发送者自己的信息
        if target_part is None:
            target_id = sender_id
        else:
            # 尝试从@中提取QQ号
            target_id = extract_qq_id_from_message(event.get_message()) if hasattr(event, 'message') else None
            
            # 如果@中未找到，尝试解析为纯数字
            if target_id is None and target_part:
                target_part_clean = target_part.strip()
                if target_part_clean.isdigit():
                    target_id = int(target_part_clean)
            
            if target_id is None:
                await bot.send(event, "用法: getauth [@用户|ID]")
                return

        resp = await api_get(f"/user/{target_id}")
        if not resp:
            await bot.send(event, "无法连接到认证服务器。")
            return
        if resp.status_code == 404:
            await bot.send(event, "未找到指定用户的信息。")
            return

        user = resp.json()
        await bot.send(event, format_user_info(user, mask=True))
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# auth命令 - 有参数时的处理器
auth_with_args_regex = r'^auth\s+(.+?)\s+(\S+)$'
auth_with_args_handler = on_regex(auth_with_args_regex, priority=1, block=True)

@auth_with_args_handler.handle()
async def handle_auth_with_args(bot: Bot, event: Event, state: T_State):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        # 获取原始消息并使用正则表达式解析
        raw_message = str(event.get_message()).strip()
        
        # 使用正则表达式提取姓名和身份证号
        match = re.match(r'^auth\s+(.+?)\s+(\S+)$', raw_message)
        if not match:
            await bot.send(event, "用法: auth [姓名] [身份证号]")
            return

        name = match.group(1).strip()
        id_number = match.group(2).strip()

        # 检查身份证号格式：18位，前17位为数字，最后一位为字母或数字
        if not validate_id_number(id_number):
            await bot.send(event, "身份证号格式错误。必须为18位，前17位为数字，最后一位为字母或数字。")
            return

        qq_id = int(event.get_user_id())

        # 检查：验证用户必须先被邀请才能进行认证
        user_resp = await api_get(f"/user/{qq_id}")
        user_exists = user_resp and user_resp.status_code != 404
        
        if not user_exists:
            # 用户不存在于系统中，意味着他们没有被邀请
            await bot.send(event, "您必须先被其他用户邀请才能进行认证。")
            return
        elif user_resp.status_code == 200:
            user_data = user_resp.json()
            inviter_id = user_data.get("inviter_id")
            if inviter_id is None:
                # 用户存在但未被邀请（未设置inviter_id）
                await bot.send(event, "您必须先被其他用户邀请才能进行认证。")
                return

        await bot.send(event, "正在提交您的身份认证信息...")

        payload = {
            "qq_id": qq_id,
            "real_name": name,
            "id_number": id_number,
            "inviter_id": inviter_id,  # 上面已验证此值存在
        }
        
        print(f"[DEBUG] 发送认证提交请求，载荷: {payload}")
        
        resp = await api_post("/auth/submit", payload)
        if not resp:
            await bot.send(event, "无法连接到认证服务器。")
            return
            
        try:
            data = resp.json()
            print(f"[DEBUG] 响应JSON: {data}")
            
            if resp.status_code == 200:
                if data.get("success"):
                    await bot.send(event, "提交成功！请等待管理员审核。")
                else:
                    await bot.send(event, f"提交失败！错误信息：{data.get('message', '未知错误')}")
            else:
                # 处理不同错误代码
                error_detail = "未知错误"
                try:
                    error_detail = data.get('detail', data.get('message', '未知错误'))
                except:
                    error_detail = f"HTTP {resp.status_code}: {resp.text}"
                
                await bot.send(event, f"提交失败！错误信息：{error_detail}")
        except Exception as e:
            print(f"[ERROR] 解析响应JSON失败: {e}")
            await bot.send(event, f"提交失败！无法解析服务器响应: {resp.text}")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# auth命令 - 无参数时的处理器
auth_no_args_regex = r'^auth$'
auth_no_args_handler = on_regex(auth_no_args_regex, priority=1, block=True)

@auth_no_args_handler.handle()
async def handle_auth_no_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        await bot.send(event, "用法: auth [姓名] [身份证号]")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# binduid1命令 - 有参数时的处理器
binduid1_with_args_regex = r'^binduid1\s+(.+)$'
binduid1_with_args_handler = on_regex(binduid1_with_args_regex, priority=1, block=True)

@binduid1_with_args_handler.handle()
async def handle_binduid1_with_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        # 获取原始消息并使用正则表达式解析
        raw_message = str(event.get_message()).strip()
        
        # 使用正则表达式提取UID
        match = re.match(r'^binduid1\s+(.+)$', raw_message)
        if not match:
            await bot.send(event, "用法: binduid1 [UID]")
            return
        
        uid = match.group(1).strip()
        qq_id = int(event.get_user_id())
        print(f"[DEBUG] 尝试绑定UID1: {uid} 给QQ: {qq_id}")
        resp = await api_post("/auth/binduid", {"qq_id": qq_id, "slot": 1, "uid": uid})
        if resp and resp.status_code == 200:
            await bot.send(event, "绑定成功！")
        else:
            await bot.send(event, "绑定失败！错误信息：身份认证未通过")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# binduid1命令 - 无参数时的处理器
binduid1_no_args_regex = r'^binduid1$'
binduid1_no_args_handler = on_regex(binduid1_no_args_regex, priority=1, block=True)

@binduid1_no_args_handler.handle()
async def handle_binduid1_no_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        await bot.send(event, "用法: binduid1 [UID]")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# binduid2命令 - 有参数时的处理器
binduid2_with_args_regex = r'^binduid2\s+(.+)$'
binduid2_with_args_handler = on_regex(binduid2_with_args_regex, priority=1, block=True)

@binduid2_with_args_handler.handle()
async def handle_binduid2_with_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        # 获取原始消息并使用正则表达式解析
        raw_message = str(event.get_message()).strip()
        
        # 使用正则表达式提取UID
        match = re.match(r'^binduid2\s+(.+)$', raw_message)
        if not match:
            await bot.send(event, "用法: binduid2 [UID]")
            return
        
        uid = match.group(1).strip()
        qq_id = int(event.get_user_id())
        print(f"[DEBUG] 尝试绑定UID2: {uid} 给QQ: {qq_id}")
        resp = await api_post("/auth/binduid", {"qq_id": qq_id, "slot": 2, "uid": uid})
        if resp and resp.status_code == 200:
            await bot.send(event, "绑定成功！")
        else:
            await bot.send(event, "绑定失败！错误信息：身份认证未通过")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# binduid2命令 - 无参数时的处理器
binduid2_no_args_regex = r'^binduid2$'
binduid2_no_args_handler = on_regex(binduid2_no_args_regex, priority=1, block=True)

@binduid2_no_args_handler.handle()
async def handle_binduid2_no_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        await bot.send(event, "用法: binduid2 [UID]")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# binduid3命令 - 有参数时的处理器
binduid3_with_args_regex = r'^binduid3\s+(.+)$'
binduid3_with_args_handler = on_regex(binduid3_with_args_regex, priority=1, block=True)

@binduid3_with_args_handler.handle()
async def handle_binduid3_with_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        # 获取原始消息并使用正则表达式解析
        raw_message = str(event.get_message()).strip()
        
        # 使用正则表达式提取UID
        match = re.match(r'^binduid3\s+(.+)$', raw_message)
        if not match:
            await bot.send(event, "用法: binduid3 [UID]")
            return
        
        uid = match.group(1).strip()
        qq_id = int(event.get_user_id())
        print(f"[DEBUG] 尝试绑定UID3: {uid} 给QQ: {qq_id}")
        resp = await api_post("/auth/binduid", {"qq_id": qq_id, "slot": 3, "uid": uid})
        if resp and resp.status_code == 200:
            await bot.send(event, "绑定成功！")
        else:
            await bot.send(event, "绑定失败！错误信息：身份认证未通过")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# binduid3命令 - 无参数时的处理器
binduid3_no_args_regex = r'^binduid3$'
binduid3_no_args_handler = on_regex(binduid3_no_args_regex, priority=1, block=True)

@binduid3_no_args_handler.handle()
async def handle_binduid3_no_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        await bot.send(event, "用法: binduid3 [UID]")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# invite命令 - 有参数时的处理器
invite_with_args_regex = r'^invite\s+(.+)$'
invite_with_args_handler = on_regex(invite_with_args_regex, priority=1, block=True)

@invite_with_args_handler.handle()
async def handle_invite_with_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        # 获取原始消息并使用正则表达式解析
        raw_message = str(event.get_message()).strip()
        
        # 使用正则表达式提取目标
        match = re.match(r'^invite\s+(.+)$', raw_message)
        if not match:
            await bot.send(event, "用法: invite [@用户 或 ID]")
            return
        
        target_part = match.group(1).strip()
        
        # 尝试从@中提取QQ号
        target_id = extract_qq_id_from_message(event.get_message()) if hasattr(event, 'message') else None
        
        # 如果@中未找到，尝试解析为纯数字
        if target_id is None and target_part.isdigit():
            target_id = int(target_part)
        
        if not target_id:
            await bot.send(event, "用法: invite [@用户 或 ID]")
            return

        inviter_id = int(event.get_user_id())
        print(f"[DEBUG] 尝试发送邀请，从 {inviter_id} 到 {target_id}")
        resp = await api_post("/auth/invite", {"inviter_id": inviter_id, "target_id": target_id})
        if resp and resp.status_code == 200:
            await bot.send(event, f"邀请已成功发送给 {target_id}。")
        else:
            detail = "未知错误"
            if resp:
                try:
                    detail = resp.json().get("detail", "未知错误")
                except:
                    detail = f"HTTP {resp.status_code}: {resp.text}"
            await bot.send(event, f"邀请失败: {detail}")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# invite命令 - 无参数时的处理器
invite_no_args_regex = r'^invite$'
invite_no_args_handler = on_regex(invite_no_args_regex, priority=1, block=True)

@invite_no_args_handler.handle()
async def handle_invite_no_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        await bot.send(event, "用法: invite [@用户 或 ID]")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# setauthstats命令 - 有参数时的处理器
setauthstats_with_args_regex = r'^setauthstats\s+(.+?)\s+(.+)$'
setauthstats_with_args_handler = on_regex(setauthstats_with_args_regex, priority=1, block=True)

@setauthstats_with_args_handler.handle()
async def handle_setauthstats_with_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        sender_id = int(event.get_user_id())
        is_superuser = str(sender_id) in driver.config.superusers

        # 获取原始消息并使用正则表达式解析
        raw_message = str(event.get_message()).strip()
        
        # 使用正则表达式提取目标和状态
        match = re.match(r'^setauthstats\s+(.+?)\s+(.+)$', raw_message)
        if not match:
            await bot.send(event, "用法: setauthstats [@用户 或 ID] [状态]")
            return

        # 提取目标和状态
        target_part = match.group(1).strip()
        status = match.group(2).strip()
        
        # 尝试从@中提取QQ号
        target_id = extract_qq_id_from_message(event.get_message()) if hasattr(event, 'message') else None
        
        # 如果@中未找到，尝试解析为纯数字
        if target_id is None and target_part.isdigit():
            target_id = int(target_part)
        
        if not target_id or not status:
            await bot.send(event, "用法: setauthstats [@用户 或 ID] [状态]")
            return

        if not is_superuser:
            # 检查数据库中的管理员状态
            resp = await api_get(f"/user/{sender_id}")
            if not resp or resp.status_code != 200 or resp.json().get("auth_status") != "Admin":
                await bot.send(event, "权限不足。")
                return

        payload = {"operator_id": sender_id, "target_id": target_id, "status": status}
        
        print(f"[DEBUG] 设置认证状态: {payload}")
        
        resp = await api_post("/auth/setstatus", payload)

        if resp and resp.status_code == 200:
            await bot.send(event, f"状态更新成功。")
        else:
            detail = "未知错误"
            if resp:
                try:
                    detail = resp.json().get("detail", "未知错误")
                except:
                    detail = f"HTTP {resp.status_code}: {resp.text}"
            await bot.send(event, f"操作失败: {detail}")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# setauthstats命令 - 无参数时的处理器
setauthstats_no_args_regex = r'^setauthstats$'
setauthstats_no_args_handler = on_regex(setauthstats_no_args_regex, priority=1, block=True)

@setauthstats_no_args_handler.handle()
async def handle_setauthstats_no_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        await bot.send(event, "用法: setauthstats [@用户 或 ID] [状态]")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# admingetauth命令 - 有参数时的处理器
admingetauth_with_args_regex = r'^admingetauth\s+(.+)$'
admingetauth_with_args_handler = on_regex(admingetauth_with_args_regex, priority=1, block=True)

@admingetauth_with_args_handler.handle()
async def handle_admingetauth_with_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        # 必须是私聊
        if not isinstance(event, PrivateMessageEvent):
            await bot.send(event, "此命令只能在私聊中使用。")
            return

        sender_id = int(event.get_user_id())
        is_superuser = str(sender_id) in driver.config.superusers

        # 获取原始消息并使用正则表达式解析
        raw_message = str(event.get_message()).strip()
        
        # 使用正则表达式提取目标
        match = re.match(r'^admingetauth\s+(.+)$', raw_message)
        if not match:
            await bot.send(event, "用法: admingetauth [@用户 或 ID] - 查询完整未脱敏信息（管理员专用，私聊）")
            return

        target_part = match.group(1).strip()
        
        # 尝试从@中提取QQ号
        target_id = extract_qq_id_from_message(event.get_message()) if hasattr(event, 'message') else None
        
        # 如果@中未找到，尝试解析为纯数字
        if target_id is None and target_part.isdigit():
            target_id = int(target_part)

        if not target_id:
            await bot.send(event, "用法: admingetauth [@用户 或 ID] - 查询完整未脱敏信息（管理员专用，私聊）")
            return

        if not is_superuser:
            resp = await api_get(f"/user/{sender_id}")
            if not resp or resp.status_code != 200 or resp.json().get("auth_status") != "Admin":
                await bot.send(event, "权限不足。")
                return

        resp = await api_get(f"/user/{target_id}")
        if not resp or resp.status_code == 404:
            await bot.send(event, "未找到指定用户的信息。")
            return

        user = resp.json()
        await bot.send(event, format_user_info(user, mask=False))
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)


# admingetauth命令 - 无参数时的处理器
admingetauth_no_args_regex = r'^admingetauth$'
admingetauth_no_args_handler = on_regex(admingetauth_no_args_regex, priority=1, block=True)

@admingetauth_no_args_handler.handle()
async def handle_admingetauth_no_args(bot: Bot, event: Event):
    event_key = get_event_key(event)
    if event_key in processed_events:
        return  # 如果已处理则跳过
    processed_events.add(event_key)
    
    try:
        await bot.send(event, "用法: admingetauth [@用户|ID] - 查询完整未脱敏信息（管理员专用，私聊）")
    finally:
        # 处理完成后清理事件键
        processed_events.discard(event_key)
