"""Compatibility command; desktop source now lives under apps/desktop/."""
from pathlib import Path
import runpy


def main():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "run_original.py"), run_name="__main__")


if __name__ == "__main__":
    main()
