"""
Unified AI config — single source of truth for model provider settings.

Priority: env vars > OpenClaw config > Hermes config > defaults.
Import from this module instead of reading config files directly.

Usage:
    from ai_config import get_config
    cfg = get_config()
    # cfg["api_key"], cfg["base_url"], cfg["model"]
"""
import json, os

_CONFIG = None

# Canonical environment variable names
# Only use AI_API_KEY for generic override. Provider-specific keys
# (DASHSCOPE_API_KEY, OPENAI_API_KEY) belong in config files, not env.
_ENV_MAP = {
    "api_key":  ["AI_API_KEY"],
    "base_url": ["AI_BASE_URL"],
    "model":    ["AI_MODEL"],
}

# Fallback config file paths (checked in order)
_CONFIG_PATHS = [
    os.path.expanduser("~/.openclaw/openclaw.json"),
    os.path.expanduser("~/.config/openclaw/openclaw.json"),
    os.path.join(os.path.dirname(__file__), ".env"),
]


def _load_from_openclaw(path):
    """Extract provider config from openclaw.json format."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return {}

    result = {}
    agents_cfg = cfg.get("agents", {}).get("defaults", {})
    model_str = agents_cfg.get("model", "")
    if model_str:
        result["model"] = model_str
        provider = model_str.split("/")[0] if "/" in model_str else "deepseek"
        providers = cfg.get("models", {}).get("providers", {})
        if provider in providers:
            pcfg = providers[provider]
            result["base_url"] = pcfg.get("baseUrl", "")
            result["api_key"] = pcfg.get("apiKey", "")
    return result


def _resolve_env(key):
    """Try multiple env var names, return first that's set."""
    for name in _ENV_MAP.get(key, []):
        val = os.environ.get(name)
        if val:
            return val
    return None


def get_config():
    """Return dict with api_key, base_url, model. Cached after first call."""
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    cfg = {
        "api_key": "",
        "base_url": "",
        "model": "deepseek/deepseek-v4-pro",  # sensible default
    }

    # 1. Try file-based configs
    for path in _CONFIG_PATHS:
        if os.path.exists(path):
            file_cfg = _load_from_openclaw(path)
            for k in cfg:
                if file_cfg.get(k):
                    cfg[k] = file_cfg[k]
            if cfg["api_key"]:
                break

    # 2. Environment overrides (highest priority)
    for k in cfg:
        env_val = _resolve_env(k)
        if env_val:
            cfg[k] = env_val

    _CONFIG = cfg
    return cfg


def get_model_name():
    """Return the short model name (without provider prefix)."""
    model = get_config()["model"]
    return model.split("/")[-1] if "/" in model else model


def get_base_url():
    """Return the base URL with /v1 suffix stripped."""
    url = get_config()["base_url"]
    return url.rstrip("/")


def clear_cache():
    """Force re-reading config on next get_config() call."""
    global _CONFIG
    _CONFIG = None
