"""LinkedIn OAuth 2.0 Setup — generates the authorization URL for Nova.

Nova's dashboard handles the callback and saves the token automatically.
You only need to open the URL in a browser once every ~60 days.

Usage (on EC2):
    /home/ec2-user/digital-twin/venv/bin/python scripts/linkedin_auth.py

Flow:
    1. This script prints an authorization URL
    2. Open it in your browser → authorize Nova on LinkedIn
    3. LinkedIn redirects to https://webhook.amplify-pixels.com/linkedin/callback
    4. Nova's dashboard exchanges the code, saves token+URN to .env automatically
    5. Restart Nova: sudo systemctl restart digital-twin

Prerequisites:
    - LINKEDIN_CLIENT_ID in .env
    - LINKEDIN_CLIENT_SECRET in .env
    - https://webhook.amplify-pixels.com/linkedin/callback added as a
      redirect URI in your LinkedIn Developer App:
      https://www.linkedin.com/developers/apps → Auth tab → Redirect URLs
"""

import os
import urllib.parse
from pathlib import Path

# ── Load .env so env vars are available ───────────────────────────────────────
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

# ── Read credentials ──────────────────────────────────────────────────────────
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
if not CLIENT_ID:
    CLIENT_ID = input("LinkedIn Client ID: ").strip()

BASE_URL = os.getenv("NOVA_BASE_URL", "https://webhook.amplify-pixels.com").rstrip("/")
REDIRECT_URI = f"{BASE_URL}/linkedin/callback"
SCOPE = "openid profile w_member_social"

# ── Build authorization URL ───────────────────────────────────────────────────
params = urllib.parse.urlencode({
    "response_type": "code",
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "state": "nova_linkedin_setup",
    "scope": SCOPE,
})
auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{params}"

print()
print("=" * 65)
print("LinkedIn OAuth Setup")
print("=" * 65)
print()
print("1. Make sure this redirect URI is registered in your LinkedIn")
print("   Developer App (Auth tab → OAuth 2.0 settings → Redirect URLs):")
print(f"\n   {REDIRECT_URI}\n")
print("2. Open this URL in your browser to authorize Nova:")
print(f"\n   {auth_url}\n")
print("3. After you approve, LinkedIn redirects to Nova's dashboard.")
print("   Nova will automatically save the token to .env.")
print()
print("4. Then restart Nova:")
print("   sudo systemctl restart digital-twin")
print()
print("Note: use the venv python on EC2:")
print("   /home/ec2-user/digital-twin/venv/bin/python scripts/linkedin_auth.py")
print()
print("Token expires in ~60 days. Re-run this script to refresh.")
print("=" * 65)
