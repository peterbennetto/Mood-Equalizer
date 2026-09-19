"""Mood Equalizer: the Streamlit screen.

Draws the sliders, the gauge and the reflection line.
Scoring lives in mood_logic.py, lines in responses.py and API calls
in api_client.py.

Session only: slider values, feedback, token counts and sidebar
settings are held in memory. Nothing is written to disk, and no API
key is ever saved.
"""

import html

import streamlit as st

from api_client import (
    DEFAULT_OLLAMA_HOST,
    PROVIDERS,
    apply_overrides,
    generate_reflection,
    load_settings,
    provider_status,
)
from mood_logic import (
    CENTRE,
    SLIDER_MAX,
    SLIDER_MIN,
    SLIDER_STEP,
    SLIDERS,
    compute_score,
    gauge_percent,
    get_band,
    get_direction,
    zone_colour,
)

# Must be the first Streamlit call.
st.set_page_config(page_title="Mood Equalizer", page_icon="\u2696", layout="centered")

# --- Styling -----------------------------------------------------------
# Hides the raw numbers on the mood sliders. This relies on Streamlit's
# internal data-testid names, so it is best-effort. Several possible
# names are listed because they differ between Streamlit versions.
# The last two rules put the numbers back inside the sidebar, so the
# temperature slider stays readable.

CSS = """
<style>
[data-testid="stSliderThumbValue"],
[data-testid="stThumbValue"] {
    visibility: hidden !important;
}
[data-testid="stTickBar"],
[data-testid="stSliderTickBar"],
[data-testid="stTickBarMin"],
[data-testid="stTickBarMax"],
[data-testid="stSliderTickBarMin"],
[data-testid="stSliderTickBarMax"] {
    display: none !important;
}
[data-testid="stSidebar"] [data-testid="stSliderThumbValue"],
[data-testid="stSidebar"] [data-testid="stThumbValue"] {
    visibility: visible !important;
}
[data-testid="stSidebar"] [data-testid="stTickBar"],
[data-testid="stSidebar"] [data-testid="stSliderTickBar"],
[data-testid="stSidebar"] [data-testid="stTickBarMin"],
[data-testid="stSidebar"] [data-testid="stTickBarMax"],
[data-testid="stSidebar"] [data-testid="stSliderTickBarMin"],
[data-testid="stSidebar"] [data-testid="stSliderTickBarMax"] {
    display: flex !important;
}
.mood-strip {
    height: 5px;
    border-radius: 3px;
    margin: 0 0 4px 0;
}
.mood-ends {
    display: flex;
    justify-content: space-between;
    font-size: 0.8rem;
    opacity: 0.75;
    margin-bottom: 18px;
}
.gauge-track {
    position: relative;
    height: 14px;
    border-radius: 7px;
    background: #2A3242;
    margin: 26px 0 8px 0;
}
.gauge-fill {
    position: absolute;
    top: 0;
    height: 14px;
    border-radius: 7px;
    opacity: 0.85;
}
.gauge-centre {
    position: absolute;
    left: 50%;
    top: -5px;
    width: 2px;
    height: 24px;
    background: #E6E9EE;
    opacity: 0.5;
}
.gauge-marker {
    position: absolute;
    top: 50%;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 3px solid #14181F;
    transform: translate(-50%, -50%);
}
.gauge-labels {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    font-size: 0.8rem;
    opacity: 0.75;
    margin-bottom: 22px;
}
.reflection {
    background: #1E2530;
    border-left: 4px solid #7FB5A8;
    border-radius: 6px;
    padding: 16px 18px;
    margin: 14px 0 6px 0;
    font-size: 1.1rem;
    line-height: 1.5;
}
</style>
"""


# --- Drawing helpers ---------------------------------------------------

def gauge_html(score):
    """Centre-anchored gauge. The marker moves from the middle to either edge."""
    pct = gauge_percent(score)
    colour = zone_colour(score)
    left = min(50.0, pct)
    width = abs(pct - 50.0)
    return (
        '<div class="gauge-track">'
        f'<div class="gauge-fill" style="left:{left}%;width:{width}%;background:{colour};"></div>'
        '<div class="gauge-centre"></div>'
        f'<div class="gauge-marker" style="left:{pct}%;background:{colour};"></div>'
        "</div>"
        '<div class="gauge-labels">'
        "<span>Lower</span>"
        '<span style="text-align:center;">Centred</span>'
        '<span style="text-align:right;">Higher</span>'
        "</div>"
    )


