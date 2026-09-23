"""One "Cable loss (dB)" box, applied at both ends (#112).

`system_loss` is subtracted from the transmitted power in `erpWatts` and
again from the received level in `receivedDbm`. So a reader who types 2
into a box labelled "Cable loss (dB)" loses **4 dB** across the link.

That is defensible as "assume both ends have a similar run" and it is
what the model does. It is not what the label said.

#112 asks for it to be fixed or documented. Fixing it properly means a
separate cable run per end — a form change, not a sign change — and
halving it here would quietly alter every prediction the planner has
made so far. So the label now says "each end", the behaviour is
documented at both sites, and `radio/cables.py` holds the sourced
per-cable figures the two-ended version will need.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
PARAMS = (STATIC / "planner-params.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_it_really_is_applied_at_both_ends() -> None:
    """The premise. If this stops being true the note below is a lie."""
    assert "request.tx_gain - request.system_loss" in PARAMS
    assert "request.rx_gain - request.system_loss" in PARAMS


def test_the_label_says_which_end_it_means() -> None:
    """A box marked "Cable loss (dB)" that counts twice is a trap."""
    assert "Cable loss (dB), each end" in HTML, (
        "the planner's cable-loss field does not say it is applied per "
        "end, while the model applies it twice"
    )


def test_both_sites_are_annotated() -> None:
    """Whoever changes one has to meet the note at the other."""
    transmit = PARAMS.index("function erpWatts")
    receive = PARAMS.index("function receivedDbm")
    assert "APPLIED TWICE" in PARAMS[transmit : transmit + 1600], (
        "the transmit-end subtraction carries no note"
    )
    assert "both ends" in PARAMS[receive - 400 : receive + 300], (
        "the receive-end subtraction carries no note"
    )
