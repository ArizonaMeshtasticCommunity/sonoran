"""The planner says where the power went, in sentences (#113).

The summary tiles say how many nodes were reached. They do not say WHY,
and "why" is the question somebody is actually asking when the answer
disappoints: is it the radio, the antenna, the cable, or the hill?

Measured after a real prediction -- Phoenix, 10 m mast, 60 ft of LMR-195
-- against this tree served locally:

    The radio sends 30.0 dBm.
    Its antenna adds 2.1 dB.
    The cable loses 6.66 dB at each end.
    Effective power leaving the site: 25.5 dBm.
    At the far end, 2.1 dB of antenna gain is added and 6.66 dB of
    cable is taken away, and the radio needs -134 dBm to hear it.

    ⚠ Your cable loses more (6.66 dB) than your antenna gains (2.1 dB).
      A shorter run, or a thicker cable, buys more than a bigger
      antenna would.

30 + 2.15 - 6.66 = 25.49, so the arithmetic agrees with the figures it
is explaining.

Getting that run to complete exposed a real bug in `tools/dev/
serve_local.js`: it served `.mjs` and `.wasm` as `text/plain`, so the
engine's module worker failed its import and every prediction hung
forever on "Asking the engine which terrain it needs" with nothing in
the console. Fixed there, and commented, because the symptom points
nowhere near the cause.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
PLANNER = (STATIC / "planner.js").read_text(encoding="utf-8")
SERVE = (Path(__file__).resolve().parents[2] / "tools" / "dev" / "serve_local.js").read_text(
    encoding="utf-8"
)


def _budget() -> str:
    start = PLANNER.index("function linkBudget(")
    return PLANNER[start : PLANNER.index("\nfunction writeSummary(", start)]


def test_the_budget_is_drawn_with_the_summary() -> None:
    assert "linkBudget(request, threshold)" in PLANNER, "nothing builds the budget"
    assert "class: 'link-budget'" in PLANNER, "the budget is never rendered"


def test_it_restates_the_engine_s_own_figures() -> None:
    """Nothing is recomputed, so this cannot disagree with the
    prediction it sits beside."""
    body = _budget()
    for name in ("tx_power", "tx_gain", "rx_gain", "system_loss"):
        assert f"request.{name}" in body, f"the budget does not read {name}"


def test_the_cable_line_says_it_applies_at_each_end() -> None:
    """`system_loss` is subtracted at both ends.

    Saying it once here while the arithmetic uses it twice is how a
    reader ends up believing the planner is wrong.
    """
    assert "at each end" in _budget(), (
        "the cable line does not say the loss applies per end, while the model applies it twice"
    )


def test_the_cable_warning_fires_only_when_it_is_true() -> None:
    """A note that always appears is a note nobody reads."""
    body = _budget()
    assert "loss > txGain" in body, "the cable-versus-antenna note is unconditional, or gone"


def test_the_warning_names_both_numbers_it_compares() -> None:
    """ "Your cable is lossy" is an opinion. With both figures beside it,
    the reader can check the claim."""
    body = _budget()
    assert "loss.toFixed(2)" in body and "txGain.toFixed(1)" in body


def test_no_zero_cable_line_when_there_is_no_cable() -> None:
    """A node with the antenna on the box loses nothing to coax, and a
    line saying "0.00 dB" is noise."""
    assert "if (loss > 0)" in _budget()


def test_the_local_server_serves_module_and_wasm_types() -> None:
    """The bug that hid the budget for two runs.

    Served as text/plain, the engine's worker import fails silently and
    a prediction hangs with nothing in the console to say why.
    """
    assert "'.mjs': 'application/javascript'" in SERVE
    assert "'.wasm': 'application/wasm'" in SERVE


def test_it_says_how_far_short_the_nearest_miss_was() -> None:
    """ "What would help most", answered without an engine re-run (#113).

    The tiles say how many nodes were reached. They do not say whether
    the next one was 0.5 dB away or 30, and that is the difference
    between "buy a better cable" and "pick a different hill".

    Every missed node already carries the level it would have received,
    so the shortfall is arithmetic on data the summary has in hand.

    Measured after a real prediction:

        "Nearest node you did not reach: Hoodrat, short by 0.5 dB.
         23 within 3 dB of that."

    The issue's other tip -- "raising the antenna 3 m reaches N more
    nodes" -- genuinely needs a re-run per suggestion and is not built.
    """
    start = PLANNER.index("const shortfalls = missed")
    body = PLANNER[start : start + 700]
    assert "item.level != null" in body, (
        "nodes outside the predicted area have no level, and offering "
        "them as 'nearly reached' would be a lie a decibel cannot fix"
    )
    assert "item.short > 0" in body, "nodes that were reached are counted as misses"
    assert "link-budget-near" in PLANNER, "the shortfall is computed and never shown"


def test_the_shortfall_is_sorted_so_the_nearest_is_first() -> None:
    """ "Nearest" has to mean nearest, not first in the node list."""
    start = PLANNER.index("const shortfalls = missed")
    assert ".sort((a, b) => a.short - b.short)" in PLANNER[start : start + 700]
