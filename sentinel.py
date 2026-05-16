"""Sentinel (Cloudflare) token extraction — shared module.

Provides extract_sentinel() which uses Playwright to load the OpenAI auth page,
wait for the SentinelSDK to initialize, and extract the anti-bot tokens + cookies
needed for subsequent API calls.
"""
import json, time, os, uuid, secrets
from urllib.parse import quote
from pathlib import Path


CACHE_FILE = Path(__file__).parent / "sentinel_cache.json"
CACHE_TTL = 600  # 10 minutes


def _load_config():
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"config.json not found at {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_cached(force_fresh=False):
    """Return cached sentinel data if still valid."""
    if force_fresh:
        return None
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                cache = json.load(f)
            age = time.time() - cache.get("ts", 0)
            if age < CACHE_TTL and cache.get("sentinel_token"):
                return cache
        except Exception:
            pass
    return None


def save_cache(data):
    """Save sentinel data to cache file."""
    data["ts"] = time.time()
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def clear_cache():
    """Delete cached sentinel data."""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()


def get_proxy_url():
    """Return proxy URL for curl_cffi requests, or None if not configured."""
    try:
        cfg = _load_config()
        return cfg.get("proxy", {}).get("default") or None
    except Exception:
        return None


def get_playwright_proxy():
    """Return Playwright proxy dict, or None if not configured."""
    try:
        cfg = _load_config()
        url = cfg.get("proxy", {}).get("default") or None
    except Exception:
        return None
    if not url:
        return None
    import re
    # Try with auth: http://user:pass@host:port
    m = re.match(r'(https?)://([^:]+):([^@]+)@([^:]+):(\d+)', url)
    if m:
        return {
            "server": f"{m.group(1)}://{m.group(4)}:{m.group(5)}",
            "username": m.group(2),
            "password": m.group(3),
        }
    # Try without auth: http://host:port
    m = re.match(r'(https?)://([^:]+):(\d+)', url)
    if m:
        return {"server": url}
    return None


def extract_sentinel(force_fresh=False, use_proxy=True):
    """Extract sentinel tokens via Playwright browser.

    Returns dict with keys:
        sentinel_token     — for username_password_create flow
        sentinel_so_token  — for oauth_create_account flow
        cookie_str         — all browser cookies as 'k=v; ...' string
        oai_did            — device ID
    """
    if not force_fresh:
        cached = get_cached()
        if cached:
            return cached

    cfg = _load_config()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError("pip install playwright && playwright install chromium")

    auth_base = cfg["chatgpt"].get("auth_base_url", "https://auth.openai.com")
    chat_client_id = cfg["chatgpt"]["chat_web_client_id"]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # 改成 False，浏览器窗口可见
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx_kwargs = {
            "user_agent": cfg["http"]["user_agent_chrome"],
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }
        if use_proxy:
            pw_proxy = get_playwright_proxy()
            if pw_proxy:
                ctx_kwargs["proxy"] = pw_proxy
        ctx = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()

        device_id = str(uuid.uuid4())
        state = secrets.token_urlsafe(32)
        scope = "openid email profile offline_access model.request model.read organization.read organization.write"
        auth_url = (
            f"{auth_base}/api/accounts/authorize"
            f"?client_id={chat_client_id}"
            f"&scope={quote(scope)}"
            f"&response_type=code"
            f"&redirect_uri={quote('https://chatgpt.com/api/auth/callback/openai')}"
            f"&audience={quote('https://api.openai.com/v1')}"
            f"&device_id={device_id}"
            f"&prompt=login"
            f"&screen_hint=signup"
            f"&state={state}"
        )

        try:
            print(f"  Loading {auth_url[:60]}...")
            page.goto(auth_url, wait_until="domcontentloaded", timeout=120000)
            print(f"  Page loaded, URL: {page.url[:80]}")
        except Exception as e:
            print(f"  Page load error: {e}")
            try:
                page.goto(auth_url, wait_until="commit", timeout=120000)
                print(f"  Retry loaded, URL: {page.url[:80]}")
            except Exception as e2:
                print(f"  Retry failed: {e2}")
                browser.close()
                return None

        for i in range(30):
            time.sleep(2)
            loaded = page.evaluate("() => typeof window.SentinelSDK !== 'undefined'")
            if loaded:
                print(f"  SentinelSDK loaded after {i * 2}s")
                break
            if i == 0:
                # Check page content on first iteration
                title = page.title()
                print(f"  Page title: {title}")
                if "cloudflare" in title.lower() or "just a moment" in title.lower():
                    print(f"  Cloudflare challenge detected, waiting...")
        else:
            print("  SentinelSDK not loaded after 60s!")
            # Save screenshot for debugging
            try:
                page.screenshot(path="sentinel_fail.png")
                print("  Screenshot saved to sentinel_fail.png")
            except:
                pass
            browser.close()
            return None

        page.evaluate("() => SentinelSDK.init()")
        time.sleep(2)

        did = page.evaluate("() => document.cookie.match(/oai-did=([^;]+)/)?.[1] || ''")

        sentinel_token = page.evaluate(
            """(did) => {
                return SentinelSDK.token().then(raw => {
                    const parsed = JSON.parse(raw);
                    parsed.id = did;
                    parsed.flow = 'username_password_create';
                    return JSON.stringify(parsed);
                });
            }""",
            did,
        )

        sentinel_so = page.evaluate(
            """(did) => {
                return SentinelSDK.token().then(raw => {
                    const parsed = JSON.parse(raw);
                    return JSON.stringify({
                        so: raw,
                        c: parsed.c,
                        id: did,
                        flow: 'oauth_create_account'
                    });
                });
            }""",
            did,
        )

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies())
        browser.close()

    result = {
        "sentinel_token": sentinel_token,
        "sentinel_so_token": sentinel_so,
        "cookie_str": cookie_str,
        "oai_did": did,
    }
    save_cache(result)
    return result


# Aliases for backward compatibility
_extract_sentinel = extract_sentinel
_get_cached_sentinel = get_cached
