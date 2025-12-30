import os
import sys
import django
import json
from pathlib import Path
from datetime import timedelta
from typing import Dict, List, Optional, Any, Tuple
import tagpro_eu

# Set up Django environment
sys.path.append(str(Path(__file__).parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tagproref.settings")
django.setup()

from reference.views import format_compact_json

with open("tpl_import/league_maps.json") as f:
    bulkmaps = json.load(f)
    bulkmaps: Dict[int, tagpro_eu.Map] = {int(k): bulkmaps[k] for k in bulkmaps}

bulkmatches: Dict[str, tagpro_eu.Match] = {}
for i in range(1, 10):
    with open(f"tpl_import/league_matches{i}.json") as f:
        for m in tagpro_eu.bulk.load_matches(f, bulkmaps):
            bulkmatches[str(m.match_id)] = m

with open("bulk_import_jsons/tpl_api_links.json", encoding="utf-8") as f:
    j = json.load(f)
    tpl_api_games = j["games"]

with open("bulk_import_jsons/all_team_seasons.json", encoding="utf-8") as f:
    all_team_seasons = json.load(f)

with open("tpl_import/schedules.json") as f:
    schedules = json.load(f)

seasons: Dict[str, List[Dict[str, Any]]] = {}
for g in tpl_api_games:
    season_name = f"{g['league']} S{g['season']}"
    if season_name not in seasons:
        seasons[season_name] = []
    seasons[season_name].append(g)


def match_from_links(g: Dict[str, Any]) -> Optional[tagpro_eu.Match]:
    if len(g["links"]) not in [1, 2]:
        return None
    if not all("tagpro.eu" in link for link in g["links"]):
        return None
    eu_id = g["links"][0].split("=")[1]
    if eu_id not in bulkmatches:
        return None
    # If there is a second tagpro.eu link, that's ok (though look into ones where the time limit is >10)
    if len(g["links"]) > 1:
        eu_id2 = g["links"][1].split("=")[1]
        if eu_id2 not in bulkmatches:
            return None
    return bulkmatches[eu_id]


def get_team_info(
    team_name: str, season_name: str
) -> Tuple[str, str, Optional[List[str]], Optional[str]]:
    season_name = season_name.lower().replace(" b", "").replace(" ", "_")
    history = all_team_seasons[team_name].get("history", {}).get(season_name, None)
    captain = history["captain"] if history else None
    roster = history["roster"] if history else []
    abbr = all_team_seasons[team_name]["abbr"]
    maps_to = all_team_seasons[team_name]["maps_to"]
    return abbr, maps_to, roster, captain


class DetectJoinHandler(tagpro_eu.PlayerEventHandler):
    def __init__(self):
        self.team = None

    def join(self, time, new_team):
        self.team = new_team


def get_t1_is_red(
    m: Optional[tagpro_eu.Match],
    g: Dict[str, Any],
    player_teams: Dict[str, Dict[str, int]],
) -> bool:
    # Get team info from all_team_seasons
    t1_abbr, _, t1_roster, _ = get_team_info(g["team1"], season_name)
    t2_abbr, _, t2_roster, _ = get_team_info(g["team2"], season_name)

    t1_is_red = 0
    if m is None:
        for p in g["stats"]:
            p_is_red = (
                2
                if g["stats"][p]["team"] == 1
                else -2 if g["stats"][p]["team"] == 2 else 0
            )
            if p.lower() in [o.lower() for o in t1_roster]:
                t1_is_red += p_is_red
            elif p.lower() in [o.lower() for o in t2_roster]:
                t1_is_red -= p_is_red
            t1_is_red += (
                1
                / 16
                * p_is_red
                * (
                    player_teams[p.lower()][g["team1"]]
                    - player_teams[p.lower()][g["team2"]]
                )
            )
    else:
        red_name: str = m.team_red.name
        blue_name: str = m.team_blue.name
        if red_name.strip().lower().endswith(t1_abbr.lower()):
            t1_is_red += 9
        elif red_name.strip().lower().endswith(t2_abbr.lower()):
            t1_is_red -= 9
        if blue_name.strip().lower().endswith(t1_abbr.lower()):
            t1_is_red -= 9
        elif red_name.strip().lower().endswith(t2_abbr.lower()):
            t1_is_red += 9

        for p in m.players:
            if p.team is None:
                handler = DetectJoinHandler()
                p.parse_events(handler)
                p_is_red = 2 if handler.team.name == "red" else -2
            else:
                p_is_red = 2 if p.team.name == red_name else -2
            if p.name.lower() in [o.lower() for o in t1_roster]:
                t1_is_red += p_is_red
            elif p.name.lower() in [o.lower() for o in t2_roster]:
                t1_is_red -= p_is_red
            t1_is_red += (
                1
                / 16
                * p_is_red
                * (
                    player_teams[p.name.lower()][g["team1"]]
                    - player_teams[p.name.lower()][g["team2"]]
                )
            )

    return t1_is_red > 0


def get_player_season_name(name: str, capitalization: Dict[str, Dict[str, int]]) -> str:
    name = name.lower()
    best_name = None
    best_amount = -1
    for n in capitalization[name]:
        if capitalization[name][n] > best_amount:
            best_name = n
            best_amount = capitalization[name][n]
    return best_name


STAT_MAPPING = {
    "minutes": "time_played",
    "pups": "powerups",
    "holdagainst": "hold_against",
    "pm": "plus_minus",
    "pupscomp": "total_pups_in_game",
    "quickret": "quick_returns",
    "retinbase": "returns_in_base",
    "keyret": "key_returns",
    "handoff": "handoffs",
    "goodhandoff": "good_handoffs",
    "goregrab": "grabs_off_handoffs",
    "goregrab": "grabs_off_regrab",
    "coregrab": "caps_off_handoffs",
    "coregrab": "caps_off_regrab",
    "longholds": "long_holds",
}


def rename_stats(stats: Dict[str, int]) -> Dict[str, int]:
    for stat in STAT_MAPPING:
        if stat in stats:
            if stats[stat] is None:
                continue
            stats[STAT_MAPPING[stat]] = stats[stat]
            if stat in ["hold", "prevent", "holdagainst"] and stats[stat]:
                stats[STAT_MAPPING[stat]] = int(
                    stats[STAT_MAPPING[stat]] * 60
                )  # convert from seconds to ticks
            if stat == "minutes":
                stats[STAT_MAPPING[stat]] = int(
                    stats[STAT_MAPPING[stat]] * 3600
                )  # convert from minutes to ticks
            del stats[stat]
    return stats


def group_matches_by_date(matches: List[Dict], season_name: str) -> List[Dict]:
    """Group matches played between same teams on same date and handle NLTP S10 week renaming."""
    # Group matches played between same teams on same date
    grouped_matches = {}
    for match in matches:
        # Create a key for grouping: team1, team2, date (normalize team order)
        team1, team2 = sorted([match["team1"], match["team2"]])
        match_key = f"{team1}_{team2}_{match['date']}"

        if match_key not in grouped_matches:
            grouped_matches[match_key] = []
        grouped_matches[match_key].append(match)

    # Process grouped matches
    new_matches = []
    for match_group in grouped_matches.values():
        if len(match_group) == 1:
            # Single match, no grouping needed
            new_matches.append(match_group[0])
        else:
            # Multiple matches on same date - group them
            # Sort by week (extract number) then by original match order
            def week_sort_key(m):
                week_str = m["week"]
                if "Week" in week_str:
                    try:
                        return int(week_str.split()[1])
                    except:
                        return 999
                return 999

            match_group.sort(key=week_sort_key)

            # Use the earliest match as the base
            base_match = match_group[0].copy()
            all_games = []

            # Collect all games from all matches
            for match in match_group:
                for game in match["games"]:
                    game["original_week"] = week_sort_key(match)
                    all_games.append(game)

            # Sort games by original week, then by game name
            def game_sort_key(g):
                week_num = g["original_week"]
                game_name = g["game_in_match"]
                # Extract game and half numbers for proper sorting
                try:
                    if "Game" in game_name and "Half" in game_name:
                        parts = game_name.split()
                        game_num = int(parts[1])
                        half_num = int(parts[3])
                        return (week_num, game_num, half_num)
                    elif "Game" in game_name:
                        game_num = int(game_name.split()[1])
                        return (week_num, game_num, 1)
                    else:
                        return (week_num, 999, 999)
                except:
                    return (week_num, 999, 999)

            all_games.sort(key=game_sort_key)

            # Rename games sequentially
            current_game_num = 1
            half_num = 1

            for game in all_games:
                original_name = game["game_in_match"]

                if "Overtime" in original_name:
                    # Overtime games keep the same game number as previous game
                    if (
                        "Overtime 2" in original_name
                        or "Overtime 3" in original_name
                        or "Overtime 4" in original_name
                    ):
                        # Multiple overtimes - extract the overtime number
                        ot_parts = original_name.split()
                        if len(ot_parts) >= 2 and ot_parts[-1].isdigit():
                            ot_num = ot_parts[-1]
                            game["game_in_match"] = (
                                f"Game {current_game_num} Overtime {ot_num}"
                            )
                        else:
                            game["game_in_match"] = f"Game {current_game_num} Overtime"
                    else:
                        game["game_in_match"] = f"Game {current_game_num} Overtime"
                else:
                    # Regular game
                    if half_num > 2:
                        # We've finished a game (after Half 1, Half 2, potentially overtimes)
                        current_game_num += 1
                        half_num = 1

                    game["game_in_match"] = f"Game {current_game_num} Half {half_num}"
                    half_num += 1

                # Remove the temporary sorting field
                del game["original_week"]

            base_match["games"] = all_games
            new_matches.append(base_match)

    # Handle NLTP S10 week renaming
    if season_name in ["NLTP S10", "NLTP B S10"]:
        for match in new_matches:
            week_str = match["week"]
            if "Week" in week_str:
                try:
                    week_num = int(week_str.split()[1])
                    new_week_num = (week_num + 2) // 3
                    match["week"] = f"Week {new_week_num}"
                except:
                    pass

    return new_matches


def do_player_first_pass(
    g: Dict[str, Any],
    capitalization: Dict[str, Dict[str, int]],
    player_teams: Dict[str, Dict[str, int]],
):
    m: Optional[tagpro_eu.Match] = match_from_links(g)
    if "stats" not in g:
        print(g)
        1 / 0
    if m is None:
        for p in g["stats"]:
            # Find the most used capitalization for players who change it during the season
            if p.lower() not in capitalization:
                capitalization[p.lower()] = {}
            if p not in capitalization[p.lower()]:
                capitalization[p.lower()][p] = 0
            capitalization[p.lower()][p] += 1

            if p.lower() not in player_teams:
                player_teams[p.lower()] = {}
            if g["team1"] not in player_teams[p.lower()]:
                player_teams[p.lower()][g["team1"]] = 0
            if g["team2"] not in player_teams[p.lower()]:
                player_teams[p.lower()][g["team2"]] = 0
            player_teams[p.lower()][g["team1"]] += 1
            player_teams[p.lower()][g["team2"]] += 1
    else:
        for p in m.players:
            # Find the most used capitalization for players who change it during the season
            if p.name.lower() not in capitalization:
                capitalization[p.name.lower()] = {}
            if p.name not in capitalization[p.name.lower()]:
                capitalization[p.name.lower()][p.name] = 0
            capitalization[p.name.lower()][p.name] += 1

            if p.name.lower() not in player_teams:
                player_teams[p.name.lower()] = {}
            if g["team1"] not in player_teams[p.name.lower()]:
                player_teams[p.name.lower()][g["team1"]] = 0
            if g["team2"] not in player_teams[p.name.lower()]:
                player_teams[p.name.lower()][g["team2"]] = 0
            player_teams[p.name.lower()][g["team1"]] += 1
            player_teams[p.name.lower()][g["team2"]] += 1


for season_name in seasons:
    teams: Dict[str, Any] = {}
    players: Dict[str, Any] = {}
    matches = []

    match_mapping: Dict[str, Any] = {}
    for g in seasons[season_name]:
        match_key = f"{g['team1']} {g['team2']} {g['week']}"
        if match_key not in match_mapping:
            match_mapping[match_key] = []
        match_mapping[match_key].append(g)

    player_capitalization: Dict[str, Dict[str, int]] = {}
    player_teams = {}

    for games in match_mapping.values():
        # Attach stats and scores to each game
        for m2 in schedules[season_name]:
            if (
                m2["week_num"] == games[0]["week"]
                and m2["team_1"] == games[0]["team1"]
                and m2["team_2"] == games[0]["team2"]
            ):
                for g in games:
                    game_key = f"g{g['game'][-1]}"
                    half_key = "ot" if g["half"] == "Overtime" else f"h{g['half'][-1]}"
                    g["stats"] = m2[f"{game_key}{half_key}_stats"]
                    for p in g["stats"]:
                        g["stats"][p] = rename_stats(g["stats"][p])
                    g["team1_score"] = m2[f"t1{game_key}{half_key}"]
                    g["team2_score"] = m2[f"t2{game_key}{half_key}"]
                    g["date"] = m2["date"]

        # From S27-31, they played 5-game regular season matches but entered it like two games of
        # two halves with G1H2 or G2H2 having two EUs.
        if (
            games[0]["season"] >= 27
            and games[0]["season"] <= 31
            and len(games) == 4
            and len(games[1]["links"]) == 2
        ):
            games: List[Dict] = games
            games.insert(2, games[1].copy())
            games[2]["links"] = [games[1]["links"][1]]
            games[1]["links"] = [games[1]["links"][0]]
            for i in range(5):
                games[i]["game"] = f"Game {i + 1}"
                games[i]["half"] = f"Half 1"
        elif (
            games[0]["season"] in [27, 29]
            and len(games) == 4
            and len(games[2]["links"]) == 2
        ):
            games: List[Dict] = games
            games.insert(3, games[2].copy())
            games[3]["links"] = [games[2]["links"][1]]
            games[2]["links"] = [games[2]["links"][0]]
            for i in range(5):
                games[i]["game"] = f"Game {i + 1}"
                games[i]["half"] = f"Half 1"
        elif (
            games[0]["season"] in [27, 29]
            and len(games) == 4
            and len(games[3]["links"]) == 2
        ):
            games: List[Dict] = games
            games.insert(4, games[3].copy())
            games[4]["links"] = [games[3]["links"][1]]
            games[3]["links"] = [games[3]["links"][0]]
            for i in range(5):
                games[i]["game"] = f"Game {i + 1}"
                games[i]["half"] = f"Half 1"

        # Split overtimes with multiple EUs into multiple games
        i = 0
        while i < len(games):
            if (
                games[i]["half"] == "Overtime"
                and len(games[i]["links"]) > 1
                and all(["tagpro.eu" in link for link in games[i]["links"]])
            ):
                for j, link in enumerate(games[i]["links"][1:]):
                    games.insert(i + j + 1, games[i].copy())
                    games[i + j + 1]["half"] = f"Overtime {j + 2}"
                    games[i + j + 1]["links"] = [link]
                games[i]["links"] = [games[i]["links"][0]]
            i += 1

        for g in games:
            do_player_first_pass(g, player_capitalization, player_teams)

    # Now actually add all the info
    for games in match_mapping.values():
        match_object = None
        for g in games:
            m: Optional[tagpro_eu.Match] = match_from_links(g)

            # Get team info from all_team_seasons
            t1_abbr, t1_maps_to, t1_roster, t1_captain = get_team_info(
                g["team1"], season_name
            )
            t2_abbr, t2_maps_to, t2_roster, t2_captain = get_team_info(
                g["team2"], season_name
            )

            # Add the teams
            if t1_maps_to not in teams:
                teams[t1_maps_to] = {
                    "season": season_name,
                    "franchise": t1_maps_to,
                    "name": t1_maps_to,
                    "abbr": t1_abbr,
                    "captain": t1_captain,
                }
            if t2_maps_to not in teams:
                teams[t2_maps_to] = {
                    "season": season_name,
                    "franchise": t2_maps_to,
                    "name": t2_maps_to,
                    "abbr": t2_abbr,
                    "captain": t2_captain,
                }

            if match_object is None:
                match_object = {
                    "season": season_name,
                    "date": (
                        g["date"]
                        if m is None
                        else (m.date - timedelta(0, 8 * 60 * 60))
                        .date()
                        .strftime("%Y-%m-%d")
                    ),  # Convert from UTC to PST
                    "week": f"Week {g['week']}",
                    "team1": t1_maps_to,
                    "team2": t2_maps_to,
                    "games": [],
                }
            elif m is not None and match_object["date"] in ["0000-00-00", ""]:
                # If the 1st game in the match can't be parsed, the schedule might have the date 0000-00-00
                # so replace it when we get a parseable match
                match_object["date"] = (
                    (m.date - timedelta(0, 8 * 60 * 60)).date().strftime("%Y-%m-%d")
                )

            t1_is_red = get_t1_is_red(m, g, player_teams)

            game_players = []
            for p in (m.players if m else g["stats"]):
                if m:
                    if p.team is None:
                        handler = DetectJoinHandler()
                        p.parse_events(handler)
                        p_is_red = handler.team.name == "red"
                    else:
                        p_is_red = p.team.name == m.team_red.name
                else:
                    # If the player's team isn't known, assume it's whatever team they played for more
                    if g["stats"][p]["team"] == 0:
                        p_is_red = (
                            player_teams[p.lower()][g["team1"]]
                            > player_teams[p.lower()][g["team2"]]
                        )
                    p_is_red = g["stats"][p]["team"] == 1

                player_season_name = get_player_season_name(
                    p.name if m else p, player_capitalization
                )
                player_object = {
                    "team": t1_maps_to if p_is_red == t1_is_red else t2_maps_to,
                    "player_season": player_season_name,
                    "playing_as": p.name if m else p,
                }
                if m is None:
                    player_object["stats"] = g["stats"][p]
                game_players.append(player_object)

                if player_season_name not in players:
                    players[player_season_name] = {
                        "season": season_name,
                        "team": None,
                        "player": player_season_name,
                        "playing_as": player_season_name,
                    }
                # If the season has rosters, set the player's season team if they're on either team's roster
                # If there are no rosters, set the player's season team to whoever they just played on
                if (t1_roster and t1_is_red) or (t2_roster and not t1_is_red):
                    if player_season_name.lower() in [n.lower() for n in t1_roster]:
                        players[player_season_name]["team"] = t1_maps_to
                    elif player_season_name.lower() in [n.lower() for n in t2_roster]:
                        players[player_season_name]["team"] = t2_maps_to
                else:
                    players[player_season_name]["team"] = (
                        t1_maps_to if p_is_red == t1_is_red else t2_maps_to
                    )

            game_players = sorted(
                game_players, key=lambda p: (p["team"], p["player_season"])
            )
            has_halves = any([g2["half"] == "Half 2" for g2 in games])
            if m:
                team1_score = m.team_red.score if t1_is_red else m.team_blue.score
                team2_score = m.team_red.score if not t1_is_red else m.team_blue.score
            else:
                team1_score = g["team1_score"]
                team2_score = g["team2_score"]
            game_object = {
                "tagpro_eu": str(m.match_id) if m else None,
                "game_in_match": (
                    f"{g['game']} {g['half']}" if has_halves else g["game"]
                ),
                "map_name": m.map.get("name", None) if m else None,
                "map_id": m.map_id if m else None,
                "red_team": t1_maps_to if t1_is_red else t2_maps_to,
                "blue_team": t1_maps_to if not t1_is_red else t2_maps_to,
                "team1_score": team1_score,
                "team2_score": team2_score,
                "players": game_players,
            }
            # Note if there was a second EU link
            if len(g["links"]) == 2 and all("tagpro.eu" in link for link in g["links"]):
                game_object["second_eu"] = g["links"][1].split("=")[1]
                game_object["switch_time"] = 60 * (
                    10 - bulkmatches[game_object["second_eu"]].timeLimit
                )
                # If the second EU has a time limit of 10 or 20 minutes, it's probably an overtime period
                if bulkmatches[game_object["second_eu"]].timeLimit >= 10:
                    game_object["switch_time"] = 600
            match_object["games"].append(game_object)

        if match_object is not None:
            # Don't add matches with no players or caps recorded
            if (
                sum(
                    [
                        len(g["players"]) + g["team1_score"] + g["team2_score"]
                        for g in match_object["games"]
                    ]
                )
                > 0
            ):
                matches.append(match_object)

    final_object = {
        "teamSeasons": sorted([t for t in teams.values()], key=lambda t: t["name"]),
        "playerSeasons": sorted(
            [p for p in players.values()], key=lambda p: (p["team"] or "", p["player"])
        ),
        "matches": matches,
    }

    # Group matches by date and handle special week renaming
    final_object["matches"] = group_matches_by_date(
        final_object["matches"], season_name
    )
    if season_name.startswith("mLTP"):
        season_name = "Minors " + season_name.split(" ")[1]
    season_name = season_name.lower().replace(" ", "_")
    with open(
        f"bulk_import_jsons/tpl_generated/{season_name}.json", "w", encoding="utf-8"
    ) as f:
        f.write(format_compact_json(final_object))
