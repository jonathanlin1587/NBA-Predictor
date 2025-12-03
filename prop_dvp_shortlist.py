import csv
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime
from typing import List, Dict, Any


# ---------------------------------------------------
# File paths (edit date if needed)
# ---------------------------------------------------
DVP_FILE = "outputs/dvp_summary_2025-12-03.txt"
LINEUPS_FILE = "outputs/lineups_2025-12-03.csv"
SCHEDULE_FILE = "outputs/schedule_2025-12-03.csv"

# ---------------------------------------------------
# Data structures
# ---------------------------------------------------

@dataclass
class Player:
    name: str
    team: str       # e.g. "TOR"
    opp: str        # opponent, e.g. "IND"
    position: str   # "PG", "SG", "SF", "PF", "C"
    stats: List[str]  # which stats to evaluate: ["PTS", "REB", "AST", "PRA", ...]


# ---------------------------------------------------
# Step 1: Parse DvP file
# ---------------------------------------------------

def parse_dvp(text: str) -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    """
    Parse the DvP summary text into a nested dict:
    dvp[stat][position][team] = {
        "value": float,   # amount allowed
        "tier": "WORST" or "BEST"
    }
    """
    dvp: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    stat = None
    pos = None
    mode = None  # 'WORST' or 'BEST'
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Section headers like "### PTS ###"
        m = re.match(r"###\s+([A-Z]+)\s+###", line)
        if m:
            stat = m.group(1)
            dvp.setdefault(stat, {})
            i += 1
            continue

        # Position header like "C — WORST (overs)"
        m = re.match(r"([A-Z]{1,2})\s+—\s+(WORST|BEST)", line)
        if m and stat:
            pos = m.group(1)     # PG/SG/SF/PF/C
            mode = m.group(2)    # WORST or BEST
            dvp[stat].setdefault(pos, {})

            # Skip the next header line (e.g. "TEAM  PTS")
            i += 2

            # Pull lines until blank or non-matching
            while i < len(lines):
                l2 = lines[i].rstrip()
                if not l2.strip():
                    break

                # Example data line: " LAC 25.8"
                m2 = re.match(r"\s*([A-Z]{2,3})\s+([\d.]+)", l2)
                if m2:
                    team = m2.group(1)
                    val = float(m2.group(2))
                    dvp[stat][pos][team] = {"value": val, "tier": mode}
                    i += 1
                    continue
                else:
                    break
            continue

        i += 1

    return dvp


# ---------------------------------------------------
# Step 2: Read schedule & build team->opponent map
# ---------------------------------------------------

