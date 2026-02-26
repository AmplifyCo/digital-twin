"""LinkedIn OAuth 2.0 Setup — generates the auth URL to open in your browser.

Usage (on EC2):
    /home/ec2-user/novabot/venv/bin/python scripts/linkedin_auth.py

What it does:
    1. Prints the LinkedIn authorization URL
    2. You open it in your Mac browser and approve
    3. LinkedIn redirects to the webhook — Nova's dashboard handles the rest:
       - Exchanges the code for a token
       - Fetches your person URN automatically via /v2/userinfo (openid)
       - Saves LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN to .env
       - Shows a success page in your browser
    4. Restart Nova:  sudo systemctl restart novabot

Requirements:
    - LINKEDIN_CLIENT_ID in .env
    - https://webhook.amplify-pixels.com/linkedin/callback registered as a
      redirect URI in your LinkedIn Developer App
      (Auth tab → OAuth 2.0 settings → Redirect URLs)
    - "Sign In with LinkedIn using OpenID Connect" product added to your app
      (needed for /v2/userinfo to fetch person URN automatically)

Run every ~60 days to refresh the token.
"""

import os
import urllib.parse
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

# ── Credentials ───────────────────────────────────────────────────────────────
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
if not CLIENT_ID:
    print("ERROR: LINKEDIN_CLIENT_ID not set in .env")
    raise SystemExit(1)

BASE_URL = os.getenv("NOVA_BASE_URL", "https://webhook.amplify-pixels.com").rstrip("/")
REDIRECT_URI = f"{BASE_URL}/linkedin/callback"

# openid + profile lets dashboard auto-fetch your person URN via /v2/userinfo.
# Requires "Sign In with LinkedIn using OpenID Connect" product on your app.
SCOPE = "openid profile w_member_social"

# ── Build auth URL ─────────────────────────────────────────────────────────────
params = urllib.parse.urlencode({
    "response_type": "code",
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "state": "nova_linkedin_setup",
    "scope": SCOPE,
})
auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{params}"

# ── Print instructions ─────────────────────────────────────────────────────────
print()
print("=" * 65)
print("LinkedIn OAuth Setup")
print("=" * 65)
print()
print("Open this URL in your browser:")
print()
print(f"  {auth_url}")
print()
print("After approving, your browser redirects to:")
print(f"  {REDIRECT_URI}?code=...")
print()
print("Nova's dashboard handles the rest automatically:")
print("  - Exchanges code for access token")
print("  - Fetches your person URN via /v2/userinfo")
print("  - Saves LINKEDIN_ACCESS_TOKEN + LINKEDIN_PERSON_URN to .env")
print("  - Shows a success page in your browser")
print()
print("Then restart Nova:")
print("  sudo systemctl restart novabot")
print()
print("=" * 65)
print(f"Redirect URI: {REDIRECT_URI}")
print(f"Scope: {SCOPE}")
print("=" * 65)
print()
