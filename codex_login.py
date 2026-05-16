"""Codex OAuth login — acquire access/refresh tokens via pure API calls.

Requires an existing ChatGPT account (phone + password).
Handles both first-time login (add-email) and subsequent logins (email OTP).

Usage:
  python codex_login.py --phone +573238903957 --password 'A8i6HDvW9!A1'
"""
import json, time, base64, hashlib, os, secrets, re, sys, random, string, argparse
from urllib.parse import quote, parse_qs, urlparse, urlencode
from pathlib import Path
from curl_cffi import requests as curl_requests

sys.path.insert(0, str(Path(__file__).parent))
from sentinel import extract_sentinel, clear_cache

CFG = json.load(open(Path(__file__).parent / "config.json"))
UA = CFG["http"]["user_agent_chrome"]


def _mail_provider():
    return CFG.get('mail', {}).get('provider', 'skymail')


def _get_mail_token():
    provider = _mail_provider()
    if provider == 'skymail':
        return _skymail_get_token()
    elif provider == 'shanmail':
        return CFG['shanmail']['token']
    else:
        raise ValueError(f"Unknown mail provider: {provider}")


def _skymail_get_token():
    r = curl_requests.post(
        f"{CFG['skymail']['base_url']}/api/public/genToken",
        json={'email': CFG['skymail']['admin_email'], 'password': CFG['skymail']['admin_password']},
        impersonate='chrome', timeout=15)
    return r.json()['data']['token']


def _get_mail_poll(token, email_addr):
    provider = _mail_provider()
    if provider == 'skymail':
        return _skymail_poll(token, email_addr)
    elif provider == 'shanmail':
        return _shanmail_poll(token, email_addr)
    else:
        raise ValueError(f"Unknown mail provider: {provider}")