def load_schedule(filename: str) -> List[Dict[str, str]]:
    """
    Load the schedule CSV into a list of dicts.

    Adjust the column names here to match your file if needed.
    Expected minimum columns:
      - 'home'
      - 'away'
    """
    games = []
    with open(filename, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            games.append(row)
    return games


def build_team_opponent_map(games: List[Dict[str, str]]) -> Dict[str, str]:
    """
    From the schedule, map each team to its opponent:
      {"TOR": "IND", "IND": "TOR", ...}
    """
    opp_map: Dict[str, str] = {}
    for g in games:
        # Adjust keys if your schedule CSV uses different column names
        home = g.get("home") or g.get("home_team") or g.get("Home") or ""
        away = g.get("away") or g.get("away_team") or g.get("Away") or ""
        home = home.strip()
        away = away.strip()
        if not home or not away:
            continue

        opp_map[home] = away
        opp_map[away] = home

    return opp_map


# ---------------------------------------------------
# Step 3: Read lineups & build Player objects
# ---------------------------------------------------

def load_lineups(filename: str) -> List[Dict[str, str]]:
    """
    Load the lineups CSV into a list of dicts.

    Expected columns (adapt if needed):
      - 'team'   : team code (e.g. TOR)
      - 'opp'    : opponent code (if present)
      - 'position' : PG/SG/SF/PF/C
      - 'player' : player full name
      - 'status' : (optional) Out / Q / etc.
    """
    rows = []
    with open(filename, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def build_players_from_lineups(
    lineup_rows: List[Dict[str, str]],
    team_opponent: Dict[str, str],
    stats_for_all: Optional[List[str]] = None,
    watchlist: Optional[List[str]] = None,
) -> List[Player]:
    """
    Convert lineup rows into Player objects.

    - If lineup has an 'opp' column, we use that.
    - Otherwise, we use team_opponent map from the schedule.
    - If watchlist is given, only include players whose names are in it.
    """
    if stats_for_all is None:
        stats_for_all = ["PTS", "REB", "AST", "PRA"]

    watch_set = set(name.lower() for name in (watchlist or []))
    players: List[Player] = []

    for row in lineup_rows:
        name = (row.get("player") or "").strip()
        team = (row.get("team") or "").strip()
        pos = (row.get("position") or "").strip().upper()
        status = (row.get("status") or "").strip()

        if not name or not team:
            continue

        # Derive opponent: prefer 'opp' column if present, else schedule map
        opp = (row.get("opp") or "").strip()
        if not opp:
            opp = team_opponent.get(team, "")
        if not opp:
            # If still blank, we can't use this row
            continue

        # Skip obvious OUT players if status says so
        if "out" in status.lower():
            continue

        # Limit to real positions
        if pos not in {"PG", "SG", "SF", "PF", "C"}:
            continue

        # If using a watchlist, only keep those names
        if watch_set and name.lower() not in watch_set:
            continue

        players.append(
            Player(
                name=name,
                team=team,
                opp=opp,
                position=pos,
                stats=stats_for_all.copy(),
            )
        )

    return players


# ---------------------------------------------------
# Step 4: Evaluate players vs DvP
# ---------------------------------------------------

def evaluate_player_matchups(
    players: List[Player],
    dvp: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]],
    stats_of_interest: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    For each player, look up the opponent and DvP for each desired stat.
    Returns a list of candidate rows.
    """
    results = []

    for p in players:
        for stat in p.stats:
            if stats_of_interest and stat not in stats_of_interest:
                continue

            if stat not in dvp or p.position not in dvp[stat]:
                continue

            opp_dvp = dvp[stat][p.position].get(p.opp)
            if not opp_dvp:
                continue

            value = opp_dvp["value"]
            tier = opp_dvp["tier"]  # "WORST" (overs) or "BEST" (unders)

            edge_score = 1 if tier == "WORST" else -1

            results.append(
                {
                    "player": p.name,
                    "team": p.team,
                    "position": p.position,
                    "opponent": p.opp,
                    "stat": stat,
                    "opp_dvp_value": value,
                    "tier": tier,
                    "edge_score": edge_score,
                }
            )

    return results


def print_shortlist(
    candidates: List[Dict[str, Any]],
    overs: bool = True,
    max_total: int = 10,
) -> None:
    """
    Clean, readable display of the DvP matchup advantages.

    Logic:
    - Filter to overs or unders using edge_score sign.
    - Group by stat (PTS/REB/AST/PRA/etc.).
    - Start by taking top 4 per stat by DvP.
    - If > max_total, reduce to 3, then 2, then 1.
    - If still > max_total when per-stat limit = 1, take overall top `max_total`.
    """

    # 1) Filter by over/under side
    if overs:
        filtered = [c for c in candidates if c["edge_score"] > 0]
        title = "OVER-Friendly Matchups"
        sort_reverse = True       # higher DvP = better for overs
    else:
        filtered = [c for c in candidates if c["edge_score"] < 0]
        title = "UNDER-Friendly Matchups"
        sort_reverse = False      # lower DvP = better for unders

    if not filtered:
        print(f"\n{title}")
        print("=" * len(title))
        print("No candidates found.")
        return

    # 2) Group by stat
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in filtered:
        stat = row["stat"]
        grouped.setdefault(stat, []).append(row)

    # 3) Sort each stat group by DvP (opp_dvp_value)
    for stat, rows in grouped.items():
        rows.sort(key=lambda c: c["opp_dvp_value"], reverse=sort_reverse)

    # Optional: stat priority (so PRA/PTS show first, etc.)
    stat_priority = ["PRA", "PTS", "REB", "AST"]
    # Stats not in priority list will be appended at the end
    remaining_stats = [s for s in grouped.keys() if s not in stat_priority]
    ordered_stats = [s for s in stat_priority if s in grouped] + sorted(remaining_stats)

    # 4) Start with top 4 per stat, then drop to 3, 2, 1 if too many
    per_stat_limit = 4
    selected: List[Dict[str, Any]] = []

    while per_stat_limit >= 1:
        selected = []
        for stat in ordered_stats:
            rows = grouped[stat]
            selected.extend(rows[:per_stat_limit])

        if len(selected) <= max_total or per_stat_limit == 1:
            break

        per_stat_limit -= 1

    # 5) If still too many when per_stat_limit == 1, trim to overall top `max_total`
    if len(selected) > max_total:
        selected.sort(key=lambda c: c["opp_dvp_value"], reverse=sort_reverse)
        selected = selected[:max_total]

    # 6) Final sort for clean printing (by DvP within stat priority)
    #    This keeps your nicest DvP plays at the top of the printout.
    def sort_key(row: Dict[str, Any]):
        stat = row["stat"]
        try:
            stat_index = ordered_stats.index(stat)
        except ValueError:
            stat_index = len(ordered_stats)
        # For overs: higher DvP first; for unders: lower first
        dvp = row["opp_dvp_value"]
        return (stat_index, -dvp if sort_reverse else dvp)

    selected.sort(key=sort_key)

    # 7) Print
    print("\n" + title)
    print("=" * len(title))
    print(f"{'PLAYER':22} {'TEAM':5} {'POS':4} {'OPP':5} {'STAT':5} {'DVP'}")
    print("-" * 55)

    for row in selected:
        print(
            f"{row['player'][:22]:22} "
            f"{row['team']:5} "
            f"{row['position']:4} "
            f"{row['opponent']:5} "
            f"{row['stat']:5} "
            f"{row['opp_dvp_value']:>4}"
        )

def export_results_to_csv(candidates: List[Dict[str, Any]], filename: str = None):
    """
    Export candidate matchups to a CSV file with date in filename.
    """
    if filename is None:
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"outputs/dvp_shortlist_results_{today}.csv"
    
    if not candidates:
        print("No candidates to export.")
        return
    
    try:
        with open(filename, "w", newline="") as f:
            fieldnames = ["player", "team", "position", "opponent", "stat", "opp_dvp_value", "tier", "edge_score"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(candidates)
        print(f"\n✓ Results exported to {filename}")
    except IOError as e:
        print(f"Error writing to {filename}: {e}")

# ---------------------------------------------------
# Main
# ---------------------------------------------------

def main():
    # 1) DvP
    with open(DVP_FILE, "r") as f:
        dvp_text = f.read()
    dvp = parse_dvp(dvp_text)

    # 2) Schedule -> team->opponent
    games = load_schedule(SCHEDULE_FILE)
    team_opponent = build_team_opponent_map(games)

    # 3) Lineups -> players
    lineup_rows = load_lineups(LINEUPS_FILE)

    # Optional: restrict to a watchlist of players you actually care about
    watchlist = [
        # Add or remove names as you like; comment this list out to scan all players
        # "Luka Doncic",
        # "Jayson Tatum",
    ]

    players = build_players_from_lineups(
        lineup_rows=lineup_rows,
        team_opponent=team_opponent,
        stats_for_all=["PTS", "REB", "AST", "PRA"],  # tweak as needed
        watchlist=watchlist,  # change to None to include everyone
    )

    # 4) Evaluate DvP matchups
    candidates = evaluate_player_matchups(
        players=players,
        dvp=dvp,
        stats_of_interest=["PTS", "REB", "AST", "PRA"],
    )

    # 5) Print over/under friendly spots
    print_shortlist(candidates, overs=True, max_total=10)
    print_shortlist(candidates, overs=False, max_total=10)

    # 6) Export to CSV
    export_results_to_csv(candidates)

if __name__ == "__main__":
    main()
