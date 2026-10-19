"""Run the repository's offline checks from Windows, macOS, or Linux."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
NPM = shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm"


def run(command: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    project_python = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    python = str(project_python) if project_python.exists() else sys.executable
    run([python, "-m", "pytest", "-q"], ROOT)
    run([NPM, "test"], ROOT / "frontend")


if __name__ == "__main__":
    main()
