#!/usr/bin/env python3
"""
Scrape NBA player stats from Basketball-Reference's "Last N Days" page.

Usage:
    python last_n_days_scraper.py              # Last 10 days (default)
    python last_n_days_scraper.py --days 5     # Last 5 days
    python last_n_days_scraper.py --days 14 --output custom.csv
"""

import argparse
import csv
import os
import sys
from datetime import datetime
from typing import List, Dict, Any

import requests
import cloudscraper
from bs4 import BeautifulSoup, Comment

BASE_URL = "https://www.basketball-reference.com/friv/last_n_days.fcgi"
OUTPUT_DIR = "outputs"


def fetch_last_n_days(n_days: int = 10, max_retries: int = 3) -> str:
    """
    Fetch the Last N Days stats page from Basketball-Reference.
    Uses cloudscraper to bypass Cloudflare protection.
    """
    import time
    import random
    
    url = f"{BASE_URL}?n={n_days}&type=per_game"
    
    for attempt in range(max_retries):
        try:
            # Create a cloudscraper session (handles Cloudflare automatically)
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'darwin',
                    'desktop': True
                }
            )
            
            # Add a small delay to be polite
            time.sleep(random.uniform(1, 2))
            
            resp = scraper.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
            
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 403:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5 + random.uniform(1, 3)
                    print(f"⏳ Rate limited (403). Waiting {wait_time:.1f}s before retry {attempt + 2}/{max_retries}...")
                    time.sleep(wait_time)
                    continue
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 3
                print(f"⏳ Error occurred. Waiting {wait_time}s before retry {attempt + 2}/{max_retries}...")
                time.sleep(wait_time)
                continue
            raise
    
    raise requests.exceptions.HTTPError(f"Failed after {max_retries} attempts")


def find_stats_table(soup: BeautifulSoup):
    """
    Find the stats table on the page.
    
    Strategy:
    1. Look for table with class containing 'stats_table'
    2. Look for any table with player data-stat headers
    3. Search inside HTML comments (BRef sometimes hides tables there)
    """
    # Try direct table with stats_table class
    for table in soup.find_all("table"):
        classes = table.get("class", [])
        if any("stats_table" in c for c in classes):
            return table
    
    # Try any table with expected headers
    for table in soup.find_all("table"):
        if table.find("th", {"data-stat": "player"}):
            return table
    
    # Search inside HTML comments
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for c in comments:
        if "table" not in c:
            continue
        try:
            comment_soup = BeautifulSoup(c, "html.parser")
            for table in comment_soup.find_all("table"):
                if table.find("th", {"data-stat": "player"}):
                    return table
        except Exception:
            continue
    
    return None


def parse_stats_table(html: str) -> List[Dict[str, Any]]:
    """
    Parse the stats table and return a list of player stat dictionaries.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = find_stats_table(soup)
    
    if table is None:
        raise RuntimeError("Could not find the stats table on the page.")
    
    tbody = table.find("tbody")
    if tbody is None:
        raise RuntimeError("Could not find <tbody> inside stats table.")
    
    players: List[Dict[str, Any]] = []
    
    # Define the stats we want to extract (BRef data-stat names)
    # Note: BRef uses different naming conventions depending on the page
    stat_columns = [
        "ranker", "player", "team_id", "g", "gs", 
        "mp", "mp_per_g",  # minutes
        "fg", "fg_per_g", "fga", "fga_per_g", "fg_pct",
        "fg3", "fg3_per_g", "fg3a", "fg3a_per_g", "fg3_pct",
        "ft", "ft_per_g", "fta", "fta_per_g", "ft_pct",
        "orb", "orb_per_g", "drb", "drb_per_g", "trb", "trb_per_g",
        "ast", "ast_per_g", "stl", "stl_per_g", "blk", "blk_per_g",
        "tov", "tov_per_g", "pf", "pf_per_g", "pts", "pts_per_g", 
        "game_score"
    ]
    
    for row in tbody.find_all("tr"):
        # Skip header rows and separator rows
        if row.find("th", {"scope": "row"}) is None and row.find("td", {"data-stat": "player"}) is None:
            continue
        
        player_data: Dict[str, Any] = {}
        
        for stat in stat_columns:
            # Try td first, then th (for ranker)
            cell = row.find("td", {"data-stat": stat})
            if cell is None:
                cell = row.find("th", {"data-stat": stat})
            
            if cell is None:
                player_data[stat] = None
                continue
            
            # Get text content
            text = cell.get_text(strip=True)
            
            # For player name, also try to get the link text
            if stat == "player":
                link = cell.find("a")
                if link:
                    text = link.get_text(strip=True)
            
            player_data[stat] = text
        
        # Skip empty rows
        if not player_data.get("player"):
            continue
        
        players.append(player_data)
    
    return players


def convert_to_numeric(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert numeric string values to floats/ints and add derived stats.
    """
    numeric_fields = [
        "g", "gs", 
        "mp", "mp_per_g",
        "fg", "fg_per_g", "fga", "fga_per_g", "fg_pct",
        "fg3", "fg3_per_g", "fg3a", "fg3a_per_g", "fg3_pct",
        "ft", "ft_per_g", "fta", "fta_per_g", "ft_pct",
        "orb", "orb_per_g", "drb", "drb_per_g", "trb", "trb_per_g",
        "ast", "ast_per_g", "stl", "stl_per_g", "blk", "blk_per_g",
        "tov", "tov_per_g", "pf", "pf_per_g", "pts", "pts_per_g", 
        "game_score"
    ]
    
    for p in players:
        for field in numeric_fields:
            val = p.get(field)
            if val is None or val == "":
                p[field] = None
                continue
            try:
                p[field] = float(val)
            except ValueError:
                p[field] = None
        
        # Add derived stats for prop betting
        # Try both naming conventions (_per_g suffix and without)
        pts = p.get("pts_per_g") or p.get("pts") or 0
        reb = p.get("trb_per_g") or p.get("trb") or 0
        ast = p.get("ast_per_g") or p.get("ast") or 0
        
        p["pr_per_g"] = round(pts + reb, 1)      # Points + Rebounds
        p["pa_per_g"] = round(pts + ast, 1)      # Points + Assists
        p["pra_per_g"] = round(pts + reb + ast, 1)  # Points + Rebounds + Assists
    
    return players


