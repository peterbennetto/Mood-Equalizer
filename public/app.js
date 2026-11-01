"use strict";

// Mood Equalizer: the screen.
//
// Draws the sliders, the gauge and the reflection line, and asks
// /api/reflect for the line. The band, the direction and the prompt are
// worked out on the server. No Gemini key is ever in the browser.
//
// Session only: slider values, feedback, token counts and temperature
// are held in memory. Nothing is stored in the browser.

// --- Scoring (mirrors mood_logic.py: keep the two in step) --------------

const CENTRE = 5;
const SLIDER_MIN = 0;
const SLIDER_MAX = 10;
const SLIDER_STEP = 0.5;

// "calm" is the Stress slider. Its left end is "High stress" (0) and its
// right end is "Low stress" (10), so the raw value is already a calm value.
const SLIDERS = [
  { key: "energy", title: "Energy", low: "Low", high: "Wired" },
  { key: "spirits", title: "Spirits", low: "Low", high: "High" },
  { key: "calm", title: "Stress", low: "High stress", high: "Low stress" },
  { key: "control", title: "Sense of control", low: "Overwhelmed", high: "In control" },
];

const ZONE_COLOURS = { green: "#5FBF8F", amber: "#E0A94A", red: "#D9635B" };

function clamp(value) {
  return Math.max(SLIDER_MIN, Math.min(SLIDER_MAX, Number(value)));
}

function distanceFromCentre(value) {
  return Math.abs(clamp(value) - CENTRE);
}

function getZone(value) {
  const distance = distanceFromCentre(value);
  if (distance <= 1) return "green";
  if (distance <= 3) return "amber";
  return "red";
}

function zoneColour(value) {
  return ZONE_COLOURS[getZone(value)];
}

function computeScore(values) {
  const total = SLIDERS.reduce((sum, s) => sum + clamp(values[s.key]), 0);
  return Math.round((total / SLIDERS.length) * 1000) / 1000;
}

// Marker position, 0 to 100 (50 is the centre). Not rounded: it only feeds CSS.
function gaugePercent(score) {
  return (clamp(score) / SLIDER_MAX) * 100;
}

// Words for screen readers, since the numbers are not shown.
function describePosition(slider, value) {
  const distance = distanceFromCentre(value);
  if (distance < 1) return "near the middle";
  const end = value < CENTRE ? slider.low : slider.high;
  return (distance > 3 ? "strongly towards " : "leans towards ") + end;
}

// --- Page state ------------------------------------------------------------

const $ = (id) => document.getElementById(id);

const state = {
  reflection: null,   // { text, source, note, snapshot }
  feedbackDone: null,
  tokensLast: null,   // [sent, received]
  tokensIn: 0,
  tokensOut: 0,
};

const inputs = {};   // slider key -> <input>
const strips = {};   // slider key -> colour strip

function readValues() {
  const values = {};
  for (const s of SLIDERS) values[s.key] = Number(inputs[s.key].value);
  return values;
}

function snapshotOf(values) {
  return SLIDERS.map((s) => values[s.key]).join(",");
}

// --- Drawing ---------------------------------------------------------------

function buildSliders() {
  const host = $("sliders");
  for (const s of SLIDERS) {
    const wrap = document.createElement("div");
    wrap.className = "mood-slider";

    const label = document.createElement("label");
    label.htmlFor = `slider-${s.key}`;
    label.textContent = s.title;

    const input = document.createElement("input");
    input.type = "range";
    input.id = `slider-${s.key}`;
    input.min = SLIDER_MIN;
    input.max = SLIDER_MAX;
    input.step = SLIDER_STEP;
    input.value = CENTRE;
    input.addEventListener("input", render);

    const strip = document.createElement("div");
    strip.className = "mood-strip";

    const ends = document.createElement("div");
    ends.className = "mood-ends";
    const low = document.createElement("span");
    low.textContent = s.low;
    const high = document.createElement("span");
    high.textContent = s.high;
    ends.append(low, high);

    wrap.append(label, input, strip, ends);
    host.append(wrap);
    inputs[s.key] = input;
    strips[s.key] = strip;
  }
}

function render() {
  const values = readValues();
  const score = computeScore(values);
  const pct = gaugePercent(score);
  const colour = zoneColour(score);

  const fill = $("gauge-fill");
  fill.style.left = `${Math.min(50, pct)}%`;
  fill.style.width = `${Math.abs(pct - 50)}%`;
  fill.style.background = colour;
  const marker = $("gauge-marker");
  marker.style.left = `${pct}%`;
  marker.style.background = colour;

  for (const s of SLIDERS) {
    strips[s.key].style.background = zoneColour(values[s.key]);
    inputs[s.key].setAttribute("aria-valuetext", describePosition(s, values[s.key]));
  }

  renderResult(values);
}

// Only show the line while the sliders still match the reading it was for.
function renderResult(values) {
  const r = state.reflection;
  const show = r && r.snapshot === snapshotOf(values);
  $("result").hidden = !show;
  if (!show) return;

  $("reflection-text").textContent = r.text;
  const note = $("reflection-note");
  if (r.note) {
    note.textContent = r.note;
  } else if (r.source === "gemini") {
    note.textContent = "Written by Gemini.";
  } else {
    note.textContent = "";
  }
  note.hidden = !note.textContent;

  const voted = state.feedbackDone !== null;
  $("feedback-prompt").hidden = voted;
  $("feedback-buttons").hidden = voted;
  $("feedback-thanks").hidden = !voted;
}

function renderTokens() {
  const last = state.tokensLast;
  let lastText = "No clicks yet.";
  if (last) {
    lastText = last[0] === 0 && last[1] === 0
      ? "Last click: 0 (no AI tokens used)."
      : `Last click: ${last[0]} sent, ${last[1]} received.`;
  }
  $("tokens-last").textContent = lastText;
  $("tokens-total").textContent =
    `Total: ${state.tokensIn} sent, ${state.tokensOut} received, ` +
    `${state.tokensIn + state.tokensOut} overall.`;
}

// --- Actions ---------------------------------------------------------------

async function equalize() {
  const button = $("equalize");
  const status = $("status");
  const values = readValues();
  const previous = state.reflection ? state.reflection.text : null;

  button.disabled = true;
  status.textContent = "Finding a line for you...";
  try {
    const response = await fetch("/api/reflect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        values,
        temperature: Number($("temperature").value),
        avoid: previous,
      }),
      signal: AbortSignal.timeout(28000),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

    const sent = Number(data.input_tokens) || 0;
    const received = Number(data.output_tokens) || 0;
    state.tokensLast = [sent, received];
    state.tokensIn += sent;
    state.tokensOut += received;
    state.reflection = {
      text: String(data.text),
      source: String(data.source),
      note: String(data.note || ""),
      snapshot: snapshotOf(values),
    };
    state.feedbackDone = null;
    status.textContent = "";
    renderTokens();
    render();
  } catch (error) {
    status.textContent = "Could not get a line just now. Please try again.";
  } finally {
    button.disabled = false;
  }
}

function vote(kind) {
  if (!state.reflection) return;
  state.feedbackDone = kind;
  render();
}

// --- Start -----------------------------------------------------------------

buildSliders();
$("equalize").addEventListener("click", equalize);
$("fb-up").addEventListener("click", () => vote("up"));
$("fb-down").addEventListener("click", () => vote("down"));
$("temperature").addEventListener("input", () => {
  $("temperature-value").textContent = Number($("temperature").value).toFixed(1);
});
renderTokens();
render();
