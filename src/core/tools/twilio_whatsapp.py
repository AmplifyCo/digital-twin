from typing import Dict, Any
import logging
from .base import BaseTool, ToolResult
from twilio.rest import Client

logger = logging.getLogger(__name__)

class TwilioWhatsAppTool(BaseTool):
    """Tool for sending WhatsApp messages via Twilio."""
    
    name = "send_whatsapp_message"
    description = (
        "Send a WhatsApp message to a specific phone number using Twilio. "
        "Use this tool when the user explicitly asks you to send a WhatsApp message, "
        "or if you need to proactively notify someone via WhatsApp."
    )
    
    parameters = {
        "type": "object",
        "properties": {
            "to_number": {
                "type": "string",
                "description": "The destination phone number (e.g., '+1234567890' or 'whatsapp:+1234567890')"
            },
            "message": {
                "type": "string",
                "description": "The message text to send"
            }
        },
        "required": ["to_number", "message"]
    }
    
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        """Initialize the Twilio WhatsApp tool.
        
        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token
            from_number: The Twilio WhatsApp number (e.g., 'whatsapp:+1234567890')
        """
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        
        # Verify credentials exist
        self.enabled = bool(account_sid and auth_token and from_number)
        
        if self.enabled:
            self.client = Client(account_sid, auth_token)

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool.
        
        Args:
            to_number: Destination phone number
            message: Message text
            
        Returns:
            ToolResult with success status and message SID
        """
        if not self.enabled:
            return ToolResult(
                error="Twilio WhatsApp tool is not configured (missing credentials)",
                success=False
            )
            
        to_number = kwargs.get("to_number")
        message_body = kwargs.get("message")
        
        if not to_number or not message_body:
            return ToolResult(
                error="Missing required parameters: to_number and message",
                success=False
            )
            
        # Ensure 'whatsapp:' prefix
        formatted_to = to_number if to_number.startswith('whatsapp:') else f"whatsapp:{to_number}"
            
        try:
            logger.info(f"Sending Twilio WhatsApp message to {formatted_to}")
            
            # Send message synchronously (Twilio Python SDK is sync)
            message = self.client.messages.create(
                from_=self.from_number,
                body=message_body,
                to=formatted_to
            )
            
            return ToolResult(
                output=f"Message successfully sent to {formatted_to} (SID: {message.sid})",
                success=True,
                data={"message_sid": message.sid, "status": message.status}
            )
            
        except Exception as e:
            error_msg = f"Failed to send Twilio WhatsApp message: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return ToolResult(
                error=error_msg,
                success=False
            )
