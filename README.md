# 🤖 Autonomous Claude Agent

> **Fully autonomous, self-driving AI agent powered by Claude API**
> > Multi-channel support • Computer use capabilities • Enterprise-ready deployment
> >
> > [![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
> > [![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
> >
> > ## 🌟 Features
> >
> > ### Core Capabilities
> > - **🔄 Fully Autonomous Agent Loop** - Runs independently until task completion
> > - - **💻 Computer Use Integration** - Desktop automation with screenshot, mouse, and keyboard control
> >   - - **🧠 Context-Aware with Vector DB** - Maintains conversation history and learns from interactions
> >     - - **🔒 Enterprise Security** - PII protection, encrypted state, and secure credential management
> >       - - **📊 Real-time Monitoring** - Built-in logging, metrics, and health checks
> >        
> >         - ### Multi-Channel Support
> >         - - 📱 **Telegram** - Full bot support with inline keyboards
> >           - - 💬 **Discord** - Server and DM interactions
> >             - - 📧 **Slack** - Workspace integration with slash commands
> >               - - 🌐 **Web Interface** - Built-in dashboard via WebSocket
> >                 - - 🔌 **Extensible** - Easy to add more channels
> >                  
> >                   - ### Tools & Automation
> >                   - - 🖥️ **Computer Use** - Screen capture, mouse/keyboard control
> >                     - - 📝 **File Operations** - Read, write, edit with version control
> >                       - - 🔧 **Bash Execution** - Sandboxed command execution
> >                         - - 🌐 **Web Search & Fetch** - Internet research capabilities
> >                           - - 📦 **Custom Tools** - Plugin system for custom extensions
> >                            
> >                             - ## 🚀 Quick Start
> >                            
> >                             - ### Prerequisites
> >                             - - Python 3.10 or higher
> >                               - - Claude API key ([Get one here](https://console.anthropic.com/))
> > - (Optional) Telegram/Discord/Slack bot tokens
> >
> > - ### Installation
> >
> > - ```bash
> >   # Clone the repository
> >   git clone https://github.com/AmplifyCo/digital-twin.git
> >   cd digital-twin
> >
> >   # Create virtual environment
> >   python -m venv venv
> >   source venv/bin/activate  # On Windows: venv\Scripts\activate
> >
> >   # Install dependencies
> >   pip install -r requirements.txt
> >
> >   # Copy environment template
> >   cp .env.example .env
> >
> >   # Edit .env with your API keys
> >   nano .env
> >   ```
> >
> > ### Configuration
> >
> > Create a `.env` file with your credentials:
> >
> > ```bash
> > # Required: Claude API
> > ANTHROPIC_API_KEY=your_api_key_here
> >
> > # Optional: Messaging Platforms
> > TELEGRAM_BOT_TOKEN=your_telegram_token
> > DISCORD_BOT_TOKEN=your_discord_token
> > SLACK_BOT_TOKEN=your_slack_token
> > SLACK_APP_TOKEN=your_slack_app_token
> >
> > # Optional: Advanced Configuration
> > MAX_ITERATIONS=50
> > THINKING_BUDGET=5000
> > AUTO_EXECUTE=true
> > ENABLE_COMPUTER_USE=true
> > ```
> >
> > ### Run the Agent
> >
> > ```bash
> > # Start the gateway (control plane)
> > python src/gateway/server.py
> >
> > # In another terminal, start a channel (e.g., Telegram)
> > python src/channels/telegram_bot.py
> >
> > # Or run everything with Docker
> > docker-compose up
> > ```
> >
> > ## 📁 Project Structure
> >
> > ```
> > digital-twin/
> > ├── src/
> > │   ├── core/
> > │   │   ├── agent.py              # Main autonomous agent loop
> > │   │   ├── tools/
> > │   │   │   ├── computer_use.py   # Desktop automation
> > │   │   │   ├── bash.py           # Shell command execution
> > │   │   │   ├── editor.py         # File operations
> > │   │   │   └── web.py            # Web search & fetch
> > │   │   └── context/
> > │   │       ├── vector_db.py      # ChromaDB integration
> > │   │       └── state.py          # State management
> > │   ├── gateway/
> > │   │   ├── server.py             # WebSocket server
> > │   │   ├── session.py            # Session management
> > │   │   └── router.py             # Message routing
> > │   ├── channels/
> > │   │   ├── telegram_bot.py       # Telegram integration
> > │   │   ├── discord_bot.py        # Discord integration
> > │   │   ├── slack_bot.py          # Slack integration
> > │   │   └── web_interface.py      # Web UI
> > │   ├── security/
> > │   │   ├── pii_filter.py         # PII detection & redaction
> > │   │   ├── encryption.py         # Data encryption
> > │   │   └── sandbox.py            # Command sandboxing
> > │   └── utils/
> > │       ├── logging.py            # Structured logging
> > │       ├── metrics.py            # Prometheus metrics
> > │       └── config.py             # Configuration loader
> > ├── deploy/
> > │   ├── docker/
> > │   │   ├── Dockerfile
> > │   │   └── docker-compose.yml
> > │   ├── ec2/
> > │   │   ├── setup.sh              # EC2 setup script
> > │   │   └── systemd/              # Service files
> > │   └── kubernetes/               # K8s manifests
> > ├── config/
> > │   ├── config.yaml               # Main configuration
> > │   └── permissions.yaml          # Permission policies
> > ├── tests/
> > │   ├── test_agent.py
> > │   ├── test_tools.py
> > │   └── test_channels.py
> > ├── docs/
> > │   ├── ARCHITECTURE.md
> > │   ├── API.md
> > │   └── SECURITY.md
> > ├── .env.example
> > ├── requirements.txt
> > ├── setup.py
> > └── README.md
> > ```
> >
> > ## 🔧 Configuration
> >
> > ### Agent Settings (`config/config.yaml`)
> >
> > ```yaml
> > agent:
> >   model: claude-opus-4-6
> >   max_iterations: 50
> >   thinking_budget: 5000
> >   auto_execute: true
> >
> > tools:
> >   computer_use:
> >     enabled: true
> >     screen_width: 1920
> >     screen_height: 1080
> >   bash:
> >     enabled: true
> >     sandbox: true
> >     allowed_commands:
> >       - npm
> >       - git
> >       - docker
> >   web_search:
> >     enabled: true
> >
> > channels:
> >   telegram:
> >     enabled: true
> >   discord:
> >     enabled: true
> >   slack:
> >     enabled: false
> >
> > security:
> >   pii_detection: true
> >   encryption: true
> >   sandbox_untrusted: true
> >
> > context:
> >   vector_db: chromadb
> >   max_context_tokens: 180000
> >   auto_compact: true
> > ```
> >
> > ### Permission Policies (`config/permissions.yaml`)
> >
> > ```yaml
> > permissions:
> >   auto_approve:
> >     - screenshot
> >     - mouse_move
> >     - read_file
> >   ask_first:
> >     - bash
> >     - file_write
> >     - network_request
> >   deny:
> >     - rm -rf
> >     - sudo
> >     - format
> > ```
> >
> > ## 🐳 Docker Deployment
> >
> > ### Local Development
> >
> > ```bash
> > docker-compose up
> > ```
> >
> > ### Production Deployment
> >
> > ```bash
> > # Build image
> > docker build -t digital-twin:latest .
> >
> > # Run with environment variables
> > docker run -d \
> >   --name claude-agent \
> >   -e ANTHROPIC_API_KEY=your_key \
> >   -p 18789:18789 \
> >   digital-twin:latest
> > ```
> >
> > ## ☁️ AWS EC2 Deployment
> >
> > ### Quick Setup (Amazon Linux 2023)
> >
> > ```bash
> > # SSH into your EC2 instance
> > ssh -i your-key.pem ec2-user@your-instance-ip
> >
> > # Clone and setup
> > git clone https://github.com/AmplifyCo/digital-twin.git
> > cd digital-twin
> > chmod +x deploy/ec2/setup.sh
> > ./deploy/ec2/setup.sh
> >
> > # Configure environment
> > nano .env
> >
> > # Start as systemd service
> > sudo systemctl start claude-agent
> > sudo systemctl enable claude-agent
> > sudo systemctl status claude-agent
> > ```
> >
> > The setup script handles:
> > - Python 3.10+ installation
> > - - Virtual environment creation
> >   - - Dependency installation
> >     - - Systemd service configuration
> >       - - Firewall rules (port 18789)
> >         - - Auto-restart on failure
> >          
> >           - ## 🔒 Security Best Practices
> >          
> >           - ### 1. **PII Protection**
> >           - ```python
> >             # Automatic PII detection and redaction
> > from src.security.pii_filter import PIIFilter
> >
> > filter = PIIFilter()
> > safe_text = filter.redact(user_input)
> > ```
> >
> > ### 2. **Encrypted State Storage**
> > ```python
> > # All session data is encrypted at rest
> > from src.security.encryption import encrypt_data, decrypt_data
> >
> > encrypted = encrypt_data(session_data, key)
> > ```
> >
> > ### 3. **Sandboxed Execution**
> > ```python
> > # Bash commands run in restricted environment
> > from src.security.sandbox import SandboxedBash
> >
> > sandbox = SandboxedBash(allowed_commands=['git', 'npm'])
> > result = await sandbox.execute('npm test')
> > ```
> >
> > ### 4. **API Key Security**
> > - Never commit `.env` files
> > - - Use environment variables in production
> >   - - Rotate keys regularly
> >     - - Use IAM roles on EC2 (avoid hardcoded keys)
> >      
> >       - ## 📊 Monitoring & Logging
> >      
> >       - ### Structured Logs
> >       - ```python
> >         import structlog
> >
> > log = structlog.get_logger()
> > log.info("agent.task.started", task_id=task_id, user_id=user_id)
> > ```
> >
> > ### Prometheus Metrics
> > ```python
> > # Access metrics at http://localhost:18789/metrics
> > from prometheus_client import Counter, Histogram
> >
> > requests = Counter('agent_requests_total', 'Total requests')
> > latency = Histogram('agent_latency_seconds', 'Request latency')
> > ```
> >
> > ### Health Checks
> > ```bash
> > # Check agent health
> > curl http://localhost:18789/health
> >
> > # Check specific components
> > curl http://localhost:18789/health/gateway
> > curl http://localhost:18789/health/vector-db
> > ```
> >
> > ## 🎯 Usage Examples
> >
> > ### 1. Simple Task
> > ```python
> > from src.core.agent import AutonomousAgent
> >
> > agent = AutonomousAgent(api_key=ANTHROPIC_API_KEY)
> > result = await agent.run("Create a Python script that analyzes log files")
> > ```
> >
> > ### 2. Multi-Step Workflow
> > ```python
> > result = await agent.run("""
> > 1. Search for best practices on API design
> > 2. Create a FastAPI project structure
> > 3. Implement 3 RESTful endpoints
> > 4. Write unit tests
> > 5. Generate API documentation
> > """)
> > ```
> >
> > ### 3. Computer Use Automation
> > ```python
> > result = await agent.run("""
> > Open Chrome, navigate to GitHub,
> > search for 'autonomous agents',
> > screenshot the top 5 results,
> > and summarize their features
> > """)
> > ```
> >
> > ## 🔌 Extending the Agent
> >
> > ### Add Custom Tool
> >
> > ```python
> > # src/core/tools/custom_tool.py
> > from src.core.tools.base import BaseTool
> >
> > class CustomTool(BaseTool):
> >     name = "custom_tool"
> >     description = "Does something custom"
> >
> >     async def execute(self, **params):
> >         # Your implementation
> >         return result
> >
> > # Register in agent
> > agent.register_tool(CustomTool())
> > ```
> >
> > ### Add New Channel
> >
> > ```python
> > # src/channels/new_channel.py
> > from src.gateway.client import GatewayClient
> >
> > class NewChannelBot:
> >     def __init__(self, gateway_url):
> >         self.gateway = GatewayClient(gateway_url)
> >
> >     async def handle_message(self, message):
> >         response = await self.gateway.send_message(message)
> >         # Send response back to user
> > ```
> >
> > ## 🐛 Troubleshooting
> >
> > ### Agent Not Responding
> > ```bash
> > # Check logs
> > tail -f logs/agent.log
> >
> > # Verify API key
> > python -c "import os; print(os.getenv('ANTHROPIC_API_KEY'))"
> >
> > # Test connection
> > python src/utils/test_connection.py
> > ```
> >
> > ### High Memory Usage
> > ```bash
> > # Check context size
> > curl http://localhost:18789/metrics | grep context
> >
> > # Clear old sessions
> > python src/utils/cleanup.py --days 7
> > ```
> >
> > ### Permission Denied
> > ```bash
> > # Check sandbox config
> > cat config/permissions.yaml
> >
> > # Run with elevated permissions (development only)
> > python src/gateway/server.py --no-sandbox
> > ```
> >
> > ## 📚 Documentation
> >
> > - [Architecture Overview](docs/ARCHITECTURE.md)
> > - - [API Reference](docs/API.md)
> >   - - [Security Guide](docs/SECURITY.md)
> >     - - [Contributing Guidelines](CONTRIBUTING.md)
> >      
> >       - ## 🤝 Contributing
> >      
> >       - Contributions are welcome! Please read our [Contributing Guidelines](CONTRIBUTING.md) first.
> >      
> >       - 1. Fork the repository
> > 2. Create a feature branch (`git checkout -b feature/amazing-feature`)
> > 3. 3. Commit your changes (`git commit -m 'Add amazing feature'`)
> >    4. 4. Push to the branch (`git push origin feature/amazing-feature`)
> >       5. 5. Open a Pull Request
> >         
> >          6. ## 📝 License
> >         
> >          7. This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
> >         
> >          8. ## ⚠️ Disclaimer
> >
> > This is an autonomous AI agent with powerful capabilities. Always:
> > - Review actions before deployment
> > - - Test in safe environments first
> >   - - Monitor system behavior
> >     - - Follow security best practices
> >       - - Comply with applicable laws and regulations
> >        
> >         - ## 🙏 Acknowledgments
> >        
> >         - - Built with [Claude API](https://www.anthropic.com/claude) by Anthropic
> >           - - Inspired by agentic AI architectures
> >             - - Vector storage powered by [ChromaDB](https://www.trychroma.com/)
> >              
> >               - ## 📞 Support
> >              
> >               - - **Issues**: [GitHub Issues](https://github.com/AmplifyCo/digital-twin/issues)
> >                 - - **Discussions**: [GitHub Discussions](https://github.com/AmplifyCo/digital-twin/discussions)
> >                   - - **Email**: support@example.com
> >                    
> >                     - ---
> >
> > **Made with ❤️ for the AI community**
