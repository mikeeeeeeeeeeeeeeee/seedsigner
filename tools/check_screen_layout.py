import os
import sys


"""
CLI utility that renders every screen the screenshot generator knows about and reports
any text that collides with the screen's button list.

Why this exists:
    `ButtonListScreen` anchors its button list to the bottom of the screen, while
    subclasses append their own header components (titles, help text, amounts) at
    positions derived from the top nav. When a screen has enough buttons, the list grows
    upward into that header content and is drawn over it. The result is unreadable, and
    nothing in the normal test suite notices, because the damage is purely geometric.

    This check caught `SettingsEntryUpdateSelectionScreen` obscuring its own setting
    name on settings with five options.

Usage:
    python tools/check_screen_layout.py

    Exits 0 when no overlaps are found, 1 otherwise. Requires the test dependencies
    (it drives `tests/screenshot_generator`) and libraqm, same as generating
    screenshots.

Note:
    This is a developer utility rather than a pytest test because `tests/base.py`
    replaces `seedsigner.gui.renderer` with a `MagicMock` for the main suite. Real
    geometry needs the real renderer, so this runs in its own process.
"""


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

    # Importing the generator installs the hardware mocks it needs at import time.
    from screenshot_generator import generator
    from screenshot_generator.utils import ScreenshotRenderer
    from seedsigner.gui.screens.screen import ButtonListScreen

    overlaps = []
    current_screenshot = {"name": "?"}

    original_set_filename = ScreenshotRenderer.set_screenshot_filename
    def track_filename(self, filename: str):
        current_screenshot["name"] = filename
        return original_set_filename(self, filename)
    ScreenshotRenderer.set_screenshot_filename = track_filename

    original_post_init = ButtonListScreen.__post_init__
    def check_layout(self):
        original_post_init(self)

        if not getattr(self, "buttons", None):
            return

        # The vertical band the button list occupies. Any positioned content that
        # intersects it is drawn over, or under, a button.
        list_top = min(button.screen_y for button in self.buttons)
        list_bottom = max(button.screen_y + button.height for button in self.buttons)

        for component in self.components:
            screen_y = getattr(component, "screen_y", None)
            height = getattr(component, "height", None)
            if screen_y is None or height is None:
                # Not a positioned component (e.g. the top nav); nothing to collide.
                continue

            if screen_y < list_bottom and screen_y + height > list_top:
                overlaps.append(dict(
                    screenshot=current_screenshot["name"],
                    screen=type(self).__name__,
                    text=getattr(component, "text", ""),
                    content_top=screen_y,
                    content_bottom=screen_y + height,
                    list_top=list_top,
                    list_bottom=list_bottom,
                ))
    ButtonListScreen.__post_init__ = check_layout

    generator.generate_screenshots("en")

    if not overlaps:
        print("\nNo layout overlaps found.")
        return 0

    print(f"\n{len(overlaps)} layout overlap(s) found:")
    for overlap in overlaps:
        print(
            f"  {overlap['screen']} ({overlap['screenshot']}): "
            f"content spans y={overlap['content_top']}-{overlap['content_bottom']}, "
            f"button list spans y={overlap['list_top']}-{overlap['list_bottom']}\n"
            f"    text: {overlap['text']!r}"
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
