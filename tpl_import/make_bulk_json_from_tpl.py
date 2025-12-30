#!/usr/bin/env python3

import os
import sys
import django
import json
import requests
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
from typing import Dict, List, Optional, Any
import re

# Setup Django environment
sys.path.append(str(Path(__file__).parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tagproref.settings")
django.setup()

from reference.models import Season, TeamSeason
from reference.utils.data_entry import infer_team, infer_season, infer_player
from reference.views import format_compact_json
import tagpro_eu


def load_tpl_api_links():
    """Load the TPL API links JSON file"""
    data_file = (
        Path(__file__).parent.parent / "bulk_import_jsons" / "tpl_api_links.json"
    )
    with open(data_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_team_abbreviations():
    """Load team abbreviations from all_team_seasons.json"""
    data_file = "bulk_import_jsons/all_team_seasons.json"
    with open(data_file, "r", encoding="utf-8") as f:
        team_data = json.load(f)

    # Create a mapping from franchise name to abbreviation
    abbr_mapping = {}
    for franchise_name, franchise_data in team_data.items():
        if "abbr" in franchise_data:
            # Map both the franchise name and the maps_to name to the abbreviation
            abbr_mapping[franchise_name] = franchise_data["abbr"]
            if "maps_to" in franchise_data:
                abbr_mapping[franchise_data["maps_to"]] = franchise_data["abbr"]

    return abbr_mapping


def convert_unix_to_pacific_date(unix_timestamp):
    """Convert unix timestamp to Pacific time date"""
    # Create timezone-aware datetime from unix timestamp (assumes UTC)
    utc_dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)

    # Convert to Pacific time (UTC-8 or UTC-7 depending on DST)
    # For simplicity, we'll use a fixed offset of UTC-8
    # In production, you'd want to use proper timezone handling
    pacific_offset_hours = -8
    pacific_dt = utc_dt.replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=pacific_offset_hours))
    )

    return pacific_dt.date()


def get_game_in_match_name(game, half, all_games_for_match):
    """Generate game_in_match field based on game and half"""
    # Count how many halves exist for this specific game
    game_halves = [g for g in all_games_for_match if g["game"] == game]

    # If there's only one half for this game, don't include half in the name
    if len(game_halves) <= 1:
        return game
    else:
        # Multiple halves exist, include the half name
        return f"{game} {half}" if half else game


def has_tagpro_eu_link(links):
    """Check if links contain a tagpro.eu link (not pastebin)"""
    if not links:
        return False

    for link in links:
        if "tagpro.eu" in link:
            return True
    return False


def get_tagpro_eu_id(links):
    """Extract tagpro.eu match ID from links"""
    for link in links:
        if "tagpro.eu" in link:
            match = re.search(r"match=(\d+)", link)
            if match:
                return match.group(1)
    return None


def load_all_league_matches():
    """Load all league matches from bulk files"""
    all_matches = []

    # Load maps first
    maps_file = "data/league_maps.json"

    with open(maps_file, encoding="utf-8") as f:
        maps = tagpro_eu.bulk.load_maps(f)

    # Load all league_matches*.json files
    i = 1
    while True:
        matches_file = Path(__file__).parent / f"league_matches{i}.json"
        if not matches_file.exists():
            break

        try:
            with open(matches_file) as f:
                file_matches = list(tagpro_eu.bulk.load_matches(f, maps))
                all_matches.extend(file_matches)
                print(f"Loaded {len(file_matches)} matches from league_matches{i}.json")
        except Exception as e:
            print(f"Error loading {matches_file}: {e}")

        i += 1

    return all_matches


