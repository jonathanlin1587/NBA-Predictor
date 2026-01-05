# NBA Prop Analyzer

A comprehensive NBA player prop betting analysis tool that combines Defense vs Position (DVP) matchups, recent player performance, and betting odds to identify value plays.

## Features

- **DVP Analysis**: Scrapes and analyzes Defense vs Position data from Hashtag Basketball
- **Player Stats**: Tracks recent player performance over the last N days
- **Odds Integration**: Fetches live betting odds from The Odds API
- **Matchup Analysis**: Identifies favorable matchups by combining DVP ratings with player stats
- **Interactive Web UI**: Streamlit-based interface for analyzing props and tracking picks
- **Bankroll Management**: Track your picks, results, and bankroll over time
- **Daily Automation**: Scripts to scrape daily schedules, lineups, and odds

## Project Structure

```
NBA/
├── app.py                      # Main Streamlit web application
├── prop_analyzer.py            # Core analysis engine
├── nba_dvp_scraper.py          # Scrapes DVP data from Hashtag Basketball
├── odds_scraper.py             # Fetches betting odds from The Odds API
├── lineups_scraper.py          # Scrapes daily lineups
├── nba_daily_schedule.py       # Fetches daily NBA schedule
├── last_n_days_scraper.py      # Scrapes recent player statistics
├── prop_dvp_shortlist.py       # Generates DVP shortlist for favorable matchups
└── outputs/                    # Data output directory (organized by date)
    ├── YYYY-MM-DD/            # Daily data folders
    ├── my_picks.json          # Your tracked picks
    ├── analyzed_picks.json    # Historical analyzed plays
    └── bankroll.json          # Bankroll tracking
```

## Installation

### Prerequisites

- Python 3.8+
- pip

### Dependencies

Install required packages:

```bash
pip install streamlit pandas requests beautifulsoup4 cloudscraper
```

Or install individually:
- `streamlit` - Web UI framework
- `pandas` - Data manipulation
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing
- `cloudscraper` - Cloudflare bypass for scraping

### API Keys

The Odds API key is currently hardcoded in `odds_scraper.py`. For production use, consider moving it to an environment variable or config file.

## Usage

### Daily Workflow

1. **Fetch Daily Schedule**
   ```bash
   python nba_daily_schedule.py
   ```
   Generates `outputs/YYYY-MM-DD/schedule_YYYY-MM-DD.csv`

2. **Scrape DVP Data**
   ```bash
   python nba_dvp_scraper.py
   ```
   Or use manual paste mode if scraping fails:
   ```bash
   python nba_dvp_scraper.py --paste
   ```
   Generates `outputs/YYYY-MM-DD/dvp_summary_YYYY-MM-DD.txt` and `dvp_full_YYYY-MM-DD.json`

3. **Scrape Lineups**
   ```bash
   python lineups_scraper.py
   ```
   Generates `outputs/YYYY-MM-DD/lineups_YYYY-MM-DD.csv`

4. **Scrape Recent Player Stats**
   ```bash
   python last_n_days_scraper.py
   ```
   Generates `outputs/YYYY-MM-DD/last_n_days_YYYY-MM-DD.csv`

5. **Generate DVP Shortlist**
   ```bash
   python prop_dvp_shortlist.py
   ```
   Generates `outputs/YYYY-MM-DD/dvp_shortlist_results_YYYY-MM-DD.csv`

6. **Fetch Betting Odds** (Optional)
   ```bash
   python odds_scraper.py
   ```
   Or fetch specific market:
   ```bash
   python odds_scraper.py --market PTS
   ```
   Generates `outputs/YYYY-MM-DD/odds_lookup_YYYY-MM-DD.json`

### Web Application

Launch the Streamlit web interface:

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`

#### Web App Features

- **DVP Explorer**: Browse Defense vs Position ratings by stat, position, and team
- **Prop Analyzer**: View top plays combining DVP matchups with recent stats
- **Odds Lookup**: Search for player prop odds across multiple sportsbooks
- **Pick Tracker**: Add, edit, and track your betting picks with results
- **Bankroll Management**: Monitor your betting bankroll and ROI

### Command Line Analysis

Run the prop analyzer directly:

```bash
python prop_analyzer.py --dvp outputs/YYYY-MM-DD/dvp_shortlist_results_YYYY-MM-DD.csv --stats outputs/YYYY-MM-DD/last_n_days_YYYY-MM-DD.csv
```

Interactive mode for entering lines and calculating edge:

```bash
python prop_analyzer.py --interactive
```

## How It Works

### DVP (Defense vs Position) Analysis

The system scrapes DVP data that shows how well each NBA team defends against each position for various statistics (points, rebounds, assists, etc.). Teams are ranked as "WORST" (favorable for overs) or "BEST" (favorable for unders).

### Scoring System

Plays are scored based on:
- **DVP Value**: How favorable the matchup is (higher = better for overs)
- **Recent Performance**: Player's average over last N days
- **Games Played**: Sample size for recent stats (minimum 2 games required)
- **Minutes Per Game**: Adjusts DVP for player's role/usage

### Projection Calculation

The system calculates a blended projection that combines:
- Recent player average
- DVP-adjusted projection (accounting for matchup and minutes)

### Edge Calculation

When you enter a betting line, the system calculates:
- **Projected Value**: Expected stat output
- **Edge %**: Percentage difference between projection and line
- **Recommendation**: Bet size suggestion based on edge

## Configuration

Key settings in `prop_analyzer.py`:

- `MIN_GAMES = 2` - Minimum games required to consider a player
- `TOP_PLAYS_PER_CATEGORY = 8` - Number of top plays to show per stat category
- `OUTPUT_DIR = "outputs"` - Output directory for all data files

## Data Files

All data is organized by date in `outputs/YYYY-MM-DD/`:

- `schedule_YYYY-MM-DD.csv` - Daily game schedule
- `dvp_summary_YYYY-MM-DD.txt` - DVP summary (top/bottom teams)
- `dvp_full_YYYY-MM-DD.json` - Complete DVP data for all teams
- `lineups_YYYY-MM-DD.csv` - Starting lineups
- `last_n_days_YYYY-MM-DD.csv` - Recent player statistics
- `dvp_shortlist_results_YYYY-MM-DD.csv` - Favorable matchup candidates
- `odds_lookup_YYYY-MM-DD.json` - Betting odds from multiple sportsbooks

## Notes

- The system requires daily data scraping before analysis
- DVP data is scraped from Hashtag Basketball (may require manual paste if scraping fails)
- Odds are fetched from The Odds API (requires API key)
- All data is stored locally in the `outputs/` directory
- The web app caches data for 5 minutes (300 seconds) to improve performance

## License

This project is for personal use and educational purposes.
