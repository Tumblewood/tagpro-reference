import csv
import os

def parse_percentage(pct_str):
    """Convert percentage string like '31.45%' to decimal like 0.3145"""
    if not pct_str or pct_str.strip() == "":
        return ""
    return f"{float(pct_str.strip().rstrip('%')) / 100:.4f}"

def process_winner(name, team, is_team_award=False):
    """Split tied/paired winners and return list of (team, player) tuples"""
    if not name or name.strip() == "" or name == "None" or name == "-":
        return []

    # Split on // for tied/paired winners
    names = [n.strip() for n in name.split("//")]
    teams = [t.strip() for t in team.split("//")] if team and "//" in team else [team.strip() if team else ""] * len(names)

    # Make sure we have same number of teams as names
    if len(teams) < len(names):
        teams.extend([""] * (len(names) - len(teams)))

    results = []
    for n, t in zip(names, teams):
        if is_team_award:
            results.append((n, ""))
        else:
            results.append((t, n))

    return results

def process_file(input_file, season_name):
    """Process a single TSV file and return list of output rows"""
    # Team awards - these put the name in the team column instead of player column
    TEAM_AWARDS = {
        "Most Cohesive Unit"
    }

    output_rows = []

    with open(input_file, "r") as f:
        lines = f.readlines()

    # Track previous award for All-Stars continuation
    prev_award = None

    # Skip header
    for line in lines[1:]:
        parts = line.strip().split("\t")

        if len(parts) < 1 or not parts[0].strip():
            continue

        award = parts[0].strip()

        # Skip empty awards
        if not award:
            continue

        is_team_award = award in TEAM_AWARDS
        is_all_stars = award.startswith("All-Stars")

        # Parse the columns
        # Format: Award | 1st | Team | % of Vote | 2nd | Team | % of Vote | 3rd | Team | % of Vote
        first_name = parts[1].strip() if len(parts) > 1 else ""
        first_team = parts[2].strip() if len(parts) > 2 else ""
        first_pct = parts[3].strip() if len(parts) > 3 else ""

        second_name = parts[4].strip() if len(parts) > 4 else ""
        second_team = parts[5].strip() if len(parts) > 5 else ""
        second_pct = parts[6].strip() if len(parts) > 6 else ""

        third_name = parts[7].strip() if len(parts) > 7 else ""
        third_team = parts[8].strip() if len(parts) > 8 else ""
        third_pct = parts[9].strip() if len(parts) > 9 else ""

        # Skip awards with no valid first place
        if not first_name or first_name == "None":
            continue

        # Determine if this is a continuation of an All-Stars award (second line)
        # The second line has the same award name as the previous line
        is_all_stars_continuation = is_all_stars and award == prev_award

        # Process each placement
        if is_all_stars_continuation:
            # Second line of All-Stars: positions 4, 5, (6 is marked with "-")
            placements = [
                (4, first_name, first_team, first_pct),
                (5, second_name, second_team, second_pct),
            ]
        else:
            # Regular awards or first line of All-Stars: positions 1, 2, 3
            placements = [
                (1, first_name, first_team, first_pct),
                (2, second_name, second_team, second_pct),
                (3, third_name, third_team, third_pct),
            ]

        for placement, name, team, pct in placements:
            winners = process_winner(name, team, is_team_award)

            for team_val, player_val in winners:
                if player_val or team_val:  # Only add if there's a value
                    output_rows.append({
                        "season": season_name,
                        "award": award,
                        "placement": str(placement),
                        "team": team_val,
                        "player": player_val,
                        "percentage": parse_percentage(pct)
                    })

        prev_award = award

    return output_rows

# Map of file prefixes to league names
FILES_TO_PROCESS = {
    "majors": "MLTP",
    "minors": "mLTP",
    "novice": "NLTP",
    "bteam": "NLTP B"
}

base_dir = "awards_import"
season_number = 35

all_output_rows = []

for file_prefix, league_name in FILES_TO_PROCESS.items():
    input_file = os.path.join(base_dir, f"{file_prefix}-{season_number}.tsv")
    season_name = f"{league_name} S{season_number}"

    if os.path.exists(input_file):
        rows = process_file(input_file, season_name)
        all_output_rows.extend(rows)
        print(f"Processed {len(rows)} rows from {file_prefix}-{season_number}.tsv")
    else:
        print(f"Skipping {input_file} (file not found)")

# Write all output to a single CSV
output_file = os.path.join(base_dir, "out", "awards.csv")
with open(output_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["season", "award", "placement", "team", "player", "percentage"])
    writer.writeheader()
    writer.writerows(all_output_rows)

print(f"\nWrote {len(all_output_rows)} total rows to {output_file}")
