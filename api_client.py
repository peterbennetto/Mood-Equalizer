"""Reflection line provider.

Picks a reflection line from Anthropic, OpenAI or Ollama, or from the
pre-written bank. Any failure falls back to the bank.

Privacy: only the band, the direction and word-only slider positions
are sent. No numbers, no personal text.
Secrets: keys are only read, never written to disk or logged.
No Streamlit code here.
"""

import os
import re
from typing import NamedTuple

from mood_logic import describe_positions
from responses import get_response

# --- Constants ---------------------------------------------------------

PROVIDERS = ("none", "anthropic", "openai", "ollama")

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "ollama": "qwen3:4b",
}
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TIMEOUT = 15.0

MAX_TOKENS = 200        # Hard cap on reply length (cost control)
MAX_LINE_CHARS = 300    # Longer replies are rejected
MIN_LINE_CHARS = 5

SYSTEM_PROMPT = (
    "You write one short reflection line for a fun mood check-in app. "
    "Rules: one or two sentences, under 30 words, plain UK English. "
    "No numbers. No dashes. Do not mention sliders, scores or bands. "
    "Never scold, blame, compare the person to others, or give orders "
    "that sound like criticism. No clinical or medical claims, and no "
    "diagnosing. Never imply that being calm or in control is a bad "
    "thing. "
    "Direction 'lift': lean towards warmth, joy and beauty. "
    "Direction 'settle': lean towards grounding, perspective and quiet. "
    "Direction 'neutral': be affirming and light. "
    "If the band is very low, include a brief, gentle nod towards "
    "talking to someone you trust or reaching out for support. "
    "If the band is very high, include a brief nod towards pausing "
    "before acting on anything big. "
    "Reply with the line only. No quotes, no preamble."
)


class Reflection(NamedTuple):
    """Result of a reflection request."""
    text: str      # The line to show
    source: str    # anthropic, openai, ollama or bank
    note: str      # Empty, or a short reason a fallback was used


# --- Settings ----------------------------------------------------------

