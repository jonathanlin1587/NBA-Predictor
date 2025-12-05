#!/usr/bin/env python3
"""
NBA Prop Analyzer - Web UI
Run with: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import os
import json
import subprocess
import sys
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

# Import from prop_analyzer
from prop_analyzer import (
    load_dvp_shortlist,
    load_last_n_days,
    merge_and_score,
    filter_top_plays,
    find_latest_file,
    calculate_projection,
    OUTPUT_DIR,
    MIN_GAMES,
)


@st.cache_data(ttl=300)
def load_dvp_ratings():
    """
    Load today's full DVP ratings from JSON.
    Structure: dvp[stat][position][team] = {"value": float, "rank": int, "tier": str}
    """
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Try loading full JSON first (has all 30 teams)
    json_file = os.path.join(OUTPUT_DIR, today, f"dvp_full_{today}.json")
    if os.path.exists(json_file):
        try:
            with open(json_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    
    # Fallback: parse the summary text file (only has top/bottom 5)
    txt_file = os.path.join(OUTPUT_DIR, today, f"dvp_summary_{today}.txt")
    if os.path.exists(txt_file):
        return parse_dvp_summary(txt_file)
    
    return {}


def parse_dvp_summary(filepath: str) -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    """
    Fallback parser for old-style DVP summary text files.
    Only contains top/bottom 5 teams per category.
    """
    if not os.path.exists(filepath):
        return {}
    
    with open(filepath, "r") as f:
        text = f.read()
    
    dvp = {}
    stat = None
    pos = None
    mode = None
    rank = 0
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        m = re.match(r"###\s+([A-Z0-9]+)\s+###", line)
        if m:
            stat = m.group(1)
            dvp.setdefault(stat, {})
            i += 1
            continue

        m = re.match(r"([A-Z]{1,2})\s+—\s+(WORST|BEST)", line)
        if m and stat:
            pos = m.group(1)
            mode = m.group(2)
            dvp[stat].setdefault(pos, {})
            rank = 0
            i += 2

            while i < len(lines):
                l2 = lines[i].rstrip()
                if not l2.strip():
                    break

                m2 = re.match(r"\s*([A-Z]{2,3})\s+([\d.]+)", l2)
                if m2:
                    team = m2.group(1)
                    val = float(m2.group(2))
                    rank += 1
                    dvp[stat][pos][team] = {"value": val, "tier": mode, "rank": rank}
                    i += 1
                    continue
                else:
                    break
            continue

        i += 1

    return dvp

# ---------------------------------------------------
# Config & Constants
# ---------------------------------------------------
PICKS_FILE = os.path.join(OUTPUT_DIR, "my_picks.json")
PARLAYS_FILE = os.path.join(OUTPUT_DIR, "parlays.json")

# Scripts to run for data refresh
DATA_SCRIPTS = [
    ("nba_dvp_scraper.py", "DVP Data"),
    ("nba_daily_schedule.py", "Schedule"),
    ("lineups_scraper.py", "Lineups"),
    ("last_n_days_scraper.py", "Player Stats"),
    ("odds_scraper.py", "Live Odds"),
    ("prop_dvp_shortlist.py", "DVP Shortlist"),
]

st.set_page_config(
    page_title="NBA Prop Analyzer",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------
# Custom CSS
# ---------------------------------------------------
st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: 700; color: #1E3A5F; margin-bottom: 0; }
    .sub-header { font-size: 1.1rem; color: #666; margin-top: 0; }
    .play-card { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 1.5rem; border-radius: 12px; color: white; margin: 1rem 0; }
    .play-title { font-size: 1.4rem; font-weight: 600; margin-bottom: 0.5rem; }
    div[data-testid="stDataFrame"] { width: 100%; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------
# Data Fetching Functions
# ---------------------------------------------------
def check_todays_data_exists() -> Dict[str, bool]:
    """Check which of today's data files exist."""
    today = datetime.now().strftime("%Y-%m-%d")
    today_dir = os.path.join(OUTPUT_DIR, today)
    return {
        "dvp_summary": os.path.exists(os.path.join(today_dir, f"dvp_summary_{today}.txt")),
        "schedule": os.path.exists(os.path.join(today_dir, f"schedule_{today}.csv")),
        "lineups": os.path.exists(os.path.join(today_dir, f"lineups_{today}.csv")),
        "player_stats": os.path.exists(os.path.join(today_dir, f"last_10_days_{today}.csv")),
        "odds": os.path.exists(os.path.join(today_dir, f"odds_best_{today}.csv")),
        "dvp_shortlist": os.path.exists(os.path.join(today_dir, f"dvp_shortlist_results_{today}.csv")),
    }


def run_script(script_name: str) -> tuple:
    """Run a Python script and return success status and output."""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script_name)
    if not os.path.exists(script_path):
        return False, f"Script not found: {script_path}"
    try:
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=120, cwd=os.path.dirname(script_path))
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Script timed out"
    except Exception as e:
        return False, str(e)


def run_all_scrapers(progress_callback=None) -> Dict[str, tuple]:
    """Run all data scrapers in order."""
    results = {}
    for i, (script, name) in enumerate(DATA_SCRIPTS):
        if progress_callback:
            progress_callback(i / len(DATA_SCRIPTS), f"Running {name}...")
        success, output = run_script(script)
        results[name] = (success, output)
    if progress_callback:
        progress_callback(1.0, "Complete!")
    return results


