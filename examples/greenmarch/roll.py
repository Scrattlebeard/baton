#!/usr/bin/env python3
"""Fair dice. Rolls are logged; commit the logs.

Usage: roll.py SPEC [-l LABEL] [--gm]
  SPEC: d20, 2d6, 3d8+2, d100-5 ...
  Public rolls append to rolls.log; --gm rolls to gm/rolls.log.
  Commit the logs — the audit trail is the point.
"""
import argparse
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("spec")
    p.add_argument("-l", "--label", default="")
    p.add_argument("--gm", action="store_true")
    a = p.parse_args()

    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", a.spec.strip().lower())
    if not m:
        sys.exit(f"bad spec: {a.spec!r} (want e.g. d20, 2d6+1)")
    n, sides, mod = int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 0)
    if not (1 <= n <= 100 and 2 <= sides <= 1000):
        sys.exit("spec out of range")

    dice = [secrets.randbelow(sides) + 1 for _ in range(n)]
    total = sum(dice) + mod
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} | {a.spec} | dice={dice} mod={mod:+d} | total={total}"
    if a.label:
        line += f" | {a.label}"

    log = HERE / ("gm/rolls.log" if a.gm else "rolls.log")
    with log.open("a") as f:
        f.write(line + "\n")
    print(line)


if __name__ == "__main__":
    main()
