"""Gmail API sandbox runner (OAuth2, no IMAP/SMTP).

Protocol: SENTI_INPUT env var (JSON) → process → JSON on stdout.

Scopes required:
  - gmail.readonly  — read emails from the designated label
  - gmail.compose   — create drafts (Senti never calls messages.send)

Security: code only queries the label specified by GMAIL_LABEL.
"""

import base64
import json
import os
import sys
import urllib.request
import urllib.parse
from email.mime.text import MIMEText

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def _get_access_token() -> str:
    """Exchange refresh token for a short-lived access token."""
    data = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["access_token"]


def _api_get(token: str, path: str, params: dict = None) -> dict:
    """GET request to Gmail API."""
    url = f"{GMAIL_API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _api_post(token: str, path: str, body: dict) -> dict:
    """POST request to Gmail API."""
    url = f"{GMAIL_API}/{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _get_label_id(token: str, label_name: str) -> str | None:
    """Find the Gmail label ID for a given label name."""
    data = _api_get(token, "labels")
    for label in data.get("labels", []):
        if label.get("name", "").lower() == label_name.lower():
            return label["id"]
    return None


def _decode_body(payload: dict) -> str:
    """Extract plain text body from a Gmail message payload."""
    # Direct body
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart — find text/plain part
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        # Nested multipart
        if part.get("parts"):
            result = _decode_body(part)
            if result:
                return result

    return ""


def list_emails(token: str, label_name: str, count: int = 10) -> str:
    label_id = _get_label_id(token, label_name)
    if not label_id:
        return f"Label '{label_name}' not found. Please create it in Gmail."

    # List messages with this label only
    data = _api_get(token, "messages", {"labelIds": label_id, "maxResults": count})
    messages = data.get("messages", [])

    if not messages:
        return f"No emails in '{label_name}' label."

    results = []
    for msg_ref in messages:
        msg = _api_get(token, f"messages/{msg_ref['id']}", {"format": "metadata", "metadataHeaders": "From,Subject,Date,Message-ID"})
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        results.append(
            f"- From: {headers.get('From', '?')}\n"
            f"  Subject: {headers.get('Subject', '(no subject)')}\n"
            f"  Date: {headers.get('Date', '?')}\n"
            f"  ID: {msg_ref['id']}"
        )

    return "\n".join(results)


def read_email(token: str, label_name: str, message_id: str) -> str:
    # Verify the message has the correct label (security check)
    msg = _api_get(token, f"messages/{message_id}", {"format": "full"})
    label_id = _get_label_id(token, label_name)

    if label_id and label_id not in msg.get("labelIds", []):
        return f"Message not in '{label_name}' label. Access denied."

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body = _decode_body(msg.get("payload", {}))

    header = (
        f"From: {headers.get('From', '?')}\n"
        f"To: {headers.get('To', '?')}\n"
        f"Subject: {headers.get('Subject', '?')}\n"
        f"Date: {headers.get('Date', '?')}\n"
        f"---\n"
    )
    return header + body[:4000]


def create_draft(token: str, to: str, subject: str, body: str) -> str:
    msg = MIMEText(body)
    msg["To"] = to
    msg["Subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    result = _api_post(token, "drafts", {"message": {"raw": raw}})

    draft_id = result.get("id", "?")
    return f"Draft created (id: {draft_id}): To={to}, Subject={subject}"


def main() -> None:
    raw = os.environ.get("SENTI_INPUT", "{}")
    request = json.loads(raw)
    function = request.get("function", "")
    args = request.get("arguments", {})

    label = os.environ.get("GMAIL_LABEL", "Senti")

    # Authenticate
    try:
        token = _get_access_token()
    except Exception as exc:
        json.dump({"result": f"Gmail auth failed: {exc}"}, sys.stdout)
        return

    try:
        if function == "email_list_inbox":
            result = list_emails(token, label, args.get("count", 10))
        elif function == "email_read":
            result = read_email(token, label, args["message_id"])
        elif function == "email_create_draft":
            result = create_draft(token, args["to"], args["subject"], args["body"])
        else:
            result = f"Unknown function: {function}"
    except Exception as exc:
        result = f"Error: {exc}"

    json.dump({"result": result}, sys.stdout)


if __name__ == "__main__":
    main()