def _to_float(value, default, low, high):
    """Convert to a float inside [low, high], or return the default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clean_key(value):
    """Blank out missing keys and the placeholder from .env.example."""
    value = (value or "").strip()
    if not value or value.lower().startswith("your-"):
        return ""
    return value


def load_settings(env=None):
    """Read settings from .env (via python-dotenv) and the environment.

    Pass `env` (a dict) to skip the file and environment, for testing.
    """
    if env is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()  # Reads .env. Does not overwrite existing vars.
        except ImportError:
            pass  # Package not installed yet. Use the environment only.
        env = os.environ

    provider = str(env.get("MOOD_PROVIDER", "none")).strip().lower()
    if provider not in PROVIDERS:
        provider = "none"

    return {
        "provider": provider,
        "anthropic_key": _clean_key(env.get("ANTHROPIC_API_KEY")),
        "anthropic_model": (env.get("ANTHROPIC_MODEL")
                            or DEFAULT_MODELS["anthropic"]).strip(),
        "openai_key": _clean_key(env.get("OPENAI_API_KEY")),
        "openai_model": (env.get("OPENAI_MODEL")
                         or DEFAULT_MODELS["openai"]).strip(),
        "ollama_host": (env.get("OLLAMA_HOST")
                        or DEFAULT_OLLAMA_HOST).strip(),
        "ollama_model": (env.get("OLLAMA_MODEL")
                         or DEFAULT_MODELS["ollama"]).strip(),
        "temperature": _to_float(env.get("MOOD_TEMPERATURE"),
                                 DEFAULT_TEMPERATURE, 0.0, 1.0),
        "timeout": _to_float(env.get("MOOD_TIMEOUT_SECONDS"),
                             DEFAULT_TIMEOUT, 3.0, 120.0),
    }


def apply_overrides(settings, overrides):
    """Return a copy of settings with sidebar overrides applied.

    Session only. Nothing is written to .env, a file, or os.environ.
    Empty values mean "keep what .env says".
    """
    result = dict(settings)
    if not overrides:
        return result

    provider = str(overrides.get("provider") or "").strip().lower()
    if provider in PROVIDERS:
        result["provider"] = provider
    target = result["provider"]

    key = str(overrides.get("api_key") or "").strip()
    model = str(overrides.get("model") or "").strip()
    host = str(overrides.get("host") or "").strip()

    if key and target in ("anthropic", "openai"):
        result[f"{target}_key"] = key
    if model and target != "none":
        result[f"{target}_model"] = model
    if host and target == "ollama":
        result["ollama_host"] = host
    return result


def provider_status(settings):
    """Return (ready, message). Message is empty when ready."""
    provider = settings["provider"]
    if provider == "none":
        return True, ""
    if provider in ("anthropic", "openai"):
        if not settings[f"{provider}_key"]:
            return False, f"No {provider} key set. Showing a pre-written line."
    if provider == "ollama":
        host = settings["ollama_host"]
        if not host.startswith(("http://", "https://")):
            return False, "Ollama host must start with http:// or https://."
    if not settings[f"{provider}_model"]:
        return False, f"No {provider} model set. Showing a pre-written line."
    return True, ""


# --- Prompt and cleaning -----------------------------------------------

def build_user_message(band, direction, values):
    """Word-only description of the reading. No numbers."""
    positions = "; ".join(describe_positions(values))
    return (
        f"Band: {band.replace('_', ' ')}. "
        f"Direction: {direction}. "
        f"Where they are: {positions}."
    )


def clean_text(raw):
    """Tidy a model reply. Return None if it is unusable."""
    if not raw:
        return None
    text = str(raw)

    # Remove reasoning blocks some local models add.
    text = re.sub(r"<think>.*?</think>", "", text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL | re.IGNORECASE)
    if "</think>" in text.lower():
        text = re.split(r"</think>", text, flags=re.IGNORECASE)[-1]

    # Swap long dashes for commas, drop wrapping quotes, tidy spaces.
    text = text.replace("\u2014", ", ").replace("\u2013", ", ")
    text = " ".join(text.split())
    text = text.strip("\"'\u201c\u201d\u2018\u2019 ").strip()

    if len(text) < MIN_LINE_CHARS or len(text) > MAX_LINE_CHARS:
        return None
    if any(ch.isdigit() for ch in text):
        return None
    return text


# --- Provider calls ----------------------------------------------------
# Each returns raw text or raises. generate_reflection catches everything.

def _call_anthropic(settings, user_message):
    import anthropic
    client = anthropic.Anthropic(
        api_key=settings["anthropic_key"],
        timeout=settings["timeout"],
        max_retries=0,  # No automatic retries
    )
    response = client.messages.create(
        model=settings["anthropic_model"],
        max_tokens=MAX_TOKENS,
        temperature=settings["temperature"],
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(
        block.text for block in response.content
        if getattr(block, "type", "") == "text"
    )


def _call_openai(settings, user_message):
    from openai import OpenAI
    client = OpenAI(
        api_key=settings["openai_key"],
        timeout=settings["timeout"],
        max_retries=0,  # No automatic retries
    )
    response = client.chat.completions.create(
        model=settings["openai_model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=settings["temperature"],
        max_tokens=MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


def _call_ollama(settings, user_message):
    import requests
    host = settings["ollama_host"].rstrip("/")
    response = requests.post(
        f"{host}/api/chat",
        json={
            "model": settings["ollama_model"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                # /no_think asks Qwen3 models to skip their reasoning text.
                {"role": "user", "content": user_message + " /no_think"},
            ],
            "stream": False,
            "options": {
                "temperature": settings["temperature"],
                "num_predict": 300,
            },
        },
        timeout=settings["timeout"],
    )
    response.raise_for_status()
    return response.json().get("message", {}).get("content", "")


# --- Main entry point --------------------------------------------------

def generate_reflection(band, direction, values, settings, avoid=None):
    """Return a Reflection. Falls back to the bank on any problem."""
    provider = settings["provider"]

    if provider == "none":
        return Reflection(get_response(band, avoid), "bank", "")

    ready, message = provider_status(settings)
    if not ready:
        return Reflection(get_response(band, avoid), "bank", message)

    try:
        user_message = build_user_message(band, direction, values)
        if provider == "anthropic":
            raw = _call_anthropic(settings, user_message)
        elif provider == "openai":
            raw = _call_openai(settings, user_message)
        else:
            raw = _call_ollama(settings, user_message)

        text = clean_text(raw)
        if text is None:
            raise ValueError("unusable reply")
        return Reflection(text, provider, "")
    except Exception as exc:  # Deliberately broad: any failure falls back
        # Only the error type is shown. Never the message or the key.
        note = (f"{provider} call failed ({type(exc).__name__}). "
                "Showing a pre-written line.")
        return Reflection(get_response(band, avoid), "bank", note)


# --- Self-check --------------------------------------------------------
# Run with:  python api_client.py
# Makes no real API calls. One test tries an unreachable local address.

def _run_checks():
    import sys
    from mood_logic import default_values
    from responses import RESPONSE_BANK

    this = sys.modules[__name__]
    bank_lines = [line for lines in RESPONSE_BANK.values() for line in lines]

    # Settings: defaults, bad provider, placeholder key, clamping.
    settings = load_settings(env={})
    assert settings["provider"] == "none"
    assert settings["ollama_model"] == "qwen3:4b"
    assert load_settings(env={"MOOD_PROVIDER": "banana"})["provider"] == "none"
    env = {"MOOD_PROVIDER": "anthropic",
           "ANTHROPIC_API_KEY": "your-anthropic-key-here"}
    assert load_settings(env=env)["anthropic_key"] == ""
    env = {"MOOD_TEMPERATURE": "9", "MOOD_TIMEOUT_SECONDS": "abc"}
    loaded = load_settings(env=env)
    assert loaded["temperature"] == 1.0 and loaded["timeout"] == DEFAULT_TIMEOUT

    # Overrides: applied to a copy, never to the environment.
    before = dict(os.environ)
    changed = apply_overrides(settings, {
        "provider": "openai", "api_key": "sk-test-not-real",
        "model": "some-model"})
    assert changed["provider"] == "openai"
    assert changed["openai_key"] == "sk-test-not-real"
    assert changed["openai_model"] == "some-model"
    assert settings["provider"] == "none"          # original untouched
    assert dict(os.environ) == before              # environment untouched
    assert apply_overrides(settings, {"provider": ""})["provider"] == "none"

    # Status checks.
    assert provider_status(settings) == (True, "")
    assert provider_status({**settings, "provider": "openai"})[0] is False
    assert provider_status({**settings, "provider": "ollama",
                            "ollama_host": "localhost"})[0] is False
    assert provider_status({**settings, "provider": "ollama"})[0] is True

    # Prompt message has no digits.
    extremes = {"energy": 0, "spirits": 10, "calm": 2, "control": 8}
    for values in (default_values(), extremes):
        message = build_user_message("very_low", "lift", values)
        assert not any(ch.isdigit() for ch in message), message

    # Cleaning.
    assert clean_text("") is None and clean_text(None) is None
    assert clean_text("Hi") is None
    assert clean_text("Take 10 minutes to rest today.") is None
    assert clean_text("x" * 400) is None
    assert clean_text('"A quiet minute helps."') == "A quiet minute helps."
    assert clean_text("<think>plan it</think>A quiet minute helps.") \
        == "A quiet minute helps."
    assert clean_text("<think>never closed") is None
    assert clean_text("Slow down \u2014 breathe.") == "Slow down , breathe."
    assert clean_text("Line one.\n\nLine two.") == "Line one. Line two."

    # Provider none: bank line, no note.
    result = generate_reflection("low", "lift", default_values(), settings)
    assert result.source == "bank" and result.note == ""
    assert result.text in RESPONSE_BANK["low"]

    # Missing key: falls back with a note.
    result = generate_reflection(
        "high", "settle", default_values(), {**settings, "provider": "anthropic"})
    assert result.source == "bank" and result.note
    assert result.text in RESPONSE_BANK["high"]

    # Mocked provider calls. Originals are restored afterwards.
    originals = (this._call_anthropic, this._call_openai, this._call_ollama)
    try:
        keyed = {**settings, "provider": "anthropic",
                 "anthropic_key": "sk-test-not-real"}

        this._call_anthropic = lambda s, m: "A quiet minute helps."
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert result.source == "anthropic" and result.text == "A quiet minute helps."

        def boom(s, m):
            raise RuntimeError("secret sk-test-not-real leaked?")
        this._call_anthropic = boom
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert result.source == "bank" and result.text in bank_lines
        assert "sk-test" not in result.note     # key never in the note
        assert "RuntimeError" in result.note

        this._call_anthropic = lambda s, m: "Rest for 10 minutes."
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert result.source == "bank"          # digits rejected

        this._call_anthropic = lambda s, m: ""
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert result.source == "bank"          # empty rejected

        this._call_openai = lambda s, m: "Something lovely is close by."
        result = generate_reflection(
            "low", "lift", default_values(),
            {**settings, "provider": "openai", "openai_key": "sk-test-not-real"})
        assert result.source == "openai"

        seen = {}
        def fake_ollama(s, m):
            seen["message"] = m
            return "<think>hm</think>Let things settle for a while."
        this._call_ollama = fake_ollama
        result = generate_reflection(
            "high", "settle", default_values(), {**settings, "provider": "ollama"})
        assert result.source == "ollama"
        assert result.text == "Let things settle for a while."
    finally:
        this._call_anthropic, this._call_openai, this._call_ollama = originals

    # Real call to an unreachable local address: must fall back cleanly.
    unreachable = {**settings, "provider": "ollama",
                   "ollama_host": "http://127.0.0.1:9", "timeout": 3.0}
    result = generate_reflection("low", "lift", default_values(), unreachable)
    assert result.source == "bank" and result.note

    print("All checks passed.")


if __name__ == "__main__":
    _run_checks()