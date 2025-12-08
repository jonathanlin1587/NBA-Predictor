#!/usr/bin/env python3
"""
NBA Prop Analyzer - Combines DVP matchups with recent player stats.

Workflow:
1. Load DVP shortlist (favorable matchups)
2. Load Last N days stats (recent performance)
3. Merge and score plays by strength
4. Interactive line entry for selected plays
5. Calculate edge and betting recommendations
"""

import csv
import os
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# ---------------------------------------------------
# Configuration
# ---------------------------------------------------
OUTPUT_DIR = "outputs"

# Minimum games in last N days to consider a player
MIN_GAMES = 2

# How many top plays to show per category
TOP_PLAYS_PER_CATEGORY = 8

# ---------------------------------------------------
# Data Classes
# ---------------------------------------------------

@dataclass
class Play:
    player: str
    team: str
    position: str
    opponent: str
    stat: str
    dvp_value: float
    tier: str  # "WORST" (overs) or "BEST" (unders)
    recent_avg: Optional[float] = None
    games_played: Optional[int] = None
    mpg: Optional[float] = None  # Minutes per game
    score: float = 0.0
    line: Optional[float] = None
    edge_pct: Optional[float] = None
    projected: Optional[float] = None  # Blended projection (recent + adjusted DVP)
    adjusted_dvp: Optional[float] = None  # DVP adjusted for player's minutes share


# ---------------------------------------------------
# Data Loading
# ---------------------------------------------------

def load_dvp_shortlist(filename: str) -> List[Dict[str, Any]]:
    """Load the DVP shortlist CSV."""
    rows = []
    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_last_n_days(filename: str) -> Dict[str, Dict[str, Any]]:
    """
    Load last N days stats into a dict keyed by player name (lowercase).
    Returns: {player_name: {stats...}}
    """
    players = {}
    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("player", "").strip()
            if not name:
                continue
            # Key by lowercase name for fuzzy matching
            key = normalize_name(name)
            players[key] = row
    return players


def normalize_name(name: str) -> str:
    """Normalize player name for matching."""
    # Remove common suffixes, lowercase, strip
    name = name.lower().strip()
    # Remove injury tags
    for suffix in [" off inj", " inj", " out", " q", " gtd"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()


def find_player_stats(player_name: str, stats_db: Dict[str, Dict]) -> Optional[Dict]:
    """Find player in stats database with fuzzy matching."""
    key = normalize_name(player_name)
    
    # Direct match
    if key in stats_db:
        return stats_db[key]
    
    # Partial match (for names with special characters)
    for db_key, stats in stats_db.items():
        if key in db_key or db_key in key:
            return stats
        # Match on last name
        if key.split()[-1] == db_key.split()[-1]:
            # Check first initial too
            if key[0] == db_key[0]:
                return stats
    
    return None


# ---------------------------------------------------
# Stat Mapping
# ---------------------------------------------------

STAT_MAP = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "PRA": "pra",
    "PR": "pr",
    "PA": "pa",
    "STL": "stl",
    "BLK": "blk",
    "3PM": "fg3",
}


def get_recent_stat(stats: Dict, stat_name: str) -> Optional[float]:
    """Get the recent average for a specific stat."""
    col = STAT_MAP.get(stat_name.upper(), stat_name.lower())
    val = stats.get(col)
    if val is None or val == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


# ---------------------------------------------------
# Play Scoring
# ---------------------------------------------------

