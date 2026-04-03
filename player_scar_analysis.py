#!/usr/bin/env .venv/bin/python
"""
Script to show minutes and SCAR stats per blowout-weighted minute for MLTP players.
Usage: .venv/bin/python player_scar_analysis.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tagproref.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.db import models
from reference.models import Player, PlayerSeason, PlayerRegulationStats
from reference.utils.stat_collection import calculate_blowout_multiplier

PLAYER_NAMES = [
    "CarrotCake",
    "DanP",
    "mex",
    "meowza",
    "OuchMyBalls",
    "jig",
    "fender",
    "realtea",
    "Arbybear",
    "Ty",
    "bbb",
    "rina",
    "joy.",
    "Cheetosrule",
    "Mr awesome:)",
    "Button",
    "kelvin",
    "NameLEss",
    "BallSaget",
    "Carrrrrl",
    "Taurus",
    "dodsfall",
    "Russ",
    "fm",
    "king krule",
    "Curry",
    "Kep",
    "AJ.",
    "aaron",
    "d0pe",
    "Phreek",
    "Spjork",
    "I'm a horse",
    "AdmaniaYT",
    "waterwheel",
    "Bamboozler",
    "Sadness",
    "Poeticalto",
    "Squeeb",
    "Prime",
    "yiss",
    "Tinderfella",
    "beef",
    "#SelfySyntax",
    "pulpo",
]
PLAYER_NAMES = [
    "Agency",
    "MarcusYallow",
    "Suchit",
    "DT",
    "Xx360NoSwagx",
    "ASAP",
    "Sif",
    "1deag",
]


def analyze_player_mltp_seasons(player_names):
    """
    Analyze MLTP seasons for a list of players.

    Args:
        player_names: List of player names to analyze

    Returns:
        Dict mapping player names to their season stats
    """
    results = {}

    for player_name in player_names:
        try:
            player = Player.objects.get(name=player_name)
        except Player.DoesNotExist:
            print(f"Warning: Player '{player_name}' not found")
            continue

        # Get all MLTP seasons for this player
        mltp_seasons = PlayerSeason.objects.filter(
            player=player,
            season__name__icontains="MLTP"
        ).select_related("season").order_by("season__name")

        if not mltp_seasons.exists():
            print(f"Warning: No MLTP seasons found for {player_name}")
            continue

        player_results = []

        for player_season in mltp_seasons:
            # Get all regulation stats for this player season
            reg_stats = PlayerRegulationStats.objects.filter(
                player_gamelog__player_season=player_season
            ).select_related(
                "player_gamelog__game__match",
                "player_gamelog__team"
            )

            if not reg_stats.exists():
                continue

            # Calculate totals
            total_minutes = 0
            total_blowout_weighted_minutes = 0
            total_oscar = 0
            total_dscar = 0

            for stat in reg_stats:
                game = stat.player_gamelog.game
                player_team = stat.player_gamelog.team
                is_team1 = player_team == game.match.team1

                # Calculate cap differential for blowout multiplier
                if is_team1:
                    cap_differential = game.team1_score - game.team2_score
                else:
                    cap_differential = game.team2_score - game.team1_score

                blowout_multiplier = calculate_blowout_multiplier(cap_differential)

                # Convert time from ticks to minutes
                time_played_minutes = (stat.time_played or 0) / 3600
                blowout_weighted_minutes = time_played_minutes * blowout_multiplier

                total_minutes += time_played_minutes
                total_blowout_weighted_minutes += blowout_weighted_minutes
                total_oscar += stat.oscar or 0
                total_dscar += stat.dscar or 0

            # Calculate per-minute stats
            if total_blowout_weighted_minutes > 0:
                oscar_per_min = total_oscar / total_blowout_weighted_minutes
                dscar_per_min = total_dscar / total_blowout_weighted_minutes
                tscar_per_min = (total_oscar + total_dscar) / total_blowout_weighted_minutes
            else:
                oscar_per_min = 0
                dscar_per_min = 0
                tscar_per_min = 0

            total_tscar = total_oscar + total_dscar

            player_results.append({
                "season": player_season.season.name,
                "minutes": total_minutes,
                "blowout_weighted_minutes": total_blowout_weighted_minutes,
                "oscar": total_oscar,
                "dscar": total_dscar,
                "tscar": total_tscar,
                "oscar_per_min": oscar_per_min,
                "dscar_per_min": dscar_per_min,
                "tscar_per_min": tscar_per_min,
            })

        if player_results:
            results[player_name] = player_results

    return results


def print_results(results):
    """Print the analysis results in a readable format."""
    for player_name, seasons in results.items():
        print(f"\n{'=' * 80}")
        print(f"Player: {player_name}")
        print(f"{'=' * 80}")

        for season_data in sorted(seasons, key=lambda x: x['season'].lower()):
            if season_data['blowout_weighted_minutes'] > 100 and int(season_data['season'][-2:]) >= 20:
                print(f"{season_data['season']}:  "
                    f"Min: {season_data['blowout_weighted_minutes']:>3.0f}  "
                    f"OSCAR: {season_data['oscar_per_min'] * 10:+.2f}  "
                    f"DSCAR per half: {season_data['dscar_per_min'] * 10:+.2f}  "
                    f"TSCAR per half: {season_data['tscar_per_min'] * 10:+.2f}")


def main():
    """Main function to run the analysis."""
    if not PLAYER_NAMES:
        print("No players in PLAYER_NAMES list. Please edit the script and add player names.")
        return

    print(f"Analyzing {len(PLAYER_NAMES)} player(s)...\n")
    results = analyze_player_mltp_seasons(PLAYER_NAMES)
    print_results(results)


if __name__ == "__main__":
    main()