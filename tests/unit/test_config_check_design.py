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


def _css_without_comments() -> str:
    """`app.css` with `/* ... */` removed.

    An assertion that means to read declarations must not be able to
    answer from prose about them. A comment naming a selector has
    produced a false result in this repository six times.
    """
    return re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)


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


# --- the report view (#202.1, #202.3) ------------------------------


def test_the_input_half_can_be_hidden() -> None:
    """The report replaces the input, it does not stack under it.

    Walked before this: the result began about 660 px down, under three
    cards inviting the reader to load a config they had already loaded.
    Measured after, on the rendered page: **258 px**.
    """
    assert "data-config-input" in INDEX, "the input half has no wrapper to hide"
    assert "data-config-loaded" in INDEX, "there is no strip to show in its place"
    code = _js_code()
    assert "function showReportView(page, showing)" in code
    assert "showReportView(page, true)" in code, "drawResult never switches to the report"


def test_there_is_a_way_back() -> None:
    """Hiding the input must not trap the reader.

    The report and the loaded config stay in `state`, so this only
    changes which half is on screen. Verified on the rendered page: the
    round trip works and the region choice survives it, which matters
    because that choice was made in the half that gets hidden.
    """
    assert "data-config-reload" in INDEX
    code = _js_code()
    assert "showReportView(page, false)" in code


def test_the_strip_names_the_file_from_the_right_field() -> None:
    """`state.fileName`, not `state.filename`.

    The first draft used the latter, which is not a field of `state`.
    It would have silently read "Checking a config" for every file ever
    loaded -- a fallback doing the work of a bug.
    """
    code = _js_code()
    assert "state.fileName" in code
    assert "state.filename" not in code, "a field that does not exist is being read"


def test_the_page_is_one_column() -> None:
    """Five widths, measured: 1881 / 1600 / 683 / 523 / 388.

    The cause was not CSS. `.page-head` -- a wrapping flex row with
    `justify-content: space-between` -- wrapped all nine of this page's
    blocks, so each one was a flex item sizing to its own content.
    """
    css = _css_without_comments()
    assert '.page.active[data-page="config"] {' in css, (
        "the column is not set on the active page; a plain "
        '[data-page="config"] loses to `.page.active` and does nothing'
    )
    block = css[css.index('.page.active[data-page="config"] {') :]
    rule = block[: block.index("}")]
    assert "flex" in rule
    assert "gap:" in rule


def test_page_head_holds_only_the_heading() -> None:
    """The structural half of the fix, and the actual cause.

    If `page-head` ever swallows the page again, every block becomes a
    flex item of a `space-between` row and the five widths come back.
    """
    section = INDEX[INDEX.index('<section class="page" data-page="config">') :]
    head = section.index('<div class="page-head">')
    notice = section.index("data-config-notice")
    # The head must close before the first block after it.
    closes = section[head:notice].count("</div>")
    opens = section[head:notice].count("<div")
    assert closes >= opens, (
        "page-head does not close before the config page's content, so "
        "every block is a flex item of a space-between row"
    )


def test_no_inline_margin_fights_the_column() -> None:
    """An inline style beats every selector.

    Two blocks carried `style="margin-top:1rem"`, which survived
    `margin-block: 0` and left a 32 px gap among 16s. Measured, not
    reasoned about -- the stylesheet looked correct.
    """
    section = INDEX[INDEX.index('<section class="page" data-page="config">') :]
    section = section[: section.index("</section>")]
    assert 'class="grid two" style="margin-top' not in section
    assert 'data-config-source style="margin-top' not in section
