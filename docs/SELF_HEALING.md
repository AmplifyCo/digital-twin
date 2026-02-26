# Self-Healing System

## Overview

The autonomous agent includes a **self-healing system** that automatically detects errors, attempts to fix them, and notifies you via Telegram. This makes the agent truly autonomous and resilient.

## Features

### 1. **Error Detection**
Continuously monitors log files for:
- ✅ Rate limit errors (429)
- ✅ API connection failures
- ✅ Import/dependency errors
- ✅ Git conflicts
- ✅ Configuration errors
- ✅ Code attribute errors
- ✅ Type errors
- ✅ Timeouts

### 2. **Auto-Fix Capabilities**
Automatically attempts to fix:
- **Rate Limits** → Switches to local fallback model (SmolLM2/DeepSeek)
- **Import Errors** → Installs missing Python packages via pip
- **Git Conflicts** → Stashes changes and pulls latest
- **Config Errors** → Restores from .env.example
- **Attribute Errors** → Checks git for code fixes

### 3. **Telegram Integration**
Real-time notifications for:
- 🚨 Critical errors detected
- ⚠️ High-severity issues
- 🔧 Auto-fix attempts (success/failure)
- ✅ Health check results

## Architecture

```
┌─────────────────────────────────────────┐
│         Self-Healing System             │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────┐                   │
│  │ Error Detector  │                   │
│  │ - Scans logs    │                   │
│  │ - Pattern match │                   │
│  │ - Severity      │                   │
│  └────────┬────────┘                   │
│           │                             │
│           ▼                             │
│  ┌─────────────────┐                   │
│  │   Auto-Fixer    │                   │
│  │ - Fix strategies│                   │
│  │ - Execution     │                   │
│  │ - Validation    │                   │
│  └────────┬────────┘                   │
│           │                             │
│           ▼                             │
│  ┌─────────────────┐                   │
│  │    Monitor      │                   │
│  │ - Periodic check│                   │
│  │ - Notifications │                   │
│  │ - Status        │                   │
│  └─────────────────┘                   │
│                                         │
└─────────────────────────────────────────┘
```

## Usage via Telegram

### Check System Health
```
You: health check
Agent: 🩺 Health Check Results
       Errors (last 30min): 2
       Auto-fixable: 1

       By Severity:
       ⚠️ High: 2

       Recent Errors:
       ✅ rate_limit: 429 rate limit exceeded...
       ❌ api_error: Connection timeout...
```

### View Error Report
```
You: show errors
Agent: 📊 Error Report (Last Hour)
       Total Errors: 5
       Auto-fixable: 3

       By Type:
       • rate_limit: 2
       • import_error: 1
       • git_error: 2
```

### Run Auto-Fix
```
You: fix errors
Agent: 🔧 Auto-Fix Complete
       Attempted: 3
       Successful: 2 ✅
       Failed: 1 ❌

       ✅ All fixes applied successfully!
```

## Error Types & Fix Strategies

### Rate Limit Errors (429)
**Detection:** `429`, `rate limit`, `RateLimitError`
**Fix:** Automatic fallback to local model (SmolLM2)
**Requires Restart:** No

### Import Errors
**Detection:** `ImportError`, `ModuleNotFoundError`, `No module named`
**Fix:** `pip install <missing-package>`
**Requires Restart:** Yes

### Git Conflicts
**Detection:** `merge conflict`, `git error`
**Fix:** `git stash && git pull`
**Requires Restart:** Yes (if code changed)

### Config Errors
**Detection:** `ConfigError`, `missing config`, `invalid configuration`
**Fix:** Copy `.env.example` to `.env` or restore defaults
**Requires Restart:** Yes

### Attribute Errors
**Detection:** `AttributeError`, `has no attribute`, `NoneType`
**Fix:** Checks git for available code fixes, suggests pull
**Requires Restart:** If fixed via git pull

## Monitoring Service

The self-healing monitor runs in the background, checking for errors every 5 minutes (configurable).

### Features:
- Periodic log scanning
- Automatic error categorization
- Auto-fix for fixable errors
- Telegram notifications for critical issues
- Health status tracking

### Enable Background Monitoring
Add to your main agent initialization:
```python
from src.core.self_healing.monitor import SelfHealingMonitor

monitor = SelfHealingMonitor(
    telegram_notifier=telegram_chat,
    check_interval=300,  # 5 minutes
    auto_fix_enabled=True
)

# Start monitoring
await monitor.start()
```

## Configuration