def _skymail_poll(token, email_addr):
    ecode = None
    h_sm = {'Authorization': token, 'Content-Type': 'application/json'}
    for _ in range(40):
        time.sleep(3); print('.', end='', flush=True)
        try:
            r = curl_requests.post(
                f"{CFG['skymail']['base_url']}/api/public/emailList",
                headers=h_sm, json={'toEmail': email_addr, 'num': 1, 'size': 5},
                impersonate='chrome', timeout=10)
            if r.status_code != 200: continue
            for em in (r.json().get('data') or []):
                raw = (em.get('content') or '') + ' ' + (em.get('text') or '')
                clean = re.sub(r'<style[^>]*>.*?</style>', '', raw, flags=re.DOTALL)
                clean = re.sub(r'<[^>]+>', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()
                m = re.search(r'(?<!\d)(\d{6})(?!\d)', clean)
                if m: ecode = m.group(1); break
        except: pass
        if ecode: break
    return ecode


def _shanmail_poll(token, email_addr):
    ecode = None
    h_sm = {'Authorization': f'Bearer {token}'}
    for _ in range(40):
        time.sleep(3); print('.', end='', flush=True)
        try:
            r = curl_requests.get(
                f"{CFG['shanmail']['base_url']}/api/mail/get_mail",
                headers=h_sm,
                impersonate='chrome', timeout=10)
            if r.status_code != 200: continue
            data = r.json()
            if isinstance(data, list):
                for em in data:
                    raw = (em.get('content') or '') + ' ' + (em.get('subject') or '') + ' ' + (em.get('text') or '')
                    clean = re.sub(r'<style[^>]*>.*?</style>', '', raw, flags=re.DOTALL)
                    clean = re.sub(r'<[^>]+>', ' ', clean)
                    clean = re.sub(r'\s+', ' ', clean).strip()
                    m = re.search(r'(?<!\d)(\d{6})(?!\d)', clean)
                    if m: ecode = m.group(1); break
        except: pass
        if ecode: break
    return ecode


def login(phone, password):
    """Full Codex OAuth login via API. Returns enriched token dict."""
    auto_email = ''.join(random.choices(string.ascii_lowercase, k=12)) + f'@{CFG["chatgpt"]["mail_domain"]}'

    timings = []
    def tick(label): timings.append((label, time.time())); print(f'[{label}]', end=' ', flush=True)
    def tock(): timings[-1] = (timings[-1][0], time.time() - timings[-1][1])

    print(f'Codex OAuth Login (API)')
    print(f'  Phone: {phone}')

    # ── 1. Sentinel ──
    tick('Sentinel')
    clear_cache()
    sd = extract_sentinel(use_proxy=False)
    if not sd:
        raise SystemExit('Sentinel extraction failed')
    tock()

    # Build session with Cloudflare-only cookies
    auth_prefixes = ('oai-login-csrf', 'oai-did', 'oai-client-auth', 'auth-session',
                     'auth_provider', 'login_session', 'unified_session',
                     'rg_context', 'iss_context')
    session = curl_requests.Session()
    for pair in sd['cookie_str'].split('; '):
        if '=' in pair:
            k, v = pair.split('=', 1)
            if not any(k.startswith(p) for p in auth_prefixes):
                session.cookies.set(k, v, domain='.openai.com')

    api_h = {
        'User-Agent': UA,
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
        'Content-Type': 'application/json',
        'Origin': 'https://auth.openai.com',
        'openai-sentinel-token': sd['sentinel_token'],
    }
    browser_h = {**api_h, 'Accept': 'text/html,application/xhtml+xml'}

    # PKCE
    cv = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
    cc = base64.urlsafe_b64encode(hashlib.sha256(cv.encode()).digest()).decode().rstrip('=')
    st = secrets.token_urlsafe(16)
    client_id = CFG['chatgpt']['codex_client_id']
    redirect_uri = 'http://localhost:1455/auth/callback'
    scope = 'openid profile email offline_access api.connectors.read api.connectors.invoke'

    # ── 2. OAuth redirect → get CSRF cookie ──
    tick('OAuth')
    oauth_url = (
        f'https://auth.openai.com/oauth/authorize'
        f'?client_id={client_id}&scope={quote(scope)}&response_type=code'
        f'&redirect_uri={quote(redirect_uri)}&prompt=login&state={st}'
        f'&code_challenge={cc}&code_challenge_method=S256'
        f'&codex_cli_simplified_flow=true&id_token_add_organizations=true'
        f'&originator=codex_cli_rs'
    )
    session.get(oauth_url, headers=browser_h, impersonate='chrome',
                allow_redirects=True, timeout=30)
    session.get('https://auth.openai.com/log-in', headers=browser_h, impersonate='chrome',
                allow_redirects=True, timeout=30)
    tock()

    # ── 3. Phone ──
    tick('Phone')
    r = session.post('https://auth.openai.com/api/accounts/authorize/continue',
                     json={'username': {'kind': 'phone_number', 'value': phone}},
                     headers=api_h, impersonate='chrome', timeout=30)
    d = r.json()
    print(f'  → {d.get("page",{}).get("type","?")}')

    session.get('https://auth.openai.com/api/accounts/client_auth_session_dump',
                headers=api_h, impersonate='chrome', timeout=30)
    tock()

    # ── 4. Password ──
    tick('Password')
    r = session.post('https://auth.openai.com/api/accounts/password/verify',
                     json={'password': password},
                     headers=api_h, impersonate='chrome', timeout=30)
    d = r.json()
    next_url = d.get('continue_url', '')
    page_type = d.get('page', {}).get('type', '?')
    print(f'  → {page_type}')
    tock()

    # ── 5. Email ──
    tick('Email')
    if page_type == 'add_email':
        r = session.post('https://auth.openai.com/api/accounts/add-email/send',
                         json={'email': auto_email},
                         headers=api_h, impersonate='chrome', timeout=30)
        d = r.json()
        next_url = d.get('continue_url', '')
        poll_email = auto_email
    else:
        r = session.get('https://auth.openai.com/api/accounts/client_auth_session_dump',
                        headers=api_h, impersonate='chrome', timeout=30)
        poll_email = r.json().get('client_auth_session', {}).get('email', '')
        if not poll_email:
            raise SystemExit('Could not determine account email')
    print(f'  → {poll_email}')
    tock()

    # ── 6. Email OTP ──
    tick('Email OTP')
    mail_token = _get_mail_token()
    ecode = _get_mail_poll(mail_token, poll_email)
    if not ecode:
        raise SystemExit('\n  FAILED: Email OTP timeout')
    print(f' {ecode}!')

    r = session.post('https://auth.openai.com/api/accounts/email-otp/validate',
                     json={'code': ecode},
                     headers=api_h, impersonate='chrome', timeout=30)
    d = r.json()
    next_url = d.get('continue_url', '')
    tock()

    # ── 7. Workspace → Consent → Code ──
    tick('Consent')
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
    r = session.get(r.headers['Location'], headers=browser_h, impersonate='chrome',
                    allow_redirects=False, timeout=30)
    r = session.get(r.headers['Location'], headers=browser_h, impersonate='chrome',
                    allow_redirects=False, timeout=30)
    loc = r.headers.get('Location', '')

    auth_code = (parse_qs(urlparse(loc).query).get('code') or [None])[0]
    if not auth_code:
        raise SystemExit(f'No code in: {loc[:150]}')
    tock()

    # ── 8. Exchange ──
    tick('Token')
    body = urlencode({
        'grant_type': 'authorization_code', 'code': auth_code,
        'redirect_uri': redirect_uri, 'client_id': client_id,
        'code_verifier': cv,
    })
    r = curl_requests.post('https://auth.openai.com/oauth/token', data=body,
                           headers={'Content-Type': 'application/x-www-form-urlencoded',
                                    'Accept': 'application/json'},
                           impersonate='chrome', timeout=30)
    if r.status_code != 200:
        raise SystemExit(f'Token exchange failed [{r.status_code}]: {r.text[:300]}')

    t = r.json()
    tock()

    # Extract account_id from JWT
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
        '_email': poll_email,
    }

    # Save
    tokens_dir = Path(__file__).parent / 'tokens'
    tokens_dir.mkdir(exist_ok=True)
    fname_phone = tokens_dir / f'codex-{phone.replace("+","")}.json'
    with open(fname_phone, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    fname_auth = tokens_dir / f'auth_{phone.replace("+","")}.json'
    with open(fname_auth, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Timing summary
    print(f'\n{"=" * 50}')
    print(f'{"Step":<30} {"Time (s)":>10}')
    print(f'{"─" * 50}')
    total = 0
    for name, elapsed in timings:
        print(f'{name:<30} {elapsed:>10.2f}')
        total += elapsed
    print(f'{"─" * 50}')
    print(f'{"TOTAL":<30} {total:>10.2f}')
    print(f'{"=" * 50}')

    print(f'\n  ACCESS_TOKEN:  {t.get("access_token","")[:60]}...')
    print(f'  REFRESH_TOKEN: {t.get("refresh_token","")[:60]}...')
    print(f'  Saved to {fname_auth}')
    print('*** SUCCESS! ***')
    return result


def main():
    parser = argparse.ArgumentParser(description="Codex OAuth Login (API-only)")
    parser.add_argument('--phone', required=True)
    parser.add_argument('--password', required=True)
    args = parser.parse_args()
    login(args.phone, args.password)


if __name__ == '__main__':
    main()
