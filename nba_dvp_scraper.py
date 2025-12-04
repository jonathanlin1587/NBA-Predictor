#!/usr/bin/env python3
"""
Parse NBA Defense vs Position data from Hashtag Basketball.

Usage:
  python nba_dvp_scraper.py           # Auto-fetch from website
  python nba_dvp_scraper.py --paste   # Manual paste mode (fallback)
"""

import re
import os
import sys
import pandas as pd
import subprocess
import argparse
import requests
from datetime import datetime
from shutil import which

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

DVP_URL = "https://hashtagbasketball.com/nba-defense-vs-position"
METRICS = ["PTS","FG%","FT%","3PM","REB","AST","STL","BLK","TO"]

def read_from_clipboard_mac():
    if which("pbpaste") is None:
        return ""
    try:
        return subprocess.check_output(["pbpaste"]).decode("utf-8", errors="replace")
    except Exception:
        return ""

def looks_like_python(text: str) -> bool:
    head = "\n".join(text.strip().splitlines()[:5]).lower()
    return ("import " in head) or ("def " in head) or head.strip().startswith("#")

def parse_position_block(raw_text: str) -> pd.DataFrame:
    raw_text = raw_text.replace("\xa0", " ").replace("\t", " ")
    rows = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        # Accept lines like "SF BOS 1 19.9 14 39.9 ..." (position + team then numbers)
        if not re.match(r"^(PG|SG|SF|PF|C)\s+[A-Z]{2,3}\b", line):
            continue
        tokens = line.split()
        pos, team = tokens[0], tokens[1]
        vals = tokens[2:]
        if len(vals) < 2 * len(METRICS):
            continue
        stat_vals = []
        for i in range(len(METRICS)):
            val_idx = 2*i + 1   # skip the rank, take the value
            try:
                stat_vals.append(float(vals[val_idx]))
            except Exception:
                stat_vals.append(None)
        row = {"POSITION": pos, "TEAM": team}
        row.update({METRICS[i]: stat_vals[i] for i in range(len(METRICS))})
        rows.append(row)

    if not rows:
        # show a tiny preview to help debug
        preview = "\n".join(raw_text.splitlines()[:10])
        raise ValueError(
            "No data rows detected — expected lines like 'SF  BOS   1  19.9 ...'.\n"
            "Make sure you copied the **table text** (not page HTML or your script).\n"
            f"First lines seen:\n{preview}"
        )

    df = pd.DataFrame(rows)
    df = df[["POSITION","TEAM","PTS","REB","AST"]].copy()
    df["PR"]  = df["PTS"] + df["REB"]
    df["PA"]  = df["PTS"] + df["AST"]
    df["PRA"] = df["PTS"] + df["REB"] + df["AST"]
    return df

def top_bottom_by_pos(df: pd.DataFrame, stat: str, n: int = 5):
    results = []
    for pos, sub in df.groupby("POSITION"):
        sub = sub.dropna(subset=[stat])
        s_desc = sub.sort_values(stat, ascending=False)
        worst = s_desc.head(n)[["TEAM", stat]].reset_index(drop=True)
        best  = s_desc.tail(n).sort_values(stat)[["TEAM", stat]].reset_index(drop=True)
        results.append((pos, stat, "WORST (overs)", worst))
        results.append((pos, stat, "BEST (unders)", best))
    return results

