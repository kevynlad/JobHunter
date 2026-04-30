"""
src/bot/key_router.py
━━━━━━━━━━━━━━━━━━━━━
Central LLM Key Router — NVIDIA NIM + Groq

Seleciona qual provedor e chave usar com base no propósito da chamada.

Provedores disponíveis:
  nvidia  → NVIDIA NIM API (Nemotron, Llama, etc.) — Free: 40 RPM
  groq    → Groq API (Llama 3, Mixtral, Gemma) — Free: 30 RPM, ultra-rápido

Uso típico:
  client, model = get_llm_client("classify")
  client, model = get_llm_client("chat")
  client, model = get_llm_client("embed")
"""

import os
import logging
from openai import AsyncOpenAI

from src.db.client import get_vault_secret

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Modelos padrão por provedor e propósito
# ─────────────────────────────────────────────────────────────

_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
_GROQ_BASE_URL   = "https://api.groq.com/openai/v1"

# Modelo escolhido por propósito
_MODELS = {
    # Classificação de vagas: raciocínio rápido + JSON obrigatório
    "classify": {
        "provider": "nvidia",
        "model":    "nvidia/nemotron-3-nano-30b-a3b",
    },
    # Chat do bot / agente conversacional: rápido + fluente
    "chat": {
        "provider": "groq",
        "model":    "llama-3.3-70b-versatile",
    },
    # Cover letter / escrita longa: qualidade alta
    "write": {
        "provider": "groq",
        "model":    "llama-3.3-70b-versatile",
    },
    # Fallback genérico (se propósito não reconhecido)
    "default": {
        "provider": "nvidia",
        "model":    "nvidia/nemotron-3-nano-30b-a3b",
    },
}

# ─────────────────────────────────────────────────────────────
# Cache de clientes (evita recriar a cada chamada)
# ─────────────────────────────────────────────────────────────
_clients: dict[str, AsyncOpenAI] = {}


def _get_client(provider: str) -> AsyncOpenAI:
    """Retorna (e cacheia) o AsyncOpenAI client para o provedor."""
    if provider in _clients:
        return _clients[provider]

    if provider == "nvidia":
        api_key = os.getenv("NVIDIA_API_KEY", "").strip() or get_vault_secret("NVIDIA_API_KEY")
        if not api_key:
            raise EnvironmentError("NVIDIA_API_KEY não encontrada no ENV nem no Vault.")
        client = AsyncOpenAI(base_url=_NVIDIA_BASE_URL, api_key=api_key)

    elif provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip() or get_vault_secret("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY não encontrada no ENV nem no Vault.")
        client = AsyncOpenAI(base_url=_GROQ_BASE_URL, api_key=api_key)

    else:
        raise ValueError(f"Provedor desconhecido: '{provider}'. Use 'nvidia' ou 'groq'.")

    _clients[provider] = client
    return client


# ─────────────────────────────────────────────────────────────
# API Pública
# ─────────────────────────────────────────────────────────────

def get_llm_client(purpose: str = "default") -> tuple[AsyncOpenAI, str]:
    """
    Retorna (client, model_name) para o propósito solicitado.

    Propósitos disponíveis:
      "classify" → NVIDIA NIM (Nemotron) — ideal para JSON estruturado
      "chat"     → Groq (Llama 3) — rápido e conversacional
      "write"    → Groq (Llama 3) — qualidade em escrita longa
      "default"  → NVIDIA NIM (fallback genérico)

    Raises:
      EnvironmentError: se a chave do provedor não estiver configurada.
    """
    config = _MODELS.get(purpose, _MODELS["default"])
    provider = config["provider"]
    model    = config["model"]

    client = _get_client(provider)
    logger.debug(f"LLM Client: purpose={purpose} → {provider}/{model}")
    return client, model


def get_available_providers() -> dict[str, bool]:
    """
    Retorna quais provedores estão configurados (têm chave).
    Útil para o /debug command do bot.
    """
    return {
        "nvidia": bool(os.getenv("NVIDIA_API_KEY", "").strip()),
        "groq":   bool(os.getenv("GROQ_API_KEY", "").strip()),
    }
