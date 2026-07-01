# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from speedrun.dialog_geometry import centered_in_available_geometry


def test_centered_in_available_geometry():
    x, y, w, h = centered_in_available_geometry(0, 0, 1920, 1080, 820, 720)
    assert (w, h) == (820, 720)
    assert x == (1920 - 820) // 2
    assert y == (1080 - 720) // 2


def test_centered_clamps_to_screen():
    x, y, w, h = centered_in_available_geometry(100, 50, 640, 480, 820, 720)
    assert (w, h) == (640, 480)
    assert x == 100
    assert y == 50


def test_centered_handles_negative_screen_origin():
    x, y, w, h = centered_in_available_geometry(-100, -50, 1920, 1080, 820, 720)
    assert (w, h) == (820, 720)
    assert x == -100 + (1920 - 820) // 2
    assert y == -50 + (1080 - 720) // 2
