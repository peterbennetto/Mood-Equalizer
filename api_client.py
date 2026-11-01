"""Reflection line provider.

Asks Google Gemini (free tier) for one short reflection line, or picks one
from the pre-written bank. Any failure falls back to the bank.

Privacy: only the band, the direction and word-only slider positions
are sent to Gemini. No numbers, no personal text.
Secrets: the key is only read from the environment. It is never written to
disk, logged, or sent to the browser.
Token counts come from Gemini's own reply. Nothing is stored here.
Standard library only, so the Vercel function needs no packages.
No web-page code here. api/reflect.py is the thin HTTP shell around
handle_reflect().
"""

import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import NamedTuple

from mood_logic import (
    SLIDERS,
    clamp,
    compute_score,
    describe_positions,
    get_band,
    get_direction,
)
from responses import get_response

# --- Constants ---------------------------------------------------------

DEFAULT_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TIMEOUT = 15.0

# Thinking tokens count against this cap, so it is far above the roughly
# 40 tokens the line itself needs. Length is enforced by MAX_LINE_CHARS.
MAX_OUTPUT_TOKENS = 1024
MAX_LINE_CHARS = 300    # Longer replies are rejected
MIN_LINE_CHARS = 5
MAX_AVOID_CHARS = 400   # Longest "previous line" the endpoint accepts
MAX_BODY_BYTES = 2048   # Largest request the endpoint accepts

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
    text: str               # The line to show
    source: str             # gemini or bank
    note: str               # Empty, or a short reason a fallback was used
    input_tokens: int = 0   # Tokens sent to Gemini (0 for the bank)
    output_tokens: int = 0  # Tokens received from Gemini, thinking included


# --- Settings ----------------------------------------------------------

def _to_float(value, default, low, high):
    """Convert to a float inside [low, high], or return the default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def _to_int(value):
    """Convert to a whole number of 0 or more. Anything odd becomes 0."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _clean_key(value):
    """Blank out missing keys and the placeholder from .env.example."""
    value = (value or "").strip()
    if not value or value.lower().startswith("your-"):
        return ""
    return value


def _clean_model(value):
    """Accept a plain model id (optionally 'models/...'). Else use the default."""
    value = (value or "").strip()
    if value.startswith("models/"):
        value = value[len("models/"):]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return DEFAULT_MODEL
    return value


def load_settings(env=None):
    """Read settings from the environment.

    On Vercel these are Project Environment Variables. Locally,
    dev_server.py copies .env into the environment first.
    Pass `env` (a dict) to skip the real environment, for testing.
    """
    if env is None:
        env = os.environ
    return {
        "gemini_key": _clean_key(env.get("GEMINI_API_KEY")),
        "model": _clean_model(env.get("GEMINI_MODEL")),
        "temperature": _to_float(env.get("MOOD_TEMPERATURE"),
                                 DEFAULT_TEMPERATURE, 0.0, 1.0),
        "timeout": _to_float(env.get("MOOD_TIMEOUT_SECONDS"),
                             DEFAULT_TIMEOUT, 3.0, 25.0),
    }


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

    # Swap long dashes for commas, drop wrapping quotes, tidy spaces.
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = " ".join(text.split())
    text = text.strip("\"'“”‘’ ").strip()

    if len(text) < MIN_LINE_CHARS or len(text) > MAX_LINE_CHARS:
        return None
    if any(ch.isdigit() for ch in text):
        return None
    return text


# --- Gemini call -------------------------------------------------------

def _parse_gemini(data):
    """Pull (text, tokens_sent, tokens_received) out of a Gemini reply.

    Text is "" when Gemini blocked the prompt or stopped early (for
    example it hit the token cap), so a cut-off line is never shown.
    Thinking tokens are billed as output, so they are counted as received.
    """
    if not isinstance(data, dict):
        return "", 0, 0
    usage = data.get("usageMetadata") or {}
    tokens_in = _to_int(usage.get("promptTokenCount"))
    tokens_out = (_to_int(usage.get("candidatesTokenCount"))
                  + _to_int(usage.get("thoughtsTokenCount")))

    candidates = data.get("candidates") or []
    if not candidates:  # Prompt blocked: no candidates come back
        return "", tokens_in, tokens_out
    candidate = candidates[0]
    if candidate.get("finishReason", "STOP") != "STOP":
        return "", tokens_in, tokens_out

    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts
                   if not part.get("thought"))
    return text, tokens_in, tokens_out