### Environment Variables
```bash
# Self-Healing Settings
SELF_HEALING_ENABLED=true
AUTO_FIX_ENABLED=true
HEALTH_CHECK_INTERVAL=300  # seconds
MAX_AUTO_FIX_ATTEMPTS=3
```

### YAML Configuration
```yaml
self_healing:
  enabled: true
  auto_fix: true
  check_interval: 300
  notify_on_fix: true
  notify_on_critical: true

  # Which errors to auto-fix
  auto_fix_types:
    - rate_limit
    - import_error
    - git_error
    - config_error
```

## Error Severity Levels

| Level    | Description | Auto-Fix | Notification |
|----------|-------------|----------|--------------|
| **Critical** | System-breaking errors | Attempted | Immediate |
| **High** | Major issues requiring attention | Yes | Immediate |
| **Medium** | Concerning but not critical | Yes | Batched |
| **Low** | Minor issues, informational | Optional | None |

## Best Practices

1. **Monitor Telegram Notifications**
   - Critical errors are sent immediately
   - Review auto-fix results to ensure correct fixes

2. **Regular Health Checks**
   - Run `health check` daily to review system status
   - Check error trends over time

3. **Restart When Needed**
   - Some fixes require a service restart to take effect
   - Agent will notify when restart is recommended

4. **Review Failed Fixes**
   - Not all errors are auto-fixable
   - Failed fixes may require manual intervention

5. **Keep Git Updated**
   - Many code errors are fixed via git updates
   - Run `pull latest from git` regularly

## Manual Intervention

When auto-fix fails, you may need to:

### SSH into EC2
```bash
ssh ec2-user@your-instance

# Check logs
tail -f /path/to/novabot/data/logs/agent.log

# Manual fix
cd /path/to/novabot
git pull
sudo systemctl restart claude-agent
```

### Common Manual Fixes

#### Permission Errors
```bash
sudo chown -R ec2-user:ec2-user /path/to/novabot
chmod +x scripts/*.sh
```

#### Dependency Issues
```bash
pip install -r requirements.txt
pip install --upgrade anthropic
```

#### Service Issues
```bash
sudo systemctl status claude-agent
sudo systemctl restart claude-agent
sudo journalctl -u claude-agent -f
```

## Logs & Debugging

### View Self-Healing Logs
```python
# Check error detector logs
from src.core.self_healing import ErrorDetector

detector = ErrorDetector()
errors = detector.scan_recent_logs(minutes=60)

for error in errors:
    print(f"{error.error_type}: {error.message}")
```

### View Fix History
```python
# Check auto-fixer logs
from src.core.self_healing import AutoFixer

fixer = AutoFixer()
summary = fixer.get_fix_summary()

print(f"Total fixes: {summary['total_fixes_attempted']}")
print(f"Success rate: {summary['success_rate']}")
```

## Limitations

### What Can Be Auto-Fixed
✅ Rate limits (fallback)
✅ Missing dependencies
✅ Simple git conflicts
✅ Basic config errors
✅ Some attribute errors (via git)

### What Cannot Be Auto-Fixed
❌ Complex code bugs
❌ Logic errors
❌ Database corruption
❌ Network infrastructure issues
❌ Hardware failures
❌ Security breaches

## Future Enhancements

Planned improvements:
- 🔄 Self-learning error patterns
- 🧠 AI-powered code fixes
- 🔍 Predictive error detection
- 📊 Error analytics dashboard
- 🔗 Integration with monitoring services (Datadog, Sentry)
- 🤖 Auto-rollback on failed fixes

## Troubleshooting

### Monitor Not Running
```bash
# Check if monitor is initialized
# Look for: "🩺 Self-healing monitor started" in logs
tail -f data/logs/agent.log | grep "Self-healing"
```

### Auto-Fix Not Working
```bash
# Verify auto_fix is enabled
grep "AUTO_FIX_ENABLED" .env

# Check fix history
# Send via Telegram: "show error report"
```

### False Positives
```bash
# Adjust error detection patterns in:
# src/core/self_healing/error_detector.py

# Modify ERROR_PATTERNS dict
```

## Support

For issues or questions:
1. Check logs: `data/logs/agent.log`
2. Run health check via Telegram
3. Review fix history
4. Check GitHub issues: [repository link]

## Summary

The self-healing system makes the autonomous agent truly autonomous by:
- ✅ Detecting errors automatically
- ✅ Fixing common issues without human intervention
- ✅ Notifying you of critical problems
- ✅ Maintaining system health 24/7

This enables the agent to run continuously on EC2 with minimal manual intervention, only alerting you when human decision-making is required.
