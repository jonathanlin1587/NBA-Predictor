#!/usr/bin/env python3
"""
Fetch NBA player prop odds from The Odds API.

Usage:
  python odds_scraper.py              # Fetch all prop odds
  python odds_scraper.py --market PTS # Fetch specific market (PTS, REB, AST, etc.)
"""

import os
import json
import csv
import argparse
import requests
from datetime import datetime
from pathlib import Path

# API Configuration
API_KEY = "126fec1461f7d63a5f2b8d1683752f13"
BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"

# Map our stat names to API market names
MARKET_MAP = {
    "PTS": "player_points",
    "REB": "player_rebounds", 
    "AST": "player_assists",
    "3PM": "player_threes",
    "STL": "player_steals",
    "BLK": "player_blocks",
    "PRA": "player_points_rebounds_assists",
    "PR": "player_points_rebounds",
    "PA": "player_points_assists",
}

# Reverse map for display
REVERSE_MARKET_MAP = {v: k for k, v in MARKET_MAP.items()}

# Only include these sportsbooks
ALLOWED_BOOKS = {
    "draftkings",
    "fanduel", 
    "betmgm",
    "bet365",
    "betrivers",  # ScoreBet is often listed as BetRivers
    "williamhill_us",  # Caesars (formerly William Hill) - remove if not wanted
}

OUTPUT_DIR = "outputs"


def get_date_output_dir(date_str: str) -> Path:
    """Get the output directory for a specific date."""
    date_dir = Path(OUTPUT_DIR) / date_str
    date_dir.mkdir(parents=True, exist_ok=True)
    return date_dir


def fetch_events() -> list:
    """Fetch today's NBA events/games."""
    url = f"{BASE_URL}/sports/{SPORT}/events"
    params = {
        "apiKey": API_KEY,
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"❌ Failed to fetch events: {e}")
        return []


def fetch_player_props(event_id: str, markets: list) -> dict:
    """Fetch player prop odds for a specific event."""
    url = f"{BASE_URL}/sports/{SPORT}/events/{event_id}/odds"
    
    # Convert our market names to API names
    api_markets = [MARKET_MAP.get(m, m) for m in markets]
    
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": ",".join(api_markets),
        "oddsFormat": "american",
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"❌ Failed to fetch props for event {event_id}: {e}")
        return {}


def parse_bookmaker_odds(bookmakers: list, market_key: str) -> list:
    """Parse odds from all bookmakers for a specific market."""
    all_odds = []
    
    for book in bookmakers:
        book_name = book.get("key", "unknown")
        book_title = book.get("title", book_name)
        
        # Filter to only allowed sportsbooks
        if book_name not in ALLOWED_BOOKS:
            continue
        
        for market in book.get("markets", []):
            if market.get("key") != market_key:
                continue
            
            for outcome in market.get("outcomes", []):
                player_name = outcome.get("description", "")
                line = outcome.get("point")
                price = outcome.get("price")
                direction = outcome.get("name", "").lower()  # "Over" or "Under"
                
                if player_name and line is not None and price is not None:
                    all_odds.append({
                        "player": player_name,
                        "line": line,
                        "odds": price,
                        "direction": direction.capitalize(),
                        "book": book_title,
                        "book_key": book_name,
                    })
    
    return all_odds


def find_best_odds(odds_list: list) -> dict:
    """
    Find the best odds for each player/line/direction combination.
    Returns dict keyed by (player, line, direction) with best odds info.
    """
    best = {}
    
    for odd in odds_list:
        key = (odd["player"], odd["line"], odd["direction"])
        
        if key not in best or odd["odds"] > best[key]["odds"]:
            best[key] = odd
    
    return best


