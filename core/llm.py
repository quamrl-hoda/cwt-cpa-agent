import json
import logging
import time
import requests
from core.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)

# Retry configuration
_MAX_RETRIES   = 3      # max attempts per LLM call
_RETRY_BACKOFF = 2.0    # seconds — doubles each retry (2s, 4s, 8s)
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def ask_llm(
    prompt: str,
    system: str = "You are a helpful logistics and CPA assistant.",
    temperature: float = 0.2,
    max_tokens: int = 1500,
) -> str:
    """
    Send a prompt to OpenRouter and return the assistant's reply as a string.
    Automatically retries up to _MAX_RETRIES times on transient network errors.

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

    last_error: str = "Unknown error"

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = requests.post(
                OPENROUTER_BASE_URL,
                headers=headers,
                json=payload,
                timeout=90,          # increased from 60 to 90s for large PDFs
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            if content is None:
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                logger.error(
                    "LLM returned null content (finish_reason=%s). "
                    "Check that LLM_MODEL='%s' is valid on OpenRouter.",
                    finish_reason, LLM_MODEL,
                )
                return (
                    f"ERROR: LLM returned no content (finish_reason={finish_reason}). "
                    "Check your LLM_MODEL setting."
                )

            reply = content.strip()
            logger.debug("LLM reply (%s chars): %s", len(reply), reply[:120])
            return reply

        except requests.exceptions.HTTPError as e:
            logger.error("OpenRouter HTTP error: %s — %s", e, response.text)
            return f"ERROR: HTTP {response.status_code} — {response.text}"

        except _RETRYABLE_EXCEPTIONS as e:
            last_error = str(e)
            wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "LLM network error (attempt %d/%d): %s — retrying in %.0fs...",
                    attempt, _MAX_RETRIES, type(e).__name__, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "LLM call failed after %d attempts: %s",
                    _MAX_RETRIES, last_error,
                )

        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return f"ERROR: {e}"

    return f"ERROR: Network failed after {_MAX_RETRIES} retries — {last_error}"


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
