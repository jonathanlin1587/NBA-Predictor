#!/usr/bin/env python3
"""
Parse daily NBA lineups from the text block you copy from your lineup site.

Usage:
  python lineups_scraper.py > output/lineups_YYYY-MM-DD.csv

Then paste the full block (starting at the first "XXX @ YYY ..."),
then press Ctrl+D (macOS/Linux) or Ctrl+Z + Enter (Windows).
"""

import sys
import re
import csv
from pathlib import Path
from datetime import date

GAME_HEADER_RE = re.compile(
    r'^([A-Z]{2,3})\s+@\s+([A-Z]{2,3})\s+(.+?ET)(.*)$'
)

POSITION_CODES = {"PG", "SG", "SF", "PF", "C"}

def parse_game_header(line: str):
    """
    Example:
    'MIA @ NYK 7:00 PM ET in 18.2h NYK by 5.5 o/u 236.5'
    -> away='MIA', home='NYK', time='7:00 PM ET', fav='NYK', spread='5.5', total='236.5'
    """
    m = GAME_HEADER_RE.match(line.strip())
    if not m:
        return None

    away, home, time_part, rest = m.groups()
    time_part = time_part.strip()

    fav = None
    spread = None
    total = None

    # Try to extract "TEAM by X" and "o/u Y"
    fav_match = re.search(r'([A-Z]{2,3})\s+by\s+(-?\d+\.?\d*)', rest)
    if fav_match:
        fav = fav_match.group(1)
        spread = fav_match.group(2)

    ou_match = re.search(r'o/u\s+(\d+\.?\d*)', rest)
    if ou_match:
        total = ou_match.group(1)

    return {
        "away": away,
        "home": home,
        "time": time_part,
        "fav": fav,
        "spread": spread,
        "total": total,
    }

def split_position_line(line: str):
    """
    Example input lines:
      'PG\tDavion Mitchell IN \tMiles McBride'
      'SG  Norman Powell IN   Mikal Bridges'

    Returns: (pos, left_str, right_str)
    """
    line = line.strip()
    if not line:
        return None

    # Split on tabs OR runs of 2+ spaces
    parts = re.split(r'\s{2,}|\t+', line)
    if len(parts) < 3:
        return None

    pos = parts[0]
    if pos not in POSITION_CODES:
        return None

    left = parts[1].strip()
    right = parts[2].strip()
    return pos, left, right

def extract_name_and_status(chunk: str):
    """
    Chunk like:
      'Davion Mitchell IN'
      'Kel\'el Ware IN'
      'Miles McBride'
    Returns (name, status) where status may be None.
    """
    tokens = chunk.split()
    if not tokens:
        return "", None

    last = tokens[-1]
    # Treat short all-caps token as status (IN, Q, O, P, OUT, etc.)
    if last.isupper() and len(last) <= 4:
        status = last
        name = " ".join(tokens[:-1]).strip()
        if not name:  # in weird case, just fall back
            name = chunk.strip()
            status = None
    else:
        name = chunk.strip()
        status = None

    return name, status

def parse_lineups_block(raw_text: str):
    """
    Main parser. Returns a list of dict rows.
    """
    lines = [ln.rstrip("\n") for ln in raw_text.splitlines()]

    rows = []
    current_game = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        # Try to detect a new game header
        game_meta = parse_game_header(line)
        if game_meta:
            current_game = game_meta

            # Next line is usually repeated "MIA @ NYK", skip if present
            if i + 1 < n and "@" in lines[i + 1] and not any(
                token in lines[i + 1] for token in ("ET", "o/u", "by")
            ):
                i += 2
            else:
                i += 1
            continue

        # If we're in a game, read position lines
        if current_game:
            pos_line = split_position_line(line)
            if pos_line:
                pos, left_chunk, right_chunk = pos_line

                # Away team (left)
                away_name, away_status = extract_name_and_status(left_chunk)
                rows.append({
                    "date": str(date.today()),
                    "game_time": current_game["time"],
                    "away_team": current_game["away"],
                    "home_team": current_game["home"],
                    "fav": current_game["fav"],
                    "spread": current_game["spread"],
                    "total": current_game["total"],
                    "team": current_game["away"],
                    "opp": current_game["home"],
                    "home_away": "A",
                    "position": pos,
                    "player": away_name,
                    "status": away_status or "",
                })

                # Home team (right)
                home_name, home_status = extract_name_and_status(right_chunk)
                rows.append({
                    "date": str(date.today()),
                    "game_time": current_game["time"],
                    "away_team": current_game["away"],
                    "home_team": current_game["home"],
                    "fav": current_game["fav"],
                    "spread": current_game["spread"],
                    "total": current_game["total"],
                    "team": current_game["home"],
                    "opp": current_game["away"],
                    "home_away": "H",
                    "position": pos,
                    "player": home_name,
                    "status": home_status or "",
                })

                i += 1
                continue
            else:
                # If we hit a blank or a non-position line, just move on.
                i += 1
                continue

        # If not in a game yet, just advance
        i += 1

    return rows

def main():
    print("Paste your lineup block (starting at the first 'XXX @ YYY ...' line).")
    print("When finished, press Ctrl+D (macOS/Linux) or Ctrl+Z then Enter (Windows).")
    print("-" * 60, file=sys.stderr)

    raw = sys.stdin.read()
    if not raw.strip():
        print("No input received. Exiting.", file=sys.stderr)
        sys.exit(1)

    rows = parse_lineups_block(raw)
    if not rows:
        print("❌ No rows parsed. Double-check the pasted format.", file=sys.stderr)
        sys.exit(1)

    # Ensure output directory exists
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)

    today_str = str(date.today())
    out_path = out_dir / f"lineups_{today_str}.csv"

    fieldnames = [
        "date", "game_time",
        "away_team", "home_team",
        "fav", "spread", "total",
        "team", "opp", "home_away",
        "position", "player", "status",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"✅ Parsed {len(rows)} lineup rows.")
    print(f"Saved to: {out_path}", file=sys.stderr)

if __name__ == "__main__":
    main()
