"""Communication channels package.

All channels are thin wrappers around ConversationManager.
They only handle transport - intelligence is channel-agnostic.
"""

from .telegram_channel import TelegramChannel
from .whatsapp_channel import WhatsAppChannel

__all__ = ["TelegramChannel", "WhatsAppChannel"]
