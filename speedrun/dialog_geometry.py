# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pure geometry helpers for Speedrun Qt dialogs (testable without Qt)."""

from __future__ import annotations


def centered_in_available_geometry(
    screen_x: int,
    screen_y: int,
    screen_width: int,
    screen_height: int,
    dialog_width: int,
    dialog_height: int,
) -> tuple[int, int, int, int]:
    """Return (x, y, width, height) centered within available screen space."""
    width = min(dialog_width, screen_width)
    height = min(dialog_height, screen_height)
    x = screen_x + max(0, (screen_width - width) // 2)
    y = screen_y + max(0, (screen_height - height) // 2)
    return x, y, width, height
