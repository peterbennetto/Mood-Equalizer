# Mood Equalizer

A fun mood check-in app. Move four sliders and it shows a live gauge. Click "Mood Equalize" for a short reflection line.

You are at your best when centred.

## What it does

- Four sliders: Energy, Spirits, Stress and Sense of control.
- No numbers are shown on them. Only word labels at each end.
- All four sliders count equally. The result is one live score.
- 5 is the centre. Both ends (0 and 10) are equally off-centre.
- A gauge shows where you are. It runs from the middle to either edge.
  Green is near the centre, amber is further out, red is at the extremes.
- Each slider has a thin colour strip that follows the same logic.
- "Mood Equalize" shows one reflection line. Below centre it leans towards warmth, joy and beauty. Above centre it leans towards grounding, perspective and quiet.
- Thumbs up and thumbs down feedback is kept for the session only.
- The sidebar has a temperature slider and a token counter (see below).

## How the score works

- Each slider runs from 0 to 10 inside the code.
- Stress is stored as a "calm" value. Low stress is 10 and High stress is 0, so no extra inversion is needed.
- Score is the simple average of the four sliders.
- Bands: very low (under 2), low (2 to under 4), balanced (4 to 6), high (over 6 to 8), very high (over 8).

## Sidebar: temperature and tokens

**Temperature** controls how varied the AI wording is. Low is steady and repeatable. High is more varied.

- Range is 0.0 to 1.0, in steps of 0.1.
- It starts at the `MOOD_TEMPERATURE` value in `.env` (default 0.7).
- It applies to this browser session only. It is never written to `.env` or any file.
- It only affects Anthropic, OpenAI and Ollama. With provider `none` it is greyed out.

**Token counter** shows how many tokens the last click used, and the session total.

- Tokens are the chunks of text an AI provider counts and bills for.
- Figures are split into sent (input) and received (output).
- The numbers come from the provider's own reply.
- Pre-written lines count as 0, because no AI call is made.
- If a call fails, it may show 0 even if the provider billed it.
- The counter is a display only. It does not stop calls.
- Totals are held in memory and reset when the browser session ends.

## Files

| File | Purpose |
|---|---|
| `app.py` | The screen |
| `mood_logic.py` | Score, bands, colour zones |
| `responses.py` | 25 pre-written lines, 5 per band |
| `api_client.py` | Optional AI provider calls, token counts, automatic fallback |
| `.env.example` | Template for your settings. Copy it to `.env` |
| `.streamlit/config.toml` | Dark theme |
| `requirements.txt` | Python packages needed |
| `private/ccscr_prompt.md` | Build spec. Local only, not in Git. The app never reads it |

## Setup (Windows, VS Code)

Python 3.10 or newer is assumed.

1. Open the `Mood Equalizer` folder in VS Code.
2. Open a terminal with Ctrl+` and create a virtual environment:

```powershell
python -m venv venv
```

3. Activate it:

```powershell
venv\Scripts\Activate.ps1
```

If PowerShell blocks this, run the next line once, then activate again.
It only affects the current terminal window.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

4. Install the packages:

```powershell
pip install -r requirements.txt
```

5. Create your settings file:

```powershell
Copy-Item .env.example .env
```

6. The default provider is `none`. The app runs with no key and uses the pre-written lines. Edit `.env` only if you want an AI provider.

## Run

```powershell
streamlit run app.py
```

The app opens in your browser. Stop it with Ctrl+C in the terminal.
After editing `.env`, stop the app and start it again.

## Choosing a provider

Set `MOOD_PROVIDER` in `.env` to one of:

- `none`: pre-written lines only. No key needed.
- `anthropic`: also set `ANTHROPIC_API_KEY`.
- `openai`: also set `OPENAI_API_KEY`.
- `ollama`: runs a model on your own PC. No key needed.

For Ollama, install it, then download the model once:

```powershell
ollama pull qwen3:4b
```

The first call can be slow while the model loads. If it falls back to a pre-written line, raise `MOOD_TIMEOUT_SECONDS` in `.env` to 60.

The sidebar can override provider, key, model, host and temperature for the current browser session only. Nothing entered there is saved.

If any provider call fails, the app shows a pre-written line and a short note.

## Privacy and cost

- Only the band, the direction and word-only slider positions are sent to a provider. No numbers and no personal text.
- Slider values, feedback, token counts and sidebar settings are held in memory only. Nothing is written to disk.
- No code path writes an API key to a file.
- One click makes at most one API call. Replies are capped at 200 tokens. There are no retries.
- Never put a real key in `.env.example`. Never share your `.env`.
- Ollama runs on your PC and costs nothing. Anthropic and OpenAI bill per token.

## Self-checks

Each logic file has built-in checks. Run them from the project folder:

```powershell
python mood_logic.py
python responses.py
python api_client.py
```

Each should print `All checks passed.`

## Known limits

- Hiding the slider numbers uses Streamlit's internal element names. It is best-effort. If numbers reappear on the mood sliders after a Streamlit upgrade, the CSS in `app.py` needs updating.
- The temperature slider is meant to show its number. If it does not, its caption still states the value.
- A simple average lets opposite extremes cancel out. For example, Energy at 0 with Spirits at 10 can read as balanced.
- Some newer AI models may reject the temperature or token settings. The app then falls back to a pre-written line.
- Token counts can under-report when a call fails.
- Ollama does not work on a hosted copy of the app. It falls back to the pre-written lines.
- Get a security and compliance review before any client or employer use.