def _call_gemini(settings, user_message):
    """Returns (text, tokens_sent, tokens_received) or raises."""
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {
            "temperature": settings["temperature"],
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }).encode("utf-8")
    request = urllib.request.Request(
        GEMINI_URL.format(model=settings["model"]),
        data=body,
        # The key goes in a header, not the URL, so it cannot end up in a log line.
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": settings["gemini_key"]},
        method="POST",
    )
    # No automatic retries: one click makes at most one API call.
    with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
        data = json.loads(response.read().decode("utf-8"))
    return _parse_gemini(data)


def _failure_note(exc):
    """Short, safe reason for a fallback. Never the message or the key."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return ("Gemini's free limit has been reached for now. "
                    "Showing a pre-written line.")
        return f"Gemini call failed (HTTP {exc.code}). Showing a pre-written line."
    return f"Gemini call failed ({type(exc).__name__}). Showing a pre-written line."


# --- Main entry points -------------------------------------------------

def generate_reflection(band, direction, values, settings, avoid=None):
    """Return a Reflection. Falls back to the bank on any problem.

    With no Gemini key the bank is used and no note is added: that is the
    normal "pre-written lines only" mode.
    """
    if not settings["gemini_key"]:
        return Reflection(get_response(band, avoid), "bank", "")

    # Set before the call so a rejected reply still reports its usage.
    tokens_in = 0
    tokens_out = 0
    try:
        user_message = build_user_message(band, direction, values)
        raw, tokens_in, tokens_out = _call_gemini(settings, user_message)
        text = clean_text(raw)
        if text is None:
            raise ValueError("unusable reply")
        return Reflection(text, "gemini", "", tokens_in, tokens_out)
    except Exception as exc:  # Deliberately broad: any failure falls back
        return Reflection(get_response(band, avoid), "bank",
                          _failure_note(exc), tokens_in, tokens_out)


def _parse_values(raw):
    """Validate the slider values from a request. None if they are bad."""
    if not isinstance(raw, dict):
        return None
    values = {}
    for slider in SLIDERS:
        value = raw.get(slider["key"])
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        values[slider["key"]] = clamp(value)
    return values


def handle_reflect(raw_body, env=None):
    """Turn a request body (bytes) into (http_status, json_payload).

    Never raises. The band and direction are worked out here, not taken
    from the browser, so the browser cannot ask for anything else.
    """
    if len(raw_body) > MAX_BODY_BYTES:
        return 413, {"error": "Request too large."}
    try:
        data = json.loads(raw_body or b"{}")
    except ValueError:  # Includes bad JSON and bad UTF-8
        return 400, {"error": "Request body must be JSON."}
    if not isinstance(data, dict):
        return 400, {"error": "Request body must be a JSON object."}

    values = _parse_values(data.get("values"))
    if values is None:
        return 400, {"error": "Send a number from 0 to 10 for each slider."}

    settings = load_settings(env)
    if not isinstance(data.get("temperature"), bool):
        settings["temperature"] = _to_float(
            data.get("temperature"), settings["temperature"], 0.0, 1.0)
    avoid = data.get("avoid")
    avoid = avoid[:MAX_AVOID_CHARS] if isinstance(avoid, str) else None

    band = get_band(compute_score(values))
    result = generate_reflection(
        band, get_direction(band), values, settings, avoid)
    return 200, {
        "text": result.text,
        "source": result.source,
        "note": result.note,
        "band": band,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


# --- Self-check --------------------------------------------------------
# Run with:  python api_client.py
# Makes no real API calls. Gemini is replaced with fakes.

def _run_checks():
    import io
    import sys

    from mood_logic import default_values
    from responses import RESPONSE_BANK

    this = sys.modules[__name__]
    bank_lines = [line for lines in RESPONSE_BANK.values() for line in lines]

    # Settings: defaults, placeholder key, bad model, clamping.
    settings = load_settings(env={})
    assert settings["gemini_key"] == ""
    assert settings["model"] == DEFAULT_MODEL
    assert settings["temperature"] == DEFAULT_TEMPERATURE
    assert settings["timeout"] == DEFAULT_TIMEOUT
    assert load_settings(env={"GEMINI_API_KEY": "your-gemini-key-here"})["gemini_key"] == ""
    assert load_settings(env={"GEMINI_API_KEY": " abc "})["gemini_key"] == "abc"
    assert load_settings(env={"GEMINI_MODEL": "models/gemini-x"})["model"] == "gemini-x"
    assert load_settings(env={"GEMINI_MODEL": "a/b?key=1"})["model"] == DEFAULT_MODEL
    loaded = load_settings(env={"MOOD_TEMPERATURE": "9", "MOOD_TIMEOUT_SECONDS": "abc"})
    assert loaded["temperature"] == 1.0 and loaded["timeout"] == DEFAULT_TIMEOUT
    assert load_settings(env={"MOOD_TIMEOUT_SECONDS": "999"})["timeout"] == 25.0
    assert load_settings(env={"MOOD_TEMPERATURE": "nan"})["temperature"] == DEFAULT_TEMPERATURE

    # Whole-number helper.
    assert _to_int(None) == 0 and _to_int("abc") == 0 and _to_int(-5) == 0
    assert _to_int(7) == 7 and _to_int(7.9) == 7 and _to_int("12") == 12

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
    assert clean_text("Slow down — breathe.") == "Slow down, breathe."
    assert clean_text("Slow down–breathe.") == "Slow down, breathe."
    assert clean_text("Line one.\n\nLine two.") == "Line one. Line two."

    # Parsing a Gemini reply: text, tokens (thinking counted as received).
    good = {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "A quiet minute "}, {"text": "helps."}]}}],
        "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 8,
                          "thoughtsTokenCount": 5},
    }
    assert _parse_gemini(good) == ("A quiet minute helps.", 30, 13)
    cut = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [
        {"text": "A quiet mi"}]}}], "usageMetadata": {"promptTokenCount": 30}}
    assert _parse_gemini(cut) == ("", 30, 0)
    blocked = {"promptFeedback": {"blockReason": "SAFETY"},
               "usageMetadata": {"promptTokenCount": 30}}
    assert _parse_gemini(blocked) == ("", 30, 0)
    safety = {"candidates": [{"finishReason": "SAFETY"}]}
    assert _parse_gemini(safety) == ("", 0, 0)
    thoughts = {"candidates": [{"content": {"parts": [
        {"text": "plan it", "thought": True}, {"text": "Fine."}]}}]}
    assert _parse_gemini(thoughts)[0] == "Fine."
    assert _parse_gemini(None) == ("", 0, 0) and _parse_gemini({}) == ("", 0, 0)

    # No key: bank line, no note, no tokens.
    result = generate_reflection("low", "lift", default_values(), settings)
    assert result.source == "bank" and result.note == ""
    assert result.text in RESPONSE_BANK["low"]
    assert (result.input_tokens, result.output_tokens) == (0, 0)

    # The real request, with urlopen replaced: key in the header only.
    originals = (this._call_gemini, urllib.request.urlopen)
    keyed = {**settings, "gemini_key": "AIza-test-not-real"}
    try:
        sent = {}

        def fake_urlopen(request, timeout=None):
            sent["url"] = request.full_url
            sent["headers"] = {k.lower(): v for k, v in request.header_items()}
            sent["body"] = json.loads(request.data)
            sent["timeout"] = timeout
            return io.BytesIO(json.dumps(good).encode("utf-8"))
        urllib.request.urlopen = fake_urlopen
        result = generate_reflection(
            "high", "settle", default_values(), {**keyed, "temperature": 0.2})
        assert result == Reflection("A quiet minute helps.", "gemini", "", 30, 13)
        assert sent["url"] == GEMINI_URL.format(model=DEFAULT_MODEL)
        assert "AIza" not in sent["url"]
        assert sent["headers"]["x-goog-api-key"] == "AIza-test-not-real"
        assert sent["body"]["generationConfig"]["temperature"] == 0.2
        assert sent["body"]["generationConfig"]["maxOutputTokens"] == MAX_OUTPUT_TOKENS
        assert sent["body"]["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
        user_text = sent["body"]["contents"][0]["parts"][0]["text"]
        assert "Band: high." in user_text
        assert sent["timeout"] == keyed["timeout"]

        # Rate limit: friendly note, no key, no tokens.
        def limited(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, None)
        urllib.request.urlopen = limited
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert result.source == "bank" and result.text in bank_lines
        assert "free limit" in result.note and "AIza" not in result.note
        assert (result.input_tokens, result.output_tokens) == (0, 0)

        # Other HTTP error: code shown, nothing else.
        def forbidden(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        urllib.request.urlopen = forbidden
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert "HTTP 403" in result.note and "AIza" not in result.note

        # Network failure: only the error type is shown.
        def down(request, timeout=None):
            raise urllib.error.URLError("secret AIza-test-not-real leaked?")
        urllib.request.urlopen = down
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert result.source == "bank" and "URLError" in result.note
        assert "AIza" not in result.note and "secret" not in result.note
    finally:
        this._call_gemini, urllib.request.urlopen = originals

    # Mocked _call_gemini: unusable replies fall back but keep their tokens.
    try:
        this._call_gemini = lambda s, m: ("Rest for 10 minutes.", 20, 9)
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert result.source == "bank" and (result.input_tokens, result.output_tokens) == (20, 9)
        this._call_gemini = lambda s, m: ("", 15, 0)
        result = generate_reflection("high", "settle", default_values(), keyed)
        assert result.source == "bank" and (result.input_tokens, result.output_tokens) == (15, 0)

        # handle_reflect: validation.
        ok_values = {"energy": 5, "spirits": 5, "calm": 5, "control": 5}
        post = lambda payload, env=None: handle_reflect(  # noqa: E731
            payload if isinstance(payload, bytes) else json.dumps(payload).encode(), env)
        assert post(b"not json")[0] == 400
        assert post(b"\xff\xfe")[0] == 400
        assert post(b"[1]")[0] == 400
        assert post(b"x" * (MAX_BODY_BYTES + 1))[0] == 413
        assert post({})[0] == 400
        assert post({"values": {"energy": 5}})[0] == 400
        assert post({"values": {**ok_values, "calm": "5"}})[0] == 400
        assert post({"values": {**ok_values, "calm": True}})[0] == 400
        assert post(b'{"values": {"energy": NaN, "spirits": 5, "calm": 5, "control": 5}}')[0] == 400
        assert post(b'{"values": {"energy": 1e999, "spirits": 5, "calm": 5, "control": 5}}')[0] == 400

        # handle_reflect: good request with no key uses the bank.
        status, payload = post({"values": ok_values}, env={})
        assert status == 200 and payload["band"] == "balanced"
        assert payload["source"] == "bank" and payload["text"] in RESPONSE_BANK["balanced"]
        assert payload["note"] == "" and payload["input_tokens"] == 0

        # handle_reflect: out-of-range numbers are clamped, band is server-side.
        status, payload = post({"values": {k: 99 for k in ok_values}}, env={})
        assert status == 200 and payload["band"] == "very_high"

        # handle_reflect: key set, temperature passed through and clamped,
        # a bad temperature or "avoid" is ignored.
        seen = {}

        def fake_gemini(s, m):
            seen["temperature"] = s["temperature"]
            seen["message"] = m
            return "Something lovely is close by.", 30, 9
        this._call_gemini = fake_gemini
        env = {"GEMINI_API_KEY": "AIza-test-not-real"}
        status, payload = post({"values": ok_values, "temperature": 0.2}, env)
        assert payload["source"] == "gemini" and seen["temperature"] == 0.2
        assert (payload["input_tokens"], payload["output_tokens"]) == (30, 9)
        post({"values": ok_values, "temperature": 7}, env)
        assert seen["temperature"] == 1.0
        post({"values": ok_values, "temperature": "hot"}, env)
        assert seen["temperature"] == DEFAULT_TEMPERATURE
        post({"values": ok_values, "temperature": True}, env)
        assert seen["temperature"] == DEFAULT_TEMPERATURE
        status, payload = post({"values": ok_values, "avoid": 5}, {})
        assert status == 200

        # The prompt carries words only, even when the browser sends numbers.
        assert not any(ch.isdigit() for ch in seen["message"]), seen["message"]

        # Response never contains the key.
        assert "AIza" not in json.dumps(payload)
    finally:
        this._call_gemini = originals[0]

    print("All checks passed.")


if __name__ == "__main__":
    _run_checks()