def calculate_projection(
    recent_avg: float, 
    dvp_value: float, 
    tier: str,
    player_mpg: float = None,
    total_position_minutes: float = 48.0
) -> float:
    """
    Calculate a blended projection using recent performance and DVP.
    
    DVP represents what a defense allows to the ENTIRE position.
    We adjust DVP by the player's share of position minutes.
    
    Formula:
        minutes_share = player_mpg / total_position_minutes
        adjusted_dvp = DVP × minutes_share
        PROJ = (60% × recent_avg) + (40% × adjusted_dvp)
    
    Weights:
    - 60% recent form (what player is actually doing)
    - 40% DVP adjusted for minutes (what matchup suggests for THIS player)
    """
    RECENT_WEIGHT = 0.6
    DVP_WEIGHT = 0.4
    
    # Adjust DVP by player's minutes share
    if player_mpg is not None and player_mpg > 0:
        minutes_share = min(player_mpg / total_position_minutes, 1.0)  # Cap at 100%
        adjusted_dvp = dvp_value * minutes_share
    else:
        # Fallback: assume ~30 MPG average starter
        adjusted_dvp = dvp_value * (30 / total_position_minutes)
    
    projected = (RECENT_WEIGHT * recent_avg) + (DVP_WEIGHT * adjusted_dvp)
    return round(projected, 1)


def score_play(play: Play) -> float:
    """
    Score a play based on alignment between DVP and recent performance.
    Higher score = stronger play.
    
    For OVERS (tier=WORST):
        - Higher recent avg relative to DVP = better
        - Player is hot AND matchup is soft
    
    For UNDERS (tier=BEST):
        - Lower recent avg relative to DVP = better  
        - Player is cold AND matchup is tough
    """
    if play.recent_avg is None or play.games_played is None:
        return 0.0
    
    if play.games_played < MIN_GAMES:
        return 0.0
    
    # Calculate adjusted DVP based on player's minutes share
    if play.mpg is not None and play.mpg > 0:
        minutes_share = min(play.mpg / 48.0, 1.0)
        play.adjusted_dvp = round(play.dvp_value * minutes_share, 1)
    else:
        play.adjusted_dvp = round(play.dvp_value * (30 / 48.0), 1)  # Default 30 MPG
    
    # Calculate blended projection using adjusted DVP
    play.projected = calculate_projection(
        play.recent_avg, 
        play.dvp_value, 
        play.tier,
        player_mpg=play.mpg
    )
    
    # Base score from games played (more games = more reliable)
    games_factor = min(play.games_played / 5, 1.0)  # Max out at 5 games
    
    if play.tier == "WORST":  # OVER play
        # Player's recent avg vs what defense allows
        # If player avg > DVP value, they're exceeding even what defense gives up
        if play.dvp_value > 0:
            performance_ratio = play.recent_avg / play.dvp_value
        else:
            performance_ratio = 1.0
        
        # Score: higher if player is hot relative to matchup
        score = performance_ratio * games_factor * 100
        
    else:  # UNDER play (tier=BEST)
        # For unders, we want player avg to be LOW
        # Lower avg = better for under
        if play.dvp_value > 0:
            # Invert: lower recent avg relative to DVP = higher score
            performance_ratio = play.dvp_value / max(play.recent_avg, 0.1)
        else:
            performance_ratio = 1.0
        
        score = performance_ratio * games_factor * 100
    
    return round(score, 1)


# ---------------------------------------------------
# Analysis
# ---------------------------------------------------

def merge_and_score(
    dvp_rows: List[Dict],
    stats_db: Dict[str, Dict]
) -> List[Play]:
    """Merge DVP shortlist with recent stats and score each play."""
    plays = []
    
    for row in dvp_rows:
        player = row.get("player", "").strip()
        if not player:
            continue
        
        # Find player's recent stats
        stats = find_player_stats(player, stats_db)
        
        recent_avg = None
        games = None
        mpg = None
        
        if stats:
            stat_name = row.get("stat", "")
            recent_avg = get_recent_stat(stats, stat_name)
            games_val = stats.get("games")
            if games_val:
                try:
                    games = int(float(games_val))
                except ValueError:
                    games = None
            
            # Get minutes per game
            mpg_val = stats.get("mpg")
            if mpg_val:
                try:
                    mpg = float(mpg_val)
                except ValueError:
                    mpg = None
        
        play = Play(
            player=player,
            team=row.get("team", ""),
            position=row.get("position", ""),
            opponent=row.get("opponent", ""),
            stat=row.get("stat", ""),
            dvp_value=float(row.get("opp_dvp_value", 0)),
            tier=row.get("tier", ""),
            recent_avg=recent_avg,
            games_played=games,
            mpg=mpg,
        )
        
        play.score = score_play(play)
        plays.append(play)
    
    return plays


