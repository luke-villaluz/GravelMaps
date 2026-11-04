#!/usr/bin/env bash
# Installs the `GravelMaps` command. Run once after cloning:  ./install.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
CMD="$BIN/GravelMaps"

# A Python 3.10+ to launch run.py with (run.py then builds its own .venv).
find_python() {
  local name py
  for name in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    while IFS= read -r py; do
      # Skip virtualenv pythons: they break if that venv is deleted.
      if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10) or sys.prefix != sys.base_prefix)' 2>/dev/null; then
        echo "$py"
        return
      fi
    done < <(type -ap "$name")
  done
  return 1
}

if ! PY="$(find_python)"; then
  # No suitable Python (macOS ships 3.9): get a private one with uv, which installs to ~/.local.
  echo "Python 3.10+ not found. Installing one for GravelMaps (no admin rights needed) ..."
  if ! command -v uv >/dev/null 2>&1 && [ ! -x "$BIN/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
  fi
  UV="$(command -v uv || echo "$BIN/uv")"
  "$UV" python install 3.12
  PY="$("$UV" python find 3.12)"
fi
echo "Using $PY"

mkdir -p "$BIN"
rm -f "$CMD"  # may be an older symlink to run.py; never write through it
cat > "$CMD" <<EOF
#!/bin/sh
exec "$PY" "$REPO/run.py" "\$@"
EOF
chmod +x "$CMD"
echo "Installed $CMD"

case ":$PATH:" in
  *":$BIN:"*) ready=1 ;;
  *)
    ready=0
    line='export PATH="$HOME/.local/bin:$PATH"'
    for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
      # zsh is the macOS default, so always set up .zshrc there; otherwise only touch existing files.
      if [ -f "$rc" ] || { [ "$rc" = "$HOME/.zshrc" ] && [ "$(uname)" = Darwin ]; }; then
        grep -qsF "$line" "$rc" || printf '\n# Added by GravelMaps\n%s\n' "$line" >> "$rc"
      fi
    done
    ;;
esac

echo
if [ "$ready" = 1 ]; then
  echo "Done. Run:  GravelMaps"
else
  echo "Done. Open a new terminal window, then run:  GravelMaps"
fi
