"""Pre-written reflection lines.

25 lines: 5 for each band. Used when no AI provider is set, and as
the fallback whenever an API call fails.
No Streamlit, no network calls, no file writes.
"""

import random

from mood_logic import BANDS

# One direction-matched set of 5 per band.
# very_low: lift (warmth, joy, beauty) plus a brief nod to real support.
# low: lift.
# balanced: neutral and affirming.
# high: settle (grounding, perspective, quiet).
# very_high: settle plus a brief nod to pausing before acting.
RESPONSE_BANK = {
    "very_low": [
        "Low days happen. Try something small and warm today, "
        "like a hot drink or a song you love.",
        "There is beauty close by, even now. A patch of sunlight "
        "or a favourite colour can be enough to start.",
        "You do not have to carry this alone. Talking to someone "
        "you trust can make a real difference.",
        "Be gentle with yourself for a while. A kind word, a soft "
        "blanket and something lovely to look at all help.",
        "A little joy counts, however small. If it stays heavy, "
        "reaching out for support is a good move.",
    ],
    "low": [
        "A bit of warmth goes a long way. Put on a song that "
        "makes you smile.",
        "Something lovely is waiting for you today. Look for a "
        "bright colour, a good smell or a friendly face.",
        "Small joys add up. Step outside, notice the sky, and let "
        "it lift you a little.",
        "Give yourself something you enjoy, even for ten minutes.",
        "A little light can shift a whole afternoon. Find one "
        "thing today that feels good.",
    ],
    "balanced": [
        "You are sitting close to centre. This is a good place "
        "to be.",
        "Steady and level. Nicely done.",
        "Everything feels well matched right now. Enjoy it.",
        "This is what centred looks like. Carry it with you.",
        "Clear and even. You are right where you want to be.",
    ],
    "high": [
        "There is a lot of movement in you right now. A quiet "
        "minute by a window can help it settle.",
        "Zoom out for a moment. Most things look smaller and "
        "clearer from a distance.",
        "Slow the pace a little. One steady breath at a time is "
        "plenty.",
        "Room for quiet is a gift. Find a still corner and let "
        "things arrange themselves.",
        "You have a lot to work with. Ground it with a walk, a "
        "glass of water or a slow stretch.",
    ],
    "very_high": [
        "Things are running fast. Before you act on anything big, "
        "take a pause and let it settle.",
        "This is a good moment to slow right down. Big decisions "
        "can wait until things are quieter.",
        "Plenty is happening inside you. Pause, take a slow "
        "breath, and look at the wider view.",
        "Let the quiet in for a while. Anything important will "
        "still be there after a pause.",
        "Ground yourself first. A slow walk or some stillness, "
        "then choose your next step.",
    ],
}


def get_response(band, avoid=None):
    """Return one random line for a band.

    If `avoid` is given (the line shown last time), it is skipped
    so the same line does not appear twice in a row.
    """
    if band not in RESPONSE_BANK:
        raise ValueError(f"Unknown band: {band}")
    options = [line for line in RESPONSE_BANK[band] if line != avoid]
    if not options:
        options = RESPONSE_BANK[band]
    return random.choice(options)


# --- Self-check --------------------------------------------------------
# Run with:  python responses.py

def _run_checks():
    # Structure: every band present, 5 lines each, 25 in total, no repeats.
    assert set(RESPONSE_BANK) == set(BANDS)
    for band in BANDS:
        assert len(RESPONSE_BANK[band]) == 5, band
    all_lines = [line for band in BANDS for line in RESPONSE_BANK[band]]
    assert len(all_lines) == 25
    assert len(set(all_lines)) == 25

    # House style: no digits, no em-dashes or en-dashes.
    for line in all_lines:
        assert not any(ch.isdigit() for ch in line), line
        assert "\u2014" not in line and "\u2013" not in line, line

    # Tone: no scolding words, no clinical words.
    banned = [
        "should", "must", "stop ", "wrong", "lazy", "stupid",
        "calm down", "overreact", "diagnos", "disorder", "depress",
        "anxiety", "anxious", "therapy", "medic", "symptom",
    ]
    for line in all_lines:
        for word in banned:
            assert word not in line.lower(), (word, line)

    # Support nod only in very_low. Pause nod only in very_high.
    support_words = ["alone", "trust", "reaching out", "support"]
    for band in BANDS:
        text = " ".join(RESPONSE_BANK[band]).lower()
        has_support = any(word in text for word in support_words)
        has_pause = "pause" in text
        assert has_support == (band == "very_low"), band
        assert has_pause == (band == "very_high"), band

    # get_response returns a line from the right band and honours avoid.
    for band in BANDS:
        for _ in range(50):
            assert get_response(band) in RESPONSE_BANK[band]
        first = RESPONSE_BANK[band][0]
        for _ in range(50):
            assert get_response(band, avoid=first) != first

    # Unknown band is caught.
    try:
        get_response("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown band should raise ValueError")

    print("All checks passed.")


if __name__ == "__main__":
    _run_checks()