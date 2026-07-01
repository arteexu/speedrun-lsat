# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Guards the clean-machine install path (docs/speedrun/INSTALL.md).

These assert the pieces the `speedrun-lsat` wheel needs so it installs and runs
without a source checkout: the packaging config force-includes the package, and
the data files it ships (taxonomy, seed deck, config) are present.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PKG = REPO_ROOT / "speedrun"


def test_required_data_files_are_present():
    for rel in (
        "config.json",
        "data/seed_deck.json",
        "taxonomy/lsat_taxonomy.json",
        "scoring/memory.py",
    ):
        assert (PKG / rel).is_file(), f"missing packaged file: {rel}"


def test_pyproject_force_includes_the_package():
    cfg = tomllib.loads(
        (REPO_ROOT / "packaging" / "speedrun" / "pyproject.toml").read_text("utf-8")
    )
    assert cfg["project"]["name"] == "speedrun-lsat"
    force = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force.get("../../speedrun") == "speedrun"


def test_path_shim_prefers_installed_package():
    """The Qt shim must try `import speedrun` before falling back to the dev tree,
    so a wheel-installed package works on a clean machine."""
    src = (REPO_ROOT / "qt" / "aqt" / "speedrun" / "__init__.py").read_text("utf-8")
    assert "import speedrun.scoring.memory" in src
