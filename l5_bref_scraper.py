import argparse
import json
import sys
from typing import List, Dict

import requests
from bs4 import BeautifulSoup, Comment


def _find_gamelog_table(soup: BeautifulSoup):
    """
    Find the regular-season game log table on a Basketball-Reference
    game log page.

    Strategy:
    1. Try id='pgl_basic' (old behavior).
    2. Otherwise, look for any table with a header cell where
       data-stat='date_game'.
    3. If still not found, search inside HTML comments too.
    """

    # 1) Direct: old/standard id
    table = soup.find("table", id="pgl_basic")
    if table is not None:
        return table

    # 2) Any visible table with a 'date_game' header
    for t in soup.find_all("table"):
        if t.find("th", {"data-stat": "date_game"}) is not None:
            return t

    # 3) Some tables are hidden inside HTML comments
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for c in comments:
        # quick skip if it clearly doesn't contain a table
        if "table" not in c:
            continue
        try:
            comment_soup = BeautifulSoup(c, "html.parser")
        except Exception:
            continue

        # Try id directly
        table = comment_soup.find("table", id="pgl_basic")
        if table and table.find("th", {"data-stat": "date_game"}):
            return table

        # Or any table with date_game header
        for t in comment_soup.find_all("table"):
            if t.find("th", {"data-stat": "date_game"}) is not None:
                return t

    return None


def fetch_last_5_games_bref(gamelog_url: str) -> List[Dict]:
    """
    Scrape the last 5 *played* regular-season games from a
    Basketball-Reference player game log page.
    """
    resp = requests.get(gamelog_url, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Optional: nicer error when no stats yet
    if "No information is available for this page" in soup.get_text():
        raise RuntimeError(
            "Basketball-Reference doesn't have a game log for this season yet."
        )

    table = _find_gamelog_table(soup)
    if table is None:
        raise RuntimeError("Could not find the game log table on this page.")

    tbody = table.find("tbody")
    if tbody is None:
        raise RuntimeError("Could not find <tbody> inside game log table.")

    games: List[Dict] = []

    for row in tbody.find_all("tr"):
        # Many rows in BRef are separators or blank; skip those
        if row.find("td", {"data-stat": "date_game"}) is None:
            continue

        def get_stat(stat_name: str, default: str = "") -> str:
            cell = row.find("td", {"data-stat": stat_name})
            if cell is None:
                return default
            return cell.get_text(strip=True)

        mp = get_stat("mp")
        # Skip games where player did not actually play
        if mp in ("", "Inactive", "Did Not Dress", "Did Not Play",
                  "Not With Team", "Player Suspended"):
            continue

        def get_int_stat(stat_name: str) -> int:
            text = get_stat(stat_name, default="0")
            try:
                return int(text) if text not in ("", None) else 0
            except ValueError:
                return 0

        game = {
            "date": get_stat("date_game"),
            "team": get_stat("team_id"),
            "home_away": get_stat("game_location"),  # "" for home, "@" for away
            "opp": get_stat("opp_id"),
            "result": get_stat("game_result"),

            "mp": mp,
            "fg": get_int_stat("fg"),
            "fga": get_int_stat("fga"),
            "fg_pct": get_stat("fg_pct"),
            "fg3": get_int_stat("fg3"),
            "fg3a": get_int_stat("fg3a"),
            "fg3_pct": get_stat("fg3_pct"),
            "ft": get_int_stat("ft"),
            "fta": get_int_stat("fta"),
            "ft_pct": get_stat("ft_pct"),

            "orb": get_int_stat("orb"),
            "drb": get_int_stat("drb"),
            "trb": get_int_stat("trb"),
            "ast": get_int_stat("ast"),
            "stl": get_int_stat("stl"),
            "blk": get_int_stat("blk"),
            "tov": get_int_stat("tov"),
            "pf": get_int_stat("pf"),
            "pts": get_int_stat("pts"),
            "game_score": get_stat("game_score"),
        }

        games.append(game)

    if not games:
        raise RuntimeError("No played games found in this game log.")

    # BRef lists games in chronological order → last 5 are most recent
    last_5 = games[-5:]
    return last_5


def main():
    parser = argparse.ArgumentParser(
        description="Scrape last 5 NBA games for a player from Basketball-Reference."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Basketball-Reference game log URL, e.g. "
             "https://www.basketball-reference.com/players/e/edwaran01/gamelog/2026",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of pretty text.",
    )

    args = parser.parse_args()

    try:
        last_5 = fetch_last_5_games_bref(args.url)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(last_5, indent=2))
    else:
        print(f"Last 5 games from {args.url}:\n")
        for g in last_5:
            ha = "vs" if g["home_away"] == "" else "@"
            line = (
                f"{g['date']}: {ha} {g['opp']} ({g['result']}) "
                f"{g['pts']} PTS, {g['trb']} REB, {g['ast']} AST, "
                f"{g['stl']} STL, {g['blk']} BLK, {g['tov']} TO "
                f"in {g['mp']} MIN"
            )
            print(line)


if __name__ == "__main__":
    main()
