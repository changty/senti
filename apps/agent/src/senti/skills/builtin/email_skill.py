"""Email proxy skill (sandboxed, draft requires approval)."""

from __future__ import annotations

from typing import Any

from senti.config import Settings
from senti.skills.base import BaseSkill


class EmailSkill(BaseSkill):
    """Email reading and drafting, executed in a sandbox container.

    Senti only has access to the dedicated EMAIL_FOLDER (default: "Senti").
    It cannot read INBOX or other folders. Drafts are saved but never sent.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "email"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        folder = self._settings.gmail_label
        return [
            {
                "type": "function",
                "function": {
                    "name": "email_list_inbox",
                    "description": (
                        f"List recent emails from the '{folder}' folder "
                        f"(subjects, senders, dates, and Message-IDs)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "count": {
                                "type": "integer",
                                "description": "Number of emails to list",
                                "default": 10,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "email_read",
                    "description": (
                        f"Read the full content of an email from the '{folder}' folder by its Message-ID. "
                        "Use email_list_inbox first to get Message-IDs."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message_id": {
                                "type": "string",
                                "description": "The Message-ID header of the email to read",
                            },
                        },
                        "required": ["message_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "email_create_draft",
                    "description": "Create an email draft (does not send). Requires approval.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {
                                "type": "string",
                                "description": "Recipient email address",
                            },
                            "subject": {
                                "type": "string",
                                "description": "Email subject",
                            },
                            "body": {
                                "type": "string",
                                "description": "Email body (plain text)",
                            },
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        return "Email skill requires the sandbox container."
