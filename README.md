# CodexTool

ChatGPT 手机号注册 & Codex OAuth Token 获取。纯 API 调用，最小化浏览器依赖（仅 Sentinel 提取需 Playwright）。

## 项目结构

```
codextool/
├── config.example.json   # 配置模板（可提交 git）
├── config.json           # 实际配置（敏感信息，gitignore）
├── .gitignore
├── main.py               # 主入口（register / login / all）
├── sentinel.py           # 共享模块：Cloudflare sentinel 提取 + 代理配置
├── chatgpt_register.py   # ChatGPT 手机号注册（API）
├── codex_login.py        # Codex OAuth 登录（API）
├── tokens/               # Token 输出（auth_{phone}.json）
├── success/              # 注册成功记录
└── fail/                 # 失败记录
```

## 环境

```bash
pip install curl_cffi playwright
playwright install chromium
```

## 配置

复制 `config.example.json` → `config.json`，填入实际值：

| 配置路径 | 说明 |
|----------|------|
| `skymail.admin_email` | SkyMail 邮箱账号 |
| `skymail.admin_password` | SkyMail 邮箱密码 |
| `phone_sms.provider` | 接码平台选择：`herosms` 或 `fivesim` |
| `phone_sms.herosms_api_key` | HeroSMS API Key |
| `phone_sms.fivesim_api_key` | 5sim API Key（Bearer Token） |
| `phone_sms.country` | 指定国家码（留空自动选最低价） |
| `phone_sms.max_price` | 单个手机号最高价格（USD） |
| `phone_sms.min_price` | 最低可信价格（低于此过滤掉） |
| `proxy.default` | HTTP 代理 URL（留空不走代理） |
| `registration.password_suffix` | 密码后缀（`!A1` 满足 OpenAI 复杂度） |

### 接码平台切换

修改 `phone_sms.provider` 字段即可：

- `"herosms"` — HeroSMS（SMS-Activate 兼容 API）
- `"fivesim"` — 5sim.net

两套 API 完全并行实现，切换后自动路由到对应服务商，无需改代码。

### 代理策略

- **注册流程**（`chatgpt_register.py`）：HeroSMS / 5sim / OpenAI 注册 API 均走代理
- **Codex 登录**（`codex_login.py`）：全程直连，不走代理
- **SkyMail**：全程直连，不走代理

代理在 `config.json` 中配置 `proxy.default`，留空则全部直连。

## 使用

### 主入口 `main.py`

```bash
# 注册 + 登录一条龙（默认）
python main.py

# 只注册，不登录
python main.py register

# 只登录已有账号
python main.py login --phone +573238903957 --password 'A8i6HDvW9!A1'

# 批量注册 + 登录
python main.py all --count 3
```

### 独立脚本

```bash
# 注册
python chatgpt_register.py --count 1
python chatgpt_register.py --no-codex          # 只注册不登录

# 登录
python codex_login.py --phone +573238903957 --password 'xxx'
```

## 输出文件

| 文件 | 来源 | 内容 |
|------|------|------|
| `tokens/auth_{phone}.json` | Codex 登录 | access_token, refresh_token, account_id |
| `tokens/codex-{phone}.json` | Codex 登录 | 同上（按手机号命名） |
| `success/chatgpt_{phone}_{timestamp}.json` | 注册成功 | 手机号、密码、姓名、邮箱、token |

Token 格式：
```json
{
  "auth_mode": "chatgpt",
  "OPENAI_API_KEY": null,
  "tokens": {
    "id_token": "eyJ...",
    "access_token": "eyJ...",
    "refresh_token": "rt_...",
    "account_id": "user-XXX"
  },
  "last_refresh": "2026-05-15T07:30:04Z"
}
```

## API 登录流程

```
Sentinel 提取 → OAuth 重定向 → /log-in (CSRF cookie)
  → POST /api/accounts/authorize/continue     (手机号)
  → GET  /api/accounts/client_auth_session_dump
  → POST /api/accounts/password/verify        (密码)
  → POST /api/accounts/add-email/send         (绑定邮箱，仅首次)
  → POST /api/accounts/email-otp/validate     (邮箱验证码)
  → POST /api/accounts/workspace/select       (工作区)
  → 跟随 consent 重定向链 → authorization_code
  → POST /oauth/token → access_token + refresh_token
```

## 关键实现

1. **Cookie 分离**：sentinel cookies 中仅保留 Cloudflare 相关（`cf_clearance`, `__cf_bm` 等），Auth 类 cookie 由 OAuth 重定向重新签发
2. **openai-sentinel-token 头**：每个 API 请求必须携带，否则 401
3. **CSRF**：显式 GET `/log-in` 获取与 session 匹配的 CSRF cookie
4. **邮箱双场景**：首次走 add-email 绑定新邮箱，再次从 session dump 获取已绑定邮箱
5. **Sentinel 缓存**：10 分钟内复用，避免重复 Playwright 开销；注册和登录间自动复用
6. **双接码平台**：HeroSMS / 5sim 自动路由，通过 `provider` 字段切换
7. **代理分层**：注册走代理（防 OpenAI 风控），登录和 SkyMail 直连
