"""The Config check page's layout and wording (#202).

Walked on the running instance at 2200x889: the report started about
**660 px down**, under three cards asking the reader to load a config
they had already loaded, while the two buttons that finish the job sat
at the top right, away from the result they belong to.

This covers the parts that are layout and vocabulary. Every feature
#115 lists is untouched.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CONFIG_JS = (STATIC / "config-check.js").read_text(encoding="utf-8")


def _js_code() -> str:
    """`config-check.js` with comments removed.

    Source-text assertions in this repository have answered from a
    comment rather than from code five times in one session, including
    one caused by the comment written to explain the rule being checked.
    """
    text = re.sub(r"/\*.*?\*/", "", CONFIG_JS, flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def test_the_comment_stripper_works() -> None:
    """Positive control."""
    code = _js_code()
    assert "const CATEGORY_ICONS" in code
    assert "an early draft of this mapping used names" not in code


# --- the icons -----------------------------------------------------


def test_every_icon_the_page_asks_for_exists_in_the_sprite() -> None:
    """The control that matters most here.

    A `<use href="#i-nope">` renders **nothing**. It does not throw and
    it does not warn -- it looks like a missing icon, which looks like a
    styling problem rather than a typo. An early draft of the mapping
    used `i-radio`, `i-device`, `i-shield` and `i-check`, none of which
    exist in this sprite, and every other test here would still have
    passed.
    """
    available = set(re.findall(r'symbol id="([^"]+)"', INDEX))
    assert available, "no sprite symbols found; this control is checking nothing"
    used = set(re.findall(r"'(i-[a-z-]+)'", _js_code()))
    assert used, "the page asks for no icons at all"
    missing = used - available
    assert not missing, f"config-check.js references icons that do not exist: {sorted(missing)}"


def test_the_emoji_headings_are_gone() -> None:
    """📡 📢 🌐 💻 💾 came from the vendored checker's `icon:` field.

    Nothing else on this dashboard is drawn that way.
    """
    code = _js_code()
    assert "category.icon" not in code, "the checker's emoji is still printed"


def test_the_vendored_checker_is_not_edited() -> None:
    """The mapping lives in our file, so the upstream pin stays intact.

    Editing the vendored copy would break `PROVENANCE.md` and the
    `check_config_checker_pin.sh` guard, and would have to be redone on
    every upstream update.
    """
    vendor = STATIC / "vendor" / "config-checker" / "js" / "checker.js"
    assert vendor.exists()
    assert "i-rf" not in vendor.read_text(encoding="utf-8"), (
        "our icons leaked into the vendored file"
    )


def test_an_unmapped_category_falls_back_to_a_real_icon() -> None:
    """A new upstream category must degrade quietly, not to an emoji."""
    code = _js_code()
    assert "const FALLBACK_ICON = 'i-config';" in code
    available = set(re.findall(r'symbol id="([^"]+)"', INDEX))
    assert "i-config" in available


# --- the wording ---------------------------------------------------


def test_the_outcome_words_match_the_rest_of_the_site() -> None:
    """FIX THIS / PASS in capitals, beside a health checklist that says
    Good and Needs fixing, is two vocabularies for one kind of list."""
    code = _js_code()
    assert "pass: 'Good'" in code
    assert "fail: 'Needs fixing'" in code


def test_warn_and_info_keep_words_of_their_own() -> None:
    """They are NOT "Can't tell yet", and must not be folded into it.

    That phrase means the evidence is missing. These two mean "we
    looked, and it is worth your attention" -- which is what the score
    row above already calls "Worth a look". Making the pages match by
    saying something slightly untrue is the wrong trade.
    """
    code = _js_code()
    assert "warn: 'Worth a look'" in code
    assert "Can't tell yet" not in code


# --- the layout ----------------------------------------------------


def test_the_optional_panel_and_downloads_follow_the_report() -> None:
    """They only ever act on a loaded config.

    Before this they came before step 1, so a reader met a panel of
    values to change before loading anything, and the two buttons that
    finish the job sat at the top right away from the result.
    """
    result = INDEX.index("data-config-result")
    extras = INDEX.index("data-config-extras")
    exports = INDEX.index("data-config-exports")
    assert result < extras, "the Optional panel still comes before the report"
    assert result < exports, "the download buttons still come before the report"


def test_the_order_is_in_the_markup_not_in_css() -> None:
    """Visual order that disagrees with focus order fails WCAG 2.4.3.

    `order:` on a flex container would have moved these visually and
    left a keyboard user tabbing through them in the old sequence.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for selector in ("[data-config-extras]", "[data-config-exports]"):
        if selector in css:
            block = css[css.index(selector) :]
            rule = block[: block.index("}")]
            assert "order:" not in rule, f"{selector} is reordered in CSS, not in the DOM"
