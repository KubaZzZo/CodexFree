"""ChatGPT phone-number registration via pure API calls.

Flow:
  1. Extract Cloudflare sentinel tokens (shared sentinel module)
  2. Get temporary phone number from HeroSMS
  3. Register account via auth.openai.com API
  4. Auto-login to Codex OAuth to get tokens (optional, --no-codex to skip)

Usage:
  python chatgpt_register.py                    # register 1 account + Codex token
  python chatgpt_register.py --count 3          # batch register 3 accounts
  python chatgpt_register.py --no-codex         # register only, skip Codex login
"""
import json, time, re, random, string, argparse, os, sys, base64, hashlib, secrets, uuid, threading
from urllib.parse import quote, urlencode
from pathlib import Path
from curl_cffi import requests as curl_requests

# Add project root to path for sentinel import
sys.path.insert(0, str(Path(__file__).parent))

from sentinel import extract_sentinel, clear_cache, get_proxy_url
from email_api import get_email_from_provider, EmailAPIError

# Import mail functions from codex_login
sys.path.insert(0, str(Path(__file__).parent))
from codex_login import _get_mail_token, _get_mail_poll

# Import mail functions from codex_login
sys.path.insert(0, str(Path(__file__).parent))
from codex_login import _get_mail_token, _get_mail_poll

# Import mail functions from codex_login
sys.path.insert(0, str(Path(__file__).parent))
from codex_login import _get_mail_token, _get_mail_poll
from email_api import get_email_from_provider, EmailAPIError
from email_api import get_email_from_provider, EmailAPIError

# ── Config ──
CFG = json.load(open(Path(__file__).parent / "config.json"))
UA = CFG["http"]["user_agent_chrome"]
PROXY_URL = get_proxy_url()

# ── Timing ──
_tls = threading.local()

def _tick(name):
    if not hasattr(_tls, "timings"): _tls.timings = []
    _tls.timings.append((name, time.time()))
    print(f'  [{name}]', end=' ', flush=True)

def _tock():
    t = _tls.timings
    t[-1] = (t[-1][0], time.time() - t[-1][1])

def _print_timings():
    t = _tls.timings; total = sum(e for _, e in t)
    print(f'\n  {"=" * 50}')
    print(f'  {"Step":<40} {"Time (s)":>8}')
    print(f'  {"-" * 50}')
    for name, elapsed in t: print(f'  {name:<40} {elapsed:>8.2f}')
    print(f'  {"-" * 50}')
    print(f'  {"TOTAL":<40} {total:>8.2f}')
    print(f'  {"=" * 50}')
    return total


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════

def _random_name():
    first = ["James", "John", "Robert", "Michael", "David", "William",
             "Mary", "Linda", "Barbara", "Jennifer"]
    last = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
            "Miller", "Davis", "Wilson", "Anderson"]
    return random.choice(first), random.choice(last)


def _random_birthdate():
    y, m, d = random.randint(1985, 2004), random.randint(1, 12), random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"


