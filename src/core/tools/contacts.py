"""Contacts tool — save, search, list, and delete contacts with relationships.

Contacts are stored in DigitalCloneBrain's collective consciousness so they're
accessible across all channels (Telegram, WhatsApp, Email, etc.).

When a user says "text Mom" or "email John", the system can look up the contact
to resolve names to phone numbers and email addresses.
"""

import json
import logging
from typing import Optional, Dict, Any
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class ContactsTool(BaseTool):
    """Tool for managing contacts with relationships and contact info.

    Stores contacts in DigitalCloneBrain's vector database so they
    appear in context when the user mentions someone by name.
    """

    name = "contacts"
    description = (
        "Save, search, list, and delete contacts. "
        "Each contact has a name, relationship, phone number, and email. "
        "Use this when the user wants to save someone's contact info, "
        "or when you need to look up a phone number or email to send a message."
    )
    parameters = {
        "operation": {
            "type": "string",
            "description": "Operation: 'save_contact', 'search_contacts', 'list_contacts', 'delete_contact'",
            "enum": ["save_contact", "search_contacts", "list_contacts", "delete_contact"]
        },
        "name": {
            "type": "string",
            "description": "Contact's full name (for save/search/delete)"
        },
        "relationship": {
            "type": "string",
            "description": "Relationship: 'wife', 'friend', 'relative', 'coworker', 'professional', 'acquaintance', 'family', 'other' (for save_contact)"
        },
        "phone": {
            "type": "string",
            "description": "Phone number with country code, no + or dashes (e.g. '19375551234') (for save_contact)"
        },
        "email": {
            "type": "string",
            "description": "Email address (for save_contact)"
        },
        "notes": {
            "type": "string",
            "description": "Any notes about this person (for save_contact)"
        }
    }

    def __init__(self, digital_brain=None):
        """Initialize contacts tool.

        Args:
            digital_brain: DigitalCloneBrain instance for storage
        """
        self.brain = digital_brain

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Override to make only 'operation' required."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": ["operation"]
            }
        }

    async def execute(
        self,
        operation: str,
        name: Optional[str] = None,
        relationship: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        notes: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Execute contacts operation."""
        if not self.brain:
            return ToolResult(success=False, error="Contacts tool not configured (no brain)")

        try:
            if operation == "save_contact":
                return await self._save_contact(name, relationship, phone, email, notes)
            elif operation == "search_contacts":
                return await self._search_contacts(name)
            elif operation == "list_contacts":
                return await self._list_contacts()
            elif operation == "delete_contact":
                return await self._delete_contact(name)
            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}")
        except Exception as e:
            logger.error(f"Contacts operation error: {e}", exc_info=True)
            return ToolResult(success=False, error=f"Contacts operation failed: {str(e)}")

    async def _save_contact(
        self,
        name: Optional[str],
        relationship: Optional[str],
        phone: Optional[str],
        email: Optional[str],
        notes: Optional[str]
    ) -> ToolResult:
        """Save or update a contact."""
        if not name:
            return ToolResult(success=False, error="Name is required to save a contact")

        # Build preferences dict for DigitalCloneBrain.remember_person()
        preferences = {}
        if phone:
            clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
            preferences["phone"] = clean_phone
        if email:
            preferences["email"] = email
        if notes:
            preferences["notes"] = notes

        await self.brain.remember_person(
            name=name,
            relationship=relationship or "unknown",
            preferences=preferences
        )

        # Build confirmation
        parts = [f"Saved contact: {name}"]
        if relationship:
            parts.append(f"Relationship: {relationship}")
        if phone:
            parts.append(f"Phone: {preferences.get('phone', phone)}")
        if email:
            parts.append(f"Email: {email}")
        if notes:
            parts.append(f"Notes: {notes}")

        result = "\n".join(parts)
        logger.info(f"📇 Contact saved: {name} ({relationship or 'unknown'})")
        return ToolResult(success=True, output=result)

    async def _search_contacts(self, query: Optional[str]) -> ToolResult:
        """Search contacts by name, relationship, or any keyword."""
        if not query:
            return ToolResult(success=False, error="Search query is required (name or keyword)")

        results = await self.brain.contacts.search(query, n_results=5)

        if not results:
            return ToolResult(success=True, output=f"No contacts found matching '{query}'")

        lines = [f"Found {len(results)} contact(s):"]
        for r in results:
            meta = r.get("metadata", {})
            name = meta.get("name", "Unknown")
            rel = meta.get("relationship", "")
            phone = meta.get("phone", "")
            email_addr = meta.get("email", "")

            line = f"• {name}"
            if rel:
                line += f" ({rel})"
            if phone:
                line += f" | Phone: {phone}"
            if email_addr:
                line += f" | Email: {email_addr}"
            lines.append(line)

        return ToolResult(success=True, output="\n".join(lines))

    async def _list_contacts(self) -> ToolResult:
        """List all contacts."""
        # Search with a broad query to get all contacts
        results = await self.brain.contacts.search("contact person", n_results=50)

        if not results:
            return ToolResult(success=True, output="No contacts saved yet.")

        lines = [f"All contacts ({len(results)}):"]
        for r in results:
            meta = r.get("metadata", {})
            name = meta.get("name", "Unknown")
            rel = meta.get("relationship", "")
            phone = meta.get("phone", "")
            email_addr = meta.get("email", "")

            line = f"• {name}"
            if rel:
                line += f" ({rel})"
            if phone:
                line += f" | Phone: {phone}"
            if email_addr:
                line += f" | Email: {email_addr}"
            lines.append(line)

        return ToolResult(success=True, output="\n".join(lines))

    async def _delete_contact(self, name: Optional[str]) -> ToolResult:
        """Delete a contact by name."""
        if not name:
            return ToolResult(success=False, error="Name is required to delete a contact")

        contact_id = f"contact_{name.lower().replace(' ', '_')}"

        try:
            self.brain.contacts.collection.delete(ids=[contact_id])
            logger.info(f"🗑️ Contact deleted: {name}")
            return ToolResult(success=True, output=f"Contact '{name}' deleted.")
        except Exception as e:
            logger.error(f"Failed to delete contact: {e}")
            return ToolResult(success=False, error=f"Could not delete '{name}': {str(e)}")
