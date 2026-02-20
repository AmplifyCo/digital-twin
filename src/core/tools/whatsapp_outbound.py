"""Tool for sending outbound WhatsApp messages using Twilio."""

import os
import logging
from typing import Dict, Any, Optional
from twilio.rest import Client
from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

class WhatsAppOutboundTool(BaseTool):
    """Tool for sending outbound WhatsApp messages via Twilio."""

    name = "send_whatsapp_message"
    description = (
        "Send a direct WhatsApp message to a specific user. "
        "Use this tool when you need to proactively contact someone, report back "
        "after finishing a background task, or send a summary of a completed action."
    )
    
    parameters = {
        "to_number": {
            "type": "string",
            "description": "The recipient's phone number (ex: '+14155551234' or 'whatsapp:+14155551234')"
        },
        "message": {
            "type": "string",
            "description": "The message text to send."
        }
    }

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        """Initialize the WhatsApp Outbound tool.

        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token
            from_number: Twilio WhatsApp sender number (e.g., 'whatsapp:+14155551234')
        """
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number

        self.enabled = bool(account_sid and auth_token and from_number)

        if self.enabled:
            # Twilio REST client for sending outbound API calls
            self.client = Client(account_sid, auth_token)
            logger.info(f"💬 WhatsAppOutboundTool: Enabled for sending from {self.from_number}")
        else:
            logger.info("💬 WhatsAppOutboundTool: Disabled (missing Twilio credentials)")

    async def execute(self, **kwargs) -> ToolResult:
        """Send an outbound WhatsApp message.

        Args:
            to_number: Recipient's phone number
            message: Message text

        Returns:
            ToolResult indicating success or failure
        """
        if not self.enabled:
            return ToolResult(
                error="WhatsApp Outbound tool is not configured (missing credentials)",
                success=False
            )

        to_number = kwargs.get("to_number")
        message = kwargs.get("message")

        if not to_number or not message:
            return ToolResult(
                error="Missing required parameters: to_number and message",
                success=False
            )

        # Ensure 'whatsapp:' prefix for destination
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

        try:
            logger.info(f"📤 Sending outbound WhatsApp message to {to_number}")

            result = self.client.messages.create(
                from_=self.from_number,
                body=message,
                to=to_number
            )

            logger.info(f"📤 WhatsApp message sent (SID: {result.sid})")

            return ToolResult(
                output=f"Successfully sent WhatsApp message to {to_number}.",
                success=True,
                data={"message_sid": result.sid}
            )

        except Exception as e:
            error_msg = f"Failed to send outbound WhatsApp message: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return ToolResult(
                error=error_msg,
                success=False
            )
