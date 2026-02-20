"""Twilio Programmable Voice channel.

Handles inbound phone calls via Twilio webhooks.
Uses TwiML to gather speech, passes it to the ConversationManager,
and responds with synthesized speech.
"""

import logging
from typing import Dict, Any, Optional
from xml.etree.ElementTree import Element, SubElement, tostring

logger = logging.getLogger(__name__)

class TwilioVoiceChannel:
    """Twilio Programmable Voice channel adapter."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        phone_number: str,
        conversation_manager,
        twilio_call_tool = None,
        allowed_numbers: Optional[List[str]] = None
    ):
        """Initialize Twilio Voice channel.

        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token
            phone_number: Twilio Phone Number
            conversation_manager: ConversationManager instance
            twilio_call_tool: Optional TwilioCallTool for ElevenLabs TTS
            allowed_numbers: Optional list of allowed numbers
        """
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.phone_number = phone_number
        self.conversation_manager = conversation_manager
        self.twilio_call_tool = twilio_call_tool
        self.allowed_numbers = allowed_numbers or []
        
        self.enabled = bool(account_sid and auth_token and phone_number)
        
        # Default voice settings - User requested Google's voice
        self.voice = "Google.en-US-Journey-F"  # High-quality Google Journey voice
        self.language = "en-US"

        if self.enabled:
            logger.info("✅ Twilio Voice channel initialized")
        else:
            logger.info("Twilio Voice channel disabled (missing credentials)")

    async def _generate_twiml(self, text: Optional[str] = None, prompt_for_input: bool = True) -> str:
        """Generate TwiML XML response, using ElevenLabs if available.
        
        Args:
            text: Text to speak (optional)
            prompt_for_input: Whether to add a Gather verb after speaking
            
        Returns:
            TwiML string
        """
        response = Element("Response")
        
        if text:
            # Try ElevenLabs first if we have the tool
            twiml_injected = False
            if self.twilio_call_tool and self.twilio_call_tool.elevenlabs_enabled:
                audio_filename = await self.twilio_call_tool._generate_elevenlabs_audio(text)
                if audio_filename and self.twilio_call_tool.base_url:
                    audio_url = f"{self.twilio_call_tool.base_url.rstrip('/')}/audio/{audio_filename}"
                    play = SubElement(response, "Play")
                    play.text = audio_url
                    twiml_injected = True
            
            # Fallback to Google Journey voices
            if not twiml_injected:
                say = SubElement(response, "Say", voice=self.voice, language=self.language)
                # Important: Twilio expects valid XML, escape special characters
                say.text = escape(text)
            
        if prompt_for_input:
            # Gather speech input
            # Timeout: time to wait for the user to start speaking
            # SpeechTimeout: time to wait for the user to stop speaking
            gather = SubElement(
                response, 
                "Gather", 
                input="speech",
                action="/twilio/voice/gather",
                timeout="5",
                speechTimeout="auto",
                language="en-US"
            )
            # You can optionally add a beep or short prompt inside Gather
            # say = SubElement(gather, "Say", voice=self.voice)
            # say.text = "I'm listening."
            
        return tostring(response, encoding="unicode")

    def _get_user_number(self, form_data: Dict[str, str]) -> str:
        """Determine the actual user's phone number based on call direction.
        
        Inbound calls trigger the webhook directly with the user's number in 'From'.
        Outbound calls (API initiated) trigger the webhook on answer or gather,
        where 'To' is the user we called and 'From' is our Twilio number.
        """
        direction = form_data.get("Direction", "")
        
        # In outbound calls, the webhook fires after the call connects.
        # The 'To' field contains the recipient's number.
        if "outbound" in direction.lower() or form_data.get("From") == self.phone_number:
            raw_number = form_data.get("To", "unknown_outbound")
        else:
            raw_number = form_data.get("From", "unknown_inbound")
            
        # Strip prefixes for clean matching
        clean_number = raw_number.replace("whatsapp:", "")
        clean_allowed = [num.replace("whatsapp:", "") for num in self.allowed_numbers]
        
        # Explicitly identify Principal to prevent LLM hallucination
        if clean_number in clean_allowed:
            return "Srinath (Principal)"
        
        return clean_number

    async def handle_incoming_call(self, form_data: Dict[str, str]) -> str:
        """Handle initial incoming call webhook (/twilio/voice).
        
        Args:
            form_data: POST form data from Twilio
            
        Returns:
            TwiML string
        """
        if not self.enabled:
            # Fallback if disabled
            response = Element('Response')
            say = SubElement(response, 'Say')
            say.text = "System is currently offline. Please try again later."
            SubElement(response, 'Hangup')
            return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n{tostring(response, encoding='utf-8').decode('utf-8')}"
            
        user_number = self._get_user_number(form_data)
        call_sid = form_data.get("CallSid", "Unknown")
        direction = form_data.get("Direction", "inbound")
        
        logger.info(f"📞 {direction.title()} voice call with {user_number} (CallSid: {call_sid})")
        
        # Return initial greeting and start gathering speech
        return await self._generate_twiml(text="Hi, I am Nova. How can I help you?", prompt_for_input=True)

    async def handle_gather(self, form_data: Dict[str, str]) -> str:
        """Handle speech recognition result webhook (/twilio/voice/gather).
        
        Args:
            form_data: POST form data from Twilio containing SpeechResult
            
        Returns:
            TwiML string
        """
        if not self.enabled:
            return await self._generate_twiml(text="System offline.", prompt_for_input=False)
            
        user_number = self._get_user_number(form_data)
        speech_result = form_data.get("SpeechResult", "").strip()
        confidence = form_data.get("Confidence", "0.0")
        
        logger.info(f"🗣️ Speech from {user_number} (confidence {confidence}): {speech_result}")
        
        if not speech_result:
            # Didn't catch that
            return await self._generate_twiml(text="I'm sorry, I didn't catch that. Could you please repeat?", prompt_for_input=True)
            
        try:
            # Process via ConversationManager
            ai_response = await self.conversation_manager.process_message(
                message=speech_result,
                channel="voice",
                user_id=user_number,
                enable_periodic_updates=False
            )
            
            # Check if this is a goodbye/end call intent from the AI
            # A simple heuristic: if the AI says goodbye or similar, we might want to hang up.
            is_goodbye = any(phrase in ai_response.lower() for phrase in ["goodbye", "have a great day", "bye for now"])
            
            if is_goodbye:
                # The call consists of this outbound API session closing.
                # Kick off an asynchronous background task to summarize what happened 
                # and WhatsApp the Principal.
                logger.info("Call ending identified. Pushing background WhatsApp reporting task.")
                
                # Fetch recent memory for the call context
                history = self.conversation_manager._get_recent_history_for_intent(user_id=user_number, limit=6)
                
                reporting_task = (
                    f"You just finished a phone call with {user_number}. "
                    f"Here is the transcript of the call:\n\n{history}\n\n"
                    "Please execute the 'send_whatsapp_message' tool to send a WhatsApp message to Srinath (Principal) "
                    "summarizing the outcome of this call. Be concise but include any relevant details like times, confirmations, or failures."
                )
                
                # To prevent blocking the Twilio Webhook (which needs to return TwiML), we run the agent task asynchronously.
                import asyncio
                async def run_reporting_task():
                    try:
                        # Sleep briefly to ensure the call officially disconnects first
                        await asyncio.sleep(5)
                        # We use the autonomous agent directly if available
                        agent = getattr(self.conversation_manager, 'agent', None)
                        if agent:
                            await agent.run(task=reporting_task)
                        else:
                            logger.error("Could not find AutonomousAgent to execute background task.")
                    except Exception as loop_e:
                        logger.error(f"Background reporting task failed: {loop_e}", exc_info=True)
                
                asyncio.create_task(run_reporting_task())
            
            # Return the AI's response and prompt for more input (unless it's a goodbye)
            return await self._generate_twiml(text=ai_response, prompt_for_input=not is_goodbye)
            
        except Exception as e:
            logger.error(f"Voice process error: {e}", exc_info=True)
            return await self._generate_twiml(text="I'm sorry, I encountered an error processing your request.", prompt_for_input=True)
