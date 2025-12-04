#!/usr/bin/env python3
"""
Parse daily NBA lineups from Basketball Monster.

Usage:
  python lineups_scraper.py           # Auto-fetch from website
  python lineups_scraper.py --paste   # Manual paste mode (fallback)
"""

import sys
import re
import csv
import argparse
from pathlib import Path
from datetime import date

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_WEB_LIBS = True
except ImportError:
    HAS_WEB_LIBS = False

LINEUP_URL = "https://basketballmonster.com/nbalineups.aspx"

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

def get_date_output_dir(date_str: str) -> Path:
    """Get the output directory for a specific date, creating it if needed."""
    date_dir = Path("outputs") / date_str
    date_dir.mkdir(parents=True, exist_ok=True)
    return date_dir


def fetch_lineups_from_web() -> list:
    """
    Fetch lineups directly from Basketball Monster website.
    Returns list of parsed rows.
    """
    if not HAS_WEB_LIBS:
        print("❌ Required libraries not installed. Run: pip install requests beautifulsoup4", file=sys.stderr)
        return []
    
    print(f"🌐 Fetching lineups from {LINEUP_URL}...", file=sys.stderr)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://basketballmonster.com/",
    }
    
    try:
        response = requests.get(LINEUP_URL, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Failed to fetch page: {e}", file=sys.stderr)
        return []
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    rows = []
    
    # Find all game containers (class="container-fluid p-2 m-2 float-left")
    game_containers = soup.find_all("div", class_=lambda x: x and "container-fluid" in x and "float-left" in x)
    
    if not game_containers:
        # Fallback: try finding tables directly
        game_containers = soup.find_all("table")
    
    print(f"📊 Found {len(game_containers)} game containers", file=sys.stderr)
    
    for container in game_containers:
        # Try to find game header info
        # Look for the header row with team names and game info
        header_text = ""
        
        # Check for text containing "@ " and "ET"
        text_content = container.get_text(" ", strip=True)
        
        # Extract game info from the container's text
        # Pattern: "XXX @ YYY H:MM PM ET ... XXX by X.X o/u XXX.X"
        game_match = re.search(
            r'([A-Z]{2,3})\s*@\s*([A-Z]{2,3})\s+(\d{1,2}:\d{2}\s*[AP]M\s*ET)',
            text_content
        )
        
        if not game_match:
            continue
        
        away_team = game_match.group(1)
        home_team = game_match.group(2)
        game_time = game_match.group(3)
        
        # Extract spread and total
        fav = None
        spread = None
        total = None
        
        fav_match = re.search(r'([A-Z]{2,3})\s+by\s+(-?\d+\.?\d*)', text_content)
        if fav_match:
            fav = fav_match.group(1)
            spread = fav_match.group(2)
        
        ou_match = re.search(r'o/u\s+(\d+\.?\d*)', text_content)
        if ou_match:
            total = ou_match.group(1)
        
        # Find the lineup table within this container
        table = container.find("table") if container.name != "table" else container
        if not table:
            continue
        
        # Parse table rows
        table_rows = table.find_all("tr")
        
        for tr in table_rows:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            
            # First cell should be position
            pos_text = cells[0].get_text(strip=True)
            if pos_text not in POSITION_CODES:
                continue
            
            # Second cell is away team player
            away_cell = cells[1]
            away_player, away_status = parse_player_cell(away_cell)
            
            # Third cell is home team player
            home_cell = cells[2]
            home_player, home_status = parse_player_cell(home_cell)
            
            if away_player:
                rows.append({
                    "date": str(date.today()),
                    "game_time": game_time,
                    "away_team": away_team,
                    "home_team": home_team,
                    "fav": fav,
                    "spread": spread,
                    "total": total,
                    "team": away_team,
                    "opp": home_team,
                    "home_away": "A",
                    "position": pos_text,
                    "player": away_player,
                    "status": away_status or "",
                })
            
            if home_player:
                rows.append({
                    "date": str(date.today()),
                    "game_time": game_time,
                    "away_team": away_team,
                    "home_team": home_team,
                    "fav": fav,
                    "spread": spread,
                    "total": total,
                    "team": home_team,
                    "opp": away_team,
                    "home_away": "H",
                    "position": pos_text,
                    "player": home_player,
                    "status": home_status or "",
                })
    
    return rows


def parse_player_cell(cell) -> tuple:
    """
    Parse a player cell from the HTML table.
    Returns (player_name, status)
    """
    # Get player name from link if exists
    link = cell.find("a")
    if link:
        player_name = link.get_text(strip=True)
    else:
        player_name = cell.get_text(strip=True)
    
    # Check for status indicators
    status = None
    cell_text = cell.get_text(" ", strip=True)
    
    # Common status patterns
    status_patterns = [
        (r'\bOUT\b', 'OUT'),
        (r'\bO\b', 'OUT'),
        (r'\bOff\s*Inj\b', 'OUT'),
        (r'\bQ\b', 'Q'),          # Questionable
        (r'\bGTD\b', 'GTD'),      # Game-time decision
        (r'\bP\b', 'P'),          # Probable
        (r'\bIN\b', 'IN'),
        (r'\bD\b', 'D'),          # Doubtful
    ]
    
    for pattern, status_code in status_patterns:
        if re.search(pattern, cell_text, re.IGNORECASE):
            status = status_code
            break
    
    # Clean up player name (remove status from name if present)
    for pattern, _ in status_patterns:
        player_name = re.sub(pattern, '', player_name, flags=re.IGNORECASE).strip()
    
    return player_name, status


def main():
    parser = argparse.ArgumentParser(description="Fetch NBA lineups from Basketball Monster")
    parser.add_argument("--paste", action="store_true", help="Use manual paste mode instead of auto-fetch")
    args = parser.parse_args()
    
    rows = []
    
    if args.paste:
        # Manual paste mode (fallback)
        print("Paste your lineup block (starting at the first 'XXX @ YYY ...' line).")
        print("When finished, press Ctrl+D (macOS/Linux) or Ctrl+Z then Enter (Windows).")
        print("-" * 60, file=sys.stderr)
        
        raw = sys.stdin.read()
        if not raw.strip():
            print("No input received. Exiting.", file=sys.stderr)
            sys.exit(1)
        
        rows = parse_lineups_block(raw)
    else:
        # Auto-fetch mode
        rows = fetch_lineups_from_web()
        
        if not rows:
            print("⚠️ Auto-fetch failed or returned no data.", file=sys.stderr)
            print("Try running with --paste flag for manual mode.", file=sys.stderr)
            sys.exit(1)
    
    if not rows:
        print("❌ No rows parsed. Double-check the source.", file=sys.stderr)
        sys.exit(1)

    # Ensure output directory exists
    today_str = str(date.today())
    date_dir = get_date_output_dir(today_str)
    out_path = date_dir / f"lineups_{today_str}.csv"

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
    print(f"📁 Saved to: {out_path}", file=sys.stderr)

if __name__ == "__main__":
    main()
