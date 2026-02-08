"""Google Drive sandbox runner.

Protocol: SENTI_INPUT env var (JSON) → process → JSON on stdout.
Uses OAuth2 with refresh token for authentication.
"""

import json
import os
import sys
import urllib.request
import urllib.parse


SCOPES = "https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"


def get_access_token() -> str:
    """Exchange refresh token for access token."""
    data = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["access_token"]


def list_files(token: str, query: str = "", max_results: int = 10) -> str:
    params = {"pageSize": max_results, "fields": "files(id,name,mimeType,modifiedTime)"}
    if query:
        params["q"] = query

    url = f"{DRIVE_API}/files?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    files = data.get("files", [])
    if not files:
        return "No files found."

    lines = []
    for f in files:
        lines.append(f"- {f['name']} ({f['mimeType']}) — modified {f.get('modifiedTime', '?')}")
    return "\n".join(lines)


def create_file(token: str, name: str, content: str, mime_type: str = "text/plain") -> str:
    metadata = json.dumps({"name": name, "mimeType": mime_type}).encode("utf-8")

    # Simple upload
    url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=media"
    req = urllib.request.Request(
        url,
        data=content.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": mime_type,
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())

    return f"Created file: {result.get('name', name)} (id: {result.get('id', '?')})"


def main() -> None:
    raw = os.environ.get("SENTI_INPUT", "{}")
    request = json.loads(raw)
    function = request.get("function", "")
    args = request.get("arguments", {})

    try:
        token = get_access_token()
    except Exception as exc:
        json.dump({"result": f"Auth failed: {exc}"}, sys.stdout)
        return

    try:
        if function == "gdrive_list_files":
            result = list_files(token, args.get("query", ""), args.get("max_results", 10))
        elif function == "gdrive_create_file":
            result = create_file(
                token, args["name"], args["content"], args.get("mime_type", "text/plain")
            )
        else:
            result = f"Unknown function: {function}"
    except Exception as exc:
        result = f"Error: {exc}"

    json.dump({"result": result}, sys.stdout)


if __name__ == "__main__":
    main()
