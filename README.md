# Nova — the AutoBot

> Your personal AI assistant that learns, remembers, and acts on your behalf.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Nova is a self-hosted, single-user AI assistant you run on your own server. It connects to you via Telegram, learns your preferences over time, and can take actions — send emails, post to X, manage your calendar, set reminders, browse the web, and more.

Unlike generic chatbots, Nova builds a memory of who you are. It remembers your communication style, preferences, and past conversations to provide increasingly personalized assistance.

---

## What Nova Can Do

- **Conversations** — Chat naturally via Telegram with context from past interactions
- **Email** — Read, compose, and reply to emails on your behalf
- **Calendar** — Check, create, and manage calendar events
- **Social Media** — Post to X (Twitter), including community posts
- **Reminders** — Set time-based reminders that fire via Telegram notifications
- **Web Browsing** — Browse pages with visual verification (screenshots)
- **Web Research** — Fetch and summarize web content
- **File Operations** — Read, write, and manage files
- **Shell Commands** — Execute scripts and terminal commands
- **Memory** — Learns and recalls your preferences, habits, and context

## Getting Started

### Prerequisites

- Python 3.10+
- [Anthropic API key](https://console.anthropic.com/)
- Telegram Bot Token ([create one via BotFather](https://t.me/BotFather))

### Installation

```bash
git clone https://github.com/AmplifyCo/digital-twin.git
cd digital-twin

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
```

### Configuration

Edit `.env` with your credentials:

```bash
# Required
ANTHROPIC_API_KEY=your_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional — enable talents as needed
EMAIL_ADDRESS=you@example.com
EMAIL_PASSWORD=your_app_password
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_SMTP_SERVER=smtp.gmail.com

CALDAV_URL=your_caldav_url
CALDAV_USERNAME=your_username
CALDAV_PASSWORD=your_password

X_API_KEY=your_x_api_key
X_API_SECRET=your_x_api_secret
X_ACCESS_TOKEN=your_x_access_token
X_ACCESS_TOKEN_SECRET=your_x_access_token_secret
```

### Run

```bash
python src/main.py
```

Nova starts and connects to Telegram. Message your bot to begin.

## Deployment (Amazon Linux / EC2)

```bash
# SSH into your instance
ssh -i your-key.pem ec2-user@your-instance-ip

# Clone, install, configure
git clone https://github.com/AmplifyCo/digital-twin.git
cd digital-twin
chmod +x deploy/ec2/setup.sh
./deploy/ec2/setup.sh

# Configure
nano .env

# Run as a service
sudo systemctl start digital-twin
sudo systemctl enable digital-twin
```

### Optional: Browser Support

For full web browsing with visual verification:

```bash
sudo yum install -y xorg-x11-server-Xvfb
pip install playwright
playwright install --with-deps chromium
```

## Adding Talents

Nova's capabilities are modular. Each talent can be enabled independently by adding the required credentials to `.env`. See `config/talents.yaml` for the full list of available and upcoming talents.

```bash
# Check talent status
python -m src.setup talents
```

## Architecture

Nova is framework-free — pure Python and asyncio with the Anthropic SDK. No LangChain, no LangGraph, no heavyweight frameworks.

The system is organized into layers that handle different responsibilities: conversation management, intelligence and memory, execution governance, and modular tool capabilities. It includes background processes for self-monitoring, scheduled tasks, and memory management.

## Security

- Single-user by design — only your Telegram chat ID can interact
- Credentials stored in `.env`, never committed
- Tool execution is governed by risk-based policies
- Side effects (emails, posts) are deduplicated to prevent double-sends
- All tool outputs are treated as untrusted data

## License

MIT — see [LICENSE](LICENSE) for details.

## Disclaimer

Nova is an autonomous AI assistant with real-world capabilities (sending emails, posting to social media, executing commands). Always review its configuration and monitor its behavior, especially when first deploying.

---

Built with [Claude](https://www.anthropic.com/claude) by Anthropic | Vector memory powered by [ChromaDB](https://www.trychroma.com/)