def fetch_dvp_from_web() -> pd.DataFrame:
    """
    Fetch DVP data directly from Hashtag Basketball website.
    Returns DataFrame with position/team/stat data.
    """
    if not HAS_BS4:
        print("❌ Required library not installed. Run: pip install beautifulsoup4", file=sys.stderr)
        return pd.DataFrame()
    
    print(f"🌐 Fetching DVP data from {DVP_URL}...", file=sys.stderr)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        response = requests.get(DVP_URL, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Failed to fetch page: {e}", file=sys.stderr)
        return pd.DataFrame()
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    rows = []
    
    # Find the main data table (class="table table-sm table-bordered table-striped table--statistics")
    tables = soup.find_all("table", class_=lambda x: x and "table--statistics" in x)
    
    if not tables:
        # Fallback: try finding any table with table-striped class
        tables = soup.find_all("table", class_=lambda x: x and "table-striped" in x)
    
    print(f"📊 Found {len(tables)} data tables", file=sys.stderr)
    
    for table in tables:
        # Find all data rows (skip header)
        table_rows = table.find_all("tr")
        
        for tr in table_rows:
            cells = tr.find_all("td")
            if len(cells) < 11:  # Position + Team + 9 stats (each with rank)
                continue
            
            # First cell: Position (PG, SG, SF, PF, C)
            pos_text = cells[0].get_text(strip=True)
            if pos_text not in ["PG", "SG", "SF", "PF", "C"]:
                continue
            
            # Second cell: Team (with rank)
            team_cell = cells[1].get_text(strip=True)
            # Extract team abbreviation (e.g., "NY 3" -> "NY", "WAS 150" -> "WAS")
            team_match = re.match(r'([A-Z]{2,3})', team_cell)
            if not team_match:
                continue
            team = team_match.group(1)
            
            # Extract stats from remaining cells
            # Each stat cell contains "value rank" (e.g., "19.8 11")
            stat_values = {}
            for i, metric in enumerate(METRICS):
                cell_idx = i + 2  # Skip Position and Team columns
                if cell_idx < len(cells):
                    cell_text = cells[cell_idx].get_text(strip=True)
                    # Extract the value (first number)
                    value_match = re.match(r'([\d.]+)', cell_text)
                    if value_match:
                        try:
                            stat_values[metric] = float(value_match.group(1))
                        except ValueError:
                            stat_values[metric] = None
                    else:
                        stat_values[metric] = None
                else:
                    stat_values[metric] = None
            
            row = {"POSITION": pos_text, "TEAM": team}
            row.update(stat_values)
            rows.append(row)
    
    if not rows:
        print("⚠️ No data rows found in tables", file=sys.stderr)
        return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    
    # Keep only the columns we need and add combo stats
    df = df[["POSITION", "TEAM", "PTS", "REB", "AST"]].copy()
    df["PR"] = df["PTS"] + df["REB"]
    df["PA"] = df["PTS"] + df["AST"]
    df["PRA"] = df["PTS"] + df["REB"] + df["AST"]
    
    return df


def fetch_from_url(url: str) -> str:
    """Try to fetch the page and extract all visible table text. Works only if the table is server-rendered."""
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    # Try to scrape any HTML tables into DataFrames, then dump as plain text
    tables = pd.read_html(r.text)  # may fail if tables are JS-rendered
    blocks = []
    for t in tables:
        # flatten to space-delimited text
        blocks.append("\n".join(" ".join(map(str, row)) for row in t.values))
    return "\n".join(blocks)


def main():
    ap = argparse.ArgumentParser(description="Fetch NBA DVP data from Hashtag Basketball")
    ap.add_argument("--paste", action="store_true", help="Use manual paste mode instead of auto-fetch")
    ap.add_argument("--url", help="Fetch table text from a custom URL (legacy option).")
    args = ap.parse_args()

    df = None
    
    if args.paste:
        # Manual paste mode (fallback)
        print("🏀 Paste your Hashtag Basketball position data below.")
        print("Press Ctrl+D (macOS/Linux) when done, or press Enter now to try clipboard.\n")
        try:
            pasted = sys.stdin.read()
        except KeyboardInterrupt:
            pasted = ""

        raw = pasted.strip()
        if not raw:
            raw = read_from_clipboard_mac()
        if looks_like_python(raw):
            print("⚠️ Clipboard looks like code, not table text. Copy the table block from the site and run again.")
            sys.exit(1)
        
        df = parse_position_block(raw)
        
    elif args.url:
        try:
            raw = fetch_from_url(args.url)
            df = parse_position_block(raw)
        except Exception as e:
            print(f"URL fetch failed: {e}\n"
                  "If the site uses client-side JS, copy the visible table from the page and paste it instead.")
            sys.exit(1)
    else:
        # Auto-fetch mode (default)
        df = fetch_dvp_from_web()
        
        if df.empty:
            print("⚠️ Auto-fetch failed or returned no data.", file=sys.stderr)
            print("Try running with --paste flag for manual mode.", file=sys.stderr)
            sys.exit(1)

    if df is None or df.empty:
        print("❌ No data parsed. Check the source.", file=sys.stderr)
        sys.exit(1)
    
    print(f"\n✅ Parsed {len(df)} rows successfully!\n")

    # Print summary to console
    for stat in ["PTS", "REB", "AST", "PR", "PA", "PRA"]:
        print(f"\n### {stat} ###")
        for pos, s, kind, table in top_bottom_by_pos(df, stat):
            print(f"\n{pos} — {kind}")
            print(table.to_string(index=False))

    # Save to file
    today = datetime.now().strftime("%Y-%m-%d")
    date_dir = os.path.join("outputs", today)
    os.makedirs(date_dir, exist_ok=True)
    out_path = os.path.join(date_dir, f"dvp_summary_{today}.txt")

    with open(out_path, "w") as f:
        for stat in ["PTS", "REB", "AST", "PR", "PA", "PRA"]:
            f.write(f"\n### {stat} ###\n")
            for pos, s, kind, table in top_bottom_by_pos(df, stat):
                f.write(f"\n{pos} — {kind}\n")
                f.write(table.to_string(index=False))
                f.write("\n")
    
    print(f"\n💾 Saved summary to {out_path}")


if __name__ == "__main__":
    main()
