import os
import django
import csv
from collections import defaultdict
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tagproref.settings")
django.setup()

from django.db import models
from reference.models import (
    Season, Player, PlayerSeason, PlayerGameLog, TeamSeason, Franchise,
    AwardType, AwardReceived
)

# Awards that should not have a team even if the player played that season
NON_TEAM_AWARDS = {
    "Behind the Scenes",
    "Behind-the-scenes",
    "Best Streamer",
    "Streamer",
    "Best Commentator",
    "Commentator",
    "Community Contributor",
}

# Team awards (require a team, not a player)
TEAM_AWARDS = {
    "Most Cohesive Unit",
    "Deceiving Record",
    "Best Roster Moves",
}

# Award name mapping to standardize variations
AWARD_NAME_MAPPING = {
    "MVB": "Most Valuable Ball",
    "Fuck you and your GASP": "FU GASP",
    "Fuck You and Your GASP": "FU GASP",
    "\"Fuck you and your GASP\"": "FU GASP",
    "Fuck that GASP": "FU GASP",
    "OBOS": "Offensive Ball of the Season",
    "DBOS": "Defensive Ball of the Season",
    "OROS": "Offensive Rookie of the Season",
    "DROS": "Defensive Rookie of the Season",
    "Offensive Rookie": "Offensive Rookie of the Season",
    "Defensive Rookie": "Defensive Rookie of the Season",
    "Rookie (ROS)": "Rookie of the Season",
    "Defense Rookie (DROS)": "Defensive Rookie of the Season",
    "5th Ball": "Best 5th Ball",
    "Best Value": "Best Valued",
    "Best Valued Ball": "Best Valued",
    "Most Well-Rounded Ball": "Well Rounded",
    "Most Well Rounded Ball": "Well Rounded",
    "Most Well Rounded": "Well Rounded",
    "Best Well Rounded Ball": "Well Rounded",
    "Well-Rounded Ball": "Well Rounded",
    "Best Two-Way Player": "Well Rounded",
    "Most Improved Ball": "Most Improved",
    "Best Western Conference Captain": "Best Western Captain",
    "Best Eastern Conference Captain": "Best Eastern Captain",
    "Western Captain": "Best Western Captain",
    "Eastern Captain": "Best Eastern Captain",
    "Cohesive": "Most Cohesive Unit",
    "Most Cohesive Team": "Most Cohesive Unit",
    "Best Individual Performance Offense": "Best Offensive Performance",
    "Best Individual Performance Defense": "Best Defensive Performance",
    "Best Individual Offensive Performance": "Best Offensive Performance",
    "Best Individual Defensive Performance": "Best Defensive Performance",
    "BIOP": "Best Offensive Performance",
    "BIDP": "Best Defensive Performance",
    "Offensive Ball of the Year": "Offensive Ball of the Season",
    "Defensive Ball of the Year": "Defensive Ball of the Season",
    "Offensive Team Ball": "Best Offensive Team Ball",
    "Defensive Team Ball": "Best Defensive Team Ball",
    "Best Captain (Overall)": "Best Overall Captain",
    "Best S8 Captain": "Best Overall Captain",
    "Best Northeast Captain": "Best Captain (Northeast)",
    "Best Atlantic Captain": "Best Captain (Atlantic)",
    "Best Central Captain": "Best Captain (Central)",
    "Best Pacific Captain": "Best Captain (Pacific)",
    "Best Rocky Division Captain": "Best Captain (Rocky)",
    "Best Cascades Division Captain": "Best Captain (Cascades)",
    "Best Ozark Division Captain": "Best Captain (Ozark)",
    "Best Blue Ridge Division Captain": "Best Captain (Blue Ridge)",
    "Best Adirondack Division Captain": "Best Captain (Adirondack)",
    "Best Allegheny Division Captain": "Best Captain (Allegheny)",
    "Best Atlantic Cocaptain": "Best Co-Captain (Atlantic)",
    "Best Northeast Cocaptain": "Best Co-Captain (Northeast)",
    "Best Central Cocaptain": "Best Co-Captain (Central)",
    "Best Pacific Cocaptain": "Best Co-Captain (Pacific)",
    "Best S8 Cocaptain": "Best Overall Co-Captain",
    "Best Overall Co-Captain": "Best Co-Captain",
    "Streamer": "Best Streamer",
    "Commentator": "Best Commentator",
    "Disappearance": "Most Notable Disappearance",
    "Best Roster Move": "Best Roster Moves",
    "Best Defensive Pairing": "Best Defensive Pair",
    "Best Offensive Pairing": "Best Offensive Pair",
    "Behind-the-scenes": "Behind the Scenes",
}