def save_to_csv(players: List[Dict[str, Any]], filename: str) -> None:
    """
    Save player stats to a CSV file.
    """
    if not players:
        print("No players to save.")
        return
    
    # Clean up column names for CSV
    fieldnames = [
        "rank", "player", "team", "games", "games_started", "mpg",
        "fg", "fga", "fg_pct", "fg3", "fg3a", "fg3_pct",
        "ft", "fta", "ft_pct", "orb", "drb", "reb",
        "ast", "stl", "blk", "tov", "pf", "pts", "game_score",
        "pr", "pa", "pra"
    ]
    
    def get_with_fallback(p: Dict, *keys):
        """Get the first non-None value from multiple keys."""
        for k in keys:
            val = p.get(k)
            if val is not None:
                return val
        return None
    
    rows = []
    for p in players:
        row = {
            "rank": p.get("ranker"),
            "player": p.get("player"),
            "team": p.get("team_id"),
            "games": p.get("g"),
            "games_started": p.get("gs"),
            "mpg": get_with_fallback(p, "mp_per_g", "mp"),
            "fg": get_with_fallback(p, "fg_per_g", "fg"),
            "fga": get_with_fallback(p, "fga_per_g", "fga"),
            "fg_pct": p.get("fg_pct"),
            "fg3": get_with_fallback(p, "fg3_per_g", "fg3"),
            "fg3a": get_with_fallback(p, "fg3a_per_g", "fg3a"),
            "fg3_pct": p.get("fg3_pct"),
            "ft": get_with_fallback(p, "ft_per_g", "ft"),
            "fta": get_with_fallback(p, "fta_per_g", "fta"),
            "ft_pct": p.get("ft_pct"),
            "orb": get_with_fallback(p, "orb_per_g", "orb"),
            "drb": get_with_fallback(p, "drb_per_g", "drb"),
            "reb": get_with_fallback(p, "trb_per_g", "trb"),
            "ast": get_with_fallback(p, "ast_per_g", "ast"),
            "stl": get_with_fallback(p, "stl_per_g", "stl"),
            "blk": get_with_fallback(p, "blk_per_g", "blk"),
            "tov": get_with_fallback(p, "tov_per_g", "tov"),
            "pf": get_with_fallback(p, "pf_per_g", "pf"),
            "pts": get_with_fallback(p, "pts_per_g", "pts"),
            "game_score": p.get("game_score"),
            "pr": p.get("pr_per_g"),
            "pa": p.get("pa_per_g"),
            "pra": p.get("pra_per_g"),
        }
        rows.append(row)
    
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
    
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"✅ Saved {len(players)} players to {filename}")


def print_top_performers(players: List[Dict[str, Any]], n: int = 10) -> None:
    """
    Print top performers by PTS, REB, AST, and PRA.
    """
    print("\n" + "=" * 70)
    print("TOP PERFORMERS (Last N Days)")
    print("=" * 70)
    
    # Helper to get value with fallbacks
    def get_val(p: Dict, *keys) -> float:
        for k in keys:
            val = p.get(k)
            if val is not None:
                return float(val)
        return 0.0
    
    categories = [
        ("PTS", ["pts_per_g", "pts"]),
        ("REB", ["trb_per_g", "trb"]),
        ("AST", ["ast_per_g", "ast"]),
        ("PRA", ["pra_per_g"]),
    ]
    
    for cat_name, keys in categories:
        sorted_players = sorted(
            players,
            key=lambda x: get_val(x, *keys),
            reverse=True
        )[:n]
        
        print(f"\n🏀 Top {n} by {cat_name}:")
        print(f"{'Player':<25} {'Team':<5} {cat_name:>6}")
        print("-" * 40)
        
        for p in sorted_players:
            name = (p.get("player") or "")[:24]
            team = p.get("team_id") or ""
            val = get_val(p, *keys)
            if val > 0:
                print(f"{name:<25} {team:<5} {val:>6.1f}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape NBA player stats from Basketball-Reference's Last N Days page."
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=10,
        choices=range(1, 61),
        metavar="N",
        help="Number of days to fetch (1-60, default: 10)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output CSV filename (default: outputs/last_n_days_YYYY-MM-DD.csv)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress top performers printout"
    )
    
    args = parser.parse_args()
    
    # Default output filename
    if args.output is None:
        today = datetime.now().strftime("%Y-%m-%d")
        args.output = os.path.join(OUTPUT_DIR, f"last_{args.days}_days_{today}.csv")
    
    print(f"🏀 Fetching last {args.days} days of NBA stats from Basketball-Reference...")
    
    try:
        html = fetch_last_n_days(args.days)
        players = parse_stats_table(html)
        players = convert_to_numeric(players)
        
        print(f"📊 Found {len(players)} players")
        
        save_to_csv(players, args.output)
        
        if not args.quiet:
            print_top_performers(players)
        
    except requests.RequestException as e:
        print(f"❌ Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

