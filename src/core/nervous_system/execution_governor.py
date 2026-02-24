"""Execution Governor — the Nervous System's central coordinator.

Architecture: Nervous System component.
Wraps tool execution with:
- Policy Gate (permission checks)
- Dead Letter Queue (poison event handling)
- Durable Outbox (side-effect deduplication)
- State tracking

This is the entry point for the Nervous System layer.
Future: Will also handle the Planner/Executor split.
"""

import logging
from typing import Dict, Any, Optional

from .policy_gate import PolicyGate
from .dead_letter_queue import DeadLetterQueue
from .outbox import DurableOutbox
from .state_machine import AgentStateMachine

logger = logging.getLogger(__name__)


class ExecutionGovernor:
    """Central coordinator for the Nervous System.

    Provides a unified interface for all execution governance:
    - policy_gate: Risk-based permission checks
    - dlq: Dead letter queue for poison events
    - outbox: Side-effect deduplication
    - state_machine: Agent state tracking

    Usage in agent.py or registry.py:
        governor = ExecutionGovernor()
        if not governor.policy_gate.check(tool_name, operation):
            return blocked
        if governor.outbox.is_duplicate(key):
            return skip
        result = await tool.execute(...)
        governor.outbox.mark_sent(key)
    """

    def __init__(self, data_dir: str = "./data", telegram_notifier=None):
        """Initialize all Nervous System components.

        Args:
            data_dir: Directory for persistent storage (DLQ, outbox)
            telegram_notifier: Optional notifier forwarded to DLQ for dead-letter alerts
        """
        self.policy_gate = PolicyGate()
        self.dlq = DeadLetterQueue(data_dir=data_dir, telegram_notifier=telegram_notifier)
        self.outbox = DurableOutbox(data_dir=data_dir)
        self.state_machine = AgentStateMachine()

        logger.info("Nervous System initialized (PolicyGate + DLQ + Outbox + StateMachine)")

    def get_status(self) -> Dict[str, Any]:
        """Get status of all Nervous System components."""
        return {
            "state_machine": self.state_machine.get_status(),
            "dlq_count": self.dlq.count(),
            "policy_gate": {
                "approval_required": self.policy_gate.require_approval
            }
        }
