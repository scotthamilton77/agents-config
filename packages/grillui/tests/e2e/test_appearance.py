"""How the board's overlays, options and composers look, read off computed style.

The human runs the board in a light palette and reads it for hours, so a dark
overlay flashing over it on every hover is the screen they asked not to have.
The numbers here are a proxy for their eye rather than the ruling itself: a
light card is one whose background is bright, whose text still reads on it, and
which stands apart from the page it floats over. Passing them does not settle
whether a person would call the card light; the screenshots a reviewer takes do.

The rest is layout a layout engine answers. Whether the recommended option is
filled, whether its caption sits inside its border, and whether the send hint
sits under the box or between the box and its button are all things the source
could say one way while the browser draws them another.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from conftest import BOARD_TIMEOUT, decision, handoff, option

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness import Session
    from playwright.sync_api import Locator, Page

BUYS = "Every answer ever given stays readable."
COSTS = "The session directory grows without bound."
FORCES = "Compaction has to be designed before launch."

PLAN = [
    decision(
        "d1",
        "Which storage?",
        options=[
            {**option("a", "Append-only log"), "pcr": [BUYS, COSTS, FORCES]},
            option("b", "Table"),
            option("c", "Both"),
        ],
    ),
    decision("d2", "How is it compacted?"),
]

PAPER = (255, 255, 255)


def rgb(css: str) -> tuple[int, int, int]:
    """The red, green and blue channels of a computed `rgb()` or `rgba()` colour."""
    found = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", css)
    assert found, f"not a computed colour: {css!r}"
    return int(found[1]), int(found[2]), int(found[3])


def luminance(colour: tuple[int, int, int]) -> float:
    """WCAG relative luminance, from 0 for black to 1 for white."""

    def linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(one: tuple[int, int, int], two: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two opaque colours."""
    light, dark = sorted((luminance(one), luminance(two)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def drawn(css: str, fade: float, ground: tuple[int, int, int]) -> tuple[int, int, int]:
    """The opaque colour a text colour is drawn in, once its alpha and fade meet the ground."""
    found = re.match(r"rgba?\([^,]+,[^,]+,[^,]+,\s*([\d.]+)", css)
    alpha = (float(found[1]) if found else 1) * fade
    r, g, b = (
        round(alpha * ink + (1 - alpha) * paper)
        for ink, paper in zip(rgb(css), ground, strict=True)
    )
    return r, g, b


# Every element of the card that carries text of its own, with its colour and
# the product of its opacity and its ancestors' up to and including the card.
INKS = """card => [card, ...card.querySelectorAll('*')]
  .filter(el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))
  .map(el => {
    let fade = 1;
    for (let at = el; at !== card.parentElement; at = at.parentElement)
      fade *= Number(getComputedStyle(at).opacity);
    return [getComputedStyle(el).color, fade];
  })"""


def style(locator: Locator, prop: str) -> str:
    return str(locator.evaluate(f"el => getComputedStyle(el).{prop}"))


def inside(inner: dict[str, float], outer: dict[str, float]) -> bool:
    """Whether one rendered box lies wholly within another."""
    return (
        outer["x"] <= inner["x"]
        and outer["y"] <= inner["y"]
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"]
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"]
    )


def hovered_card(page: Page) -> Locator:
    """Raise the trade-off card off d1's first option and return it once it shows."""
    page.hover("#col-d1 .pcricon")
    page.wait_for_selector(".hovercard .pcr", state="visible", timeout=BOARD_TIMEOUT)
    return page.locator(".hovercard")


def test_the_hovercard_is_light_and_still_reads_as_an_overlay(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given an option carrying a trade-off
    When the human hovers its icon
    Then the card that rises has a light background, its text and its labels
         read on that background, and it is set apart from the page by a shadow
         or a background that is not the page's paper.

    Every piece of text on the card is read, as the colour it is drawn in: a
    colour's alpha and the opacity of the text and of what holds it all make it
    paler than its computed colour, so a colour that passes while the text is
    half transparent passes nothing.
    """
    session = launcher(handoff=handoff(PLAN))
    page = board(session)
    card = hovered_card(page)

    ground = rgb(style(card, "backgroundColor"))
    assert luminance(ground) >= 0.7, f"the card is dark: {ground}"
    inks = card.evaluate(INKS)
    assert len(inks) >= 8, inks
    for colour, fade in inks:
        ink = drawn(colour, fade, ground)
        assert contrast(ink, ground) >= 4.5, f"{colour} at {fade} on {ground} does not read"
    shadow = style(card, "boxShadow")
    assert shadow != "none" or ground != PAPER, "nothing sets the card apart from the page"


def test_the_hovercard_title_shares_the_case_of_its_headers(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given the trade-off card raised over an option
    When its title line and its buys/costs/forces headers are read
    Then both carry the same text transform.

    A lower-case title over upper-case headers reads as one of the two being a
    mistake, which is the question the card exists to stop the human asking.
    """
    session = launcher(handoff=handoff(PLAN))
    page = board(session)
    card = hovered_card(page)

    title = style(card.locator(".hid"), "textTransform")
    headers = card.locator(".pcr b").evaluate_all(
        "bs => bs.map(b => getComputedStyle(b).textTransform)"
    )
    assert len(headers) == 3, headers
    assert set(headers) == {title}, (title, headers)


def test_the_recommended_option_is_dressed_like_the_others_and_captioned_inside(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given a decision still being asked, offering three options
    When its block renders
    Then the recommended option keeps its arrow but wears the alternatives' own
         foreground and background, and its caption sits inside its border,
         above the line carrying the arrow and the label, with no caption line
         left outside the controls.

    A filled option reads as the answer already given, so the recommendation is
    carried by the arrow and the caption rather than by a fill.
    """
    session = launcher(handoff=handoff(PLAN))
    page = board(session)

    recommended = page.locator('#col-d1 [data-act="pick"][data-opt="a"]')
    alternatives = page.locator('#col-d1 [data-act="pick"]:not([data-opt="a"])').all()
    assert len(alternatives) == 2, alternatives
    for prop in ("color", "backgroundColor"):
        assert {style(alt, prop) for alt in alternatives} == {style(recommended, prop)}, prop

    caption = recommended.locator(".rec-line")
    assert caption.count() == 1, "the caption is not inside the recommended option"
    assert page.locator("#col-d1 .rec-line").count() == 1, "a caption line is left outside"
    lines = recommended.inner_text().splitlines()
    assert lines[0].strip().upper() == "RECOMMENDED ANSWER", lines
    assert lines[1].startswith("➡️"), lines
    above = caption.bounding_box()
    label = recommended.locator(".olab").bounding_box()
    border = recommended.bounding_box()
    assert above and label and border
    assert inside(above, border), ("the caption renders outside the option", above, border)
    assert above["y"] + above["height"] <= label["y"] + 1, (above, label)


def assert_hint_beneath_the_box(free: Locator, send: str) -> None:
    """The send hint sits under the textarea, and the send control beside the box on its row."""
    box = free.locator("textarea").bounding_box()
    hint = free.locator(".hint").bounding_box()
    button = free.locator(send).bounding_box()
    assert box and hint and button
    assert hint["y"] >= box["y"] + box["height"] - 1, ("hint is not beneath the box", box, hint)
    assert hint["x"] >= box["x"] - 1, (box, hint)
    assert hint["x"] + hint["width"] <= box["x"] + box["width"] + 1, (box, hint)
    assert button["x"] >= box["x"] + box["width"] - 1, ("send is not beside the box", box, button)
    assert button["y"] < box["y"] + box["height"], ("send is below the box's row", box, button)
    assert button["y"] + button["height"] > box["y"], ("send is above the box's row", box, button)


def test_every_composer_puts_the_send_hint_beneath_its_box(
    launcher: Callable[..., Session], board: Callable[[Session], Page]
) -> None:
    """
    Given the decision's free-text box, a draft thread's box and an open
    thread's box
    When each renders
    Then at all three the send hint sits beneath the textarea and inside its
         width, and the send control sits beside the box rather than after a
         hint in between.

    The three are one composer the human types into all session, so a hint that
    moved in one of them would be the one place the chord is not where the eye
    has learned to find it.
    """
    session = launcher(handoff=handoff(PLAN))
    session.stub.script("Retention is what that turns on.")
    page = board(session)

    assert_hint_beneath_the_box(page.locator("#col-d1 .free"), '[data-act="free"]')

    page.click('[data-act="threads"][data-id="d1"]')
    page.wait_for_selector('[data-act="draftsay"]', timeout=BOARD_TIMEOUT)
    assert_hint_beneath_the_box(
        page.locator('.free:has([data-act="draftsay"])'), '[data-act="draftsay"]'
    )

    page.fill("#ft-say", "Why this store?")
    page.click('[data-act="draftsay"]')
    page.wait_for_selector('[data-act="say"]', timeout=BOARD_TIMEOUT)
    assert_hint_beneath_the_box(page.locator('.free:has([data-act="say"])'), '[data-act="say"]')
