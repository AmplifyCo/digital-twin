"""WhatsApp channel adapter - thin wrapper around ConversationManager.

This demonstrates how easy it is to add new channels.
Same ConversationManager = same intelligence across all channels!
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class WhatsAppChannel:
    """WhatsApp channel adapter - thin transport layer only.

    Uses the SAME ConversationManager as Telegram, Discord, etc.
    = Same intelligence, same Brain, same context continuity!
    """

    def __init__(
        self,
        api_key: str,
        phone_number: str,
        conversation_manager
    ):
        """Initialize WhatsApp channel.

        Args:
            api_key: WhatsApp Business API key
            phone_number: WhatsApp business phone number
            conversation_manager: ConversationManager instance (core intelligence)
        """
        self.api_key = api_key
        self.phone_number = phone_number
        self.conversation_manager = conversation_manager
        self.enabled = bool(api_key and phone_number)

        if self.enabled:
            logger.info("WhatsApp channel initialized (thin wrapper)")
        else:
            logger.info("WhatsApp channel disabled")

    async def handle_incoming_message(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming message from WhatsApp webhook.

        This is just routing - intelligence is in ConversationManager.

        Args:
            webhook_data: WhatsApp webhook data

        Returns:
            Response dict
        """
        try:
            # Extract message (WhatsApp format)
            message_data = webhook_data.get("entry", [{}])[0].get("changes", [{}])[0]
            message = message_data.get("value", {}).get("messages", [{}])[0]

            sender = message.get("from")
            text = message.get("text", {}).get("body", "")

            if not text:
                return {"ok": True}

            logger.info(f"WhatsApp message from {sender}: {text}")

            # CORE INTELLIGENCE HERE (same as Telegram!)
            response = await self.conversation_manager.process_message(
                message=text,
                channel="whatsapp",
                user_id=sender
            )

            # Send response via WhatsApp
            await self.send_message(sender, response)

            return {"ok": True}

        except Exception as e:
            logger.error(f"WhatsApp webhook error: {e}")
            return {"ok": False, "error": str(e)}

    async def send_message(self, recipient: str, text: str):
        """Send message via WhatsApp Business API.

        This is just transport - no intelligence here.

        Args:
            recipient: Recipient phone number
            text: Message to send
        """
        if not self.enabled:
            return

        try:
            # WhatsApp Business API call
            # (Implementation depends on which WhatsApp API you use)
            logger.info(f"Sending WhatsApp message to {recipient}")

            # Example with Twilio WhatsApp:
            # await twilio_client.messages.create(
            #     from_=f'whatsapp:{self.phone_number}',
            #     to=f'whatsapp:{recipient}',
            #     body=text
            # )

        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")
