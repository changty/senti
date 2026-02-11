"""Human-in-the-loop approval flow via Telegram inline keyboards."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from senti.exceptions import ApprovalDeniedError, ApprovalTimeoutError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120  # seconds
MAX_CODE_PREVIEW = 1500


@dataclass
class ApprovalRequest:
    """Pending approval request with an asyncio.Future for the result."""

    request_id: str
    tool_name: str
    arguments: dict[str, Any]
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


class HITLManager:
    """Manages approval requests via Telegram inline keyboards."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._pending: dict[str, ApprovalRequest] = {}

    async def request_approval(
        self,
        update: Update,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        is_user_skill: bool = False,
    ) -> str:
        """Send an approval request and wait for user response.

        Returns "approve", "deny", or "trust".
        """
        request_id = str(uuid.uuid4())[:8]
        req = ApprovalRequest(
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        self._pending[request_id] = req

        # Build message text and keyboard
        text, parse_mode = self._format_message(tool_name, arguments, is_user_skill)
        keyboard = self._build_keyboard(request_id, is_user_skill)

        try:
            await update.effective_chat.send_message(
                text=text, reply_markup=keyboard, parse_mode=parse_mode,
            )
        except Exception:
            # Fallback to plain text if HTML parsing fails
            if parse_mode:
                text_plain, _ = self._format_message(
                    tool_name, arguments, is_user_skill, plain=True,
                )
                await update.effective_chat.send_message(
                    text=text_plain, reply_markup=keyboard,
                )

        try:
            result = await asyncio.wait_for(req.future, timeout=self._timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise ApprovalTimeoutError(f"Approval for {tool_name} timed out after {self._timeout}s")
        finally:
            self._pending.pop(request_id, None)

    def _format_message(
        self, tool_name: str, arguments: dict[str, Any],
        is_user_skill: bool, *, plain: bool = False,
    ) -> tuple[str, str | None]:
        """Build the approval message text. Returns (text, parse_mode)."""
        # Code preview for run_python and create_skill
        if tool_name == "run_python" and not plain:
            code = arguments.get("code", "")
            if len(code) > MAX_CODE_PREVIEW:
                code = code[:MAX_CODE_PREVIEW] + "\n..."
            text = (
                f"<b>Approval required: {tool_name}</b>\n\n"
                f"<pre>{_html_escape(code)}</pre>\n\n"
                f"Execute this code?"
            )
            return text, "HTML"

        if tool_name == "create_skill" and not plain:
            name = arguments.get("name", "?")
            code = arguments.get("code", "")
            if len(code) > MAX_CODE_PREVIEW:
                code = code[:MAX_CODE_PREVIEW] + "\n..."
            text = (
                f"<b>Approval required: create skill '{_html_escape(name)}'</b>\n\n"
                f"<pre>{_html_escape(code)}</pre>\n\n"
                f"Create this skill?"
            )
            return text, "HTML"

        # Default format
        args_preview = json.dumps(arguments, indent=2, ensure_ascii=False)
        if len(args_preview) > 500:
            args_preview = args_preview[:500] + "\n..."

        text = (
            f"Approval required for: {tool_name}\n\n"
            f"Arguments:\n{args_preview}\n\n"
            f"This action requires your approval."
        )
        return text, None

    def _build_keyboard(
        self, request_id: str, is_user_skill: bool,
    ) -> InlineKeyboardMarkup:
        """Build inline keyboard buttons."""
        buttons = [
            InlineKeyboardButton("Approve", callback_data=f"approve:{request_id}"),
            InlineKeyboardButton("Deny", callback_data=f"deny:{request_id}"),
        ]
        if is_user_skill:
            buttons.append(
                InlineKeyboardButton("Approve & Trust", callback_data=f"trust:{request_id}"),
            )
        return InlineKeyboardMarkup([buttons])

    async def handle_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        await query.answer()

        data = query.data or ""
        if ":" not in data:
            return

        action, request_id = data.split(":", 1)
        req = self._pending.get(request_id)

        if req is None:
            await query.edit_message_text("This approval request has expired.")
            return

        if action == "approve":
            req.future.set_result("approve")
            await query.edit_message_text(f"Approved: {req.tool_name}")
            logger.info("User approved tool: %s", req.tool_name)
        elif action == "deny":
            req.future.set_result("deny")
            await query.edit_message_text(f"Denied: {req.tool_name}")
            logger.info("User denied tool: %s", req.tool_name)
        elif action == "trust":
            req.future.set_result("trust")
            await query.edit_message_text(f"Trusted: {req.tool_name}")
            logger.info("User trusted tool: %s", req.tool_name)

    def get_callback_handler(self) -> CallbackQueryHandler:
        """Return a handler to register with the Telegram app."""
        return CallbackQueryHandler(self.handle_callback)


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