def render_slider(slider):
    """One slider, then its colour strip and word labels. Returns the value."""
    value = st.slider(
        slider["title"],
        min_value=SLIDER_MIN,
        max_value=SLIDER_MAX,
        value=CENTRE,
        step=SLIDER_STEP,
        key=f"slider_{slider['key']}",
    )
    st.markdown(
        f'<div class="mood-strip" style="background:{zone_colour(value)};"></div>'
        '<div class="mood-ends">'
        f"<span>{html.escape(slider['low_label'])}</span>"
        f"<span>{html.escape(slider['high_label'])}</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    return value


# --- Sidebar (session only) --------------------------------------------

def sidebar_overrides(base):
    """Optional overrides. Held in session memory only. Never saved."""
    st.sidebar.header("Session settings")
    st.sidebar.caption(
        "Optional. Kept in memory for this browser session only. "
        "Never written to .env or any file. Leave blank to use .env."
    )
    choice = st.sidebar.selectbox(
        "Provider", ["From .env"] + list(PROVIDERS), key="ov_provider"
    )
    provider = "" if choice == "From .env" else choice
    target = provider or base["provider"]

    api_key = st.sidebar.text_input(
        "API key (Anthropic or OpenAI)",
        type="password",
        key="ov_key",
        help="Applies to the provider selected above. Not needed for Ollama.",
    )
    model_hint = base.get(f"{target}_model", "") if target != "none" else ""
    model = st.sidebar.text_input("Model", key="ov_model", placeholder=model_hint)
    host = st.sidebar.text_input(
        "Ollama host", key="ov_host", placeholder=DEFAULT_OLLAMA_HOST
    )

    # Temperature: only used by AI providers, so it is greyed out for "none".
    st.sidebar.divider()
    ai_active = target != "none"
    temperature = st.sidebar.slider(
        "Temperature",
        min_value=0.0,
        max_value=1.0,
        value=round(float(base["temperature"]), 1),
        step=0.1,
        key="ov_temp",
        disabled=not ai_active,
        help="Low is steady and repeatable. High is more varied wording.",
    )
    if ai_active:
        st.sidebar.caption(
            f"Temperature now: {temperature:.1f}. Low is steady, high is more varied."
        )
    else:
        st.sidebar.caption("Temperature only applies to Anthropic, OpenAI and Ollama.")

    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "host": host,
        "temperature": temperature if ai_active else None,
    }


# --- Token counter (session only) --------------------------------------

def record_tokens(result):
    """Add one reflection's token usage to the session totals."""
    state = st.session_state
    state["tokens_last"] = (result.input_tokens, result.output_tokens)
    state["tokens_in_total"] = state.get("tokens_in_total", 0) + result.input_tokens
    state["tokens_out_total"] = state.get("tokens_out_total", 0) + result.output_tokens


def render_token_counter(slot):
    """Fill the sidebar placeholder with the last and total token counts."""
    state = st.session_state
    last = state.get("tokens_last")
    total_in = state.get("tokens_in_total", 0)
    total_out = state.get("tokens_out_total", 0)

    with slot.container():
        st.divider()
        st.markdown("**Tokens (this session)**")
        if last is None:
            st.caption("No clicks yet.")
        elif last == (0, 0):
            st.caption("Last click: 0 (no AI tokens used).")
        else:
            st.caption(f"Last click: {last[0]} sent, {last[1]} received.")
        st.caption(
            f"Total: {total_in} sent, {total_out} received, "
            f"{total_in + total_out} overall."
        )
        st.caption(
            "Counts come from the provider's reply. Pre-written lines count as 0. "
            "A failed call may show 0 even if the provider billed it."
        )


# --- Feedback ----------------------------------------------------------

def record_feedback(vote):
    """Store a thumbs vote in session memory only."""
    reflection = st.session_state.get("reflection")
    if not reflection:
        return
    log = st.session_state.setdefault("feedback_log", [])
    log.append(
        {"band": reflection["band"], "source": reflection["source"], "vote": vote}
    )
    st.session_state["feedback_done"] = vote


# --- Main screen -------------------------------------------------------

def main():
    st.markdown(CSS, unsafe_allow_html=True)

    st.title("Mood Equalizer")
    st.caption("You are at your best when centred.")
    st.caption("Move the sliders to show where you are, and it will help you centre.")

    base = load_settings()
    settings = apply_overrides(base, sidebar_overrides(base))
    ready, status_message = provider_status(settings)
    st.sidebar.caption(f"Active provider: {settings['provider']}")
    if not ready:
        st.sidebar.warning(status_message)

    # Reserve the counter's spot now. It is filled after the button is
    # handled, so the numbers are up to date on the same click.
    counter_slot = st.sidebar.empty()

    # The gauge sits above the sliders but needs their values,
    # so reserve its spot now and fill it in afterwards.
    gauge_slot = st.empty()

    values = {slider["key"]: render_slider(slider) for slider in SLIDERS}
    score = compute_score(values)
    band = get_band(score)
    direction = get_direction(band)
    gauge_slot.markdown(gauge_html(score), unsafe_allow_html=True)

    snapshot = tuple(values[slider["key"]] for slider in SLIDERS)

    if st.button("Mood Equalize", type="primary"):
        previous = (st.session_state.get("reflection") or {}).get("text")
        with st.spinner("Finding a line for you..."):
            result = generate_reflection(
                band, direction, values, settings, avoid=previous
            )
        record_tokens(result)
        st.session_state["reflection"] = {
            "text": result.text,
            "source": result.source,
            "note": result.note,
            "band": band,
            "snapshot": snapshot,
        }
        st.session_state["feedback_done"] = None

    render_token_counter(counter_slot)

    reflection = st.session_state.get("reflection")
    # Only show the line while the sliders still match the reading it was for.
    if reflection and reflection["snapshot"] == snapshot:
        st.markdown(
            f'<div class="reflection">{html.escape(reflection["text"])}</div>',
            unsafe_allow_html=True,
        )
        if reflection["note"]:
            st.caption(reflection["note"])
        elif reflection["source"] != "bank":
            st.caption(f"Written by {reflection['source']}.")

        if st.session_state.get("feedback_done") is None:
            st.caption("Was this helpful?")
            col_up, col_down, _spacer = st.columns([1, 1, 6])
            col_up.button("\U0001F44D", key="fb_up", on_click=record_feedback, args=("up",))
            col_down.button("\U0001F44E", key="fb_down", on_click=record_feedback, args=("down",))
        else:
            st.caption("Thanks for the feedback.")


main()