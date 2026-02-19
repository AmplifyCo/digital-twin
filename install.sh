#!/bin/bash
# Wrapper for dt-setup installation
# This script is maintained for backward compatibility.
# The installation logic has moved to dt-setup itself.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Digital Twin Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "ℹ️  Note: Installation logic is now built into dt-setup."
echo "   Redirecting you there..."
echo ""

# Execute dt-setup
if [ -f "$SCRIPT_DIR/dt-setup" ]; then
    chmod +x "$SCRIPT_DIR/dt-setup"
    exec "$SCRIPT_DIR/dt-setup" "$@"
else
    echo "❌ Error: dt-setup script not found!"
    exit 1
fi
