from __future__ import annotations

import configparser
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "project_checks.ini"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/check.py <setup|quick|affected|full|release>")
        return 2
    name = sys.argv[1]
    parser = configparser.ConfigParser()
    parser.read(CONFIG, encoding="utf-8")
    command = parser.get("checks", name, fallback="").strip()
    if not command:
        print(f"check not configured: {name}")
        return 2
    print(f"[check:{name}] {command}")
    completed = subprocess.run(command, cwd=ROOT, shell=True)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
