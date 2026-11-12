"""Create the explicitly requested Python-based Linux .sh release (no native build)."""
from __future__ import annotations

import argparse
from pathlib import Path

from release_tools.linux_package import build_installer


def main() -> int:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--output-dir", type=Path, default=root/"artifacts"/"releases")
    options = parser.parse_args()
    installer = build_installer(root, options.output_dir.resolve(), options.version)
    print(f"Linux Python installer ready: {installer}")
    print("Requires target Python 3.10-3.12, internet, and Qt desktop libraries. This is not a frozen Linux binary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
