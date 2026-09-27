"""The phone header is a bar, and the theme control is a button (#91).

Measured on a 390x844 phone, on the dashboard's first load:

    before   brand 44, menu 48, status 19, theme 57
             page heading began at 249 px -- 30% of the viewport
    after    two compact rows, heading at 129 px

The theme control was a 151x44 labelled `<select>` offering a
three-way choice most people make once. It is a 44x44 button now that
cycles system -> light -> dark, verified by clicking through all three
and by Enter.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def test_the_theme_control_says_which_state_it_is_in() -> None:
    """The requirement outlived the control it was written for.

    A cycling icon button in the menu carried its state in an
    `aria-label`, because `aria-pressed` would be wrong for three states
    and an icon alone says nothing to a screen reader.

    The control moved to the settings page on 2026-09-26 and became three
    named options, which says the state in a stronger way: the chosen one
    carries `aria-checked` and every option is a word rather than a glyph.
    The claim is the same -- a reader is TOLD the state rather than having
    to infer it -- so it is asserted on the new control.
    """
    assert 'data-setting="theme"' in INDEX, "the theme control is not on the settings page"
    start = INDEX.index('data-setting="theme"')
    group = INDEX[INDEX.rindex("<div", 0, start) : INDEX.index("</div>", start)]
    assert 'role="radiogroup"' in group, "the theme options are not a radio group"
    assert "aria-label" in group, "the group does not name what it changes"
    # `aria-pressed` would still be wrong: three states, not on/off.
    assert "aria-pressed" not in group

    code = APP[APP.index("function drawSettingChoice") :]
    code = code[: code.index("\nfunction ")]
    assert "aria-checked" in code, "nothing says which option is chosen"


def test_the_theme_keeps_all_three_states() -> None:
    """Following the system is the default and must stay reachable.

    A two-way toggle would make somebody whose operating system is set
    to light say so again here.
    """
    # Read from the STORE now, which is where the three live since the
    # cycle button was replaced by a choice. `preset.js`'s sibling holds
    # them as the field's allowed values, so an option the store would
    # refuse cannot be offered and a missing one cannot be chosen.
    settings = (STATIC / "settings.js").read_text(encoding="utf-8")
    start = settings.index("theme: { values: [")
    values = settings[start : start + 120]
    for mode in ("system", "light", "dark"):
        assert f"'{mode}'" in values, f"the theme setting lost {mode}"
    assert "fallback: 'system'" in values, (
        "following the system is no longer the default, so a reader whose "
        "device is set to light would have to say so again here"
    )


def test_each_state_has_its_own_words() -> None:
    """Three names, one per state, or two of the three are unlabelled.

    The old button carried them in `aria-label` because it showed only an
    icon. The settings page shows the words themselves, which is why
    "Follow my device" reads better there than "Theme: following the
    system" did on a button.
    """
    start = APP.index("const SETTING_WORDS = {")
    words = APP[start : APP.index("};", start)]
    theme = words[words.index("theme:") :]
    for state in ("system", "light", "dark"):
        assert f"{state}:" in theme, f"no words for the {state} option"
    assert "Follow my device" in theme, "the system option does not say what it follows"


def test_the_phone_layout_is_a_bar_not_a_stack() -> None:
    """Four full-width blocks became two compact rows."""
    # Two blocks open with this query. Find ours by the note above it.
    start = CSS.index("One app bar at phone width")
    block = CSS[start : start + 1800]
    assert "flex-direction: row" in block, "the sidebar still stacks at phone width"
    assert ".brand-text { display: none" in block, (
        "the wordmark still takes a row of its own; it is the widest "
        "thing in the bar and the heading below already names the page"
    )


def test_the_settings_options_are_big_enough_for_a_thumb() -> None:
    """WCAG 2.2 SC 2.5.8 is 24x24 CSS px; a finger wants more.

    The claim moved with the control. `.settings-option` has vertical
    padding plus the line box, which clears 24 px, and the e2e's "no form
    control invites the iOS zoom" journey holds the font size separately.
    Asserted because a squeezed row is the easy way to lose it.
    """
    start = CSS.index(".settings-option {")
    rule = CSS[start : CSS.index("}", start)]
    found = re.search(r"padding:\s*\.(\d+)rem", rule)
    assert found, f"no vertical padding on the option: {rule!r}"
    # .45rem top and bottom plus a ~1.2rem line box is over 24px at a
    # 16px root. Asserted as a floor rather than a computed height,
    # because the line box depends on the font.
    assert int(found.group(1)) >= 4, f"padding is only .{found.group(1)}rem"
    assert "font-size: .85rem" in rule, "the option text shrank below the tap-target assumption"