# ---------------------------------------------------
# Persistent Storage Functions
# ---------------------------------------------------
def load_picks() -> List[Dict]:
    if os.path.exists(PICKS_FILE):
        try:
            with open(PICKS_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []


def save_picks(picks: List[Dict]):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(PICKS_FILE, "w") as f:
        json.dump(picks, f, indent=2)


def add_pick(pick: Dict):
    picks = load_picks()
    pick["added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    pick["result"] = "pending"
    pick["profit"] = 0.0
    picks.append(pick)
    save_picks(picks)


def remove_pick(index: int):
    picks = load_picks()
    if 0 <= index < len(picks):
        picks.pop(index)
        save_picks(picks)


def update_pick_result(index: int, result: str, profit: float):
    picks = load_picks()
    if 0 <= index < len(picks):
        picks[index]["result"] = result
        picks[index]["profit"] = profit
        save_picks(picks)


def clear_all_picks():
    save_picks([])


def load_parlays() -> List[Dict]:
    if os.path.exists(PARLAYS_FILE):
        try:
            with open(PARLAYS_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []


def save_parlays(parlays: List[Dict]):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(PARLAYS_FILE, "w") as f:
        json.dump(parlays, f, indent=2)


# ---------------------------------------------------
# Data Loading (Cached)
# ---------------------------------------------------
@st.cache_data(ttl=300)
def load_data():
    dvp_file = find_latest_file("dvp_shortlist_results_")
    stats_file = find_latest_file("last_")
    if not dvp_file or not stats_file:
        return None, None, None, None
    dvp_rows = load_dvp_shortlist(dvp_file)
    stats_db = load_last_n_days(stats_file)
    plays = merge_and_score(dvp_rows, stats_db)
    return plays, dvp_file, stats_file, stats_db


@st.cache_data(ttl=300)
def load_lineups_data():
    today = datetime.now().strftime("%Y-%m-%d")
    lineups_file = os.path.join(OUTPUT_DIR, today, f"lineups_{today}.csv")
    if os.path.exists(lineups_file):
        return pd.read_csv(lineups_file)
    return None


@st.cache_data(ttl=300)
def load_schedule_data():
    today = datetime.now().strftime("%Y-%m-%d")
    schedule_file = os.path.join(OUTPUT_DIR, today, f"schedule_{today}.csv")
    if os.path.exists(schedule_file):
        return pd.read_csv(schedule_file)
    return None


@st.cache_data(ttl=300)
def load_odds_data():
    today = datetime.now().strftime("%Y-%m-%d")
    odds_file = os.path.join(OUTPUT_DIR, today, f"odds_best_{today}.csv")
    if os.path.exists(odds_file):
        return pd.read_csv(odds_file)
    return None


# ---------------------------------------------------
# Utility Functions
# ---------------------------------------------------
def american_to_decimal(american_odds: int) -> float:
    if american_odds > 0:
        return (american_odds / 100) + 1
    else:
        return (100 / abs(american_odds)) + 1


def decimal_to_implied_prob(decimal_odds: float) -> float:
    return 1 / decimal_odds


def calculate_kelly(win_prob: float, decimal_odds: float, fraction: float = 0.25) -> Dict[str, Any]:
    b = decimal_odds - 1
    p = win_prob
    q = 1 - p
    kelly_full = (b * p - q) / b if b > 0 else 0
    kelly_full = max(0, min(kelly_full, 0.25))
    kelly_adjusted = kelly_full * fraction
    return {
        "kelly_full": kelly_full * 100,
        "kelly_adjusted": kelly_adjusted * 100,
        "fraction_used": fraction,
    }


def estimate_win_probability(edge_pct: float, base_prob: float = 0.50) -> float:
    prob_boost = edge_pct * 0.005
    return max(0.45, min(0.75, base_prob + prob_boost))


def calculate_edge(projected: float, line: float, direction: str) -> Dict[str, Any]:
    if line <= 0:
        return {"edge_pct": 0, "recommendation": "Invalid line", "color": "gray"}
    diff = projected - line
    edge_pct = (diff / line) * 100
    if direction == "OVER":
        if edge_pct > 8:
            return {"edge_pct": edge_pct, "recommendation": "STRONG OVER ✓✓", "color": "green"}
        elif edge_pct > 3:
            return {"edge_pct": edge_pct, "recommendation": "LEAN OVER ✓", "color": "blue"}
        elif edge_pct > -3:
            return {"edge_pct": edge_pct, "recommendation": "TOSS-UP", "color": "orange"}
        else:
            return {"edge_pct": edge_pct, "recommendation": "PASS", "color": "gray"}
    else:
        edge_pct = -edge_pct
        if edge_pct > 8:
            return {"edge_pct": edge_pct, "recommendation": "STRONG UNDER ✓✓", "color": "green"}
        elif edge_pct > 3:
            return {"edge_pct": edge_pct, "recommendation": "LEAN UNDER ✓", "color": "blue"}
        elif edge_pct > -3:
            return {"edge_pct": edge_pct, "recommendation": "TOSS-UP", "color": "orange"}
        else:
            return {"edge_pct": edge_pct, "recommendation": "PASS", "color": "gray"}


def calculate_profit(pick: Dict) -> float:
    result = pick.get("result", "pending")
    bet = pick.get("bet_amount", 0)
    odds = pick.get("odds", -110)
    if result == "won":
        decimal_odds = american_to_decimal(odds)
        return bet * (decimal_odds - 1)
    elif result == "lost":
        return -bet
    return 0.0


# ---------------------------------------------------
# Player Analyzer Function
# ---------------------------------------------------
def show_player_analyzer(player_name: str, player_data: Dict, all_plays: List, bankroll: float, odds_df):
    """Show full analyzer view for a specific player."""
    st.markdown(f"## 🔍 Player Analyzer: {player_name}")
    
    # Load DVP ratings
    dvp_ratings = load_dvp_ratings()
    
    # Load lineups to get player position and opponent
    lineups_df = load_lineups_data()
    
    # Get player's team, position, opponent from plays or lineups
    player_team = ""
    player_opponent = ""
    player_position = ""
    
    # First try from plays
    for play in all_plays:
        if player_name.lower() in play.player.lower():
            player_team = play.team
            player_opponent = play.opponent
            player_position = play.position
            break
    
    # If not found in plays, try lineups
    if lineups_df is not None and not lineups_df.empty and (not player_team or not player_position):
        player_last = player_name.lower().split()[-1]
        match = lineups_df[lineups_df["player"].str.lower().str.contains(player_last, na=False)]
        if not match.empty:
            row = match.iloc[0]
            player_team = row.get("team", player_team)
            player_position = row.get("position", player_position)
            # Get opponent from away/home teams
            if row.get("team") == row.get("away_team"):
                player_opponent = row.get("home_team", player_opponent)
            else:
                player_opponent = row.get("away_team", player_opponent)
    
    # Helper to safely get float from player_data (handles both key styles)
    def get_stat(primary_key, fallback_key=None):
        val = player_data.get(primary_key)
        if val is None and fallback_key:
            val = player_data.get(fallback_key)
        try:
            return float(val) if val is not None else 0.0
        except (ValueError, TypeError):
            return 0.0
    
    # Get stats using correct keys from CSV: pts, reb, ast, fg3, stl, blk, mpg
    pts = get_stat('pts')
    reb = get_stat('reb', 'trb')  # CSV uses 'reb'
    ast = get_stat('ast')
    fg3 = get_stat('fg3')
    stl = get_stat('stl')
    blk = get_stat('blk')
    mpg = get_stat('mpg', 'mp')  # CSV uses 'mpg'
    
    # Player Stats Card
    st.markdown("""
    <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 1.5rem; border-radius: 12px; color: white; margin-bottom: 1rem;'>
        <h3 style='margin: 0; color: #f0f0f0;'>📊 Recent Stats (L10)</h3>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("PTS", f"{pts:.1f}")
    with col2:
        st.metric("REB", f"{reb:.1f}")
    with col3:
        st.metric("AST", f"{ast:.1f}")
    with col4:
        st.metric("3PM", f"{fg3:.1f}")
    with col5:
        st.metric("STL", f"{stl:.1f}")
    with col6:
        st.metric("MPG", f"{mpg:.0f}")
    
    if player_team and player_opponent:
        st.info(f"🏀 {player_team} vs {player_opponent}")
    
    st.divider()
    
    # Find player's plays from the system
    player_plays = [p for p in all_plays if player_name.lower() in p.player.lower()]
    
    if player_plays:
        st.markdown("### 🎯 Available Plays from DVP Analysis")
        for play in player_plays:
            direction = "OVER" if play.score > 0 else "UNDER"
            emoji = "🟢" if direction == "OVER" else "🔴"
            st.write(f"{emoji} **{play.stat}** {direction} | Proj: {play.projected:.1f} | Score: {play.score:.1f}")
    
    st.divider()
    
    # Custom Line Analyzer for each stat
    st.markdown("### 🎯 Custom Line Analyzer")
    st.caption("Enter lines to analyze any stat for this player")
    
    stat_options = ["PTS", "REB", "AST", "3PM", "PRA", "PR", "PA", "RA", "STL", "BLK"]
    selected_stat = st.selectbox("Select Stat", stat_options, key="player_analyzer_stat")
    
    # Get player's average for selected stat (using correct scraper keys)
    if selected_stat == "PRA":
        avg = pts + reb + ast
    elif selected_stat == "PR":
        avg = pts + reb
    elif selected_stat == "PA":
        avg = pts + ast
    elif selected_stat == "RA":
        avg = reb + ast
    elif selected_stat == "PTS":
        avg = pts
    elif selected_stat == "REB":
        avg = reb
    elif selected_stat == "AST":
        avg = ast
    elif selected_stat == "3PM":
        avg = fg3
    elif selected_stat == "STL":
        avg = stl
    elif selected_stat == "BLK":
        avg = blk
    else:
        avg = 0.0
    
    # Look up DVP rating for this matchup
    dvp_info = None
    dvp_value = None
    dvp_tier = None
    dvp_rank = None
    
    # Map stat names to DVP stat names
    dvp_stat_map = {"3PM": "3PM", "PTS": "PTS", "REB": "REB", "AST": "AST", "STL": "STL", "BLK": "BLK", "PRA": "PRA", "PR": "PR", "PA": "PA", "RA": "RA"}
    dvp_stat = dvp_stat_map.get(selected_stat, selected_stat)
    
    if dvp_ratings and player_position and player_opponent:
        stat_dvp = dvp_ratings.get(dvp_stat, {})
        pos_dvp = stat_dvp.get(player_position, {})
        dvp_info = pos_dvp.get(player_opponent)
        if dvp_info:
            dvp_value = dvp_info.get("value")
            dvp_tier = dvp_info.get("tier")
            dvp_rank = dvp_info.get("rank")
    
    # Display stats with DVP info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(f"L10 Avg {selected_stat}", f"{avg:.1f}")
    with col2:
        if dvp_value:
            st.metric(f"DVP Allows ({player_position})", f"{dvp_value:.1f}")
        else:
            st.metric("DVP", "N/A")
    with col3:
        if dvp_tier and dvp_rank:
            if dvp_tier == "WORST":
                tier_emoji = "🔥"
                tier_label = "SMASH"
            elif dvp_tier == "MID":
                tier_emoji = "⚪"
                tier_label = "NEUTRAL"
            else:
                tier_emoji = "🧊"
                tier_label = "FADE"
            st.metric(f"Matchup", f"{tier_emoji} #{dvp_rank}/30 {tier_label}")
        else:
            st.metric("Matchup", "N/A")
    
    # Show DVP insight
    if dvp_info:
        if dvp_tier == "WORST":
            st.success(f"🔥 **Great matchup!** {player_opponent} ranks #{dvp_rank}/30 WORST vs {player_position}s in {selected_stat} (allows {dvp_value:.1f})")
        elif dvp_tier == "MID":
            st.info(f"⚪ **Neutral matchup.** {player_opponent} ranks #{dvp_rank}/30 vs {player_position}s in {selected_stat} (allows {dvp_value:.1f})")
        else:
            st.warning(f"🧊 **Tough matchup!** {player_opponent} ranks #{dvp_rank}/30 BEST vs {player_position}s in {selected_stat} (allows {dvp_value:.1f})")
    
    # Look up live odds if available
    live_line, live_odds_val, live_book = None, -110, None
    if odds_df is not None and not odds_df.empty:
        player_last = player_name.lower().split()[-1]
        match = odds_df[(odds_df["player"].str.lower().str.contains(player_last)) & (odds_df["stat"] == selected_stat)]
        if not match.empty:
            live_line = match.iloc[0]["line"]
            live_odds_val = int(match.iloc[0]["odds"])
            live_book = match.iloc[0]["book"]
            st.success(f"📡 Found Line: **{live_line}** @ **{live_odds_val:+d}** on **{live_book}**")
    
    # Direction selection
    direction = st.radio("Direction", ["OVER", "UNDER"], horizontal=True, key="player_dir")
    
    col1, col2 = st.columns(2)
    with col1:
        default_line = float(live_line) if live_line else float(avg)
        line = st.number_input("Line", value=default_line, step=0.5, key="player_line")
    with col2:
        default_odds = live_odds_val if live_line else -110
        odds = st.number_input("Odds", value=default_odds, step=5, key="player_odds")
    
    if avg > 0 and line > 0:
        # Calculate projection - blend L10 avg with DVP if available
        if dvp_value and mpg > 0:
            # Use the calculate_projection function from prop_analyzer
            projected = calculate_projection(avg, dvp_value, dvp_tier or "WORST", player_mpg=mpg)
            st.caption(f"📊 Projection: {projected:.1f} (blended from L10 {avg:.1f} + DVP {dvp_value:.1f})")
        else:
            projected = avg
            st.caption(f"📊 Projection: {projected:.1f} (L10 avg only - no DVP data)")
        
        result = calculate_edge(projected, line, direction)
        edge_pct = result["edge_pct"]
        
        decimal_odds = american_to_decimal(int(odds))
        implied_prob = decimal_to_implied_prob(decimal_odds)
        win_prob = estimate_win_probability(edge_pct)
        kelly = calculate_kelly(win_prob, decimal_odds, fraction=0.25)
        kelly_bet = bankroll * (kelly['kelly_adjusted'] / 100) if bankroll > 0 else 0
        edge_over_book = (win_prob - implied_prob) * 100
        
        # Show recommendation
        if result["color"] == "green":
            st.success(f"### {result['recommendation']} | Edge: {edge_pct:+.1f}%")
        elif result["color"] == "blue":
            st.info(f"### {result['recommendation']} | Edge: {edge_pct:+.1f}%")
        elif result["color"] == "orange":
            st.warning(f"### {result['recommendation']} | Edge: {edge_pct:+.1f}%")
        else:
            st.error(f"### {result['recommendation']} | Edge: {edge_pct:+.1f}%")
        
        # Kelly Analysis Box
        st.markdown("""
        <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1rem; border-radius: 10px; margin: 1rem 0;'>
            <h4 style='color: white; margin: 0;'>📊 Kelly Criterion Analysis</h4>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Win %", f"{win_prob*100:.1f}%")
        with col2:
            st.metric("Book %", f"{implied_prob*100:.1f}%")
        with col3:
            st.metric("Edge", f"{edge_over_book:+.1f}%")
        with col4:
            st.metric("Kelly %", f"{kelly['kelly_adjusted']:.2f}%")
        with col5:
            st.metric("Kelly Bet", f"${kelly_bet:.2f}")
        with col6:
            st.metric("Full Kelly", f"${bankroll * kelly['kelly_full'] / 100:.2f}")
        
        st.divider()
        
        # Bet amount and add to picks
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            bet_amt = st.number_input(
                "💵 Your Bet Amount",
                min_value=0.0,
                max_value=bankroll if bankroll > 0 else 10000.0,
                value=round(kelly_bet, 2) if kelly_bet > 0 else 25.0,
                step=5.0,
                key="player_bet",
                help=f"Kelly suggests ${kelly_bet:.2f}"
            )
        with col2:
            potential_win = bet_amt * (decimal_odds - 1)
            st.metric("Win $", f"${potential_win:.2f}")
        with col3:
            st.metric("Total $", f"${bet_amt + potential_win:.2f}")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("➕ Add to Picks", type="primary", key="player_add_pick", use_container_width=True):
                add_pick({
                    "player": player_name, "stat": selected_stat, "direction": direction,
                    "opponent": player_opponent, "projection": projected, "line": line,
                    "odds": int(odds), "edge_%": round(edge_pct, 1), "bet_amount": round(bet_amt, 2),
                    "recommendation": result["recommendation"],
                    "win_prob_%": round(win_prob * 100, 1),
                    "kelly_%": round(kelly['kelly_adjusted'], 2),
                    "kelly_bet": round(kelly_bet, 2),
                    "implied_prob_%": round(implied_prob * 100, 1),
                })
                st.success(f"✅ Added {player_name} {selected_stat} {direction}!")
                st.balloons()
        with col2:
            if st.button("🎰 Add to Parlay", key="player_add_parlay", use_container_width=True):
                if "parlay_legs" not in st.session_state:
                    st.session_state.parlay_legs = []
                st.session_state.parlay_legs.append({
                    "player": player_name, "stat": selected_stat, "direction": direction,
                    "opponent": player_opponent, "line": line, "odds": int(odds),
                    "projection": projected, "win_prob": win_prob
                })
                st.success(f"🎰 Added to parlay! ({len(st.session_state.parlay_legs)} legs)")


# ---------------------------------------------------
# Main App
# ---------------------------------------------------
def main():
    st.markdown('<p class="main-header">🏀 NBA Prop Analyzer</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">DVP Matchups + Recent Performance → Smart Betting</p>', unsafe_allow_html=True)
    st.divider()
    
    plays, dvp_file, stats_file, stats_db = load_data()
    
    if plays is None:
        st.warning("⚠️ Data files not found or outdated.")
        files_status = check_todays_data_exists()
        missing = [k for k, v in files_status.items() if not v]
        if missing:
            st.info(f"Missing: {', '.join(missing)}")
        
        if st.button("🚀 Fetch All Data Now", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = run_all_scrapers(lambda p, m: (progress_bar.progress(p), status_text.text(m)))
            all_success = all(s for s, _ in results.values())
            for name, (success, _) in results.items():
                if success:
                    st.success(f"✅ {name}")
                else:
                    st.error(f"❌ {name}")
            if all_success:
                st.balloons()
                st.cache_data.clear()
                st.rerun()
        return
    
    # Sidebar
    with st.sidebar:
        st.markdown("## 🏀 Settings")
        top_n = st.slider("Plays per category", 5, 50, 25)
        bankroll = st.number_input("💵 Bankroll", min_value=0.0, value=500.0, step=50.0)
        
        st.divider()
        
        # Sidebar Tools
        st.markdown("### 🛠️ Tools")
        sidebar_tool = st.radio("", ["📊 Data Status", "🎰 Parlay Builder", "📤 Export"], label_visibility="collapsed")
        
        st.divider()
        
        if sidebar_tool == "📊 Data Status":
            st.markdown("#### 📊 Data Status")
            files_status = check_todays_data_exists()
            for key, exists in files_status.items():
                st.caption(f"{'✅' if exists else '❌'} {key.replace('_', ' ').title()}")
            st.caption(f"📂 {os.path.basename(dvp_file)}")
            st.caption(f"📊 {len(plays)} matchups")
        
        elif sidebar_tool == "🎰 Parlay Builder":
            st.markdown("#### 🎰 Quick Parlay")
            if "parlay_legs" not in st.session_state:
                st.session_state.parlay_legs = []
            
            # Show current parlay legs
            if st.session_state.parlay_legs:
                st.markdown("**Current Legs:**")
                combined_odds = 1.0
                for i, leg in enumerate(st.session_state.parlay_legs):
                    st.caption(f"{i+1}. {leg['player']} {leg['stat']} {leg['direction']}")
                    combined_odds *= american_to_decimal(leg.get('odds', -110))
                
                # Calculate combined American odds
                if combined_odds >= 2:
                    combined_american = int((combined_odds - 1) * 100)
                else:
                    combined_american = int(-100 / (combined_odds - 1))
                
                st.metric("Combined Odds", f"{combined_american:+d}")
                
                parlay_bet = st.number_input("Parlay Bet $", value=10.0, step=5.0, key="parlay_bet")
                potential_win = parlay_bet * (combined_odds - 1)
                st.info(f"Potential Win: **${potential_win:.2f}**")
                
                def clear_parlay():
                    st.session_state.parlay_legs = []
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("💾 Save", key="save_parlay"):
                        parlays = load_parlays()
                        parlays.append({
                            "legs": st.session_state.parlay_legs,
                            "odds": combined_american,
                            "bet": parlay_bet,
                            "potential": potential_win,
                            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "result": "pending"
                        })
                        save_parlays(parlays)
                        st.session_state.parlay_legs = []
                        st.success("Saved!")
                with col2:
                    st.button("🗑️ Clear", key="clear_parlay", on_click=clear_parlay)
            else:
                st.info("Add plays from Analyzer")
        
        elif sidebar_tool == "📤 Export":
            st.markdown("#### 📤 Export Data")
            picks = load_picks()
            if picks:
                # DraftKings format
                dk_format = []
                for p in picks:
                    dk_format.append(f"{p['player']} {p['stat']} {p['direction']} {p.get('line', '')}")
                st.text_area("Copy for DK/FD", "\n".join(dk_format), height=150)
            else:
                st.info("No picks to export")
        
        st.divider()
        
        def start_fetch():
            st.session_state.fetching = True
        
        if not st.session_state.get("fetching"):
            st.button("🔄 Fetch Fresh Data", type="primary", use_container_width=True, on_click=start_fetch)
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = run_all_scrapers(lambda p, m: (progress_bar.progress(p), status_text.text(m)))
            st.session_state.fetching = False
            st.cache_data.clear()
            st.success("Done! Refresh the page to see new data.")
    
    top_plays = filter_top_plays(plays, top_n)
    
    # Create tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "📅 Today", "📈 Overs", "📉 Unders", "🎯 Analyzer", "🔍 Search", "📋 Picks", "💰 Odds", "📊 Analytics"
    ])
    
    # Tab 1: Today's Games
    with tab1:
        st.subheader("📅 Today's Games")
        lineups_df = load_lineups_data()
        schedule_df = load_schedule_data()
        
        if lineups_df is not None and not lineups_df.empty:
            # Get unique games with their info
            game_cols = ["game_time", "away_team", "home_team", "fav", "spread", "total"]
            available_cols = [c for c in game_cols if c in lineups_df.columns]
            games_df = lineups_df[available_cols].drop_duplicates()
            
            # Summary table at top
            st.markdown("### 🏀 Game Lines")
            game_summary = []
            for _, game in games_df.iterrows():
                away = game.get("away_team", "")
                home = game.get("home_team", "")
                time = game.get("game_time", "")
                fav = game.get("fav", "")
                spread = game.get("spread", 0)
                total = game.get("total", 0)
                
                # Format spread display
                if fav == away:
                    spread_display = f"{away} -{spread}"
                elif fav == home:
                    spread_display = f"{home} -{spread}"
                else:
                    spread_display = f"PK"
                
                game_summary.append({
                    "Time": time,
                    "Away": away,
                    "Home": home,
                    "Spread": spread_display,
                    "O/U": total,
                })
            
            st.dataframe(
                pd.DataFrame(game_summary), 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "Time": st.column_config.TextColumn(width="small"),
                    "Away": st.column_config.TextColumn(width="small"),
                    "Home": st.column_config.TextColumn(width="small"),
                    "Spread": st.column_config.TextColumn(width="medium"),
                    "O/U": st.column_config.NumberColumn(format="%.1f", width="small"),
                }
            )
            
            st.divider()
            st.markdown("### 📋 Starting Lineups")
            
            # Individual game lineups
            for _, game in games_df.iterrows():
                away = game.get("away_team", "")
                home = game.get("home_team", "")
                time = game.get("game_time", "")
                fav = game.get("fav", "")
                spread = game.get("spread", 0)
                total = game.get("total", 0)
                
                # Format header
                spread_str = f"{fav} -{spread}" if fav else "PK"
                header = f"🏀 {away} @ {home} | {time} | {spread_str} | O/U {total}"
                
                with st.expander(header, expanded=False):
                    game_lineups = lineups_df[(lineups_df["away_team"] == away) & (lineups_df["home_team"] == home)]
                    
                    # Game info bar
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Time", time)
                    with col2:
                        st.metric("Favorite", fav if fav else "PK")
                    with col3:
                        st.metric("Spread", f"-{spread}" if spread else "PK")
                    with col4:
                        st.metric("O/U Total", f"{total}")
                    
                    st.divider()
                    
                    # Lineups side by side
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"### {away}")
                        away_players = game_lineups[game_lineups["team"] == away]
                        for _, p in away_players.iterrows():
                            status = str(p.get("status", "")).strip()
                            status_emoji = ""
                            status_text = ""
                            if status and status.lower() not in ["nan", ""]:
                                if status.upper() in ["OUT", "O"]:
                                    status_emoji = "🔴"
                                    status_text = " (OUT)"
                                elif status.upper() in ["Q", "GTD"]:
                                    status_emoji = "🟡"
                                    status_text = " (Q)"
                                elif status.upper() in ["P", "PROB"]:
                                    status_emoji = "🟠"
                                    status_text = " (P)"
                                elif status.upper() in ["IN"]:
                                    status_emoji = "🟢"
                                    status_text = " (IN)"
                            st.write(f"**{p['position']}**: {p['player']}{status_text} {status_emoji}")
                    
                    with col2:
                        st.markdown(f"### {home}")
                        home_players = game_lineups[game_lineups["team"] == home]
                        for _, p in home_players.iterrows():
                            status = str(p.get("status", "")).strip()
                            status_emoji = ""
                            status_text = ""
                            if status and status.lower() not in ["nan", ""]:
                                if status.upper() in ["OUT", "O"]:
                                    status_emoji = "🔴"
                                    status_text = " (OUT)"
                                elif status.upper() in ["Q", "GTD"]:
                                    status_emoji = "🟡"
                                    status_text = " (Q)"
                                elif status.upper() in ["P", "PROB"]:
                                    status_emoji = "🟠"
                                    status_text = " (P)"
                                elif status.upper() in ["IN"]:
                                    status_emoji = "🟢"
                                    status_text = " (IN)"
                            st.write(f"**{p['position']}**: {p['player']}{status_text} {status_emoji}")
        else:
            st.info("No lineup data. Click 'Fetch Fresh Data' in sidebar.")
    
    # Tab 2: Over Plays
    with tab2:
        st.subheader("📈 Top Over Plays")
        if top_plays["overs"]:
            over_data = [{"#": i, "Player": p.player, "Team": p.team, "vs": p.opponent, "Stat": p.stat, "L10": p.recent_avg, "PROJ": p.projected, "Score": p.score} for i, p in enumerate(top_plays["overs"], 1)]
            st.dataframe(pd.DataFrame(over_data), use_container_width=True, hide_index=True)
        else:
            st.info("No over plays found")
    
    # Tab 3: Under Plays
    with tab3:
        st.subheader("📉 Top Under Plays")
        if top_plays["unders"]:
            under_data = [{"#": i, "Player": p.player, "Team": p.team, "vs": p.opponent, "Stat": p.stat, "L10": p.recent_avg, "PROJ": p.projected, "Score": p.score} for i, p in enumerate(top_plays["unders"], 1)]
            st.dataframe(pd.DataFrame(under_data), use_container_width=True, hide_index=True)
        else:
            st.info("No under plays found")
    
    # Tab 4: Line Analyzer
    with tab4:
        st.subheader("🎯 Line Analyzer")
        odds_df = load_odds_data()
        if odds_df is not None:
            st.success("✅ Live odds loaded")
        
        all_plays_list = [(p, "OVER", "🟢") for p in top_plays["overs"]] + [(p, "UNDER", "🔴") for p in top_plays["unders"]]
        
        if all_plays_list:
            total = len(all_plays_list)
            
            # Create dropdown options for all plays
            play_options = []
            for i, (p, d, e) in enumerate(all_plays_list):
                play_options.append(f"{i+1}. {e} {p.player} - {p.stat} {d} (vs {p.opponent})")
            
            # Initialize play index in session state if needed
            if "play_index" not in st.session_state:
                st.session_state.play_index = 0
            
            # Ensure index is valid
            st.session_state.play_index = max(0, min(st.session_state.play_index, total - 1))
            idx = st.session_state.play_index
            
            # Dropdown selector - use index from session state
            selected_idx = st.selectbox(
                "Jump to play",
                options=range(total),
                index=idx,
                format_func=lambda i: play_options[i],
                key="play_dropdown",
                label_visibility="collapsed"
            )
            
            # Update session state from dropdown (no rerun needed - selectbox handles it)
            if selected_idx != st.session_state.play_index:
                st.session_state.play_index = selected_idx
            
            idx = st.session_state.play_index
            
            # Navigation buttons - use callbacks to avoid full page rerun
            def go_first():
                st.session_state.play_index = 0
            def go_prev():
                st.session_state.play_index = max(0, st.session_state.play_index - 1)
            def go_next():
                st.session_state.play_index = min(total - 1, st.session_state.play_index + 1)
            def go_last():
                st.session_state.play_index = total - 1
            
            col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])
            with col1:
                st.button("⏮️", key="first", on_click=go_first)
            with col2:
                st.button("◀️", key="prev", on_click=go_prev)
            with col3:
                st.markdown(f"<h4 style='text-align:center'>{idx + 1} / {total}</h4>", unsafe_allow_html=True)
            with col4:
                st.button("▶️", key="next", on_click=go_next)
            with col5:
                st.button("⏭️", key="last", on_click=go_last)
            
            play, direction, emoji = all_plays_list[idx]
            
            # Look up live odds
            live_line, live_odds_val, live_book = None, -110, None
            if odds_df is not None:
                player_last = play.player.lower().split()[-1] if play.player else ""
                dir_match = "Over" if direction == "OVER" else "Under"
                match = odds_df[(odds_df["player"].str.lower().str.contains(player_last)) & (odds_df["stat"] == play.stat) & (odds_df["direction"] == dir_match)]
                if not match.empty:
                    live_line = match.iloc[0]["line"]
                    live_odds_val = int(match.iloc[0]["odds"])
                    live_book = match.iloc[0]["book"]
            
            st.markdown(f"### {emoji} {play.player} - {play.stat} {direction}")
            st.caption(f"vs {play.opponent} | {play.team}")
            if live_line:
                st.info(f"📡 Line: **{live_line}** @ **{live_odds_val:+d}** on **{live_book}**")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("L10", f"{play.recent_avg:.1f}" if play.recent_avg else "N/A")
            with col2:
                st.metric("PROJ", f"{play.projected:.1f}" if play.projected else "N/A")
            with col3:
                st.metric("Score", f"{play.score:.1f}")
            with col4:
                st.metric("MPG", f"{play.mpg:.0f}" if play.mpg else "?")
            
            default_line = float(live_line) if live_line else (float(play.projected) if play.projected else 20.0)
            default_odds = live_odds_val if live_line else -110
            
            col1, col2 = st.columns(2)
            with col1:
                line = st.number_input("Line", value=default_line, step=0.5, key=f"line_{idx}")
            with col2:
                odds = st.number_input("Odds", value=default_odds, step=5, key=f"odds_{idx}")
            
            if play.projected and line > 0:
                result = calculate_edge(play.projected, line, direction)
                edge_pct = result["edge_pct"]
                
                # Calculate Kelly values
                decimal_odds = american_to_decimal(int(odds))
                implied_prob = decimal_to_implied_prob(decimal_odds)
                win_prob = estimate_win_probability(edge_pct)
                kelly = calculate_kelly(win_prob, decimal_odds, fraction=0.25)
                kelly_bet = bankroll * (kelly['kelly_adjusted'] / 100) if bankroll > 0 else 0
                edge_over_book = (win_prob - implied_prob) * 100
                
                # Show recommendation with Kelly info
                if result["color"] == "green":
                    st.success(f"### {result['recommendation']} | Edge: {edge_pct:+.1f}%")
                elif result["color"] == "blue":
                    st.info(f"### {result['recommendation']} | Edge: {edge_pct:+.1f}%")
                elif result["color"] == "orange":
                    st.warning(f"### {result['recommendation']} | Edge: {edge_pct:+.1f}%")
                else:
                    st.error(f"### {result['recommendation']} | Edge: {edge_pct:+.1f}%")
                
                # Kelly Criterion Analysis Box
                with st.container():
                    st.markdown("""
                    <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1rem; border-radius: 10px; margin: 1rem 0;'>
                        <h4 style='color: white; margin: 0 0 0.5rem 0;'>📊 Kelly Criterion Analysis</h4>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    col1, col2, col3, col4, col5, col6 = st.columns(6)
                    with col1:
                        st.metric("Win %", f"{win_prob*100:.1f}%")
                    with col2:
                        st.metric("Book %", f"{implied_prob*100:.1f}%")
                    with col3:
                        st.metric("Edge", f"{edge_over_book:+.1f}%")
                    with col4:
                        st.metric("Kelly %", f"{kelly['kelly_adjusted']:.2f}%")
                    with col5:
                        st.metric("Kelly Bet", f"${kelly_bet:.2f}")
                    with col6:
                        st.metric("Full Kelly", f"${bankroll * kelly['kelly_full'] / 100:.2f}")
                
                st.divider()
                
                # Bet amount and potential return
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    bet_amt = st.number_input(
                        "💵 Your Bet Amount", 
                        min_value=0.0, 
                        max_value=bankroll if bankroll > 0 else 10000.0,
                        value=round(kelly_bet, 2) if kelly_bet > 0 else 25.0,
                        step=5.0, 
                        key=f"bet_{idx}",
                        help=f"Kelly suggests ${kelly_bet:.2f} based on your ${bankroll:.0f} bankroll"
                    )
                with col2:
                    potential_win = bet_amt * (decimal_odds - 1)
                    st.metric("Win $", f"${potential_win:.2f}")
                with col3:
                    st.metric("Total $", f"${bet_amt + potential_win:.2f}")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("➕ Add to Picks", type="primary", key=f"add_{idx}", use_container_width=True):
                        add_pick({
                            "player": play.player, "stat": play.stat, "direction": direction,
                            "opponent": play.opponent, "projection": play.projected, "line": line,
                            "odds": int(odds), "edge_%": round(edge_pct, 1), "bet_amount": round(bet_amt, 2),
                            "recommendation": result["recommendation"],
                            "win_prob_%": round(win_prob * 100, 1),
                            "kelly_%": round(kelly['kelly_adjusted'], 2),
                            "kelly_bet": round(kelly_bet, 2),
                            "implied_prob_%": round(implied_prob * 100, 1),
                        })
                        st.success(f"✅ Added!")
                        st.balloons()
                with col2:
                    if st.button("🎰 Add to Parlay", key=f"parlay_{idx}", use_container_width=True):
                        if "parlay_legs" not in st.session_state:
                            st.session_state.parlay_legs = []
                        st.session_state.parlay_legs.append({
                            "player": play.player, "stat": play.stat, "direction": direction,
                            "opponent": play.opponent, "line": line, "odds": int(odds),
                            "projection": play.projected, "win_prob": win_prob
                        })
                        st.success(f"🎰 Added to parlay! ({len(st.session_state.parlay_legs)} legs)")
    
    # Tab 5: Player Search
    with tab5:
        st.subheader("🔍 Player Search & Analyzer")
        st.caption("Search any player to see their stats, DVP matchup, and analyze lines")
        
        search_name = st.text_input("Search player name", placeholder="e.g., LeBron, Curry, Tatum", key="tab_search")
        
        if search_name and stats_db:
            matches = [k for k in stats_db.keys() if search_name.lower() in k.lower()]
            if matches:
                selected_player = st.selectbox("Select player", matches[:15], key="tab_player_select")
                if selected_player:
                    player_data = stats_db[selected_player]
                    display_name = player_data.get("player", selected_player)
                    
                    st.divider()
                    
                    # Show full player analyzer
                    show_player_analyzer(
                        display_name,
                        player_data,
                        plays,
                        bankroll,
                        load_odds_data()
                    )
            else:
                st.info("No players found matching that name")
        else:
            st.info("👆 Enter a player name above to search")
            
            # Show some quick stats about available data
            if stats_db:
                st.markdown("---")
                st.markdown(f"**📊 {len(stats_db)} players** in database")
                
                # Show sample players
                sample_players = list(stats_db.keys())[:10]
                st.caption("Sample players: " + ", ".join([stats_db[p].get("player", p) for p in sample_players]))
    
    # Tab 6: My Picks
    with tab6:
        st.subheader("📋 My Picks")
        picks = load_picks()
        
        if picks:
            # Extract unique dates from picks
            all_dates = sorted(set(p.get("added_at", "")[:10] for p in picks if p.get("added_at")), reverse=True)
            
            # View mode and filters
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                view_mode = st.radio("View", ["📇 Cards", "📊 Spreadsheet"], horizontal=True, label_visibility="collapsed")
            with col2:
                date_options = ["All Time"] + all_dates
                selected_date = st.selectbox("📅 Filter by Day", date_options, label_visibility="collapsed")
            with col3:
                result_filter = st.selectbox("📊 Result", ["All", "Pending", "Won", "Lost", "Push"], label_visibility="collapsed")
            
            # Filter picks
            filtered_picks = picks.copy()
            if selected_date != "All Time":
                filtered_picks = [p for p in filtered_picks if p.get("added_at", "").startswith(selected_date)]
            if result_filter != "All":
                filtered_picks = [p for p in filtered_picks if p.get("result", "pending") == result_filter.lower()]
            
            # Stats for filtered picks
            won = [p for p in filtered_picks if p.get("result") == "won"]
            lost = [p for p in filtered_picks if p.get("result") == "lost"]
            pending = [p for p in filtered_picks if p.get("result") == "pending"]
            total_profit = sum(calculate_profit(p) for p in filtered_picks)
            total_wagered = sum(p.get("bet_amount", 0) for p in filtered_picks if p.get("result") in ["won", "lost"])
            
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Picks", len(filtered_picks))
            with col2:
                st.metric("Record", f"{len(won)}W - {len(lost)}L")
            with col3:
                win_rate = len(won) / (len(won) + len(lost)) * 100 if (len(won) + len(lost)) > 0 else 0
                st.metric("Win Rate", f"{win_rate:.1f}%")
            with col4:
                st.metric("P/L", f"${total_profit:+.2f}")
            with col5:
                roi = (total_profit / total_wagered * 100) if total_wagered > 0 else 0
                st.metric("ROI", f"{roi:+.1f}%")
            
            st.divider()
            
            # Get original indices for filtered picks (needed for update/remove)
            pick_indices = [(i, p) for i, p in enumerate(picks) if p in filtered_picks]
            
            if view_mode == "📊 Spreadsheet":
                # Spreadsheet view
                if filtered_picks:
                    # Build dataframe with calculated profit
                    table_data = []
                    for orig_idx, pick in pick_indices:
                        profit = calculate_profit(pick)
                        table_data.append({
                            "Player": pick.get("player", ""),
                            "Stat": pick.get("stat", ""),
                            "Dir": pick.get("direction", ""),
                            "Line": pick.get("line", ""),
                            "Odds": pick.get("odds", -110),
                            "Edge%": f"{pick.get('edge_%', 0):+.1f}",
                            "Win%": f"{pick.get('win_prob_%', '')}",
                            "Kelly%": f"{pick.get('kelly_%', '')}",
                            "Bet $": f"${pick.get('bet_amount', 0):.2f}",
                            "Kelly $": f"${pick.get('kelly_bet', 0):.2f}" if pick.get('kelly_bet') else "",
                            "Result": pick.get("result", "pending").upper(),
                            "P/L": f"${profit:+.2f}",
                            "Date": pick.get("added_at", "")[:10] if pick.get("added_at") else "",
                        })
                    
                    df_table = pd.DataFrame(table_data)
                    st.dataframe(
                        df_table, 
                        use_container_width=True, 
                        hide_index=True,
                        column_config={
                            "Player": st.column_config.TextColumn(width="medium"),
                            "Stat": st.column_config.TextColumn(width="small"),
                            "Dir": st.column_config.TextColumn(width="small"),
                            "Line": st.column_config.NumberColumn(format="%.1f", width="small"),
                            "Odds": st.column_config.NumberColumn(width="small"),
                            "Edge%": st.column_config.TextColumn(width="small"),
                            "Win%": st.column_config.TextColumn(width="small", help="Estimated win probability"),
                            "Kelly%": st.column_config.TextColumn(width="small", help="Kelly % of bankroll"),
                            "Bet $": st.column_config.TextColumn(width="small"),
                            "Kelly $": st.column_config.TextColumn(width="small", help="Kelly suggested bet"),
                            "Result": st.column_config.TextColumn(width="small"),
                            "P/L": st.column_config.TextColumn(width="small"),
                            "Date": st.column_config.TextColumn(width="small"),
                        }
                    )
                    
                    # Quick result update buttons
                    st.markdown("#### Quick Update Results")
                    pending_picks = [(i, p) for i, p in pick_indices if p.get("result") == "pending"]
                    if pending_picks:
                        for orig_idx, pick in pending_picks[:10]:  # Show first 10 pending
                            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
                            with col1:
                                st.write(f"{pick['player']} {pick['stat']} {pick['direction']}")
                            with col2:
                                if st.button("✅", key=f"tbl_won_{orig_idx}"):
                                    update_pick_result(orig_idx, "won", calculate_profit({**pick, "result": "won"}))
                                    st.rerun()
                            with col3:
                                if st.button("❌", key=f"tbl_lost_{orig_idx}"):
                                    update_pick_result(orig_idx, "lost", calculate_profit({**pick, "result": "lost"}))
                                    st.rerun()
                            with col4:
                                if st.button("➖", key=f"tbl_push_{orig_idx}"):
                                    update_pick_result(orig_idx, "push", 0.0)
                                    st.rerun()
                            with col5:
                                if st.button("🗑️", key=f"tbl_del_{orig_idx}"):
                                    remove_pick(orig_idx)
                                    st.rerun()
                    else:
                        st.success("✅ All picks have been graded!")
            else:
                # Card view (original expander view)
                for orig_idx, pick in pick_indices:
                    result = pick.get("result", "pending")
                    profit = calculate_profit(pick)
                    emoji = "🟢" if pick.get("direction") == "OVER" else "🔴"
                    result_emoji = {"won": "✅", "lost": "❌", "push": "➖", "pending": "⏳"}.get(result, "⏳")
                    added_date = pick.get("added_at", "")[:10] if pick.get("added_at") else ""
                    
                    with st.expander(f"{result_emoji} {emoji} {pick['player']} {pick['stat']} {pick['direction']} @ {pick.get('line', '?')} | P/L: ${profit:+.2f} | {added_date}"):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.markdown("**📋 Pick Details**")
                            st.write(f"Opponent: {pick.get('opponent', '?')}")
                            st.write(f"Projection: {pick.get('projection', '?')}")
                            st.write(f"Line: {pick.get('line', '?')}")
                            st.write(f"Odds: {pick.get('odds', -110)}")
                        with col2:
                            st.markdown("**📊 Kelly Analysis**")
                            st.write(f"Win Prob: {pick.get('win_prob_%', '?')}%")
                            st.write(f"Edge: {pick.get('edge_%', 0):+.1f}%")
                            st.write(f"Kelly %: {pick.get('kelly_%', '?')}%")
                            st.write(f"Kelly Bet: ${pick.get('kelly_bet', '?')}")
                        with col3:
                            st.markdown("**💰 Bet Info**")
                            st.write(f"Your Bet: ${pick.get('bet_amount', 0):.2f}")
                            st.write(f"Rec: {pick.get('recommendation', '?')}")
                            st.write(f"Added: {pick.get('added_at', '?')}")
                            potential = pick.get('bet_amount', 0) * (american_to_decimal(pick.get('odds', -110)) - 1)
                            st.write(f"Potential: ${potential:.2f}")
                        
                        st.divider()
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            if st.button("✅ Won", key=f"won_{orig_idx}"):
                                update_pick_result(orig_idx, "won", calculate_profit({**pick, "result": "won"}))
                                st.rerun()
                        with col2:
                            if st.button("❌ Lost", key=f"lost_{orig_idx}"):
                                update_pick_result(orig_idx, "lost", calculate_profit({**pick, "result": "lost"}))
                                st.rerun()
                        with col3:
                            if st.button("➖ Push", key=f"push_{orig_idx}"):
                                update_pick_result(orig_idx, "push", 0.0)
                                st.rerun()
                        with col4:
                            if st.button("🗑️", key=f"del_{orig_idx}"):
                                remove_pick(orig_idx)
                                st.rerun()
            
            st.divider()
            
            # Export and clear options
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🗑️ Clear All Picks"):
                    clear_all_picks()
                    st.rerun()
            with col2:
                picks_df = pd.DataFrame(filtered_picks)
                csv = picks_df.to_csv(index=False)
                st.download_button("📥 Download CSV", csv, f"picks_{selected_date}.csv", "text/csv")
        else:
            st.info("No picks yet. Add some from the Analyzer tab!")
    
    # Tab 7: Live Odds
    with tab7:
        st.subheader("💰 Live Odds")
        odds_df = load_odds_data()
        
        if odds_df is not None and not odds_df.empty:
            stat_filter = st.selectbox("Filter by Stat", ["All"] + sorted(odds_df["stat"].unique().tolist()))
            dir_filter = st.radio("Direction", ["All", "Over", "Under"], horizontal=True)
            
            filtered = odds_df.copy()
            if stat_filter != "All":
                filtered = filtered[filtered["stat"] == stat_filter]
            if dir_filter != "All":
                filtered = filtered[filtered["direction"] == dir_filter]
            
            player_search = st.text_input("🔎 Search Player")
            if player_search:
                filtered = filtered[filtered["player"].str.lower().str.contains(player_search.lower())]
            
            st.dataframe(filtered[["player", "stat", "line", "direction", "odds", "book", "game"]], use_container_width=True, hide_index=True)
        else:
            st.warning("No odds data. Click 'Fetch Fresh Data' in sidebar.")
    
    # Tab 8: Analytics
    with tab8:
        st.subheader("📊 Analytics Dashboard")
        picks = load_picks()
        
        if picks:
            won = [p for p in picks if p.get("result") == "won"]
            lost = [p for p in picks if p.get("result") == "lost"]
            pending = [p for p in picks if p.get("result") == "pending"]
            total_profit = sum(calculate_profit(p) for p in picks)
            total_wagered = sum(p.get("bet_amount", 0) for p in picks if p.get("result") in ["won", "lost"])
            
            # Summary Stats
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Total Picks", len(picks))
            with col2:
                st.metric("Record", f"{len(won)}W - {len(lost)}L")
            with col3:
                win_rate = len(won) / (len(won) + len(lost)) * 100 if (len(won) + len(lost)) > 0 else 0
                st.metric("Win Rate", f"{win_rate:.1f}%")
            with col4:
                roi = (total_profit / total_wagered * 100) if total_wagered > 0 else 0
                st.metric("ROI", f"{roi:+.1f}%")
            with col5:
                st.metric("Net P/L", f"${total_profit:+.2f}")
            
            st.divider()
            
            # Kelly Analysis Section
            st.markdown("### 📈 Kelly Criterion Performance")
            
            # Compare actual bets vs Kelly suggestions
            graded_picks = [p for p in picks if p.get("result") in ["won", "lost"]]
            if graded_picks:
                kelly_suggested_total = sum(p.get("kelly_bet", 0) for p in graded_picks)
                actual_bet_total = sum(p.get("bet_amount", 0) for p in graded_picks)
                
                # Calculate what profit would have been with Kelly
                kelly_profit = 0
                for p in graded_picks:
                    kelly_bet = p.get("kelly_bet", p.get("bet_amount", 0))
                    if p.get("result") == "won":
                        kelly_profit += kelly_bet * (american_to_decimal(p.get("odds", -110)) - 1)
                    else:
                        kelly_profit -= kelly_bet
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Your Total Wagered", f"${actual_bet_total:.2f}")
                with col2:
                    st.metric("Kelly Suggested Total", f"${kelly_suggested_total:.2f}")
                with col3:
                    st.metric("Kelly P/L (if followed)", f"${kelly_profit:+.2f}")
                
                # Win prob accuracy
                st.markdown("#### 🎯 Win Probability Accuracy")
                probs_with_results = [(p.get("win_prob_%", 50), p.get("result")) for p in graded_picks if p.get("win_prob_%")]
                if probs_with_results:
                    # Group by probability ranges
                    ranges = {"45-50%": [], "50-55%": [], "55-60%": [], "60-65%": [], "65%+": []}
                    for prob, result in probs_with_results:
                        if prob < 50:
                            ranges["45-50%"].append(1 if result == "won" else 0)
                        elif prob < 55:
                            ranges["50-55%"].append(1 if result == "won" else 0)
                        elif prob < 60:
                            ranges["55-60%"].append(1 if result == "won" else 0)
                        elif prob < 65:
                            ranges["60-65%"].append(1 if result == "won" else 0)
                        else:
                            ranges["65%+"].append(1 if result == "won" else 0)
                    
                    for range_name, results in ranges.items():
                        if results:
                            actual_wr = sum(results) / len(results) * 100
                            st.write(f"**{range_name}**: {sum(results)}W-{len(results)-sum(results)}L (Actual: {actual_wr:.0f}%)")
            
            st.divider()
            
            # Performance by stat
            st.markdown("### 📊 Performance by Stat")
            stats_perf = {}
            for p in picks:
                stat = p.get("stat", "?")
                if stat not in stats_perf:
                    stats_perf[stat] = {"won": 0, "lost": 0, "profit": 0, "avg_edge": [], "avg_kelly": []}
                if p.get("result") == "won":
                    stats_perf[stat]["won"] += 1
                elif p.get("result") == "lost":
                    stats_perf[stat]["lost"] += 1
                stats_perf[stat]["profit"] += calculate_profit(p)
                if p.get("edge_%"):
                    stats_perf[stat]["avg_edge"].append(p.get("edge_%", 0))
                if p.get("kelly_%"):
                    stats_perf[stat]["avg_kelly"].append(p.get("kelly_%", 0))
            
            for stat, data in sorted(stats_perf.items(), key=lambda x: x[1]["profit"], reverse=True):
                total = data["won"] + data["lost"]
                wr = data["won"] / total * 100 if total > 0 else 0
                avg_edge = sum(data["avg_edge"]) / len(data["avg_edge"]) if data["avg_edge"] else 0
                avg_kelly = sum(data["avg_kelly"]) / len(data["avg_kelly"]) if data["avg_kelly"] else 0
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.write(f"**{stat}**")
                with col2:
                    st.write(f"{data['won']}W-{data['lost']}L ({wr:.0f}%)")
                with col3:
                    st.write(f"Avg Edge: {avg_edge:+.1f}%")
                with col4:
                    st.write(f"P/L: ${data['profit']:+.2f}")
            
            st.divider()
            
            # Performance by direction
            st.markdown("### ⬆️⬇️ Performance by Direction")
            dir_perf = {"OVER": {"won": 0, "lost": 0, "profit": 0}, "UNDER": {"won": 0, "lost": 0, "profit": 0}}
            for p in picks:
                direction = p.get("direction", "OVER")
                if p.get("result") == "won":
                    dir_perf[direction]["won"] += 1
                elif p.get("result") == "lost":
                    dir_perf[direction]["lost"] += 1
                dir_perf[direction]["profit"] += calculate_profit(p)
            
            col1, col2 = st.columns(2)
            with col1:
                data = dir_perf["OVER"]
                total = data["won"] + data["lost"]
                wr = data["won"] / total * 100 if total > 0 else 0
                st.metric("🟢 OVERS", f"{data['won']}W-{data['lost']}L ({wr:.0f}%)")
                st.caption(f"P/L: ${data['profit']:+.2f}")
            with col2:
                data = dir_perf["UNDER"]
                total = data["won"] + data["lost"]
                wr = data["won"] / total * 100 if total > 0 else 0
                st.metric("🔴 UNDERS", f"{data['won']}W-{data['lost']}L ({wr:.0f}%)")
                st.caption(f"P/L: ${data['profit']:+.2f}")
            
            # Bankroll tracking
            st.divider()
            st.markdown("### 💰 Bankroll Simulation")
            starting_br = st.number_input("Starting Bankroll", value=500.0, step=50.0, key="sim_bankroll")
            
            # Calculate running bankroll
            running_br = starting_br
            br_history = [starting_br]
            for p in picks:
                if p.get("result") in ["won", "lost"]:
                    running_br += calculate_profit(p)
                    br_history.append(running_br)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Starting", f"${starting_br:.2f}")
            with col2:
                st.metric("Current", f"${running_br:.2f}")
            with col3:
                change = running_br - starting_br
                pct_change = (change / starting_br) * 100 if starting_br > 0 else 0
                st.metric("Change", f"${change:+.2f}", f"{pct_change:+.1f}%")
        else:
            st.info("No picks yet to analyze.")


if __name__ == "__main__":
    main()
