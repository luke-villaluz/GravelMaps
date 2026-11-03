"""Arrow-key launcher shown when GravelMaps is started with no arguments."""
import sys
import termios
import tty

HIDE, SHOW, CLEAR_LINE = "\x1b[?25l", "\x1b[?25h", "\x1b[2K"
BOLD, DIM, CYAN, RESET = "\x1b[1m", "\x1b[2m", "\x1b[36m", "\x1b[0m"


def read_key():
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        seq = sys.stdin.read(2)
        return {"[A": "up", "[B": "down"}.get(seq, "esc")
    if ch in ("\r", "\n"):
        return "enter"
    return ch


def choose(title, options):
    """options: list of (label, hint). Returns the chosen index, or None if the user quit."""
    out = sys.stdout
    idx = 0

    def draw(first):
        if not first:
            out.write(f"\x1b[{len(options)}A")
        for i, (label, hint) in enumerate(options):
            line = f"  {CYAN}{BOLD}❯ {label}{RESET}" if i == idx else f"    {label}"
            out.write(f"\r{CLEAR_LINE}{line}  {DIM}{hint}{RESET}\n")
        out.flush()

    out.write(f"\n{title}\n{DIM}↑/↓ to move, Enter to select, q to quit{RESET}\n\n{HIDE}")
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        draw(True)
        while True:
            key = read_key()
            if key in ("up", "k"):
                idx = (idx - 1) % len(options)
            elif key in ("down", "j"):
                idx = (idx + 1) % len(options)
            elif key.isdigit() and 1 <= int(key) <= len(options):
                idx = int(key) - 1
                draw(False)
                return idx
            elif key == "enter":
                return idx
            elif key in ("q", "esc"):
                return None
            draw(False)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        out.write(SHOW + "\n")
        out.flush()
