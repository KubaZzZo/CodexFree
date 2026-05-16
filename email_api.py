"""Email API integration for skymail and shanmail providers."""
import time
import random
import string
from typing import Optional, Tuple
from curl_cffi import requests


class EmailAPIError(Exception):
    """Base exception for email API errors."""
    pass


class ShanMailAPI:
    """ShanMail API client."""

    def __init__(self, api_key: str, base_url: str = "https://zizhu.shanyouxiang.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')

    def get_email(self, email_type: str = "outlook") -> Tuple[str, str]:
        """Get email and password from shanmail.

        Args:
            email_type: 'outlook' or 'hotmail'

        Returns:
            Tuple of (email, password)
        """
        url = f"{self.base_url}/huoqu"
        params = {
            "card": self.api_key,
            "shuliang": 1,
            "leixing": email_type
        }

        try:
            resp = requests.get(url, params=params, impersonate="chrome110", timeout=30)
            resp.raise_for_status()

            # Response format: email----password
            result = resp.text.strip()
            if '----' not in result:
                raise EmailAPIError(f"Invalid shanmail response format: {result}")

            email, password = result.split('----', 1)
            return email.strip(), password.strip()

        except Exception as e:
            raise EmailAPIError(f"Failed to get email from shanmail: {e}")

    def check_balance(self) -> int:
        """Check remaining email balance."""
        url = f"{self.base_url}/yue"
        params = {"card": self.api_key}

        try:
            resp = requests.get(url, params=params, impersonate="chrome110", timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data.get("num", 0)
        except Exception as e:
            raise EmailAPIError(f"Failed to check shanmail balance: {e}")


class SkyMailAPI:
    """SkyMail API client."""

    def __init__(self, base_url: str, admin_email: str, admin_password: str):
        self.base_url = base_url.rstrip('/')
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.session = requests.Session()
        self._token = None

    def _login(self):
        """Login to skymail and get token."""
        url = f"{self.base_url}/api/login"
        data = {
            "email": self.admin_email,
            "password": self.admin_password
        }

        try:
            resp = self.session.post(url, json=data, impersonate="chrome110", timeout=30)
            resp.raise_for_status()
            result = resp.json()
            self._token = result.get("token")
            if not self._token:
                raise EmailAPIError("No token in skymail login response")
        except Exception as e:
            raise EmailAPIError(f"Failed to login to skymail: {e}")

    def get_email(self) -> Tuple[str, str]:
        """Create a new email account.

        Returns:
            Tuple of (email, password)
        """
        if not self._token:
            self._login()

        # Generate random email and password
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

        url = f"{self.base_url}/api/account/create"
        headers = {"Authorization": f"Bearer {self._token}"}
        data = {
            "username": username,
            "password": password
        }

        try:
            resp = self.session.post(url, json=data, headers=headers, impersonate="chrome110", timeout=30)
            resp.raise_for_status()
            result = resp.json()
            email = result.get("email")
            if not email:
                raise EmailAPIError("No email in skymail create response")
            return email, password
        except Exception as e:
            raise EmailAPIError(f"Failed to create skymail account: {e}")

    def get_verification_code(self, email: str, timeout: int = 60) -> Optional[str]:
        """Poll for verification code in email inbox.

        Args:
            email: Email address to check
            timeout: Maximum seconds to wait

        Returns:
            Verification code or None if not found
        """
        if not self._token:
            self._login()

        url = f"{self.base_url}/api/messages"
        headers = {"Authorization": f"Bearer {self._token}"}
        params = {"email": email}

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                resp = self.session.get(url, params=params, headers=headers, impersonate="chrome110", timeout=30)
                resp.raise_for_status()
                messages = resp.json()

                if messages and len(messages) > 0:
                    # Look for verification code in latest message
                    latest = messages[0]
                    body = latest.get("body", "")
                    subject = latest.get("subject", "")

                    # Extract 6-digit code
                    import re
                    match = re.search(r'\b\d{6}\b', body + subject)
                    if match:
                        return match.group(0)

                time.sleep(3)
            except Exception:
                time.sleep(3)

        return None


def get_email_from_provider(config: dict) -> Tuple[str, Optional[str]]:
    """Get email from configured provider.

    Args:
        config: Configuration dict with mail settings

    Returns:
        Tuple of (email, password) - password is None for domain-based emails
    """
    provider = config.get("mail", {}).get("provider")

    if provider == "shanmail":
        api_key = config.get("mail", {}).get("shanmail_api_key")
        if not api_key:
            raise EmailAPIError("shanmail_api_key not configured")

        client = ShanMailAPI(api_key)
        email, password = client.get_email(email_type="outlook")
        return email, password

    elif provider == "skymail":
        skymail_config = config.get("mail", {}).get("skymail", {})
        base_url = skymail_config.get("base_url")
        admin_email = skymail_config.get("admin_email")
        admin_password = skymail_config.get("admin_password")

        if not all([base_url, admin_email, admin_password]):
            raise EmailAPIError("skymail configuration incomplete")

        client = SkyMailAPI(base_url, admin_email, admin_password)
        email, password = client.get_email()
        return email, password

    else:
        # Fallback to domain-based email generation
        mail_domain = config.get("chatgpt", {}).get("mail_domain")
        if not mail_domain:
            raise EmailAPIError("No mail provider configured and no mail_domain set")

        email = ''.join(random.choices(string.ascii_lowercase, k=12)) + f'@{mail_domain}'
        return email, None