def filter_top_plays(
    plays: List[Play],
    top_n: int = TOP_PLAYS_PER_CATEGORY,
    max_per_player: int = 0  # 0 = no limit
) -> Dict[str, List[Play]]:
    """
    Filter and group top plays by category.
    Returns dict with 'overs' and 'unders' lists.
    
    Args:
        plays: List of all plays
        top_n: Number of top plays to return per category
        max_per_player: Max plays allowed per player (0 = no limit)
    """
    # Filter out plays with no recent data or low games
    valid_plays = [
        p for p in plays 
        if p.recent_avg is not None 
        and p.games_played is not None 
        and p.games_played >= MIN_GAMES
    ]
    
    # Split by over/under
    overs = [p for p in valid_plays if p.tier == "WORST"]
    unders = [p for p in valid_plays if p.tier == "BEST"]
    
    # Sort by score (descending)
    overs.sort(key=lambda x: x.score, reverse=True)
    unders.sort(key=lambda x: x.score, reverse=True)
    
    # Group by stat AND player to get variety
    def diversify(plays_list: List[Play], n: int, max_player: int = 0) -> List[Play]:
        """Get top plays with stat and player diversity."""
        result = []
        stat_counts = {}
        player_counts = {}  # Track player occurrences
        
        for p in plays_list:
            stat = p.stat
            player_key = p.player.lower()
            
            stat_counts.setdefault(stat, 0)
            player_counts.setdefault(player_key, 0)
            
            # Skip if player already at limit (when limit is set)
            if max_player > 0 and player_counts[player_key] >= max_player:
                continue
            
            # Allow up to 3 plays per stat initially
            if stat_counts[stat] < 3:
                result.append(p)
                stat_counts[stat] += 1
                player_counts[player_key] += 1
            
            if len(result) >= n:
                break
        
        # If we don't have enough, add more (respecting player limit)
        if len(result) < n:
            for p in plays_list:
                if p not in result:
                    player_key = p.player.lower()
                    # Respect player limit even in overflow
                    if max_player > 0 and player_counts.get(player_key, 0) >= max_player:
                        continue
                    result.append(p)
                    player_counts[player_key] = player_counts.get(player_key, 0) + 1
                if len(result) >= n:
                    break
        
        return result[:n]
    
    return {
        "overs": diversify(overs, top_n, max_per_player),
        "unders": diversify(unders, top_n, max_per_player),
    }


def count_player_occurrences(plays: Dict[str, List[Play]]) -> Dict[str, int]:
    """Count how many times each player appears across all plays."""
    counts = {}
    all_plays = plays.get("overs", []) + plays.get("unders", [])
    for p in all_plays:
        key = p.player.lower()
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------
# Display
# ---------------------------------------------------

def print_plays_table(plays: List[Play], title: str, show_index: bool = True):
    """Print a formatted table of plays."""
    if not plays:
        print(f"\n{title}")
        print("=" * len(title))
        print("No plays found.")
        return
    
    print(f"\n{title}")
    print("=" * 100)
    
    header = f"{'#':>3}  " if show_index else ""
    header += f"{'PLAYER':<18} {'STAT':<5} {'L10':<6} {'MPG':<5} {'DVP':<5} {'ADJ':<5} {'PROJ':<6} {'OPP':<4} {'SCORE':<6}"
    print(header)
    print("-" * 100)
    
    for i, p in enumerate(plays, 1):
        idx = f"{i:>3}  " if show_index else ""
        recent = f"{p.recent_avg:.1f}" if p.recent_avg else "N/A"
        mpg = f"{p.mpg:.0f}" if p.mpg else "?"
        adj_dvp = f"{p.adjusted_dvp:.1f}" if p.adjusted_dvp else "N/A"
        proj = f"{p.projected:.1f}" if p.projected else "N/A"
        print(
            f"{idx}"
            f"{p.player[:17]:<18} "
            f"{p.stat:<5} "
            f"{recent:<6} "
            f"{mpg:<5} "
            f"{p.dvp_value:<5.1f} "
            f"{adj_dvp:<5} "
            f"{proj:<6} "
            f"{p.opponent:<4} "
            f"{p.score:<6.1f}"
        )