def normalize_award_name(name):
    """Normalize award name using mapping."""
    return AWARD_NAME_MAPPING.get(name, name)


def create_award_abbreviation(name):
    """Create a reasonable abbreviation for an award name."""
    # Special cases
    abbr_map = {
        "Best 5th Ball": "5th Ball",
        "Best Streamer": "Best Streamer",
        "Best Commentator": "Best Commentator",
        "Behind the Scenes": "Behind the Scenes",
        "Most Notable Disappearance": "Disappearance",
        "Best Roster Moves": "Best Roster Moves",
        "Best Call-up": "Best Call-up",
        "Forget MLTP": "Forget MLTP",
        "Best Veteran": "Best Veteran",
        "Best Offensive Team Ball": "BOTB",
        "Best Defensive Team Ball": "BDTB",
        "Best Offensive Performance": "BOP",
        "Best Defensive Performance": "BDP",
        "Best Overall Captain": "Best Captain",
        "Rookie of the Season": "ROS",
        "Random Stat": "Random Stat",
        "Deceiving Record": "Deceiving Record",
        "Community Contributor": "Community Contributor",
    }

    if name in abbr_map:
        return abbr_map[name]

    # For divisional captain awards, use the division name
    if name.startswith("Best Captain (") or name.startswith("Best Co-Captain ("):
        return name

    return name


def find_or_create_award_type(award_name):
    """Find or create an AwardType for the given award name."""
    normalized_name = normalize_award_name(award_name)

    # Try to find existing award type
    try:
        return AwardType.objects.get(name=normalized_name)
    except AwardType.DoesNotExist:
        pass

    # Try case-insensitive match
    award_types = AwardType.objects.filter(name__iexact=normalized_name)
    if award_types.exists():
        return award_types.first()

    # Return None if not found (we'll handle creation separately)
    return None


def find_player(player_name, season):
    """Find a player using the priority system."""
    if not player_name:
        return None

    # 1. PlayerSeason from that season with matching name
    player_seasons = PlayerSeason.objects.filter(
        season=season,
        playing_as__iexact=player_name
    )
    if player_seasons.exists():
        return player_seasons.first().player

    # 2. Player with matching name
    try:
        return Player.objects.get(name__iexact=player_name)
    except Player.DoesNotExist:
        pass
    except Player.MultipleObjectsReturned:
        # If multiple, just take the first
        return Player.objects.filter(name__iexact=player_name).first()

    # 3. PlayerSeason from any season with matching name
    player_seasons = PlayerSeason.objects.filter(playing_as__iexact=player_name)
    if player_seasons.exists():
        return player_seasons.first().player

    # 4. PlayerGameLog from that season with matching name
    game_logs = PlayerGameLog.objects.filter(
        game__match__season=season,
        playing_as__iexact=player_name
    )
    if game_logs.exists():
        return game_logs.first().player_season.player

    return None


def find_team(team_name, season, player=None, award_name=None):
    """Find a team using the priority system."""
    # Check if this award should not have a team
    if award_name and award_name in NON_TEAM_AWARDS:
        return None

    if not team_name:
        # 1. If player has a PlayerSeason for that season, use their team
        if player:
            player_seasons = PlayerSeason.objects.filter(
                season=season,
                player=player
            )
            if player_seasons.exists():
                return player_seasons.first().team
        return None

    # 2. TeamSeason for that season with matching name or abbr
    team_seasons = TeamSeason.objects.filter(
        season=season
    ).filter(
        models.Q(name__iexact=team_name) | models.Q(abbr__iexact=team_name)
    )
    if team_seasons.exists():
        return team_seasons.first()

    # 3. Franchise with matching name or abbr that has a team in this season
    franchises = Franchise.objects.filter(
        models.Q(name__iexact=team_name) | models.Q(abbr__iexact=team_name)
    )
    for franchise in franchises:
        team_season = TeamSeason.objects.filter(
            franchise=franchise,
            season=season
        ).first()
        if team_season:
            return team_season

    return None


ONLY_SEASONS = None # {"MLTP S19"}  # Set to None to import all seasons


