# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is CodexFree

Python tool for automated ChatGPT phone-number registration and Codex OAuth token acquisition. Pure API calls with minimal browser dependency (Playwright only for Cloudflare sentinel extraction).

## Commands

```bash
# Install dependencies
pip install curl_cffi playwright
playwright install chromium

# Register + login (default)
python main.py

# Register only
python main.py register

# Login only (existing account)
python main.py login --phone +573238903957 --password 'A8i6HDvW9!A1'

# Batch register + login
python main.py all --count 3

# Standalone scripts
python chatgpt_register.py --count 1
python chatgpt_register.py --no-codex
python codex_login.py --phone +573238903957 --password 'xxx'
```

## Architecture

Four Python files, no package structure — all scripts import from project root.

| File | Role |
|------|------|
| `main.py` | CLI entry point, dispatches to `register` / `login` / `all` subcommands |
| `sentinel.py` | Shared module: Playwright-based Cloudflare sentinel token extraction with 10-min file cache (`sentinel_cache.json`) |
| `chatgpt_register.py` | Registration flow + embedded `login_codex()` for post-registration token fetch |
| `codex_login.py` | Standalone Codex OAuth login for existing accounts |

### Key flows

**Registration** (`chatgpt_register.py → run_registration → register_account`):
1. Sentinel extraction (Playwright, cached)
2. SMS number acquisition (HeroSMS or 5sim, auto-routed by `phone_sms.provider`)
3. OpenAI auth API: create-account → register → phone-otp → create_account
4. Optional: Codex OAuth login (`login_codex`)

**Codex Login** (`codex_login.py → login` or `chatgpt_register.py → login_codex`):
1. Sentinel extraction
2. PKCE OAuth authorize → CSRF cookie
3. Phone → password → email binding/OTP (via SkyMail)
4. Workspace select → consent redirects → authorization_code
5. Token exchange → save to `tokens/`

### SMS Provider Routing

All SMS operations go through `_get_sms_*()` dispatch functions that route based on `config.json → phone_sms.provider`:
- `"herosms"` → HeroSMS (SMS-Activate compatible API)
- `"fivesim"` → 5sim.net

### Proxy Strategy

- **Registration** (`chatgpt_register.py`): all requests use proxy from `config.json → proxy.default`
- **Codex login** (`codex_login.py`): direct connection, no proxy
- **SkyMail**: direct connection, no proxy
- **Sentinel**: uses proxy for Playwright (configurable via `use_proxy` param)

### Cookie Separation

Sentinel cookies are filtered — only Cloudflare cookies (`cf_clearance`, `__cf_bm`, etc.) are kept. Auth-class cookies (`oai-login-csrf`, `oai-did`, `auth-session`, etc.) are discarded so OAuth redirects issue fresh ones.

## Configuration

Copy `config.example.json` → `config.json`. Key sections:
- `mail.provider` — email provider: `"skymail"` (default) or `"shanmail"`
- `skymail` — SkyMail email service (admin login + mailbox creation)
- `shanmail` — ShanMail email service (`shanyouxiang.com`, Bearer token)
- `chatgpt` — OpenAI endpoints and client IDs
- `phone_sms` — SMS provider selection, API keys, price filters, country preferences
- `registration` — password generation parameters
- `timeouts` — request/poll timeouts
- `proxy` — HTTP proxy URL (empty = direct)

## Output Directories

| Directory | Content |
|-----------|---------|
| `tokens/` | `auth_{phone}.json`, `codex-{phone}.json` — OAuth tokens |
| `success/` | Full registration records |
| `fail/` | Failed attempt records |

All are gitignored.

## Dependencies

- `curl_cffi` — HTTP client with TLS fingerprint impersonation (Chrome)
- `playwright` — headless Chromium for sentinel extraction only
