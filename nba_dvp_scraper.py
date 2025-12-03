import re
import os
import sys
import pandas as pd
import subprocess
import argparse
import requests
from datetime import datetime
from shutil import which

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="Fetch table text from a URL (server-rendered tables only).")
    args = ap.parse_args()

    if args.url:
        try:
            raw = fetch_from_url(args.url)
        except Exception as e:
            print(f"URL fetch failed: {e}\n"
                  "If the site uses client-side JS, copy the visible table from the page and paste it instead.")
            sys.exit(1)
    else:
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
    print(f"\n✅ Parsed {len(df)} rows successfully!\n")

    for stat in ["PTS","REB","AST","PR","PA","PRA"]:
        print(f"\n### {stat} ###")
        for pos, s, kind, table in top_bottom_by_pos(df, stat):
            print(f"\n{pos} — {kind}")
            print(table.to_string(index=False))

    df = parse_position_block(raw)
    print(f"\n✅ Parsed {len(df)} rows successfully!\n")

    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = "outputs"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"dvp_summary_{today}.txt")

    with open(out_path, "w") as f:
        for stat in ["PTS","REB","AST","PR","PA","PRA"]:
            f.write(f"\n### {stat} ###\n")
            for pos, s, kind, table in top_bottom_by_pos(df, stat):
                f.write(f"\n{pos} — {kind}\n")
                f.write(table.to_string(index=False))
                f.write("\n")
    print(f"💾 Saved summary to {out_path}")

if __name__ == "__main__":
    main()
