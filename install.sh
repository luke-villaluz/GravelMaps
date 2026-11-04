#!/usr/bin/env bash
# Installs the `GravelMaps` command. Either run it from a clone (./install.sh), or with no clone:
#   curl -fsSL https://raw.githubusercontent.com/luke-villaluz/GravelMaps/main/install.sh | bash
# which downloads the code to ~/GravelMaps. Re-running either one updates and keeps your map data.
set -euo pipefail

TARBALL="https://codeload.github.com/luke-villaluz/GravelMaps/tar.gz/refs/heads/main"
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

# Download the latest code into $1, replacing old code but keeping data/ and .venv/.
download() {
  local dest="$1" tmp
  if [ -d "$dest/.git" ]; then
    echo "$dest is a git clone; updating it with git pull ..."
    git -C "$dest" pull --ff-only
    return
  fi
  if [ -d "$dest" ] && [ -n "$(ls -A "$dest")" ] && [ ! -f "$dest/run.py" ]; then
    echo "$dest already exists and isn't GravelMaps; move it aside and run this again." >&2
    exit 1
  fi
  echo "Downloading GravelMaps to $dest ..."
  tmp="$(mktemp -d)"
  curl -fsSL "$TARBALL" | tar -xzf - -C "$tmp" --strip-components=1
  mkdir -p "$dest"
  find "$dest" -mindepth 1 -maxdepth 1 ! -name data ! -name .venv -exec rm -rf {} +
  cp -R "$tmp/." "$dest/"
  rm -rf "$tmp"
}

main() {
  local src="${BASH_SOURCE[0]:-}" repo
  if [ -n "$src" ] && [ -f "$(dirname "$src")/run.py" ]; then
    repo="$(cd "$(dirname "$src")" && pwd)"
  else
    repo="$HOME/GravelMaps"  # piped from curl: no clone to point at
    download "$repo"
  fi

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
exec "$PY" "$repo/run.py" "\$@"
EOF
  chmod +x "$CMD"
  echo "Installed $CMD"

  case ":$PATH:" in
    *":$BIN:"*) ;;
    *)
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
  echo "Done. From now on, open a terminal window and type:  GravelMaps"
  # Start it right away when there's someone at the keyboard. Under `curl | bash` stdin is the
  # script itself, so read keys from the terminal instead.
  if [ -t 1 ] && { : </dev/tty; } 2>/dev/null; then
    echo "Starting it now ..."
    exec "$CMD" </dev/tty
  fi
}

main "$@"  # last line: a partially downloaded script never runs