def extract_game_data_from_bulk(game_id: str, all_matches) -> Dict:
    """Extract basic game data from bulk matches."""
    try:
        # Find the match in our loaded matches
        m = None
        for match in all_matches:
            if match.match_id == game_id:
                m = match
                break

        if not m:
            print(f"Match {game_id} not found in bulk files")
            return None

        # Get the set of players who joined each team
        r_players = set()
        b_players = set()
        for e in m.create_timeline():
            if e[1][:4] == "Join":
                if m.team_red.name in e[1][10:]:
                    r_players.add(e[2].name)
                elif m.team_blue.name in e[1][10:]:
                    b_players.add(e[2].name)

        # Extract player stats from the match
        players = []
        for player in m.players:
            # Determine which team the player was on
            team = "red" if player.name in r_players else "blue"
            players.append({"username": player.name, "team": team})

        # Return all relevant game data
        return {
            "game_id": game_id,
            "date": m.date.timestamp(),  # Unix timestamp
            "map_name": m.map.name,
            "map_id": getattr(m, "map_id", None),
            "team_red": {
                "name": m.team_red.name,
                "score": m.team_red.score,
                "players": r_players,
            },
            "team_blue": {
                "name": m.team_blue.name,
                "score": m.team_blue.score,
                "players": b_players,
            },
            "players": players,
        }
    except Exception as e:
        print(f"Error processing match {game_id}: {e}")
        return None


def create_bulk_json_for_season(
    tpl_data, league_name, season_number, all_matches, team_abbrs
):
    """Create bulk import JSON for a specific league and season"""

    # Filter games for this specific league and season
    season_games = [
        game
        for game in tpl_data["games"]
        if game["league"] == league_name and game["season"] == season_number
    ]

    if not season_games:
        print(f"No games found for {league_name} S{season_number}")
        return None

    # Get season group for team inference
    season_name = f"{league_name} S{season_number}"
    season_group = [s for s in Season.objects.filter(name=season_name)]

    # Track unique entities
    team_seasons: Dict[str, Dict] = {}
    player_seasons: Dict[str, Dict] = {}
    matches: Dict[str, Dict] = {}

    print(f"Processing {len(season_games)} games for {season_name}...")

    # Group games by match (week + teams) to determine which games have multiple halves
    matches_games = {}
    for game_info in season_games:
        match_key = (
            f"Week {game_info['week']} {game_info['team1']} vs {game_info['team2']}"
        )
        if match_key not in matches_games:
            matches_games[match_key] = []
        matches_games[match_key].append(game_info)

    for game_info in season_games:
        # Skip games without tagpro.eu links
        if not has_tagpro_eu_link(game_info.get("links", [])):
            print(
                f"Skipping game without tagpro.eu: {league_name} S{season_number}, Week {game_info['week']}"
            )
            continue

        tagpro_eu_id = get_tagpro_eu_id(game_info["links"])

        try:
            # Extract game data from bulk matches
            game_data = extract_game_data_from_bulk(tagpro_eu_id, all_matches)

            if not game_data:
                print(f"Could not extract game data for {tagpro_eu_id}, skipping...")
                continue

            # Infer teams
            red_team = (
                infer_team(season_group, game_info["team1"]) if season_group else None
            )
            blue_team = (
                infer_team(season_group, game_info["team2"]) if season_group else None
            )

            # Use inferred names if available, otherwise use TPL names
            team1_name = red_team.name if red_team else game_info["team1"]
            team2_name = blue_team.name if blue_team else game_info["team2"]

            # Get game date from tagpro.eu data and convert to Pacific time
            game_date = convert_unix_to_pacific_date(game_data["date"])

            # Create team season entries
            season_obj = (
                red_team.season
                if red_team
                else (blue_team.season if blue_team else None)
            )
            if not season_obj and season_group:
                season_obj = season_group[0]  # Fallback to first season in group

            if season_obj:
                # Team 1
                team1_key = f"{season_obj.name} {team1_name}"
                if team1_key not in team_seasons:
                    # Get abbreviation from our loaded team data
                    team1_abbr = (
                        red_team.abbr
                        if red_team
                        else team_abbrs.get(team1_name, game_info["team1"])
                    )

                    team_seasons[team1_key] = {
                        "season": season_obj.name,
                        "franchise": (
                            red_team.franchise.name
                            if red_team and red_team.franchise
                            else team1_name
                        ),
                        "name": team1_name,
                        "abbr": team1_abbr,
                    }

                # Team 2
                team2_key = f"{season_obj.name} {team2_name}"
                if team2_key not in team_seasons:
                    # Get abbreviation from our loaded team data
                    team2_abbr = (
                        blue_team.abbr
                        if blue_team
                        else team_abbrs.get(team2_name, game_info["team2"])
                    )

                    team_seasons[team2_key] = {
                        "season": season_obj.name,
                        "franchise": (
                            blue_team.franchise.name
                            if blue_team and blue_team.franchise
                            else team2_name
                        ),
                        "name": team2_name,
                        "abbr": team2_abbr,
                    }

            # Create match entry
            match_key = (
                f"{season_name} Week {game_info['week']} {team1_name} vs {team2_name}"
            )
            if match_key not in matches:
                matches[match_key] = {
                    "season": season_name,
                    "date": game_date.isoformat(),
                    "week": f"Week {game_info['week']}",
                    "team1": team1_name,
                    "team2": team2_name,
                    "games": [],
                }

            # Add game to match - get all games for this match to determine half naming
            current_match_key = (
                f"Week {game_info['week']} {game_info['team1']} vs {game_info['team2']}"
            )
            games_for_this_match = matches_games[current_match_key]
            game_in_match = get_game_in_match_name(
                game_info["game"], game_info.get("half"), games_for_this_match
            )

            game_entry = {
                "game_in_match": game_in_match,
                "tagpro_eu": int(tagpro_eu_id),
                "map_name": game_data.get("map_name"),
                "red_team": (
                    team1_name
                    if game_data["team_red"]["name"] == game_info["team1"]
                    or not red_team
                    else team2_name
                ),
                "blue_team": (
                    team2_name
                    if game_data["team_blue"]["name"] == game_info["team2"]
                    or not blue_team
                    else team1_name
                ),
                "team1_score": (
                    game_data["team_red"]["score"]
                    if game_data["team_red"]["name"] == game_info["team1"]
                    or not red_team
                    else game_data["team_blue"]["score"]
                ),
                "team2_score": (
                    game_data["team_blue"]["score"]
                    if game_data["team_blue"]["name"] == game_info["team2"]
                    or not blue_team
                    else game_data["team_red"]["score"]
                ),
                "players": game_data["players"],
            }

            matches[match_key]["games"].append(game_entry)

            # Add player seasons
            for player_data in game_data["players"]:
                player = infer_player(None, player_data["username"])
                if player and season_obj:
                    player_key = (
                        f"{season_obj.name} {player.name} {player_data['username']}"
                    )
                    if player_key not in player_seasons:
                        player_seasons[player_key] = {
                            "season": season_obj.name,
                            "player": player.name,
                            "playing_as": player_data["username"],
                            "team": (
                                team1_name
                                if player_data["team"] == "red"
                                and game_entry["red_team"] == team1_name
                                else (
                                    team2_name
                                    if player_data["team"] == "blue"
                                    and game_entry["blue_team"] == team2_name
                                    else (
                                        team1_name
                                        if player_data["team"] == "red"
                                        else team2_name
                                    )
                                )
                            ),
                        }

        except Exception as e:
            print(f"Error processing game {tagpro_eu_id}: {e}")
            continue

    # Build final JSON structure
    result = {
        "team_seasons": list(team_seasons.values()),
        "player_seasons": list(player_seasons.values()),
        "matches": list(matches.values()),
    }

    return result


