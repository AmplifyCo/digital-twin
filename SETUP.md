# Digital Twin Setup Guide

The simplest AI agent setup you'll ever do.

## 🚀 Quick Start (2 Commands!)

```bash
git clone https://github.com/AmplifyCo/digital-twin.git
cd digital-twin && ./dt-setup
```

**That's it!** The script handles everything:
- ✅ Auto-installs locally (no sudo needed)
- ✅ Installs dependencies
- ✅ Configures system services & auto-start
- ✅ Sets up email/calendar tools
- ✅ Ready to run!

## Prerequisites

- Python 3.8+
- Anthropic API key (get from https://console.anthropic.com/settings/keys)
- Gmail account (optional, for email/calendar features)

## What Happens When You Run `./dt-setup`?

```bash
$ ./dt-setup

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Welcome to Digital Twin Setup!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

First-time setup detected.

First-time setup detected.

   Target: ~/.local/bin (Local User)
   Installing to ~/.local/bin...

✅ dt-setup installed successfully!

📦 Dependencies not found. Installing required packages...
Running: pip install -r requirements.txt

[... pip install output ...]

✅ Dependencies installed successfully!

============================================================
  🤖 Digital Twin Configuration Wizard
============================================================

This wizard will help you set up:
  • Core API credentials (Anthropic)
  • Communication tools (Telegram, Email, Calendar)

Configure core API keys? (y/n) [y]: y

🔑 CORE CONFIGURATION

Get your API key from: https://console.anthropic.com/settings/keys

Enter Anthropic API key: sk-ant-xxxxx

✅ Core configuration complete!

📧 EMAIL CONFIGURATION

Enter your email address: john@gmail.com
✅ Detected provider: gmail.com

Auto-configured:
   IMAP Server: imap.gmail.com:993
   SMTP Server: smtp.gmail.com:587

Enter app password: [hidden]

✅ Email configuration complete!

🎉 Setup Complete!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 Starting Digital Twin bot...

[Bot starts running...]
```

## Detailed Setup

### Update Configuration Later

```bash
dt-setup              # Full wizard
dt-setup email        # Update email only
dt-setup telegram     # Update Telegram only
dt-setup core         # Update API keys only
dt-setup calendar     # Update calendar only
```

Works from **any directory** (like `git`, `python`, `npm`)!

### Start the Bot

```bash
dt-setup start
```

Check logs for successful tool registration:
```
📧 Email tool registered
📅 Calendar tool registered
```

---

**All commands:**

**Bot Management:**
- `dt-setup start` - Start the bot
- `dt-setup stop` - Stop the bot
- `dt-setup restart` - Restart the bot
- `dt-setup status` - Check if bot is running

**Configuration:**
- `dt-setup` - Full setup wizard
- `dt-setup core` - Update API key
- `dt-setup email` - Update email settings
- `dt-setup telegram` - Update Telegram settings
- `dt-setup calendar` - Update calendar settings
- `dt-setup tunnel` - Update Cloudflare Tunnel settings

**Tunnel Management:**
- `dt-setup tunnel-start` - Start Cloudflare Tunnel
- `dt-setup tunnel-stop` - Stop Cloudflare Tunnel
- `dt-setup tunnel-status` - Check tunnel status

## Manual Setup

If you prefer to manually edit `.env`:

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your credentials:
   ```bash
   nano .env
   ```

3. Add email/calendar sections (see `.env.example` for templates)

## Configuration Options

### Simple Commands (After Installation)

```bash
dt-setup                   # Full wizard (all tools)
dt-setup digital-twin      # Full wizard (alias)
dt-setup core              # API keys only
dt-setup telegram          # Telegram only
dt-setup email             # Email only
dt-setup calendar          # Calendar only
dt-setup tunnel            # Cloudflare Tunnel only
dt-setup help              # Show help
```

Works from **any directory**, just like `git`, `python`, `npm`.

### Advanced: Python Direct Usage

If you haven't installed with `make install`, you can still use:

```bash
python configure.py --email-only              # Email only
python configure.py --calendar-only           # Calendar only
python configure.py --core-only               # API keys only
python configure.py --telegram-only           # Telegram only
python configure.py --tunnel-only             # Cloudflare Tunnel only
python configure.py --env-file /path/to/.env  # Custom .env location
```

## Supported Providers

### Auto-Configured Providers

The wizard automatically configures these providers:

| Provider | Email Domain | IMAP/SMTP | CalDAV |
|----------|-------------|-----------|--------|
| **Gmail** | @gmail.com | ✅ | ✅ |
| **Outlook** | @outlook.com, @hotmail.com, @live.com | ✅ | ✅ |
| **Yahoo** | @yahoo.com | ✅ | ❌ |
| **iCloud** | @icloud.com | ✅ | ✅ |

### App Passwords Required

Most providers require app-specific passwords (not your regular password):

#### Gmail
1. Enable 2FA: https://myaccount.google.com/security
2. Create App Password: https://myaccount.google.com/apppasswords
3. Use 16-character app password

#### Outlook/Microsoft
1. Enable 2FA: https://account.microsoft.com/security
2. Create App Password in security settings
3. Use app password

#### iCloud
1. Go to: https://appleid.apple.com/account/manage
2. Generate app-specific password
3. Use app-specific password

## Testing Your Setup

Once configured, test the tools:

### Email Commands
- "Check my emails"
- "Read my unread messages"
- "Send email to john@example.com with subject 'Meeting' and body 'See you at 2pm'"
- "Reply to email [email_id] with 'Thanks!'"

### Calendar Commands
- "What's on my calendar today?"
- "Show me this week's appointments"
- "Create appointment for tomorrow at 2pm titled 'Team meeting'"
- "List my events for the next 7 days"

## Cloudflare Tunnel Setup (Optional)

Cloudflare Tunnel securely exposes your Digital Twin bot to the internet without port forwarding or firewall configuration.

### Quick Setup

1. **Get your tunnel token:**
   - Go to: https://one.dash.cloudflare.com/
   - Navigate to: **Zero Trust > Networks > Tunnels**
   - Create a new tunnel or select existing
   - Copy the tunnel token

2. **Configure the tunnel:**
   ```bash
   dt-setup tunnel
   ```
   - Paste your tunnel token when prompted
   - Specify local service URL (e.g., http://localhost:8000)

3. **Start the tunnel:**
   ```bash
   dt-setup tunnel-start
   ```

4. **Check tunnel status:**
   ```bash
   dt-setup tunnel-status
   ```

5. **Stop the tunnel:**
   ```bash
   dt-setup tunnel-stop
   ```

### Use Cases

- **Telegram Webhooks:** Faster response than polling
- **Remote Access:** Access your bot from anywhere
- **Web Dashboard:** Share your bot's web interface
- **API Endpoints:** Expose REST API to external services

### Tunnel Management

The tunnel runs as a background process and logs to `logs/tunnel.log`.

**Common commands:**
```bash
dt-setup tunnel-start     # Start tunnel in background
dt-setup tunnel-stop      # Stop tunnel
dt-setup tunnel-status    # Check if tunnel is running
dt-setup tunnel           # Update tunnel configuration
```

## Auto-Updates (Optional)

Keep your Digital Twin bot automatically updated with the latest features and bug fixes.

### Enable Auto-Updates

Choose your preferred update frequency:

**Daily (Nightly) - Recommended:**
```bash
dt-setup auto-update enable daily
```
Updates automatically at 3 AM every day.

**Weekly:**
```bash
dt-setup auto-update enable weekly
```
Updates automatically every Sunday at 3 AM.

**Hourly:**
```bash
dt-setup auto-update enable hourly
```
Updates every hour (use with caution - only for active development).

### What Happens During Auto-Update?

1. ✅ Checks for new commits on GitHub
2. ✅ Pulls updates if available
3. ✅ Updates dependencies if `requirements.txt` changed
4. ✅ Automatically restarts the bot
5. ✅ Logs everything to `logs/auto-update.log`

**Safety features:**
- Only updates if there are changes
- Stashes local uncommitted changes before updating
- Preserves your `.env` configuration (never overwritten)

### Manual Update Check

Run an update check immediately:

```bash
dt-setup auto-update now
```

### Check Auto-Update Status

See if auto-updates are enabled and when they'll run next:

```bash
dt-setup auto-update status
```

### Disable Auto-Updates

Turn off automatic updates:

```bash
dt-setup auto-update disable
```

### View Update Logs

Check what updates have been applied:

```bash
tail -f logs/auto-update.log
```

## Troubleshooting

### Tools Not Appearing

**Check logs:**
```bash
tail -f logs/agent.log
```

**Look for:**
- `📧 Email tool registered` (email working)
- `📅 Calendar tool registered` (calendar working)
- `Email tool not registered (missing credentials in .env)` (missing config)

### Authentication Failures

**Common issues:**
1. Using regular password instead of app password ❌
2. 2FA not enabled
3. Wrong IMAP/SMTP server
4. Incorrect CalDAV URL format

**Solutions:**
1. Generate app-specific password
2. Enable 2FA on your account
3. Run `python configure.py` to auto-detect correct servers
4. Check `.env.example` for correct URL formats

### Gmail CalDAV URL

Make sure to replace `YOUR_EMAIL` with your actual email:
```bash
# ❌ Wrong
CALDAV_URL=https://apidata.googleusercontent.com/caldav/v2/YOUR_EMAIL@gmail.com/events

# ✅ Correct
CALDAV_URL=https://apidata.googleusercontent.com/caldav/v2/john.doe@gmail.com/events
```

### Permission Errors

If running on EC2, make sure `.env` has correct permissions:
```bash
chmod 600 .env  # Only owner can read/write
```

## Security Notes

- **Never commit `.env` to git** (already in `.gitignore`)
- Use app-specific passwords, never your main account password
- `.env` is protected by Layer 14 security (bot cannot modify it)
- Store API keys and passwords securely
- On EC2: Use IAM roles when possible instead of hardcoded credentials

## Need Help?

1. Check logs: `tail -f logs/agent.log`
2. Review `.env.example` for configuration templates
3. Run configuration wizard: `python configure.py`
4. Verify credentials at provider websites
