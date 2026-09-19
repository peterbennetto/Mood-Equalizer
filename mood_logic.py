"""Mood scoring logic.

Pure Python. No Streamlit, no network calls, no file writes.
Everything here can be tested on its own.
"""

# --- Constants ---------------------------------------------------------

CENTRE = 5.0          # The target midpoint
SLIDER_MIN = 0.0
SLIDER_MAX = 10.0
SLIDER_STEP = 0.5

# The four sliders, in display order.
# "calm" is the Stress slider. Its left end is "High stress" (0) and its
# right end is "Low stress" (10), so the raw value is already a calm
# value. No inversion is needed anywhere else.
SLIDERS = [
    {"key": "energy", "title": "Energy",
     "low_label": "Low", "high_label": "Wired"},
    {"key": "spirits", "title": "Spirits",
     "low_label": "Low", "high_label": "High"},
    {"key": "calm", "title": "Stress",
     "low_label": "High stress", "high_label": "Low stress"},
    {"key": "control", "title": "Sense of control",
     "low_label": "Overwhelmed", "high_label": "In control"},
]

# Band names, from the low end to the high end.
BANDS = ["very_low", "low", "balanced", "high", "very_high"]

# Which way each band's response should lean.
# lift = warmth, joy, beauty. settle = grounding, perspective, quiet.
BAND_DIRECTION = {
    "very_low": "lift",
    "low": "lift",
    "balanced": "neutral",
    "high": "settle",
    "very_high": "settle",
}

# Zone colours (used for the gauge and the slider strips).
ZONE_COLOURS = {
    "green": "#5FBF8F",
    "amber": "#E0A94A",
    "red": "#D9635B",
}


# --- Helpers -----------------------------------------------------------

def clamp(value):
    """Keep a slider value inside 0 to 10."""
    return max(SLIDER_MIN, min(SLIDER_MAX, float(value)))


def default_values():
    """All sliders start at the centre."""
    return {slider["key"]: CENTRE for slider in SLIDERS}


# --- Score, band, direction --------------------------------------------

def compute_score(values):
    """Equal-weight average of the four sliders. Returns 0 to 10."""
    keys = [slider["key"] for slider in SLIDERS]
    missing = [key for key in keys if key not in values]
    if missing:
        raise ValueError(f"Missing slider values: {missing}")
    total = sum(clamp(values[key]) for key in keys)
    return round(total / len(keys), 3)


def get_band(score):
    """Turn a 0 to 10 score into a band name.

    Edges are symmetric around 5, so 0 and 10 land in equally
    extreme bands.
    """
    score = round(clamp(score), 3)
    if score < 2:
        return "very_low"
    if score < 4:
        return "low"
    if score <= 6:
        return "balanced"
    if score <= 8:
        return "high"
    return "very_high"


def get_direction(band):
    """Return lift, settle or neutral for a band."""
    return BAND_DIRECTION[band]


# --- Colour zones ------------------------------------------------------

def distance_from_centre(value):
    """How far a value is from 5. Same for 0 and 10."""
    return abs(clamp(value) - CENTRE)


def get_zone(value):
    """Return green, amber or red based on distance from 5."""
    distance = distance_from_centre(value)
    if distance <= 1:
        return "green"
    if distance <= 3:
        return "amber"
    return "red"


def zone_colour(value):
    """Hex colour for a value's zone."""
    return ZONE_COLOURS[get_zone(value)]


def gauge_percent(score):
    """Marker position along the gauge, 0 to 100 (50 is the centre)."""
    return round(clamp(score) / SLIDER_MAX * 100, 1)


# --- Description for the API prompt ------------------------------------

def describe_positions(values):
    """Word-only description of each slider, with no numbers.

    Used later when asking an AI provider for a reflection line.
    Example: "Energy: leans towards Low".
    """
    lines = []
    for slider in SLIDERS:
        value = clamp(values[slider["key"]])
        distance = distance_from_centre(value)
        if distance < 1:
            position = "near the middle"
        else:
            end = slider["low_label"] if value < CENTRE else slider["high_label"]
            strength = "strongly towards" if distance > 3 else "leans towards"
            position = f"{strength} {end}"
        lines.append(f"{slider['title']}: {position}")
    return lines


# --- Self-check --------------------------------------------------------
# Run with:  python mood_logic.py

def _run_checks():
    # Default is dead centre.
    assert compute_score(default_values()) == 5.0
    assert get_band(5.0) == "balanced"

    # Equal weighting: one slider moved by 4 shifts the score by 1.
    values = default_values()
    values["energy"] = 9.0
    assert compute_score(values) == 6.0

    # Extremes.
    assert compute_score({k: 0 for k in default_values()}) == 0.0
    assert compute_score({k: 10 for k in default_values()}) == 10.0

    # Band edges, and symmetry around 5.
    assert get_band(0) == "very_low" and get_band(10) == "very_high"
    assert get_band(1.99) == "very_low" and get_band(8.01) == "very_high"
    assert get_band(2) == "low" and get_band(8) == "high"
    assert get_band(3.99) == "low" and get_band(6.01) == "high"
    assert get_band(4) == "balanced" and get_band(6) == "balanced"
    for offset in (0, 0.5, 1, 1.99, 2, 3, 3.99, 4, 5):
        low_band = get_band(CENTRE - offset)
        high_band = get_band(CENTRE + offset)
        assert BANDS.index(low_band) + BANDS.index(high_band) == 4, offset

    # Directions.
    assert get_direction("very_low") == "lift"
    assert get_direction("low") == "lift"
    assert get_direction("balanced") == "neutral"
    assert get_direction("high") == "settle"
    assert get_direction("very_high") == "settle"

    # Zones: 0 and 10 are equally red, 5 is green.
    assert get_zone(5) == "green" and get_zone(4) == "green" and get_zone(6) == "green"
    assert get_zone(3) == "amber" and get_zone(7) == "amber"
    assert get_zone(1.5) == "red" and get_zone(9) == "red"
    assert get_zone(0) == get_zone(10) == "red"

    # Gauge position.
    assert gauge_percent(0) == 0 and gauge_percent(5) == 50 and gauge_percent(10) == 100

    # Missing key is caught.
    try:
        compute_score({"energy": 5})
    except ValueError:
        pass
    else:
        raise AssertionError("Missing keys should raise ValueError")

    # Descriptions never contain digits.
    text = " ".join(describe_positions(default_values()))
    assert not any(ch.isdigit() for ch in text)

    print("All checks passed.")


if __name__ == "__main__":
    _run_checks()