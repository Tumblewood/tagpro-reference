import csv
import os
import sys
import django
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tagproref.settings")
django.setup()

from reference.models import Season, TeamSeason, PlayerSeason, Transaction

CSV_PATH = os.path.join(os.path.dirname(__file__), "transactions.csv")

ADD_OR_DRAFT_TYPES = {"draft", "add", "prelim", "trade for"}


def parse_week_number(week_str):
    """Parse 'Week 4' -> 4."""
    parts = week_str.strip().split()
    if len(parts) == 2 and parts[0].lower() == "week" and parts[1].isdigit():
        return int(parts[1])
    raise ValueError(f"Cannot parse week: {week_str!r}")


def find_player_season(season, player_name):
    """Find PlayerSeason by playing_as (case-insensitive), falling back to player.name."""
    qs = PlayerSeason.objects.filter(season=season)
    ps = qs.filter(playing_as__iexact=player_name).first()
    if ps:
        return ps
    return qs.filter(player__name__iexact=player_name).first()


def main():
    created = 0
    skipped = 0
    flagged = []

    season_cache = {}
    team_cache = {}

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for i, row in enumerate(rows, start=2):  # start=2 because row 1 is header
        season_name = row["season"].strip()
        player_name = row["player"].strip()
        tc = int(row["tc"])
        team_abbr = row["team"].strip()
        transaction_type = row["type"].strip()
        week_str = row["week"].strip()

        try:
            before_week = parse_week_number(week_str)
        except ValueError as e:
            flagged.append(f"Row {i}: {e}")
            continue

        # Resolve season
        if season_name not in season_cache:
            season_cache[season_name] = Season.objects.filter(name=season_name).first()
        season = season_cache[season_name]
        if season is None:
            flagged.append(f"Row {i}: Season not found: {season_name!r}")
            continue

        # Resolve team
        team_key = (season.id, team_abbr)
        if team_key not in team_cache:
            team_cache[team_key] = TeamSeason.objects.filter(season=season, abbr=team_abbr).first()
        team = team_cache[team_key]
        if team is None:
            flagged.append(f"Row {i}: Team not found: abbr={team_abbr!r} in {season_name!r}")
            continue

        # Resolve player season
        player_season = find_player_season(season, player_name)
        if player_season is None:
            flagged.append(
                f"Row {i}: Player not found: {player_name!r} in {season_name!r}"
            )
            continue

        # Check for existing transaction (idempotent)
        exists = Transaction.objects.filter(
            team=team,
            player_season=player_season,
            transaction_type=transaction_type,
            before_week=before_week,
        ).exists()

        if exists:
            skipped += 1
            continue

        Transaction.objects.create(
            team=team,
            player_season=player_season,
            transaction_type=transaction_type,
            before_week=before_week,
            net_tc_spent=tc,
        )
        created += 1

    print(f"Created: {created} | Already existed (skipped): {skipped}")
    if flagged:
        print(f"\nFLAGGED — {len(flagged)} rows could not be processed:")
        for msg in flagged:
            print(f"  {msg}")
    else:
        print("No issues flagged.")


if __name__ == "__main__":
    main()
