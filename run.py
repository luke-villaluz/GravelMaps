#!/usr/bin/env python3
"""One-command launcher: sets up a virtualenv, installs deps, builds map data, starts the server.

Usage:  python3 run.py              # interactive menu
        python3 run.py [--regions ca nv] [--rebuild] [--update-data] [--port 8000]

Symlink it onto your PATH to get a `GravelMaps` command that works from any directory:
        ln -s "$PWD/run.py" ~/.local/bin/GravelMaps
"""
import hashlib
import os
import signal
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.realpath(__file__))  # realpath: works when run via a symlink
VENV = os.path.join(ROOT, ".venv")
REQS = os.path.join(ROOT, "requirements.txt")
STAMP = os.path.join(VENV, ".requirements.sha256")


def venv_python():
    if os.name == "nt":
        return os.path.join(VENV, "Scripts", "python.exe")
    return os.path.join(VENV, "bin", "python")


def main():
    if sys.version_info < (3, 10):
        sys.exit(f"GravelMaps needs Python 3.10 or newer (you have {sys.version.split()[0]}).")

    py = venv_python()
    if not os.path.exists(py):
        print("Creating virtual environment in .venv ...")
        venv.create(VENV, with_pip=True)

    with open(REQS, "rb") as f:
        want = hashlib.sha256(f.read()).hexdigest()
    have = open(STAMP).read().strip() if os.path.exists(STAMP) else ""
    if want != have:
        print("Installing dependencies ...")
        subprocess.check_call([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
        subprocess.check_call([py, "-m", "pip", "install", "--quiet", "-r", REQS])
        with open(STAMP, "w") as f:
            f.write(want)

    child = subprocess.Popen([py, "-m", "gravelmaps", *sys.argv[1:]], cwd=ROOT)
    # Ctrl+C (still works besides typing q) reaches the child too; let it shut the server down cleanly.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    sys.exit(child.wait())


if __name__ == "__main__":
    main()
