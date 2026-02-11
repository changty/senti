"""Helper script to obtain a Gmail OAuth2 refresh token with limited scopes.

Usage:
    python scripts/gmail_oauth.py

Prerequisites:
    1. Go to https://console.cloud.google.com/apis/credentials
    2. Create an OAuth 2.0 Client ID (type: Desktop app)
    3. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env

This script will:
    1. Open your browser for Google sign-in
    2. Ask you to authorize gmail.readonly + gmail.compose scopes
    3. Print the refresh token to add to your .env as GMAIL_REFRESH_TOKEN
"""

import http.server
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser

# Only these two scopes — no full access
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

REDIRECT_PORT = 8089
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main():
    # Load from .env or environment
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        # Try loading from .env file
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GOOGLE_CLIENT_ID="):
                        client_id = line.split("=", 1)[1].strip()
                    elif line.startswith("GOOGLE_CLIENT_SECRET="):
                        client_secret = line.split("=", 1)[1].strip()

    if not client_id or not client_secret:
        print("Error: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set.")
        print("Set them in .env or as environment variables.")
        sys.exit(1)

    # Build authorization URL
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    })

    print("Opening browser for Google sign-in...")
    print(f"If it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for the redirect with the authorization code
    auth_code = None

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            auth_code = params.get("code", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization complete!</h1><p>You can close this tab.</p>")

        def log_message(self, format, *args):
            pass  # Suppress logs

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), Handler)
    server.handle_request()

    if not auth_code:
        print("Error: No authorization code received.")
        sys.exit(1)

    # Exchange code for tokens
    data = urllib.parse.urlencode({
        "code": auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        tokens = json.loads(resp.read())

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("Error: No refresh token returned. Try again with prompt=consent.")
        print(f"Response: {tokens}")
        sys.exit(1)

    print("\nSuccess! Add this to your .env:\n")
    print(f"GMAIL_REFRESH_TOKEN={refresh_token}")
    print(f"\nScopes granted: {', '.join(SCOPES)}")
    print("  - gmail.readonly: can read emails (Senti only reads the 'Senti' label)")
    print("  - gmail.compose: can create drafts (Senti never sends)")


if __name__ == "__main__":
    main()
