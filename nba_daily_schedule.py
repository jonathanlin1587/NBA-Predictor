# nba_daily_schedule.py
import os, sys, json, requests, pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
OUTPUT_DIR = "outputs"

def fetch_schedule(yyyymmdd: str) -> dict:
    r = requests.get(ESPN_SCOREBOARD, params={"dates": yyyymmdd}, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_games(data: dict, tz="America/Toronto") -> pd.DataFrame:
    rows = []
    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        start_utc = datetime.fromisoformat(ev["date"].replace("Z","+00:00"))
        start_local = start_utc.astimezone(ZoneInfo(tz))

        home = next(t for t in comp["competitors"] if t["homeAway"]=="home")
        away = next(t for t in comp["competitors"] if t["homeAway"]=="away")

        nets = [b["names"][0] for b in comp.get("broadcasts", []) if b.get("names")]
        network = ", ".join(nets) if nets else ""

        spread = ou = moneyline_home = moneyline_away = ""
        if comp.get("odds"):
            o = comp["odds"][0]
            spread = o.get("details", "")
            ou = f"O/U {o.get('overUnder')}" if o.get("overUnder") else ""
            moneyline_home = o.get("homeTeamOdds", {}).get("moneyLine", "")
            moneyline_away = o.get("awayTeamOdds", {}).get("moneyLine", "")

        rows.append({
            "date_local": start_local.date().isoformat(),
            "time_local": start_local.strftime("%-I:%M %p"),
            "away": away["team"]["abbreviation"],
            "home": home["team"]["abbreviation"],
            "network": network,
            "spread": spread,
            "over_under": ou,
            "ml_home": moneyline_home,
            "ml_away": moneyline_away,
            "game_id": ev.get("id","")
        })
    return pd.DataFrame(rows).sort_values(["time_local","away"])

def main():
    if len(sys.argv) >= 2:
        yyyymmdd = sys.argv[1]
    else:
        yyyymmdd = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y%m%d")

    data = fetch_schedule(yyyymmdd)
    df = parse_games(data)

    # --- make sure output folder exists ---
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today_str = datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%Y-%m-%d")
    out_csv = os.path.join(OUTPUT_DIR, f"schedule_{today_str}.csv")

    df.to_csv(out_csv, index=False)
    print(f"✅ Saved {out_csv}\n")
    print(df.to_string(index=False))

if __name__ == "__main__":
    main()
