"""Configuration loader for the autonomous agent."""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from .types import AgentConfig


def load_config(env_file: str = ".env", config_file: str = "config/agent.yaml") -> AgentConfig:
    """Load configuration from environment and yaml files.

    Args:
        env_file: Path to .env file
        config_file: Path to agent.yaml config file

    Returns:
        AgentConfig instance with all settings
    """
    # Load environment variables
    load_dotenv(env_file)

    # Load YAML config if exists
    yaml_config = {}
    if Path(config_file).exists():
        with open(config_file, 'r') as f:
            yaml_config = yaml.safe_load(f) or {}

    # Build config from environment (takes precedence) and YAML
    models_config = yaml_config.get("agent", {}).get("models", {})
    local_model_config = yaml_config.get("local_model", {})

    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    grok_api_key = os.getenv("GROK_API_KEY", "")

    config = AgentConfig(
        # API - Multi-tier model configuration
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        default_model=os.getenv("DEFAULT_MODEL", models_config.get("default", "gemini/gemini-2.0-flash")),
        subagent_model=os.getenv("SUBAGENT_MODEL", models_config.get("subagent", "gemini/gemini-2.0-flash")),
        chat_model=os.getenv("CHAT_MODEL", models_config.get("chat", "gemini/gemini-2.0-flash")),
        intent_model=os.getenv("INTENT_MODEL", models_config.get("intent", "gemini/gemini-2.0-flash")),

        # Gemini (optional — intent + simple chat via LiteLLM)
        gemini_model=os.getenv("GEMINI_MODEL", yaml_config.get("agent", {}).get("models", {}).get("gemini_flash", "gemini/gemini-2.0-flash")),
        gemini_enabled=bool(gemini_api_key),

        # Grok (optional, via LiteLLM — fallback)
        grok_enabled=bool(grok_api_key),
        grok_models=yaml_config.get("agent", {}).get("models", {}).get("grok", {}) or {
            "flash": os.getenv("GROK_FLASH_MODEL", "xai/grok-beta"),
            "haiku": os.getenv("GROK_HAIKU_MODEL", "xai/grok-1"),
            "sonnet": os.getenv("GROK_SONNET_MODEL", "xai/grok-advanced"),
            "quality": os.getenv("GROK_QUALITY_MODEL", "xai/grok-4.1")
        },

        # Local Models (optional)
        local_model_enabled=os.getenv("LOCAL_MODEL_ENABLED", str(local_model_config.get("enabled", False))).lower() == "true",
        local_model_name=os.getenv("LOCAL_MODEL_NAME", local_model_config.get("name", "HuggingFaceTB/SmolLM2-1.7B-Instruct")),
        local_model_endpoint=os.getenv("LOCAL_MODEL_ENDPOINT", local_model_config.get("endpoint")),
        local_model_for=os.getenv("LOCAL_MODEL_FOR", local_model_config.get("use_for", "trivial,simple")),

        # Specialized local coder model
        local_coder_enabled=os.getenv("LOCAL_CODER_ENABLED", str(local_model_config.get("coder", {}).get("enabled", False))).lower() == "true",
        local_coder_name=os.getenv("LOCAL_CODER_NAME", local_model_config.get("coder", {}).get("name", "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B")),
        local_coder_endpoint=os.getenv("LOCAL_CODER_ENDPOINT", local_model_config.get("coder", {}).get("endpoint")),

        # Execution
        max_iterations=int(os.getenv("MAX_ITERATIONS", yaml_config.get("agent", {}).get("execution", {}).get("max_iterations", 50))),
        timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", yaml_config.get("agent", {}).get("execution", {}).get("timeout_seconds", 300))),
        retry_attempts=int(os.getenv("RETRY_ATTEMPTS", yaml_config.get("agent", {}).get("execution", {}).get("retry_attempts", 3))),
        self_build_mode=os.getenv("SELF_BUILD_MODE", "true").lower() == "true",

        # Brain
        vector_db_path=os.getenv("VECTOR_DB_PATH", "./data/lancedb"),
        core_brain_path=os.getenv("CORE_BRAIN_PATH", "./data/core_brain"),
        digital_clone_brain_path=os.getenv("DIGITAL_CLONE_BRAIN_PATH", "./data/digital_clone_brain"),
        memory_path=os.getenv("MEMORY_PATH", "./data/memory"),

        # Git
        auto_commit=os.getenv("AUTO_COMMIT", "true").lower() == "true",
        git_user_name=os.getenv("GIT_USER_NAME", ""),
        git_user_email=os.getenv("GIT_USER_EMAIL", ""),

        # Monitoring
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        
        # Twilio Voice & WhatsApp
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        twilio_phone_number=os.getenv("TWILIO_PHONE_NUMBER"),
        twilio_whatsapp_number=os.getenv("TWILIO_WHATSAPP_NUMBER") or 
            (f"whatsapp:{os.getenv('TWILIO_PHONE_NUMBER')}" if os.getenv("TWILIO_PHONE_NUMBER") and not os.getenv("TWILIO_PHONE_NUMBER").startswith("whatsapp:") else os.getenv("TWILIO_PHONE_NUMBER")),
        
        # WhatsApp (Meta Cloud API - Deprecated but kept for fallback/legacy)
        whatsapp_api_token=os.getenv("WHATSAPP_API_TOKEN"),
        whatsapp_phone_id=os.getenv("WHATSAPP_PHONE_ID"), 
        whatsapp_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN"),
        whatsapp_allowed_numbers=os.getenv("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if os.getenv("WHATSAPP_ALLOWED_NUMBERS") else [],

        # Identity
        bot_name=os.getenv("BOT_NAME", "Nova"),
        owner_name=os.getenv("OWNER_NAME", "User"),

        dashboard_enabled=yaml_config.get("monitoring", {}).get("dashboard", {}).get("enabled", True),
        dashboard_host=os.getenv("DASHBOARD_HOST", yaml_config.get("monitoring", {}).get("dashboard", {}).get("host", "0.0.0.0")),
        dashboard_port=int(os.getenv("DASHBOARD_PORT", yaml_config.get("monitoring", {}).get("dashboard", {}).get("port", 18789))),

        # Logging
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=os.getenv("LOG_FILE", "./data/logs/agent.log"),
    )

    # Validate required fields
    # Validate required fields
    if not config.api_key and not config.gemini_enabled and not config.grok_enabled:
        raise ValueError("At least one API key (ANTHROPIC_API_KEY or GEMINI_API_KEY or GROK_API_KEY) is required")

    return config
