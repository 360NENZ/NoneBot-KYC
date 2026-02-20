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
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

### 3. NoneBot2 插件

**安装依赖：**
```bash
pip install nonebot2 nonebot-adapter-onebot httpx
```

将 `auth_plugin.py` 放入你的 NoneBot2 插件目录，并将其添加到 `pyproject.toml` 或 `bot.py` 中：

```python
# bot.py
import nonebot
nonebot.init()
nonebot.load_plugin("auth_plugin")  # 或使用插件目录
```

在 `.env` 中设置超级用户：
```
SUPERUSERS=["123456789"]  # 主人 QQ ID(s)
```

如果 API 服务器运行在不同的主机或端口，请更新 `auth_plugin.py` 中的 `API_BASE`。

---

## 命令列表

| 命令 | 描述 |
|---|---|
| `help` | 显示命令列表 |
| `auth [姓名] [身份证号]` | 提交实名认证信息 |
| `getauth` | 查询自己的认证状态（脱敏显示） |
| `getauth [@用户\|ID]` | 查询其他用户的状态（管理员专用，脱敏显示） |
| `admingetauth [@用户\|ID]` | 查询完整未脱敏信息（管理员/所有者，仅私聊） |
| `setauthstats [@用户\|ID] [状态]` | 设置用户认证状态（管理员/所有者） |
| `invite [@用户\|ID]` | 邀请用户注册 |
| `binduid1 [UID]` | 绑定主 UID |
| `binduid2 [UID]` | 绑定第二 UID |
| `binduid3 [UID]` | 绑定第三 UID |

## 认证状态与邀请额度

| 状态 | 额度 |
|---|---|
| 未认证 | 0 |
| 待审核 | 0 |
| 已认证 | 0 |
| 已认证 加强版 | 5 |
| 已认证 豁免 | 5 |
| 已封禁 | 0 |
| 管理员 | 无限制 |

## 注意事项
- 身份证号必须正好18位（17位数字 + 1位字母或数字校验码）
- `getauth` 姓名显示为 `***`，身份证号显示为 `X*******X`
- `admingetauth` 显示完整详情，仅限私聊使用
- NoneBot 所有者（超级用户）拥有最高权限，绕过所有检查