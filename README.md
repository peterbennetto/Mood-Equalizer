# Mood Equalizer

A fun mood check-in app. Move four sliders and it shows a live gauge. Click "Mood Equalize" for a short reflection line, written by Google Gemini (free tier) or taken from a pre-written bank.

You are at your best when centred.

It is a static page plus one small Python function, so it deploys to Vercel as it is.

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
- A "Settings and tokens" panel has a temperature slider and a token counter (see below).

## How the score works

- Each slider runs from 0 to 10 inside the code.
- Stress is stored as a "calm" value. Low stress is 10 and High stress is 0, so no extra inversion is needed.
- Score is the simple average of the four sliders.
- Bands: very low (under 2), low (2 to under 4), balanced (4 to 6), high (over 6 to 8), very high (over 8).

## Settings and tokens

**Temperature** controls how varied the Gemini wording is. Low is steady and repeatable. High is more varied.

- Range is 0.0 to 1.0, in steps of 0.1.
- The starting value comes from `MOOD_TEMPERATURE` (default 0.7).
- Changes apply to this browser tab only. Nothing is stored.
- It only affects lines written by Gemini.

**Token counter** shows how many tokens the last click used, and the session total.

- Tokens are the chunks of text Gemini counts.
- Figures are split into sent (input) and received (output, including Gemini's thinking).
- The numbers come from Gemini's own reply.
- Pre-written lines count as 0, because no AI call is made.
- If a call fails, it may show 0 even if Gemini counted it.
- The counter is a display only. It does not stop calls.
- Totals are held in memory and reset when the page is reloaded.

## Files

| File | Purpose |
|---|---|
| `public/index.html`, `public/style.css`, `public/app.js` | The screen. Served as static files |
| `api/reflect.py` | The Vercel function. `POST /api/reflect`. A thin HTTP shell |
| `api_client.py` | Request checks, the Gemini call, token counts, automatic fallback |
| `mood_logic.py` | Score, bands, colour zones |
| `responses.py` | 25 pre-written lines, 5 per band |
| `vercel.json` | Function timeout and security headers |
| `.python-version` | Python version for Vercel (3.12) |
| `.vercelignore` | Keeps `.env`, `venv` and `private` out of uploads |
| `dev_server.py` | Runs the app on your PC without the Vercel CLI |
| `.env.example` | Template for your settings. Copy it to `.env` |
| `private/ccscr_prompt.md` | Build spec. Local only, not in Git. The app never reads it |

No packages need installing. The app uses only the Python standard library.

The scoring maths is written twice: in `mood_logic.py` (used to pick the band on the server) and at the top of `public/app.js` (used to move the gauge live). If you change one, change the other.

## Get a free Gemini key

1. Go to https://aistudio.google.com/apikey and sign in with a Google account.
2. Create an API key. No card is needed for the free tier.
3. Keep it secret. Never put it in `.env.example`, in the page code, or in Git.

## Run on your PC

Python 3.10 or newer is assumed.

```powershell
Copy-Item .env.example .env
```

Open `.env` and replace `your-gemini-key-here` with your key. Leave it as it is to try the app with pre-written lines only. Then:

```powershell
python dev_server.py
```

Open http://localhost:3000. Stop it with Ctrl+C. After editing `.env`, stop it and start it again.

The terminal prints `[Gemini]` when a key was found, or `[pre-written lines only]` when not. On the page, a line written by Gemini says "Written by Gemini." underneath.

## Publish on Vercel

The key lives only in a Vercel Environment Variable on the server. It is never sent to the browser.

**Option A: from GitHub (easiest)**

1. Push this project to a GitHub repository. `.env`, `venv` and `private` are already ignored.
2. In Vercel, choose Add New, then Project, and import the repository.
3. Set Framework Preset to `Other`. Leave the build and output settings empty.
4. Under Environment Variables add `GEMINI_API_KEY` with your key. Optionally add `GEMINI_MODEL`, `MOOD_TEMPERATURE` and `MOOD_TIMEOUT_SECONDS`.
5. Deploy.

**Option B: from the command line**

```powershell
npm install -g vercel
vercel
vercel env add GEMINI_API_KEY
vercel --prod
```

Answer the prompts, choosing `Other` if asked for a framework. Paste the key when `vercel env add` asks, and pick Production, Preview and Development.

Environment Variables only take effect on a new deployment. After changing one, redeploy.

### Checking it worked

- Open the deployed page, move the sliders and click "Mood Equalize". A line written by Gemini says "Written by Gemini." and the token counter shows numbers above 0.
- If it says "Gemini call failed (HTTP 400)" or "(HTTP 403)", the key is wrong or not allowed. For `(HTTP 404)`, the model name in `GEMINI_MODEL` is wrong or not available to your key.
- If it says "Gemini's free limit has been reached for now", the free quota is used up. It resets daily. Lines fall back to the pre-written bank meanwhile.
- If the page shows "Could not get a line just now", open the function logs in the Vercel dashboard.

## Privacy and cost

- Only the band, the direction and word-only slider positions are sent to Gemini. No numbers and no personal text. The browser sends the slider numbers to your own server, which turns them into words.
- Slider values, feedback, token counts and temperature are held in memory in the visitor's browser tab. Nothing is stored in the browser or on the server.
- The Gemini key is read from an environment variable. No code path writes it to a file, logs it, or sends it to the browser. It is sent to Google in a request header, not in the URL.
- One click makes at most one Gemini call. There are no retries.
- Never put a real key in `.env.example`. Never share your `.env`.
- The free tier costs nothing. Google's pricing page says free-tier prompts and replies may be used to improve Google's products. Only the word descriptions above are sent, but check Google's terms (https://ai.google.dev/gemini-api/terms) before sharing the app widely.
- The free quota belongs to your Google project and is shared by every visitor. A busy or abused public link can use it up, and the app then shows pre-written lines. To limit abuse, add a rate-limit rule in Vercel's Firewall for `/api/reflect`.

## Self-checks

Each logic file has built-in checks. Run them from the project folder:

```powershell
python mood_logic.py
python responses.py
python api_client.py
```

Each should print `All checks passed.` None of them make a real Gemini call.

## Known limits

- The Gemini call has been tested against a fake reply only. The first real call will be on your machine. If `GEMINI_MODEL` (default `gemini-3.5-flash-lite`) is not available to your key, set it to another model your key can use.
- Google's docs say some newer Gemini models ignore the temperature setting. If you switch `GEMINI_MODEL` to one of them, the slider may have no visible effect.
- A simple average lets opposite extremes cancel out. For example, Energy at 0 with Spirits at 10 can read as balanced.
- Token counts can under-report when a call fails.
- If the server cannot be reached, the page shows an error. It does not fall back to pre-written lines on its own.
- Vercel's Hobby plan is for non-commercial use.
- Get a security and compliance review before any client or employer use.
