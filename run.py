"""Preserve the original desktop launch command."""
from pathlib import Path
import runpy


def main():
    return runpy.run_path(str(Path(__file__).resolve().with_name("run_original.py")), run_name="__main__")


if __name__ == "__main__":
    main()