def main():
    print("Loading TPL API links...")
    tpl_data = load_tpl_api_links()

    team_abbrs = load_team_abbreviations()

    print("Loading all league matches from bulk files...")
    all_matches = load_all_league_matches()

    if not all_matches:
        print(
            "No matches loaded! Please ensure league_matches*.json and league_maps.json files exist in the data directory."
        )
        return

    # Get unique combinations of league and season
    seasons = set()
    for game in tpl_data["games"]:
        seasons.add((game["league"], game["season"]))

    seasons = sorted(list(seasons))

    # Create output directory
    output_dir = Path(__file__).parent.parent / "bulk_import_jsons" / "tpl_generated"
    output_dir.mkdir(exist_ok=True)

    # Process each season
    for league, season in seasons:
        json_data = create_bulk_json_for_season(
            tpl_data, league, season, all_matches, team_abbrs
        )

        if json_data:
            # Write to file using compact format
            filename = f"{league} S{season}.json"
            output_file = output_dir / filename

            # Use the compact formatter from data_entry.py
            formatted_json = format_compact_json(json_data)

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(formatted_json)

            print(
                f"Created {filename} with {len(json_data['team_seasons'])} teams, {len(json_data['player_seasons'])} player seasons, {len(json_data['matches'])} matches"
            )

    print(f"\nAll files written to {output_dir}")


if __name__ == "__main__":
    main()