def print_summary(plays: Dict[str, List[Play]]):
    """Print the full analysis summary."""
    print("\n" + "=" * 100)
    print("🏀 NBA PROP ANALYZER - TOP PLAYS")
    print("=" * 100)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Min Games Required: {MIN_GAMES}")
    
    # Column explanations
    print("\nColumns:")
    print("  L10  = Last 10 Days Average")
    print("  MPG  = Minutes Per Game (player's share of position)")
    print("  DVP  = What defense allows to ENTIRE position")
    print("  ADJ  = DVP adjusted for player's minutes (DVP × MPG/48)")
    print("  PROJ = Blended projection (60% L10 + 40% ADJ) ← Compare to line!")
    
    print_plays_table(plays["overs"], "📈 TOP OVER PLAYS (Hot Player + Weak Defense)")
    print_plays_table(plays["unders"], "📉 TOP UNDER PLAYS (Cold Player + Strong Defense)")
    
    print("\n" + "-" * 100)
    print("💡 PROJ accounts for player's minutes share of what defense allows")
    print("   Example: DVP=24.8, MPG=31 → ADJ=16.0 (player gets 65% of position stats)")


# ---------------------------------------------------
# Interactive Line Entry
# ---------------------------------------------------

def calculate_edge(play: Play, line: float) -> Dict[str, Any]:
    """
    Calculate edge based on PROJECTED value vs line.
    
    Projection = 60% recent avg + 40% DVP
    This accounts for both player form AND matchup.
    """
    if play.projected is None:
        if play.recent_avg is None:
            return {"edge_pct": None, "recommendation": "NO DATA", "projected": None}
        # Fallback to recent avg if no projection
        projected = play.recent_avg
    else:
        projected = play.projected
    
    diff = projected - line
    edge_pct = (diff / line) * 100 if line > 0 else 0
    
    if play.tier == "WORST":  # OVER play
        if edge_pct > 8:
            rec = "STRONG OVER ✓✓"
        elif edge_pct > 3:
            rec = "LEAN OVER ✓"
        elif edge_pct > -3:
            rec = "TOSS-UP"
        else:
            rec = "PASS (line too high)"
    else:  # UNDER play
        edge_pct = -edge_pct  # Flip for unders
        if edge_pct > 8:
            rec = "STRONG UNDER ✓✓"
        elif edge_pct > 3:
            rec = "LEAN UNDER ✓"
        elif edge_pct > -3:
            rec = "TOSS-UP"
        else:
            rec = "PASS (line too low)"
    
    return {
        "edge_pct": edge_pct,
        "diff": diff,
        "projected": projected,
        "recommendation": rec,
    }


