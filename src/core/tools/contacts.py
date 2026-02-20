"""Contacts tool — save, search, list, and delete contacts with relationships.

Contacts are stored in TWO places for resilience:
1. PRIMARY: JSON file at data/contacts.json (reliable, survives ChromaDB corruption)
2. SECONDARY: DigitalCloneBrain's ChromaDB (for semantic search enrichment)

When a user says "text Mom" or "email John", the system can look up the contact
to resolve names to phone numbers and email addresses.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)

# Primary contacts storage (JSON file)
# Resolve absolute path relative to this file: src/core/tools/contacts.py -> ... -> data/contacts.json
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CONTACTS_FILE = _PROJECT_ROOT / "data" / "contacts.json"


class ContactsTool(BaseTool):
    """Tool for managing contacts with relationships and contact info.

    Uses a JSON file as primary storage (reliable, simple, no corruption).
    ChromaDB is secondary — used for semantic enrichment only.
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
            "description": "Operation to perform. Must be one of: save_contact, search_contacts, list_contacts, delete_contact"
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
            digital_brain: DigitalCloneBrain instance for ChromaDB (secondary)
        """
        self.brain = digital_brain
        self._contacts = self._load_contacts()
        logger.info(f"📇 Contacts storage: {CONTACTS_FILE}")
        logger.info(f"📇 Contacts loaded: {len(self._contacts)}")

    # ── JSON File Operations (Primary Store) ────────────────────────────

    def _load_contacts(self) -> Dict[str, Dict[str, Any]]:
        """Load contacts from JSON file. Returns dict keyed by lowercase name."""
        try:
            CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            if CONTACTS_FILE.exists():
                with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Ensure keys are lowercase for consistent lookup
                    return {k.lower(): v for k, v in data.items()}
        except Exception as e:
            logger.warning(f"Failed to load contacts file: {e}")
        return {}

    def _save_contacts(self):
        """Persist contacts dict to JSON file."""
        try:
            CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._contacts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save contacts file: {e}")

    # ── Tool Interface ──────────────────────────────────────────────────

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

    # ── Operations ──────────────────────────────────────────────────────

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

        # Clean phone number
        clean_phone = None
        if phone:
            clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")

        # Build contact record
        key = name.lower()
        contact = {
            "name": name,
            "relationship": relationship or "unknown",
        }
        if clean_phone:
            contact["phone"] = clean_phone
        if email:
            contact["email"] = email
        if notes:
            contact["notes"] = notes

        # PRIMARY: Save to JSON file
        self._contacts[key] = contact
        self._save_contacts()

        # SECONDARY: Also save to ChromaDB for semantic enrichment (non-critical)
        if self.brain:
            try:
                await self.brain.remember_person(
                    name=name,
                    relationship=relationship or "unknown",
                    preferences={k: v for k, v in contact.items() if k not in ("name", "relationship")}
                )
            except Exception as e:
                logger.warning(f"ChromaDB contact save failed (non-critical, JSON is primary): {e}")

        # Build confirmation
        parts = [f"Saved contact: {name}"]
        if relationship:
            parts.append(f"Relationship: {relationship}")
        if clean_phone:
            parts.append(f"Phone: {clean_phone}")
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

        query_lower = query.lower()
        matches = []

        # Search JSON contacts (exact and fuzzy match)
        for key, contact in self._contacts.items():
            # Match on name, relationship, phone, email, notes
            searchable = " ".join(str(v).lower() for v in contact.values())
            if query_lower in searchable or query_lower in key:
                matches.append(contact)

        if not matches:
            return ToolResult(success=True, output=f"No contacts found matching '{query}'")

        lines = [f"Found {len(matches)} contact(s):"]
        for contact in matches:
            line = f"• {contact.get('name', 'Unknown')}"
            rel = contact.get("relationship", "")
            if rel:
                line += f" ({rel})"
            if contact.get("phone"):
                line += f" | Phone: {contact['phone']}"
            if contact.get("email"):
                line += f" | Email: {contact['email']}"
            lines.append(line)

        return ToolResult(success=True, output="\n".join(lines))

    async def _list_contacts(self) -> ToolResult:
        """List all contacts."""
        if not self._contacts:
            return ToolResult(success=True, output="No contacts saved yet.")

        lines = [f"All contacts ({len(self._contacts)}):"]
        for contact in self._contacts.values():
            line = f"• {contact.get('name', 'Unknown')}"
            rel = contact.get("relationship", "")
            if rel:
                line += f" ({rel})"
            if contact.get("phone"):
                line += f" | Phone: {contact['phone']}"
            if contact.get("email"):
                line += f" | Email: {contact['email']}"
            lines.append(line)

        return ToolResult(success=True, output="\n".join(lines))

    async def _delete_contact(self, name: Optional[str]) -> ToolResult:
        """Delete a contact by name."""
        if not name:
            return ToolResult(success=False, error="Name is required to delete a contact")

        key = name.lower()
        if key not in self._contacts:
            return ToolResult(success=False, error=f"Contact '{name}' not found")

        # Remove from JSON
        del self._contacts[key]
        self._save_contacts()

        # Also remove from ChromaDB (non-critical)
        if self.brain:
            try:
                contact_id = f"contact_{key.replace(' ', '_')}"
                self.brain.contacts.collection.delete(ids=[contact_id])
            except Exception as e:
                logger.debug(f"ChromaDB contact delete failed (non-critical): {e}")

        logger.info(f"🗑️ Contact deleted: {name}")
        return ToolResult(success=True, output=f"Contact '{name}' deleted.")
