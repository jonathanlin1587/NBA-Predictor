#!/usr/bin/env python3
"""
NBA Prop Analyzer - Web UI
Run with: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import os
import json
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

# ---------------------------------------------------
# Config & Constants
# ---------------------------------------------------
PICKS_FILE = os.path.join(OUTPUT_DIR, "my_picks.json")

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
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E3A5F;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-top: 0;
    }
    .play-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        padding: 1.5rem;
        border-radius: 12px;
        color: white;
        margin: 1rem 0;
    }
    .play-title {
        font-size: 1.4rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .nav-btn {
        font-size: 1.5rem;
    }
    div[data-testid="stDataFrame"] {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------
# Persistent Picks Storage
# ---------------------------------------------------
def load_picks() -> List[Dict]:
    """Load picks from JSON file."""
    if os.path.exists(PICKS_FILE):
        try:
            with open(PICKS_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []


def save_picks(picks: List[Dict]):
    """Save picks to JSON file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(PICKS_FILE, "w") as f:
        json.dump(picks, f, indent=2)


def add_pick(pick: Dict):
    """Add a pick and save to file."""
    picks = load_picks()
    # Add timestamp
    pick["added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    picks.append(pick)
    save_picks(picks)


def remove_pick(index: int):
    """Remove a pick by index."""
    picks = load_picks()
    if 0 <= index < len(picks):
        picks.pop(index)
        save_picks(picks)


def clear_all_picks():
    """Clear all picks."""
    save_picks([])


# ---------------------------------------------------
# Data Loading (Cached)
# ---------------------------------------------------
@st.cache_data(ttl=300)
def load_data():
    """Load and process all data."""
    dvp_file = find_latest_file("dvp_shortlist_results_")
    stats_file = find_latest_file("last_")
    
    if not dvp_file or not stats_file:
        return None, None, None, None
    
    dvp_rows = load_dvp_shortlist(dvp_file)
    stats_db = load_last_n_days(stats_file)
    plays = merge_and_score(dvp_rows, stats_db)
    
    return plays, dvp_file, stats_file, stats_db


# ---------------------------------------------------
# Utility Functions
# ---------------------------------------------------
def american_to_decimal(american_odds: int) -> float:
    """Convert American odds to decimal odds."""
    if american_odds > 0:
        return (american_odds / 100) + 1
    else:
        return (100 / abs(american_odds)) + 1


def decimal_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability."""
    return 1 / decimal_odds


def calculate_kelly(win_prob: float, decimal_odds: float, fraction: float = 0.25) -> Dict[str, Any]:
    """Calculate Kelly Criterion bet size."""
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
        "edge_over_book": (win_prob - decimal_to_implied_prob(decimal_odds)) * 100,
    }


def estimate_win_probability(edge_pct: float, base_prob: float = 0.50) -> float:
    """Estimate win probability from edge percentage."""
    prob_boost = edge_pct * 0.005
    estimated_prob = base_prob + prob_boost
    return max(0.45, min(0.75, estimated_prob))


def calculate_edge(projected: float, line: float, direction: str) -> Dict[str, Any]:
    """Calculate edge and recommendation."""
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


# ---------------------------------------------------
# Main App
# ---------------------------------------------------
def main():
    # Header
    st.markdown('<p class="main-header">🏀 NBA Prop Analyzer</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">DVP Matchups + Recent Performance → Smart Betting</p>', unsafe_allow_html=True)
    st.divider()
    
    # Load data
    plays, dvp_file, stats_file, stats_db = load_data()
    
    if plays is None:
        st.error("❌ Could not load data files. Make sure you've run the scrapers first.")
        st.code("""
# Run these commands first:
python nba_daily_schedule.py
python lineups_scraper.py  # (paste lineup data)
python nba_dvp_scraper.py  # (paste DVP data)
python prop_dvp_shortlist.py
python last_n_days_scraper.py
        """)
        return
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        
        top_n = st.slider("Plays per category", 5, 25, 15)
        bankroll = st.number_input("💵 Bankroll", min_value=0.0, value=1000.0, step=100.0)
        
        st.divider()
        st.caption(f"📂 DVP: {os.path.basename(dvp_file)}")
        st.caption(f"📂 Stats: {os.path.basename(stats_file)}")
        st.caption(f"📊 {len(plays)} total matchups loaded")
        
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    # Filter plays
    top_plays = filter_top_plays(plays, top_n)
    
    # Create tabs - now with 4 tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📈 Over Plays", "📉 Under Plays", "🎯 Line Analyzer", "📋 My Picks"])
    
    # ---------------------------------------------------
    # Tab 1: Over Plays
    # ---------------------------------------------------
    with tab1:
        st.subheader("📈 Top Over Plays")
        st.caption("Players who are HOT facing WEAK defenses")
        
        if top_plays["overs"]:
            over_data = []
            for i, p in enumerate(top_plays["overs"], 1):
                over_data.append({
                    "#": i,
                    "Player": p.player,
                    "Team": p.team,
                    "vs": p.opponent,
                    "Stat": p.stat,
                    "L10": p.recent_avg,
                    "MPG": p.mpg,
                    "DVP": p.dvp_value,
                    "ADJ": p.adjusted_dvp,
                    "PROJ": p.projected,
                    "Score": p.score,
                })
            
            df_overs = pd.DataFrame(over_data)
            st.dataframe(
                df_overs,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "#": st.column_config.NumberColumn(width="small"),
                    "Player": st.column_config.TextColumn(width="medium"),
                    "L10": st.column_config.NumberColumn(format="%.1f", help="Last 10 days avg"),
                    "MPG": st.column_config.NumberColumn(format="%.0f", help="Minutes per game"),
                    "DVP": st.column_config.NumberColumn(format="%.1f", help="Defense allows to ENTIRE position"),
                    "ADJ": st.column_config.NumberColumn(format="%.1f", help="DVP × (MPG/48) = Player's share"),
                    "PROJ": st.column_config.NumberColumn(format="%.1f", help="60% L10 + 40% ADJ"),
                    "Score": st.column_config.NumberColumn(format="%.1f"),
                }
            )
            st.caption("**ADJ** = DVP adjusted for player's minutes share")
        else:
            st.info("No over plays found")
    
    # ---------------------------------------------------
    # Tab 2: Under Plays
    # ---------------------------------------------------
    with tab2:
        st.subheader("📉 Top Under Plays")
        st.caption("Players who are COLD facing STRONG defenses")
        
        if top_plays["unders"]:
            under_data = []
            for i, p in enumerate(top_plays["unders"], 1):
                under_data.append({
                    "#": i,
                    "Player": p.player,
                    "Team": p.team,
                    "vs": p.opponent,
                    "Stat": p.stat,
                    "L10": p.recent_avg,
                    "MPG": p.mpg,
                    "DVP": p.dvp_value,
                    "ADJ": p.adjusted_dvp,
                    "PROJ": p.projected,
                    "Score": p.score,
                })
            
            df_unders = pd.DataFrame(under_data)
            st.dataframe(
                df_unders,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "#": st.column_config.NumberColumn(width="small"),
                    "Player": st.column_config.TextColumn(width="medium"),
                    "L10": st.column_config.NumberColumn(format="%.1f", help="Last 10 days avg"),
                    "MPG": st.column_config.NumberColumn(format="%.0f", help="Minutes per game"),
                    "DVP": st.column_config.NumberColumn(format="%.1f", help="Defense allows to ENTIRE position"),
                    "ADJ": st.column_config.NumberColumn(format="%.1f", help="DVP × (MPG/48) = Player's share"),
                    "PROJ": st.column_config.NumberColumn(format="%.1f", help="60% L10 + 40% ADJ"),
                    "Score": st.column_config.NumberColumn(format="%.1f"),
                }
            )
            st.caption("**ADJ** = DVP adjusted for player's minutes share")
        else:
            st.info("No under plays found")
    
    # ---------------------------------------------------
    # Tab 3: Line Analyzer (Improved)
    # ---------------------------------------------------
    with tab3:
        st.subheader("🎯 Line Analyzer")
        
        # Build play list
        all_plays_list = []
        for p in top_plays["overs"]:
            all_plays_list.append((p, "OVER", "🟢"))
        for p in top_plays["unders"]:
            all_plays_list.append((p, "UNDER", "🔴"))
        
        # Two modes: Browse plays or Custom entry
        mode = st.radio("Mode", ["📋 Browse Plays", "✏️ Custom Entry"], horizontal=True)
        
        st.divider()
        
        if mode == "📋 Browse Plays" and all_plays_list:
            # Initialize play index in session state
            if "play_index" not in st.session_state:
                st.session_state.play_index = 0
            
            total_plays = len(all_plays_list)
            
            # Navigation buttons
            col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])
            
            with col1:
                if st.button("⏮️ First", use_container_width=True):
                    st.session_state.play_index = 0
            
            with col2:
                if st.button("◀️ Prev", use_container_width=True):
                    st.session_state.play_index = max(0, st.session_state.play_index - 1)
            
            with col3:
                st.markdown(f"<h3 style='text-align: center;'>{st.session_state.play_index + 1} / {total_plays}</h3>", unsafe_allow_html=True)
            
            with col4:
                if st.button("Next ▶️", use_container_width=True):
                    st.session_state.play_index = min(total_plays - 1, st.session_state.play_index + 1)
            
            with col5:
                if st.button("Last ⏭️", use_container_width=True):
                    st.session_state.play_index = total_plays - 1
            
            # Get current play
            play, direction, emoji = all_plays_list[st.session_state.play_index]
            
            # Display current play info
            st.markdown(f"""
            <div class="play-card">
                <div class="play-title">{emoji} {play.player} - {play.stat} {direction}</div>
                <div>vs {play.opponent} | {play.team} | {play.position}</div>
            </div>
            """, unsafe_allow_html=True)
            
            # Stats display
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("L10 Avg", f"{play.recent_avg:.1f}" if play.recent_avg else "N/A")
            with col2:
                st.metric("MPG", f"{play.mpg:.0f}" if play.mpg else "?")
            with col3:
                st.metric("ADJ DVP", f"{play.adjusted_dvp:.1f}" if play.adjusted_dvp else "N/A")
            with col4:
                st.metric("PROJ", f"{play.projected:.1f}" if play.projected else "N/A")
            with col5:
                st.metric("Score", f"{play.score:.1f}")
            
            st.divider()
            
            # Line and odds input
            col1, col2 = st.columns(2)
            with col1:
                line = st.number_input("Betting Line", min_value=0.0, max_value=100.0, value=float(play.projected) if play.projected else 20.0, step=0.5, key="browse_line")
            with col2:
                odds = st.number_input("Odds (American)", min_value=-500, max_value=500, value=-110, step=5, key="browse_odds")
            
            # Calculate and display edge
            if play.projected and line > 0:
                result = calculate_edge(play.projected, line, direction)
                edge_pct = result["edge_pct"]
                rec = result["recommendation"]
                
                # Show recommendation
                if result["color"] == "green":
                    st.success(f"### {rec} | Edge: {edge_pct:+.1f}%")
                elif result["color"] == "blue":
                    st.info(f"### {rec} | Edge: {edge_pct:+.1f}%")
                elif result["color"] == "orange":
                    st.warning(f"### {rec} | Edge: {edge_pct:+.1f}%")
                else:
                    st.error(f"### {rec} | Edge: {edge_pct:+.1f}%")
                
                # Kelly calculation
                decimal_odds = american_to_decimal(odds)
                implied_prob = decimal_to_implied_prob(decimal_odds)
                win_prob = estimate_win_probability(edge_pct)
                kelly = calculate_kelly(win_prob, decimal_odds, fraction=0.25)
                kelly_bet = bankroll * (kelly['kelly_adjusted'] / 100) if bankroll > 0 else 0
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Est. Win %", f"{win_prob*100:.1f}%")
                with col2:
                    st.metric("¼ Kelly", f"{kelly['kelly_adjusted']:.2f}%")
                with col3:
                    st.metric("Kelly Suggests", f"${kelly_bet:.2f}")
                
                # Custom bet amount input
                st.divider()
                col1, col2 = st.columns([2, 1])
                with col1:
                    custom_bet = st.number_input(
                        "💵 Your Bet Amount", 
                        min_value=0.0, 
                        max_value=bankroll if bankroll > 0 else 10000.0,
                        value=round(kelly_bet, 2),
                        step=5.0,
                        key="browse_bet_amt",
                        help="Kelly suggests above, but enter your own amount"
                    )
                with col2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("➕ Add to My Picks", type="primary", key="add_browse"):
                        pick_data = {
                            "player": play.player,
                            "stat": play.stat,
                            "direction": direction,
                            "opponent": play.opponent,
                            "projection": play.projected,
                            "line": line,
                            "odds": odds,
                            "edge_%": round(edge_pct, 1),
                            "win_prob_%": round(win_prob * 100, 1),
                            "kelly_%": round(kelly['kelly_adjusted'], 2),
                            "kelly_bet": round(kelly_bet, 2),
                            "bet_amount": round(custom_bet, 2),
                            "recommendation": rec,
                        }
                        add_pick(pick_data)
                        st.success(f"✅ Added {play.player} {play.stat} {direction} for ${custom_bet:.2f}!")
                        st.balloons()
        
        elif mode == "✏️ Custom Entry":
            st.markdown("### Enter a custom play")
            
            col1, col2 = st.columns(2)
            with col1:
                custom_player = st.text_input("Player Name", placeholder="e.g., LeBron James")
                custom_stat = st.selectbox("Stat", ["PTS", "REB", "AST", "3PM", "STL", "BLK", "PR", "PA", "PRA"])
                custom_direction = st.selectbox("Direction", ["OVER", "UNDER"])
            
            with col2:
                custom_proj = st.number_input("Your Projection", min_value=0.0, max_value=100.0, value=20.0, step=0.5)
                custom_line = st.number_input("Betting Line", min_value=0.0, max_value=100.0, value=20.0, step=0.5, key="custom_line")
                custom_odds = st.number_input("Odds (American)", min_value=-500, max_value=500, value=-110, step=5, key="custom_odds")
            
            custom_opponent = st.text_input("Opponent (optional)", placeholder="e.g., LAL")
            
            if custom_player and custom_proj > 0 and custom_line > 0:
                result = calculate_edge(custom_proj, custom_line, custom_direction)
                edge_pct = result["edge_pct"]
                rec = result["recommendation"]
                
                st.divider()
                
                if result["color"] == "green":
                    st.success(f"### {rec} | Edge: {edge_pct:+.1f}%")
                elif result["color"] == "blue":
                    st.info(f"### {rec} | Edge: {edge_pct:+.1f}%")
                elif result["color"] == "orange":
                    st.warning(f"### {rec} | Edge: {edge_pct:+.1f}%")
                else:
                    st.error(f"### {rec} | Edge: {edge_pct:+.1f}%")
                
                # Kelly
                decimal_odds = american_to_decimal(custom_odds)
                win_prob = estimate_win_probability(edge_pct)
                kelly = calculate_kelly(win_prob, decimal_odds, fraction=0.25)
                kelly_bet = bankroll * (kelly['kelly_adjusted'] / 100) if bankroll > 0 else 0
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Est. Win %", f"{win_prob*100:.1f}%")
                with col2:
                    st.metric("¼ Kelly", f"{kelly['kelly_adjusted']:.2f}%")
                with col3:
                    st.metric("Kelly Suggests", f"${kelly_bet:.2f}")
                
                # Custom bet amount input
                st.divider()
                col1, col2 = st.columns([2, 1])
                with col1:
                    custom_bet_amt = st.number_input(
                        "💵 Your Bet Amount", 
                        min_value=0.0, 
                        max_value=bankroll if bankroll > 0 else 10000.0,
                        value=round(kelly_bet, 2),
                        step=5.0,
                        key="custom_bet_amt",
                        help="Kelly suggests above, but enter your own amount"
                    )
                with col2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("➕ Add Custom Pick", type="primary", key="add_custom"):
                        pick_data = {
                            "player": custom_player,
                            "stat": custom_stat,
                            "direction": custom_direction,
                            "opponent": custom_opponent or "?",
                            "projection": custom_proj,
                            "line": custom_line,
                            "odds": custom_odds,
                            "edge_%": round(edge_pct, 1),
                            "win_prob_%": round(win_prob * 100, 1),
                            "kelly_%": round(kelly['kelly_adjusted'], 2),
                            "kelly_bet": round(kelly_bet, 2),
                            "bet_amount": round(custom_bet_amt, 2),
                            "recommendation": rec,
                            "custom": True,
                        }
                        add_pick(pick_data)
                        st.success(f"✅ Added: {custom_player} {custom_stat} {custom_direction} for ${custom_bet_amt:.2f}!")
                        st.balloons()
    
    # ---------------------------------------------------
    # Tab 4: My Picks (Persistent)
    # ---------------------------------------------------
    with tab4:
        st.subheader("📋 My Picks")
        st.caption("Your picks are saved and persist across refreshes")
        
        picks = load_picks()
        
        if picks:
            # Summary stats
            total_bets = sum(p.get("bet_amount", 0) for p in picks)
            avg_edge = sum(p.get("edge_%", 0) for p in picks) / len(picks)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Picks", len(picks))
            with col2:
                st.metric("Total Bet Amount", f"${total_bets:.2f}")
            with col3:
                st.metric("Avg Edge", f"{avg_edge:+.1f}%")
            
            st.divider()
            
            # Display picks as a table
            picks_df = pd.DataFrame(picks)
            
            # Reorder columns for display
            display_cols = ["player", "stat", "direction", "opponent", "projection", "line", "odds", "edge_%", "kelly_bet", "bet_amount", "recommendation"]
            available_cols = [c for c in display_cols if c in picks_df.columns]
            
            st.dataframe(
                picks_df[available_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "player": st.column_config.TextColumn("Player", width="medium"),
                    "stat": st.column_config.TextColumn("Stat", width="small"),
                    "direction": st.column_config.TextColumn("Dir", width="small"),
                    "projection": st.column_config.NumberColumn("PROJ", format="%.1f"),
                    "line": st.column_config.NumberColumn("Line", format="%.1f"),
                    "odds": st.column_config.NumberColumn("Odds"),
                    "edge_%": st.column_config.NumberColumn("Edge %", format="%.1f"),
                    "kelly_bet": st.column_config.NumberColumn("Kelly $", format="%.2f", help="What Kelly recommended"),
                    "bet_amount": st.column_config.NumberColumn("Your Bet $", format="%.2f", help="What you're actually betting"),
                }
            )
            
            st.divider()
            
            # Individual pick management
            st.markdown("### Remove Individual Picks")
            for i, pick in enumerate(picks):
                col1, col2 = st.columns([4, 1])
                with col1:
                    emoji = "🟢" if pick.get("direction") == "OVER" else "🔴"
                    st.text(f"{emoji} {pick['player']} {pick['stat']} {pick['direction']} @ {pick['line']} ({pick.get('recommendation', '')})")
                with col2:
                    if st.button("🗑️", key=f"remove_{i}"):
                        remove_pick(i)
                        st.rerun()
            
            st.divider()
            
            # Bulk actions
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("🗑️ Clear All Picks", type="secondary"):
                    clear_all_picks()
                    st.rerun()
            
            with col2:
                csv = picks_df.to_csv(index=False)
                st.download_button(
                    "📥 Download CSV",
                    csv,
                    f"my_picks_{datetime.now().strftime('%Y-%m-%d')}.csv",
                    "text/csv"
                )
            
            with col3:
                # Calculate potential winnings
                if st.button("📊 Calculate Potential"):
                    st.markdown("### Potential Returns")
                    for pick in picks:
                        odds = pick.get("odds", -110)
                        bet = pick.get("bet_amount", 0)
                        decimal_odds = american_to_decimal(odds)
                        potential_win = bet * (decimal_odds - 1)
                        st.text(f"{pick['player']} {pick['stat']}: Bet ${bet:.2f} → Win ${potential_win:.2f}")
        
        else:
            st.info("No picks yet. Add some from the Line Analyzer tab!")
            st.markdown("""
            ### How to add picks:
            1. Go to **🎯 Line Analyzer** tab
            2. Browse plays with ◀️ ▶️ buttons or enter custom picks
            3. Enter the betting line and odds
            4. Click **➕ Add to My Picks**
            
            Your picks will be saved here and persist even after refreshing!
            """)


if __name__ == "__main__":
    main()
