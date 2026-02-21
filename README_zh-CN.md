# 实名认证系统

[English](README.md) | [简体中文](README_zh-CN.md)

## 文件列表
- `api_server.py` — FastAPI 后端（连接到 MariaDB）
- `auth_plugin.py` — NoneBot2 插件
- `schema.sql` — MariaDB 数据库表结构

---

## 安装配置

### 1. 数据库
```bash
mysql -u root -p < schema.sql
```

> **从旧版本升级？**  
> `qq_id` 和 `inviter_id` 列从 `BIGINT` 改为 `VARCHAR(64)`。  
> 启动服务器前请先执行 `schema.sql` 底部的迁移语句。

### 2. API 服务器

**安装依赖：**
```bash
pip install fastapi uvicorn aiomysql httpx
```

**通过环境变量配置：**
```bash
export DB_HOST=127.0.0.1
export DB_PORT=3306
export DB_USER=auth_user
export DB_PASSWORD=auth_pass
export DB_NAME=auth_db
```

**运行：**
```bash
uvicorn api_server:app --host 127.0.0.1 --port 8000
```

### 3. NoneBot2 插件

**安装依赖（选择对应适配器）：**
```bash
pip install nonebot2 httpx

# OneBot V11（Lagrange、go-cqhttp 等）
pip install nonebot-adapter-onebot

# QQ 官方机器人
pip install nonebot-adapter-qq
```

> 两个适配器可同时安装和加载。  
> 插件在运行时通过可选导入自动检测已安装的适配器。

将 `auth_plugin.py` 放入 NoneBot2 插件目录并加载：

```python
# bot.py
import nonebot
nonebot.init()
nonebot.load_plugin("auth_plugin")
```

在 `.env` 中设置超级用户：
```
SUPERUSERS=["123456789"]   # 主人 QQ 号（OneBot）或 openid（QQ 官方）
```

如果 API 服务器运行在不同的主机或端口，请更新 `auth_plugin.py` 中的 `API_BASE`。

---

## 适配器说明

| 特性 | OneBot V11 | QQ 官方机器人 |
|---|---|---|
| 用户 ID 格式 | 整数 QQ 号 | 字符串 openid |
| 群消息触发 | 所有消息 | 必须 @ 机器人 |
| 私聊事件类型 | `PrivateMessageEvent` | `DirectMessageCreateEvent` / `C2CMessageCreateEvent` |
| @提及 segment 类型 | `type="at"` | `type="mention_user"` |

**QQ 官方机器人群消息说明：**  
机器人只能接收 @ 了自己的群消息。用户需在群内使用 `@机器人 [命令]` 的格式；  
插件会自动识别并跳过消息开头的机器人 @ mention，再进行命令匹配，无需手动配置。

**用户 ID：**  
两个适配器均通过 `event.get_user_id()` 返回字符串形式的 ID。  
数据库使用 `VARCHAR(64)` 存储，传统 QQ 号和 openid 均可兼容，无需额外转换。

---

## 命令列表

| 命令 | 描述 |
|---|---|
| `help` | 显示命令列表 |
| `auth [姓名] [身份证号]` | 提交实名认证信息 |
| `getauth` | 查询自己的认证状态（脱敏显示） |
| `getauth [@用户\|ID]` | 查询其他用户的状态（管理员专用，脱敏显示） |
| `admingetauth [@用户\|ID]` | 查询完整未脱敏信息（管理员/所有者，**仅私聊**） |
| `setauthstats [@用户\|ID] [状态]` | 设置用户认证状态（管理员/所有者） |
| `invite [@用户\|ID]` | 邀请用户注册 |
| `binduid1 [UID]` | 绑定主 UID |
| `binduid2 [UID]` | 绑定第二 UID |
| `binduid3 [UID]` | 绑定第三 UID |
| `initadmin` | 初始化第一个管理员账户（仅超级用户） |

## 认证状态与邀请额度

| 状态 | 邀请额度 |
|---|---|
| 未认证 | 0 |
| 待审核 | 0 |
| 已认证 | 0 |
| 已认证 加强版 | 5 |
| 已认证 豁免 | 5 |
| 已封禁 | 0 |
| 管理员 | 无限制 |

## 注意事项
- 身份证号必须正好 18 位（17 位数字 + 1 位字母或数字校验码）。
- `getauth` 姓名显示为 `***`，身份证号显示为 `X*******X`。
- `admingetauth` 显示完整信息，**仅限私聊使用**。
- NoneBot 所有者（超级用户）绕过所有权限检查，即使数据库中没有 Admin 记录也可设置任意状态。
- 首次部署后请使用 `initadmin` 命令为自己在数据库中授予管理员状态。