def import_awards():
    """Import awards from CSV files."""
    unmapped_players = []
    unmapped_teams = []
    new_award_types_needed = set()
    created_count = 0
    skipped_count = 0

    csv_files = [
        "awards_import/out/awards.csv",
        "awards_import/out/awards-manual.csv"
    ]

    # First pass: collect all unique award types
    all_award_types = set()
    for csv_file in csv_files:
        with open(csv_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if ONLY_SEASONS and row["season"] not in ONLY_SEASONS:
                    continue
                all_award_types.add(normalize_award_name(row["award"]))

    # Check which award types need to be created
    print("Checking award types...")
    for award_name in sorted(all_award_types):
        award_type = find_or_create_award_type(award_name)
        if not award_type:
            new_award_types_needed.add(award_name)

    if new_award_types_needed:
        print(f"\nCreating {len(new_award_types_needed)} new AwardTypes...")
        # Get the highest ordering value
        max_ordering = AwardType.objects.aggregate(models.Max('ordering'))['ordering__max'] or 0

        for i, award_name in enumerate(sorted(new_award_types_needed)):
            # Double-check it doesn't exist (in case of race conditions or case issues)
            existing = find_or_create_award_type(award_name)
            if existing:
                print(f"  Skipped (already exists): {award_name}")
                continue

            abbr = create_award_abbreviation(award_name)
            ordering = max_ordering + i + 1
            AwardType.objects.create(
                name=award_name,
                abbr=abbr,
                ordering=ordering
            )
            print(f"  Created: {award_name} ({abbr})")
        print()

    print("All award types ready in database.\n")

    # Second pass: import the awards
    for csv_file in csv_files:
        print(f"\nProcessing {csv_file}...")
        with open(csv_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if ONLY_SEASONS and row["season"] not in ONLY_SEASONS:
                    continue
                season_name = row["season"]
                award_name = normalize_award_name(row["award"])
                placement = int(row["placement"]) if row["placement"] else 1
                team_name = row["team"]
                player_name = row["player"]
                percentage = float(row["percentage"]) if row["percentage"] else None

                # Find season
                try:
                    season = Season.objects.get(name=season_name)
                except Season.DoesNotExist:
                    print(f"  Season not found: {season_name}")
                    continue

                # Find award type
                award_type = find_or_create_award_type(award_name)
                if not award_type:
                    print(f"  Award type not found: {award_name}")
                    continue

                # Find player
                player = None
                if player_name:
                    player = find_player(player_name, season)
                    if not player:
                        unmapped_players.append((season_name, award_name, player_name))

                # Find team
                team = None
                if team_name or player:
                    team = find_team(team_name, season, player, award_name)
                    if not team and team_name and award_name not in NON_TEAM_AWARDS:
                        # Only report if it's not a non-team award
                        unmapped_teams.append((season_name, award_name, team_name or "(from player)"))

                # Validate required fields
                if award_name in TEAM_AWARDS:
                    # Team awards require a team
                    if not team:
                        print(f"  Skipping {season_name} {award_name} - team award requires a team")
                        continue
                else:
                    # Player awards require a player
                    if not player:
                        print(f"  Skipping {season_name} {award_name} - player award requires a player")
                        continue

                # Check if already exists
                existing = AwardReceived.objects.filter(
                    season=season,
                    player=player,
                    award=award_type,
                    placement=placement
                ).first()

                if existing:
                    skipped_count += 1
                    continue

                # Create award
                AwardReceived.objects.create(
                    season=season,
                    team=team,
                    player=player,
                    award=award_type,
                    placement=placement,
                    vote_share=percentage
                )
                created_count += 1

    print(f"\n{'='*60}")
    print(f"Import complete!")
    print(f"Created: {created_count}")
    print(f"Skipped (already exists): {skipped_count}")

    if unmapped_players:
        print(f"\n{'='*60}")
        print(f"Unmapped players ({len(unmapped_players)}):")
        for season, award, player in sorted(set(unmapped_players)):
            print(f"  {season} - {award}: {player}")

    if unmapped_teams:
        print(f"\n{'='*60}")
        print(f"Unmapped teams ({len(unmapped_teams)}):")
        for season, award, team in sorted(set(unmapped_teams)):
            print(f"  {season} - {award}: {team}")


if __name__ == "__main__":
    import_awards()
