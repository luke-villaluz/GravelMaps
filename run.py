#!/usr/bin/env python3
"""One-command launcher: sets up a virtualenv, installs deps, builds map data, starts the server.

Usage:  python3 run.py [--regions nevada,utah] [--rebuild] [--update-data] [--port 8000]
"""
import hashlib
import os
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.abspath(__file__))
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

    try:
        code = subprocess.call([py, "-m", "gravelmaps", "run", *sys.argv[1:]], cwd=ROOT)
    except KeyboardInterrupt:
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