def fetch_all_props(markets: list = None) -> list:
    """
    Fetch all player props for today's games.
    Returns list of prop odds with best odds highlighted.
    """
    if markets is None:
        markets = ["PTS", "REB", "AST", "3PM"]  # Default markets
    
    print(f"🌐 Fetching NBA events...", end=" ")
    events = fetch_events()
    
    if not events:
        print("No events found.")
        return []
    
    print(f"Found {len(events)} games")
    
    all_props = []
    
    for event in events:
        event_id = event.get("id")
        home_team = event.get("home_team", "")
        away_team = event.get("away_team", "")
        commence_time = event.get("commence_time", "")
        
        print(f"  📊 Fetching props for {away_team} @ {home_team}...")
        
        props_data = fetch_player_props(event_id, markets)
        
        if not props_data:
            continue
        
        bookmakers = props_data.get("bookmakers", [])
        
        for market in markets:
            api_market = MARKET_MAP.get(market, market)
            odds_list = parse_bookmaker_odds(bookmakers, api_market)
            
            if not odds_list:
                continue
            
            # Find best odds for each combo
            best_odds = find_best_odds(odds_list)
            
            # Add to results with best odds flag
            for odd in odds_list:
                key = (odd["player"], odd["line"], odd["direction"])
                is_best = (odd["book"] == best_odds[key]["book"] and 
                          odd["odds"] == best_odds[key]["odds"])
                
                all_props.append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "game": f"{away_team} @ {home_team}",
                    "home_team": home_team,
                    "away_team": away_team,
                    "player": odd["player"],
                    "stat": market,
                    "line": odd["line"],
                    "direction": odd["direction"],
                    "odds": odd["odds"],
                    "book": odd["book"],
                    "is_best": is_best,
                })
    
    return all_props


def get_best_odds_summary(all_props: list) -> list:
    """
    Get only the best odds for each player/stat/direction combo.
    """
    best = {}
    
    for prop in all_props:
        key = (prop["player"], prop["stat"], prop["line"], prop["direction"])
        
        if key not in best or prop["odds"] > best[key]["odds"]:
            best[key] = prop
    
    return list(best.values())


def save_to_csv(props: list, filename: str):
    """Save props to CSV file."""
    if not props:
        print("No props to save.")
        return
    
    fieldnames = [
        "date", "game", "player", "stat", "line", 
        "direction", "odds", "book", "is_best"
    ]
    
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(props)
    
    print(f"💾 Saved {len(props)} props to {filename}")


def save_best_odds_json(props: list, filename: str):
    """Save best odds summary as JSON for easy lookup."""
    best_props = get_best_odds_summary(props)
    
    # Create lookup dict by player + stat + direction
    lookup = {}
    for prop in best_props:
        player_key = prop["player"].lower().replace(" ", "_")
        stat = prop["stat"]
        direction = prop["direction"].lower()
        
        if player_key not in lookup:
            lookup[player_key] = {}
        if stat not in lookup[player_key]:
            lookup[player_key][stat] = {}
        
        lookup[player_key][stat][direction] = {
            "line": prop["line"],
            "odds": prop["odds"],
            "book": prop["book"],
            "game": prop["game"],
        }
    
    with open(filename, "w") as f:
        json.dump(lookup, f, indent=2)
    
    print(f"💾 Saved best odds lookup to {filename}")


def main():
    parser = argparse.ArgumentParser(description="Fetch NBA player prop odds")
    parser.add_argument("--markets", nargs="+", default=["PTS", "REB", "AST", "3PM"],
                       help="Markets to fetch (PTS, REB, AST, 3PM, STL, BLK, PRA, PR, PA)")
    args = parser.parse_args()
    
    print("🏀 NBA Odds Scraper - The Odds API")
    print("=" * 50)
    
    # Fetch all props
    all_props = fetch_all_props(args.markets)
    
    if not all_props:
        print("❌ No props fetched.")
        return
    
    print(f"\n✅ Fetched {len(all_props)} total prop lines")
    
    # Get unique players
    unique_players = set(p["player"] for p in all_props)
    print(f"📊 {len(unique_players)} unique players")
    
    # Save to files
    today = datetime.now().strftime("%Y-%m-%d")
    date_dir = get_date_output_dir(today)
    
    # Save all odds (for reference)
    all_csv = date_dir / f"odds_all_{today}.csv"
    save_to_csv(all_props, str(all_csv))
    
    # Save best odds only
    best_props = get_best_odds_summary(all_props)
    best_csv = date_dir / f"odds_best_{today}.csv"
    save_to_csv(best_props, str(best_csv))
    
    # Save JSON lookup
    json_file = date_dir / f"odds_lookup_{today}.json"
    save_best_odds_json(all_props, str(json_file))
    
    # Show API usage
    print(f"\n📈 API requests used this call: ~{len(fetch_events()) + 1}")
    print("💡 Tip: Check your remaining quota at https://the-odds-api.com/")


if __name__ == "__main__":
    main()

