"""
llm.py — Thin wrapper around OpenRouter's chat completions API.

Usage:
    from core.llm import ask_llm
    response = ask_llm("Extract the shipper name from this text: ...")
"""

import json
import logging
import requests
from core.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)


def ask_llm(
    prompt: str,
    system: str = "You are a helpful logistics and CPA assistant.",
    temperature: float = 0.2,
    max_tokens: int = 1500,
) -> str:
    """
    Send a prompt to OpenRouter and return the assistant's reply as a string.

    Args:
        prompt:      The user message / question.
        system:      System-level instruction for the model.
        temperature: Lower = more deterministic (good for extraction).
        max_tokens:  Max reply length.

    Returns:
        The model's text response, or an error string starting with "ERROR:".
    """
    if not OPENROUTER_API_KEY:
        raise EnvironmentError("OPENROUTER_API_KEY is not set in your .env file.")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/cwt-cpa-agent",  # required by OpenRouter
        "X-Title": "CWT CPA Agent",
    }

    payload = {
        "model": LLM_MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    }

    try:
        response = requests.post(OPENROUTER_BASE_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if content is None:
            # Some models / error states return null content
            finish_reason = data["choices"][0].get("finish_reason", "unknown")
            logger.error(
                "LLM returned null content (finish_reason=%s). "
                "Check that LLM_MODEL='%s' is a valid, accessible model on OpenRouter.",
                finish_reason, LLM_MODEL,
            )
            return f"ERROR: LLM returned no content (finish_reason={finish_reason}). Check your LLM_MODEL setting."
        reply = content.strip()
        logger.debug("LLM reply (%s chars): %s", len(reply), reply[:120])
        return reply

    except requests.exceptions.HTTPError as e:
        logger.error("OpenRouter HTTP error: %s — %s", e, response.text)
        return f"ERROR: HTTP {response.status_code} — {response.text}"

    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return f"ERROR: {e}"


def ask_llm_json(prompt: str, system: str = "You are a helpful logistics and CPA assistant.") -> dict:
    """
    Like ask_llm() but expects a JSON response from the model.
    Strips markdown code fences and parses the JSON automatically.

    Returns a dict, or {"error": "..."} on failure.
    """
    json_system = (
        system
        + "\n\nIMPORTANT: Respond ONLY with valid JSON. No preamble, no explanation, "
          "no markdown code fences. Just the raw JSON object."
    )
    raw = ask_llm(prompt, system=json_system, temperature=0.1)

    # Strip common markdown fences if the model ignores the instruction
    clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON: %s\nRaw output: %s", e, raw)
        return {"error": f"JSON parse failed: {e}", "raw": raw}