def interactive_mode(plays: Dict[str, List[Play]]):
    """Interactive mode for entering lines and getting recommendations."""
    all_plays = plays["overs"] + plays["unders"]
    
    if not all_plays:
        print("\nNo plays to analyze.")
        return
    
    print("\n" + "=" * 80)
    print("📊 LINE ENTRY MODE")
    print("=" * 80)
    print("Enter play # and line to analyze (e.g., '1 25.5')")
    print("Commands: 'list' to show plays, 'quit' to exit, 'export' to save\n")
    
    analyzed = []
    
    while True:
        try:
            user_input = input("Enter play # and line (or command): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        
        if not user_input:
            continue
        
        if user_input.lower() == "quit":
            break
        
        if user_input.lower() == "list":
            print_plays_table(plays["overs"][:10], "OVERS")
            print_plays_table(plays["unders"][:10], "UNDERS")
            continue
        
        if user_input.lower() == "export":
            export_analyzed(analyzed)
            continue
        
        # Parse input
        parts = user_input.split()
        if len(parts) < 2:
            print("  ⚠️  Format: <play #> <line>  (e.g., '1 25.5')")
            continue
        
        try:
            play_num = int(parts[0])
            line = float(parts[1])
        except ValueError:
            print("  ⚠️  Invalid input. Use: <play #> <line>")
            continue
        
        if play_num < 1 or play_num > len(all_plays):
            print(f"  ⚠️  Play # must be between 1 and {len(all_plays)}")
            continue
        
        play = all_plays[play_num - 1]
        result = calculate_edge(play, line)
        
        direction = "OVER" if play.tier == "WORST" else "UNDER"
        
        print(f"\n  {play.player} - {play.stat} {direction}")
        print(f"  ├─ Recent L10: {play.recent_avg:.1f}")
        print(f"  ├─ DVP allows: {play.dvp_value:.1f}")
        print(f"  ├─ Projection: {result['projected']:.1f} (60% L10 + 40% DVP)")
        print(f"  ├─ Line: {line}")
        print(f"  ├─ Edge: {result['edge_pct']:+.1f}%")
        print(f"  └─ 💡 {result['recommendation']}\n")
        
        play.line = line
        play.edge_pct = result["edge_pct"]
        analyzed.append((play, result))
    
    if analyzed:
        export_analyzed(analyzed)


def export_analyzed(analyzed: List[tuple]):
    """Export analyzed plays (with lines entered) to CSV."""
    if not analyzed:
        print("No plays to export.")
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    date_dir = get_date_output_dir(today)
    os.makedirs(date_dir, exist_ok=True)
    filename = os.path.join(date_dir, f"analyzed_plays_{today}.csv")
    
    fieldnames = [
        "player", "team", "opponent", "stat", "direction",
        "recent_avg", "dvp_value", "projected", "line", "edge_pct", "recommendation"
    ]
    
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for play, result in analyzed:
            writer.writerow({
                "player": play.player,
                "team": play.team,
                "opponent": play.opponent,
                "stat": play.stat,
                "direction": "OVER" if play.tier == "WORST" else "UNDER",
                "recent_avg": play.recent_avg,
                "dvp_value": play.dvp_value,
                "projected": play.projected,
                "line": play.line,
                "edge_pct": round(result["edge_pct"], 1) if result["edge_pct"] else None,
                "recommendation": result["recommendation"],
            })
    
    print(f"\n✅ Exported {len(analyzed)} analyzed plays to {filename}")


def export_top_plays(plays: Dict[str, List[Play]]):
    """Auto-export all top plays to CSV (without lines)."""
    all_plays = plays["overs"] + plays["unders"]
    
    if not all_plays:
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    date_dir = get_date_output_dir(today)
    os.makedirs(date_dir, exist_ok=True)
    filename = os.path.join(date_dir, f"top_plays_{today}.csv")
    
    fieldnames = [
        "rank", "player", "team", "position", "opponent", "stat", "direction",
        "recent_avg", "mpg", "dvp_value", "adjusted_dvp", "projected", "score"
    ]
    
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # Write overs first
        for i, play in enumerate(plays["overs"], 1):
            writer.writerow({
                "rank": i,
                "player": play.player,
                "team": play.team,
                "position": play.position,
                "opponent": play.opponent,
                "stat": play.stat,
                "direction": "OVER",
                "recent_avg": play.recent_avg,
                "mpg": play.mpg,
                "dvp_value": play.dvp_value,
                "adjusted_dvp": play.adjusted_dvp,
                "projected": play.projected,
                "score": play.score,
            })
        
        # Then unders
        for i, play in enumerate(plays["unders"], 1):
            writer.writerow({
                "rank": i,
                "player": play.player,
                "team": play.team,
                "position": play.position,
                "opponent": play.opponent,
                "stat": play.stat,
                "direction": "UNDER",
                "recent_avg": play.recent_avg,
                "mpg": play.mpg,
                "dvp_value": play.dvp_value,
                "adjusted_dvp": play.adjusted_dvp,
                "projected": play.projected,
                "score": play.score,
            })
    
    print(f"\n📁 Auto-exported {len(all_plays)} top plays to {filename}")


# ---------------------------------------------------
# Main
# ---------------------------------------------------

def get_date_output_dir(date_str: str = None) -> str:
    """Get the output directory for a specific date."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(OUTPUT_DIR, date_str)


def extract_date_from_filename(filepath: str) -> str:
    """Extract date (YYYY-MM-DD) from filename."""
    import re
    filename = os.path.basename(filepath)
    # Match date pattern in filename
    match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    return "0000-00-00"


def find_latest_file(prefix: str, directory: str = OUTPUT_DIR) -> Optional[str]:
    """Find the most recent file with given prefix, searching in date subfolders."""
    files = []
    
    # First, check if directory has date subfolders
    if os.path.exists(directory):
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            
            # Check in date subfolders (YYYY-MM-DD format)
            if os.path.isdir(item_path) and len(item) == 10 and item[4] == '-':
                for f in os.listdir(item_path):
                    if f.startswith(prefix) and f.endswith(".csv"):
                        files.append(os.path.join(item_path, f))
            
            # Also check root directory for backwards compatibility
            elif os.path.isfile(item_path):
                if item.startswith(prefix) and item.endswith(".csv"):
                    files.append(item_path)
    
    if not files:
        return None
    
    # Sort by date in filename (newest first), not modification time
    files.sort(key=extract_date_from_filename, reverse=True)
    return files[0]


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="NBA Prop Analyzer")
    parser.add_argument("--dvp", help="DVP shortlist CSV file")
    parser.add_argument("--stats", help="Last N days stats CSV file")
    parser.add_argument("--top", type=int, default=TOP_PLAYS_PER_CATEGORY,
                        help=f"Top plays per category (default: {TOP_PLAYS_PER_CATEGORY})")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Enter interactive line entry mode")
    
    args = parser.parse_args()
    
    # Find files
    dvp_file = args.dvp or find_latest_file("dvp_shortlist_results_")
    stats_file = args.stats or find_latest_file("last_")
    
    if not dvp_file:
        print("❌ Could not find DVP shortlist file. Run prop_dvp_shortlist.py first.")
        sys.exit(1)
    
    if not stats_file:
        print("❌ Could not find last N days stats file. Run last_n_days_scraper.py first.")
        sys.exit(1)
    
    print(f"📂 DVP File: {dvp_file}")
    print(f"📂 Stats File: {stats_file}")
    
    # Load data
    dvp_rows = load_dvp_shortlist(dvp_file)
    stats_db = load_last_n_days(stats_file)
    
    print(f"📊 Loaded {len(dvp_rows)} DVP plays, {len(stats_db)} players with stats")
    
    # Merge and score
    plays = merge_and_score(dvp_rows, stats_db)
    
    # Filter top plays
    top_plays = filter_top_plays(plays, args.top)
    
    # Print summary
    print_summary(top_plays)
    
    # Auto-export top plays
    export_top_plays(top_plays)
    
    # Interactive mode
    if args.interactive:
        interactive_mode(top_plays)
    else:
        print("\n💡 Run with -i flag for interactive line entry mode")
        print(f"   python prop_analyzer.py -i --top {args.top}")


if __name__ == "__main__":
    main()