def _generate_password():
    reg = CFG.get("registration", {})
    length = reg.get("password_random_length", 12)
    length = int(length) if length else 12
    suffix = reg.get("password_suffix", "!A1")
    charset = reg.get("password_charset", "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    base_len = max(1, length - len(suffix))
    return "".join(random.choices(charset, k=base_len)) + suffix


# ═══════════════════════════════════════════
# HeroSMS (SMS-Activate compatible API)
# ═══════════════════════════════════════════

HEROSMS_BASE = "https://hero-sms.com"


def _sms_api(action, **params):
    p = {"api_key": CFG["phone_sms"]["herosms_api_key"], "action": action, **params}
    r = curl_requests.get(f"{HEROSMS_BASE}/stubs/handler_api.php", params=p,
                          proxy=PROXY_URL, impersonate="chrome", timeout=30)
    return r.text.strip()


def _sms_balance():
    return _sms_api("getBalance")


def _sms_get_prices(service="dr", country=None):
    params = {"service": service}
    if country:
        params["country"] = country
    resp = _sms_api("getPrices", **params)
    if not resp:
        return None
    try:
        return json.loads(resp)
    except json.JSONDecodeError:
        return None


def _sms_pick_country(service="dr", preferred=None):
    sms_cfg = CFG.get("phone_sms", {})
    max_price = sms_cfg.get("max_price", 0.08)
    min_price = sms_cfg.get("min_price", 0.04)
    blocked = set(sms_cfg.get("blocked_countries", []))

    prices = _sms_get_prices(service=service)
    if not prices:
        return preferred or "6", None

    candidates = []
    for country_code, operators in prices.items():
        if country_code in blocked or not isinstance(operators, dict):
            continue
        for op_code, info in operators.items():
            if not isinstance(info, dict):
                continue
            cost = float(info.get("cost", 999))
            cnt = int(info.get("count", 0))
            if cost <= max_price and cnt > 0:
                candidates.append((cost, country_code, op_code, cnt))

    if not candidates:
        print(f"  No countries under ${max_price}")
        return preferred or "6", None

    candidates.sort(key=lambda x: x[0])
    reliable = [c for c in candidates if c[0] >= min_price]
    if reliable:
        candidates = reliable

    if preferred:
        pref = [c for c in candidates if c[1] == preferred]
        if pref:
            return pref[0][1], pref[0][2]

    best = candidates[0]
    print(f"  Best country: {best[1]} price=${best[0]:.4f} count={best[3]}")
    return best[1], best[2]


def _sms_get_number(service="dr", country=None, operator=None):
    params = {"service": service}
    if country: params["country"] = country
    if operator and operator != service: params["operator"] = operator
    resp = _sms_api("getNumber", **params)
    if resp.startswith("ACCESS_NUMBER:"):
        parts = resp.split(":")
        if len(parts) >= 3:
            return parts[1], parts[2]
    print(f'  [SMS] getNumber failed: {resp}')
    return None, None


def _sms_get_status(activation_id):
    resp = _sms_api("getStatus", id=activation_id)
    if resp.startswith("STATUS_OK:"):
        return "OK", resp.split(":", 2)[1] if len(resp.split(":")) > 1 else ""
    if resp.startswith("STATUS_WAIT_CODE"):
        return "WAIT_CODE", ""
    if resp.startswith("STATUS_WAIT_RESEND"):
        return "WAIT_RESEND", ""
    if resp.startswith("STATUS_CANCEL"):
        return "CANCEL", ""
    return "UNKNOWN", resp


def _sms_set_status(activation_id, status):
    resp = _sms_api("setStatus", id=activation_id, status=str(status))
    return resp


def _sms_poll(activation_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(CFG["timeouts"]["poll_interval"])
        status, code = _sms_get_status(activation_id)
        print(".", end="", flush=True)
        if status == "OK" and code:
            return code
        if status in ("CANCEL",):
            return None
    return None


def _sms_resend(activation_id):
    return _sms_api("resend", id=activation_id)


# ═══════════════════════════════════════════
# 5sim.net SMS Provider
# ═══════════════════════════════════════════

FIVESIM_BASE = "https://5sim.net/v1"


def _5sim_api(method, path, **params):
    sms_cfg = CFG.get("phone_sms", {})
    token = sms_cfg.get("fivesim_api_key", "")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{FIVESIM_BASE}{path}"
    r = curl_requests.request(method, url, params=params or None,
                              proxy=PROXY_URL,
                              headers=headers, impersonate="chrome", timeout=30)
    try:
        return r.json()
    except Exception:
        return r.text.strip()


def _5sim_balance():
    data = _5sim_api("GET", "/user/profile")
    if isinstance(data, dict):
        return float(data.get("balance", 0))
    return 0.0


def _5sim_get_prices(product="openai"):
    data = _5sim_api("GET", "/guest/prices", product=product)
    if not isinstance(data, dict):
        return None
    # Restructure: {country: {operator: {cost, count, rate}}}
    result = {}
    for country, ops in data.items():
        if not isinstance(ops, dict):
            continue
        result[country] = {}
        for op, info in ops.items():
            if isinstance(info, dict):
                result[country][op] = {
                    "cost": info.get("cost", 0),
                    "count": info.get("count", 0),
                    "rate": info.get("rate", 0),
                }
    return result


# Known countries that have had openai stock on 5sim
_FIVESIM_COUNTRIES = [
    "indonesia", "philippines", "vietnam", "usa", "germany",
    "india", "brazil", "mexico", "russia", "unitedkingdom",
    "france", "colombia", "pakistan", "nigeria", "china",
]


def _5sim_pick_country(product="openai", preferred=None):
    sms_cfg = CFG.get("phone_sms", {})
    blocked = set(sms_cfg.get("blocked_countries", []))

    # Try prices API first (may show 0 stock but worth trying)
    prices = _5sim_get_prices(product)
    if prices:
        candidates = []
        for country, ops in prices.items():
            if country in blocked:
                continue
            for op, info in ops.items():
                cost = float(info.get("cost", 999))
                cnt = int(info.get("count", 0))
                if cnt > 0:
                    candidates.append((cost, country, op, cnt))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            if preferred and preferred != "any":
                pref = [c for c in candidates if c[1] == preferred]
                if pref:
                    return pref[0][1], pref[0][2]
            best = candidates[0]
            print(f"  Best 5sim country: {best[1]} price=${best[0]:.4f} count={best[3]}")
            return best[1], best[2]

    # Prices API unreliable; return preferred or first candidate
    # _5sim_get_number will try multiple countries
    if preferred and preferred != "any" and preferred not in blocked:
        return preferred, "any"
    return "any", "any"


def _5sim_get_number(country="any", operator="any", product="openai"):
    sms_cfg = CFG.get("phone_sms", {})
    blocked = set(sms_cfg.get("blocked_countries", []))

    # Build list of countries to try
    countries_to_try = []
    if country and country != "any":
        countries_to_try.append(country)
    countries_to_try.extend(c for c in _FIVESIM_COUNTRIES if c != country and c not in blocked)

    for c in countries_to_try:
        data = _5sim_api("GET", f"/user/buy/activation/{c}/{operator}/{product}")
        if isinstance(data, dict) and data.get("id") and data.get("phone"):
            print(f"  5sim: got number from {c}")
            return str(data["id"]), str(data["phone"])
        if isinstance(data, dict) and data.get("id") is None:
            # "no free phones" — try next country
            continue
    return None, None


def _5sim_check(order_id):
    data = _5sim_api("GET", f"/user/check/{order_id}")
    if not isinstance(data, dict):
        return "UNKNOWN", ""
    status = data.get("status", "")
    sms_list = data.get("sms") or []
    if status == "RECEIVED" and sms_list:
        code = sms_list[-1].get("code", "")
        return "OK", str(code) if code else ""
    if status == "FINISHED":
        return "OK", ""
    if status == "CANCELED":
        return "CANCEL", ""
    if status == "BANNED":
        return "CANCEL", ""
    return "WAIT_CODE", ""


def _5sim_finish(order_id):
    return _5sim_api("GET", f"/user/finish/{order_id}")


def _5sim_cancel(order_id):
    return _5sim_api("GET", f"/user/cancel/{order_id}")


def _5sim_ban(order_id):
    return _5sim_api("GET", f"/user/ban/{order_id}")


def _5sim_poll(order_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(CFG["timeouts"]["poll_interval"])
        status, code = _5sim_check(order_id)
        print(".", end="", flush=True)
        if status == "OK" and code:
            return code
        if status == "CANCEL":
            return None
    return None


# ═══════════════════════════════════════════
# Provider Routing
# ═══════════════════════════════════════════

def _provider():
    return CFG.get("phone_sms", {}).get("provider", "herosms")


def _get_sms_balance():
    if _provider() == "fivesim":
        return f"ACCESS_BALANCE:{_5sim_balance()}"
    return _sms_balance()


def _get_sms_pick_country():
    sms_cfg = CFG.get("phone_sms", {})
    if _provider() == "fivesim":
        return _5sim_pick_country(
            product=sms_cfg.get("fivesim_product", "openai"),
            preferred=sms_cfg.get("country") or None,
        )
    return _sms_pick_country(
        service=sms_cfg.get("service", "dr"),
        preferred=sms_cfg.get("country") or None,
    )


def _get_sms_number(country, operator=None):
    sms_cfg = CFG.get("phone_sms", {})
    if _provider() == "fivesim":
        return _5sim_get_number(
            country=country or "any",
            operator=operator or sms_cfg.get("fivesim_operator", "any"),
            product=sms_cfg.get("fivesim_product", "openai"),
        )
    return _sms_get_number(
        service=sms_cfg.get("service", "dr"),
        country=country, operator=operator,
    )


def _get_sms_poll(order_id, timeout=120):
    if _provider() == "fivesim":
        return _5sim_poll(order_id, timeout=timeout)
    return _sms_poll(order_id, timeout=timeout)


def _get_sms_resend(order_id):
    if _provider() == "fivesim":
        return ""  # 5sim has no resend; just re-poll
    return _sms_resend(order_id)


def _get_sms_finish(order_id):
    if _provider() == "fivesim":
        return _5sim_finish(order_id)
    return _sms_set_status(order_id, 6)


def _get_sms_cancel(order_id):
    if _provider() == "fivesim":
        return _5sim_cancel(order_id)
    return _sms_set_status(order_id, 8)


# ═══════════════════════════════════════════
# Registration API
# ═══════════════════════════════════════════

def _api_headers(sentinel_token):
    return {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://auth.openai.com",
        "openai-sentinel-token": sentinel_token,
    }


def register_account(sentinel_data, phone, password, activation_id):
    """Register a new ChatGPT account via API calls. Returns account info or None."""
    auth_base = CFG["chatgpt"].get("auth_base_url", "https://auth.openai.com")
    chat_base = CFG["chatgpt"].get("chat_base_url", "https://chatgpt.com")
    ua = CFG["http"]["user_agent_chrome"]
    did = sentinel_data.get("oai_did", str(uuid.uuid4()))
    session_logging_id = str(uuid.uuid4()).replace("-", "")

    # Build session with sentinel cookies (Cloudflare-only)
    auth_prefixes = ('oai-login-csrf', 'oai-did', 'oai-client-auth', 'auth-session',
                     'auth_provider', 'login_session', 'unified_session',
                     'rg_context', 'iss_context')
    session = curl_requests.Session()
    if PROXY_URL:
        session.proxies = {"http": PROXY_URL, "https": PROXY_URL}
    for pair in sentinel_data['cookie_str'].split('; '):
        if '=' in pair:
            k, v = pair.split('=', 1)
            if not any(k.startswith(p) for p in auth_prefixes):
                session.cookies.set(k, v, domain='.openai.com')

    base_headers = {"User-Agent": ua, "Accept": "application/json"}

    first, last = _random_name()
    birthdate = _random_birthdate()

    # 1-Prime session (create-account + signin + authorize)
    _tick('1-Auth flow')
    session.get(f"{auth_base}/create-account",
        headers={**base_headers, "Accept": "text/html,application/xhtml+xml"},
        impersonate="chrome", timeout=30)

    signin_url = (
        f"{chat_base}/api/auth/signin/openai"
        f"?prompt=login"
        f"&ext-oai-did={did}"
        f"&auth_session_logging_id={session_logging_id}"
        f"&screen_hint=login_or_signup"
        f"&login_hint={quote(phone, safe='')}"
    )
    session.post(signin_url,
        data=urlencode({"csrfToken": "true"}),
        headers={**base_headers, "Content-Type": "application/x-www-form-urlencoded",
                 "Origin": chat_base, "Referer": f"{chat_base}/"},
        impersonate="chrome", timeout=30)

    scope = "openid email profile offline_access model.request model.read organization.read organization.write"
    auth_session_url = (
        f"{auth_base}/api/accounts/authorize"
        f"?client_id={CFG['chatgpt']['chat_web_client_id']}"
        f"&scope={quote(scope)}"
        f"&response_type=code"
        f"&redirect_uri={quote('https://chatgpt.com/api/auth/callback/openai')}"
        f"&audience={quote('https://api.openai.com/v1')}"
        f"&device_id={did}"
        f"&prompt=login"
        f"&screen_hint=login_or_signup"
        f"&login_hint={quote(phone, safe='')}"
        f"&state={secrets.token_urlsafe(16)}"
    )
    r = session.get(auth_session_url,
        headers={**base_headers, "Accept": "text/html,application/xhtml+xml", "Origin": auth_base, "Referer": f"{chat_base}/"},
        impersonate="chrome", timeout=30)
    redirect_path = r.url.split("auth.openai.com")[-1]
    print(f'→ {redirect_path[:40]}')
    _tock()

    # Check for error redirect
    if "/error" in redirect_path:
        print('  [!] Auth flow failed (error redirect)')
        return None

    # Check if already registered
    if "log-in" in redirect_path or "login" in redirect_path:
        print('  Already registered!')
        return None

    # 2-Register phone + password
    _tick('2-Register')
    register_h = {
        **base_headers,
        "Origin": auth_base,
        "Referer": f"{auth_base}/create-account/password",
    }
    if sentinel_data.get("sentinel_token"):
        register_h["openai-sentinel-token"] = sentinel_data["sentinel_token"]
    r = session.post(f"{auth_base}/api/accounts/user/register",
        json={"password": password, "username": phone},
        headers=register_h, impersonate="chrome", timeout=30)
    reg_data = {}
    try:
        reg_data = r.json()
    except:
        reg_data = {"_raw": r.text[:300]}
    print(f'→ {r.status_code}')
    _tock()

    if r.status_code != 200:
        return None

    # 3-Trigger SMS via continue_url from register response
    _tick('3-Send SMS')
    continue_url = reg_data.get("continue_url", "")
    if continue_url:
        r = session.get(continue_url,
            headers={**base_headers, "Origin": auth_base, "Referer": f"{auth_base}/create-account/password"},
            impersonate="chrome", timeout=30)
        print(f'→ {r.status_code}', end='')
    else:
        _tock()
        return None
    _tock()

    # 4-Poll for SMS code
    _tick('4-SMS OTP')
    sms_code = _get_sms_poll(activation_id, timeout=120)
    if not sms_code:
        print(' resend...', end='', flush=True)
        r = session.post(f"{auth_base}/api/accounts/phone-otp/resend",
            headers={**base_headers, "Origin": auth_base, "Referer": f"{auth_base}/contact-verification"},
            impersonate="chrome", timeout=30)
        if r.status_code == 200:
            sms_code = _get_sms_poll(activation_id, timeout=180)
    if not sms_code:
        print(' timeout')
        _tock()
        return None
    print(f' {sms_code}')
    _tock()

    # 5-Validate phone OTP
    _tick('5-Validate')
    r = session.post(f"{auth_base}/api/accounts/phone-otp/validate",
        json={"code": sms_code},
        headers={**base_headers, "Origin": auth_base, "Referer": f"{auth_base}/contact-verification"},
        impersonate="chrome", timeout=30)
    print(f'→ {r.status_code}')
    _tock()

    if r.status_code != 200:
        return None

    # 6-Create account
    _tick('6-Create')
    create_h = {
        **base_headers,
        "Origin": auth_base,
        "Referer": f"{auth_base}/about-you",
    }
    if sentinel_data.get("sentinel_token"):
        create_h["openai-sentinel-token"] = sentinel_data["sentinel_token"]
    if sentinel_data.get("sentinel_so_token"):
        create_h["openai-sentinel-so-token"] = sentinel_data["sentinel_so_token"]
    r = session.post(f"{auth_base}/api/accounts/create_account",
        json={"name": f"{first} {last}", "birthdate": birthdate},
        headers=create_h, impersonate="chrome", timeout=30)
    print(f'→ {r.status_code}')
    _tock()

    if r.status_code != 200:
        return None

    print(f'  Registered: {phone}')

    return {
        'phone': phone,
        'password': password,
        'name': f'{first} {last}',
        'birthdate': birthdate,
        'activation_id': activation_id,
        'registered_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }


# ═══════════════════════════════════════════
# Codex OAuth login (API-only)
# ═══════════════════════════════════════════

def login_codex(phone, password, auto_email=None, sentinel_data=None):
    """Login to Codex OAuth and get tokens via pure API calls."""
    _tls.timings = []
    if auto_email is None:
        try:
            auto_email, _ = get_email_from_provider(CFG)
        except EmailAPIError as e:
            print(f'  Email API error: {e}, falling back to domain email')
            auto_email = ''.join(random.choices(string.ascii_lowercase, k=12)) + f'@{CFG["chatgpt"]["mail_domain"]}'

    # 1-Sentinel (reuse from registration if provided)
    _tick('1-Sentinel')
    if sentinel_data:
        sd = sentinel_data
        print(f'→ reused')
    else:
        clear_cache()
        sd = extract_sentinel()
    if not sd:
        raise SystemExit('Sentinel extraction failed')
    _tock()

    # Build session
    auth_prefixes = ('oai-login-csrf', 'oai-did', 'oai-client-auth', 'auth-session',
                     'auth_provider', 'login_session', 'unified_session',
                     'rg_context', 'iss_context')
    session = curl_requests.Session()
    for pair in sd['cookie_str'].split('; '):
        if '=' in pair:
            k, v = pair.split('=', 1)
            if not any(k.startswith(p) for p in auth_prefixes):
                session.cookies.set(k, v, domain='.openai.com')

    api_h = _api_headers(sd['sentinel_token'])
    browser_h = {**api_h, 'Accept': 'text/html,application/xhtml+xml'}

    # PKCE
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip('=')
    oauth_state = secrets.token_urlsafe(16)
    client_id = CFG['chatgpt']['codex_client_id']
    redirect_uri = 'http://localhost:1455/auth/callback'
    scope = 'openid profile email offline_access api.connectors.read api.connectors.invoke'

    # 2-OAuth redirect + CSRF
    _tick('2-OAuth')
    oauth_url = (
        f'https://auth.openai.com/oauth/authorize'
        f'?client_id={client_id}&scope={quote(scope)}&response_type=code'
        f'&redirect_uri={quote(redirect_uri)}&prompt=login&state={oauth_state}'
        f'&code_challenge={code_challenge}&code_challenge_method=S256'
        f'&codex_cli_simplified_flow=true&id_token_add_organizations=true'
        f'&originator=codex_cli_rs'
    )
    session.get(oauth_url, headers=browser_h, impersonate='chrome',
                allow_redirects=True, timeout=30)
    session.get('https://auth.openai.com/log-in', headers=browser_h, impersonate='chrome',
                allow_redirects=True, timeout=30)
    _tock()

    # 3-Phone
    _tick('3-Phone')
    r = session.post('https://auth.openai.com/api/accounts/authorize/continue',
                     json={'username': {'kind': 'phone_number', 'value': phone}},
                     headers=api_h, impersonate='chrome', timeout=30)
    page = r.json().get('page', {}).get('type', '?')
    print(f'→ {page}')
    session.get('https://auth.openai.com/api/accounts/client_auth_session_dump',
                headers=api_h, impersonate='chrome', timeout=30)
    _tock()

    # 4-Password
    _tick('4-Password')
    r = session.post('https://auth.openai.com/api/accounts/password/verify',
                     json={'password': password},
                     headers=api_h, impersonate='chrome', timeout=30)
    d = r.json()
    next_url = d.get('continue_url', '')
    page_type = d.get('page', {}).get('type', '?')
    print(f'→ {page_type}')
    _tock()

    # 5-Email setup
    _tick('5-Email')
    if page_type == 'add_email':
        r = session.post('https://auth.openai.com/api/accounts/add-email/send',
                         json={'email': auto_email},
                         headers=api_h, impersonate='chrome', timeout=30)
        d = r.json()
        next_url = d.get('continue_url', '')
        poll_email_addr = auto_email
    else:
        r = session.get('https://auth.openai.com/api/accounts/client_auth_session_dump',
                        headers=api_h, impersonate='chrome', timeout=30)
        poll_email_addr = r.json().get('client_auth_session', {}).get('email', '')
        if not poll_email_addr:
            raise SystemExit('Could not determine account email')
    print(f'→ {poll_email_addr}')
    _tock()

    # 6-Email OTP
    _tick('6-Email OTP')
    mail_token = _get_mail_token()
    ecode = _get_mail_poll(mail_token, poll_email_addr)
    print(f' {ecode}' if ecode else ' timeout')
    _tock()

    if not ecode:
        raise SystemExit('Email OTP timeout')

    r = session.post('https://auth.openai.com/api/accounts/email-otp/validate',
                     json={'code': ecode},
                     headers=api_h, impersonate='chrome', timeout=30)
    d = r.json()
    next_url = d.get('continue_url', '')

    # 7-Consent
    _tick('7-Consent')
    r = session.get('https://auth.openai.com/api/accounts/client_auth_session_dump',
                    headers=api_h, impersonate='chrome', timeout=30)
    ws = r.json().get('client_auth_session', {}).get('workspaces', [])
    if ws:
        r = session.post('https://auth.openai.com/api/accounts/workspace/select',
                         json={'workspace_id': ws[0]['id']},
                         headers=api_h, impersonate='chrome', timeout=30)
        next_url = r.json().get('continue_url', '')

    r = session.get(next_url, headers=browser_h, impersonate='chrome',
                    allow_redirects=False, timeout=30)
    loc = r.headers.get('Location', '')
    r = session.get(loc, headers=browser_h, impersonate='chrome',
                    allow_redirects=False, timeout=30)
    loc = r.headers.get('Location', '')
    r = session.get(loc, headers=browser_h, impersonate='chrome',
                    allow_redirects=False, timeout=30)
    loc = r.headers.get('Location', '')
    _tock()

    # 8-Token exchange
    _tick('8-Token')
    from urllib.parse import urlparse, parse_qs
    auth_code = (parse_qs(urlparse(loc).query).get('code') or [None])[0]
    if not auth_code:
        raise SystemExit(f'No code in redirect: {loc[:150]}')

    body = urlencode({
        'grant_type': 'authorization_code', 'code': auth_code,
        'redirect_uri': redirect_uri, 'client_id': client_id,
        'code_verifier': code_verifier,
    })
    r = curl_requests.post('https://auth.openai.com/oauth/token', data=body,
                           headers={'Content-Type': 'application/x-www-form-urlencoded',
                                    'Accept': 'application/json'},
                           impersonate='chrome', timeout=30)
    if r.status_code != 200:
        raise SystemExit(f'Token exchange failed [{r.status_code}]: {r.text[:300]}')

    t = r.json()
    _tock()

    account_id = None
    try:
        parts = t.get('id_token', '').split('.')
        payload = parts[1] + '=' * (4 - len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        auth = decoded.get('https://api.openai.com/auth', {})
        account_id = auth.get('chatgpt_account_id') or auth.get('user_id')
    except:
        pass

    result = {
        'auth_mode': 'chatgpt',
        'OPENAI_API_KEY': None,
        'tokens': {
            'id_token': t.get('id_token', ''),
            'access_token': t.get('access_token', ''),
            'refresh_token': t.get('refresh_token', ''),
            'account_id': account_id,
        },
        'last_refresh': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        '_email': poll_email_addr,
    }

    # Save to tokens/
    tokens_dir = Path(__file__).parent / 'tokens'
    tokens_dir.mkdir(exist_ok=True)
    safe_phone = phone.replace("+", "")
    with open(tokens_dir / f'codex-{safe_phone}.json', 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(tokens_dir / f'auth_{safe_phone}.json', 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    _print_timings()
    print(f'  ACCESS:  {t.get("access_token","")[:50]}...')
    print(f'  REFRESH: {t.get("refresh_token","")[:50]}...')
    print(f'  Saved: {tokens_dir / f"auth_{safe_phone}.json"}')

    return result


# ═══════════════════════════════════════════
# Main
# ═══════════════════════════════════════════

def run_registration():
    """Register one account with retry logic. Returns (account_info, token_info)."""
    _tls.timings = []
    t_start = time.time()
    print(f'{"─" * 50}\n  ChatGPT Phone Registration\n{"─" * 50}')

    # Sentinel (only once, reuse across retries)
    _tick('0-Sentinel')
    sd = extract_sentinel()
    if not sd:
        return None, None
    _tock()

    # Get country preference
    sms_cfg = CFG.get("phone_sms", {})
    if sms_cfg.get("country"):
        country = sms_cfg["country"]
    else:
        country, _ = _get_sms_pick_country()

    password = _generate_password()
    name = _random_name()
    birth = _random_birthdate()
    print(f'  Password: {password}  Name: {name[0]} {name[1]}  Birth: {birth}')

    for retry in range(100):
        _tick(f'Get-Phone#{retry+1}')
        bal = _get_sms_balance()
        activation_id, phone = _get_sms_number(country)
        if not phone:
            print(f'  [!] Failed to get phone number (country={country})')
            _tock()
            return None, None
        if not phone.startswith('+'):
            phone = f'+{phone}'
        print(f'→ {phone} (bal={bal.split(":")[-1] if ":" in bal else bal})')
        _tock()

        result = register_account(sd, phone, password, activation_id)
        if result is not None:
            _get_sms_finish(activation_id)
            _print_timings()
            print(f'  [REGISTER] {phone}  Wall: {time.time() - t_start:.1f}s')
            return result, sd

        print(f'  [!] Failed, retrying...')
        activation_id = None
        phone = None
        time.sleep(2)

    print('  FAILED: All retries exhausted')
    return None, None


def save_result(data, sub="success"):
    """Save registration/token result to output directory."""
    out_dir = Path(CFG.get("output", {}).get("directory", "."))
    out_dir = out_dir / sub if out_dir != Path(".") else Path(sub)
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = CFG.get("output", {}).get("filename_pattern", "chatgpt_{email}_{timestamp}.json")
    identifier = data.get("phone", "unknown").replace("+", "")
    fname = pattern.format(email=identifier, timestamp=int(time.time()))
    out_path = out_dir / fname
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'  Saved: {out_path}')
    return out_path


def main():
    parser = argparse.ArgumentParser(description="ChatGPT Phone Number Registration")
    parser.add_argument("--count", type=int, default=1, help="Number of accounts to register")
    parser.add_argument("--no-codex", action="store_true", help="Skip Codex OAuth login")
    parser.add_argument("--codex-only", action="store_true", help="Only Codex login (requires --phone --password)")
    parser.add_argument("--phone", default=None, help="Phone number for --codex-only")
    parser.add_argument("--password", default=None, help="Password for --codex-only")
    args = parser.parse_args()

    if args.codex_only:
        if not args.phone or not args.password:
            parser.error("--codex-only requires --phone and --password")
        token = login_codex(args.phone, args.password)
        result = {"success": True, "phone": args.phone, "password": args.password, "token": token}
        save_result(result, "tokens")
        return

    sms_providers = ["herosms", "fivesim"]
    current = CFG.get("phone_sms", {}).get("provider", "herosms")
    print("\n  请选择接码平台:")
    for idx, p in enumerate(sms_providers, 1):
        mark = " *" if p == current else ""
        print(f"    [{idx}] {p}{mark}")
    choice = input("  输入选择 (直接回车使用当前): ").strip()
    if choice == "1":
        CFG.setdefault("phone_sms", {})["provider"] = "herosms"
    elif choice == "2":
        CFG.setdefault("phone_sms", {})["provider"] = "fivesim"
    print(f"  当前接码平台: {CFG['phone_sms']['provider']}")

    mail_providers = ["shanmail", "skymail", "domain"]
    current_mail = CFG.get("mail", {}).get("provider", "domain")
    print("\n  请选择邮箱方式:")
    for idx, p in enumerate(mail_providers, 1):
        mark = " *" if p == current_mail else ""
        print(f"    [{idx}] {p}{mark}")
    choice = input("  输入选择 (直接回车使用当前): ").strip()
    if choice == "1":
        CFG.setdefault("mail", {})["provider"] = "shanmail"
    elif choice == "2":
        CFG.setdefault("mail", {})["provider"] = "skymail"
    elif choice == "3":
        CFG.setdefault("mail", {})["provider"] = "domain"
    print(f"  当前邮箱方式: {CFG.get('mail', {}).get('provider', 'domain')}")

    results = []
    for i in range(args.count):
        print(f'\n{"#" * 40}\n  Account {i + 1}/{args.count}\n{"#" * 40}')
        try:
            account, sd = run_registration()
            if not account:
                results.append({"success": False, "error": "registration failed"})
                continue
            result = {"success": True, **account}
            save_result(result, "success")

            if not args.no_codex:
                print(f'\n  Logging into Codex...')
                token = login_codex(account["phone"], account["password"])
                result["token"] = token
                save_result(result, "tokens")

            results.append(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append({"success": False, "error": str(e)})

    success = sum(1 for r in results if r.get("success"))
    print(f'\n  Done. {success}/{args.count} registered.')


if __name__ == "__main__":
    main()
