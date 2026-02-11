"""Telegram message filters for access control."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram.ext.filters import UpdateFilter

if TYPE_CHECKING:
    from telegram import Update

logger = logging.getLogger(__name__)


class AllowedUserFilter(UpdateFilter):
    """Only allows messages from whitelisted Telegram user IDs."""

    def __init__(self, allowed_ids: list[int]) -> None:
        super().__init__()
        self._allowed = set(allowed_ids)

    def filter(self, update: Update) -> bool:
        user = update.effective_user
        if user is None:
            return False
        allowed = user.id in self._allowed
        if not allowed:
            logger.warning("Blocked message from unauthorized user %d (%s)", user.id, user.username)
        return allowed
