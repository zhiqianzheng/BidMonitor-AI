"""Start the maintained desktop edition with its own modules and data directory."""
from pathlib import Path
import runpy
import sys


def main():
    desktop = Path(__file__).resolve().parent / "original_desktop"
    sys.path.insert(0, str(desktop))
    runpy.run_path(str(desktop / "run.py"), run_name="__main__")


if __name__ == "__main__":
    main()
