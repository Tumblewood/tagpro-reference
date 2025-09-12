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
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tagproref.settings')
django.setup()

from reference.views.data_entry import format_compact_json

with open("tpl_import/league_maps.json") as f:
    bulkmaps = json.load(f)
    bulkmaps: Dict[int, tagpro_eu.Map] = {
        int(k): bulkmaps[k]
        for k in bulkmaps
    }

bulkmatches: Dict[str, tagpro_eu.Match] = {}
for i in range(1, 10):
    with open(f"tpl_import/league_matches{i}.json") as f:
        for m in tagpro_eu.bulk.load_matches(f, bulkmaps):
            bulkmatches[str(m.match_id)] = m

with open("bulk_import_jsons/tpl_api_links.json", encoding="utf-8") as f:
    j = json.load(f)
    tpl_api_games = j['games']

with open("bulk_import_jsons/all_team_seasons.json", encoding="utf-8") as f:
    all_team_seasons = json.load(f)

seasons: Dict[str, List[Dict[str, Any]]] = {}
for g in tpl_api_games:
    season_name = f"{g['league']} S{g['season']}"
    if season_name not in seasons:
        seasons[season_name] = []
    seasons[season_name].append(g)

def match_from_links(g: Dict[str, Any]) -> Optional[tagpro_eu.Match]:
    if len(g['links']) != 1:
        return None
    if "tagpro.eu" not in g['links'][0]:
        return None
    eu_id = g['links'][0].split("=")[1]
    if eu_id not in bulkmatches:
        return None
    return bulkmatches[eu_id]

def get_team_info(team_name: str, season_name: str) -> Tuple[str, str, Optional[List[str]], Optional[str]]:
    season_name = season_name.lower().replace(" b", "").replace(" ", "_")
    history = all_team_seasons[team_name].get("history", {}).get(season_name, None)
    captain = history['captain'] if history else None
    roster = history['roster'] if history else []
    abbr = all_team_seasons[team_name]['abbr']
    maps_to = all_team_seasons[team_name]['maps_to']
    return abbr, maps_to, roster, captain


class DetectJoinHandler(tagpro_eu.PlayerEventHandler):
    def __init__(self):
        self.team = None
    
    def join(self, time, new_team):
        self.team = new_team


def get_t1_is_red(g: Dict[str, Any], player_teams: Dict[str, Dict[str, int]]) -> bool:
    # Get team info from all_team_seasons
    t1_abbr, _, t1_roster, _ = get_team_info(g['team1'], season_name)
    t2_abbr, _, t2_roster, _ = get_team_info(g['team2'], season_name)

    # Determine which team was red
    red_name: str = m.team_red.name
    blue_name: str = m.team_blue.name
    t1_is_red = 0
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
        t1_is_red += 1/16 * p_is_red * (player_teams[p.name.lower()][g['team1']] - player_teams[p.name.lower()][g['team2']])
    
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

    # Approximate season rosters (helps if rosters are missing)
    player_capitalization: Dict[str, Dict[str, int]] = {}
    player_teams = {}
    for games in match_mapping.values():
        # From S27-31, they played 5-game regular season matches but entered it like two games of
        # two halves with G1H2 having two EUs.
        if games[0]['season'] >= 27\
                and games[0]['season'] <= 31\
                and len(games) == 4\
                and len(games[1]['links']) == 2:
            games: List[Dict] = games
            games.insert(2, games[1].copy())
            games[2]['links'] = [games[1]['links'][1]]
            games[1]['links'] = [games[1]['links'][0]]
            for i in range(5):
                games[i]['game'] = f"Game {i + 1}"
                games[i]['half'] = f"Half 1"
        
        # Split overtimes with multiple EUs into multiple games
        i = 0
        while i < len(games):
            if games[i]['half'] == "Overtime"\
                    and len(games[i]['links']) > 1\
                    and all(["tagpro.eu" in link for link in games[i]['links']]):
                for j, link in enumerate(games[i]['links'][1:]):
                    games.insert(i + j + 1, games[i].copy())
                    games[i + j + 1]['half'] = f"Overtime {j + 2}"
                    games[i + j + 1]['links'] = [link]
                games[i]['links'] = [games[i]['links'][0]]
            i += 1

        for g in games:
            m: Optional[tagpro_eu.Match] = match_from_links(g)
            if m is None:
                continue

            for p in m.players:
                # Find the most used capitalization for players who change it during the season
                if p.name.lower() not in player_capitalization:
                    player_capitalization[p.name.lower()] = {}
                    if p.name not in player_capitalization[p.name.lower()]:
                        player_capitalization[p.name.lower()][p.name] = 0
                    player_capitalization[p.name.lower()][p.name] += 1

                if p.name.lower() not in player_teams:
                    player_teams[p.name.lower()] = {}
                if g['team1'] not in player_teams[p.name.lower()]:
                    player_teams[p.name.lower()][g['team1']] = 0
                if g['team2'] not in player_teams[p.name.lower()]:
                    player_teams[p.name.lower()][g['team2']] = 0
                player_teams[p.name.lower()][g['team1']] += 1
                player_teams[p.name.lower()][g['team2']] += 1
    
    # Now actually add all the info
    for games in match_mapping.values():
        match_object = None
        for g in games:
            m: Optional[tagpro_eu.Match] = match_from_links(g)
            if m is None:
                continue

            # Get team info from all_team_seasons
            t1_abbr, t1_maps_to, t1_roster, t1_captain = get_team_info(g['team1'], season_name)
            t2_abbr, t2_maps_to, t2_roster, t2_captain = get_team_info(g['team2'], season_name)

            # Add the teams
            if t1_maps_to not in teams:
                teams[t1_maps_to] = {
                    'season': season_name,
                    'franchise': t1_maps_to,
                    'name': t1_maps_to,
                    'abbr': t1_abbr,
                    'captain': t1_captain
                }
            if t2_maps_to not in teams:
                teams[t2_maps_to] = {
                    'season': season_name,
                    'franchise': t2_maps_to,
                    'name': t2_maps_to,
                    'abbr': t2_abbr,
                    'captain': t2_captain
                }

            if match_object is None:
                match_object = {
                    'season': season_name,
                    'date': (m.date - timedelta(0, 8 * 60 * 60)).date().strftime("%Y-%m-%d"),  # Convert from UTC to PST
                    'week': f"Week {g['week']}",
                    'team1': t1_maps_to,
                    'team2': t2_maps_to,
                    'games': []
                }

            t1_is_red = get_t1_is_red(g, player_teams)
            red_name: str = m.team_red.name
            blue_name: str = m.team_blue.name

            game_players = []
            for p in m.players:
                if p.team is None:
                    handler = DetectJoinHandler()
                    p.parse_events(handler)
                    p_is_red = handler.team.name == "red"
                else:
                    p_is_red = p.team.name == red_name

                player_season_name = get_player_season_name(p.name, player_capitalization)
                game_players.append({
                    'team': t1_maps_to if p_is_red == t1_is_red else t2_maps_to,
                    'player_season': player_season_name,
                    'playing_as': p.name
                })

                if player_season_name not in players:
                    players[player_season_name] = {
                        'season': season_name,
                        'team': None,
                        'player': player_season_name,
                        'playing_as': player_season_name
                    }
                # If the season has rosters, set the player's season team if they're on either team's roster
                # If there are no rosters, set the player's season team to whoever they just played on
                if (t1_roster and t1_is_red) or (t2_roster and not t1_is_red):
                    if player_season_name.lower() in [n.lower() for n in t1_roster]:
                        players[player_season_name]['team'] = t1_maps_to
                    elif player_season_name.lower() in [n.lower() for n in t2_roster]:
                        players[player_season_name]['team'] = t2_maps_to
                else:
                    players[player_season_name]['team'] = t1_maps_to if t1_is_red else t2_maps_to

            game_players = sorted(game_players, key=lambda p: (p['team'], p['player_season']))
            has_halves = any([g2['half'] != "Half 1" for g2 in games])
            match_object['games'].append({
                'tagpro_eu': str(m.match_id),
                'game_in_match': f"{g['game']} {g['half']}" if has_halves else g['game'],
                'map_name': m.map.get("name", None),
                'map_id': m.map_id,
                'red_team': t1_maps_to if t1_is_red else t2_maps_to,
                'blue_team': t1_maps_to if not t1_is_red else t2_maps_to,
                'team1_score': m.team_red.score if t1_is_red else m.team_blue.score,
                'team2_score': m.team_red.score if not t1_is_red else m.team_blue.score,
                'players': game_players
            })
        
        if match_object is not None:
            matches.append(match_object)

    final_object = {
        'teamSeasons': sorted([t for t in teams.values()], key=lambda t: t['name']),
        'playerSeasons': sorted([p for p in players.values()], key=lambda p: (p['team'] or "", p['player'])),
        'matches': matches
    }
    if season_name.startswith("mLTP"):
        season_name = "Minors " + season_name.split(" ")[1]
    season_name = season_name.lower().replace(" ", "_")
    with open(f"bulk_import_jsons/tpl_generated/{season_name}.json", "w", encoding="utf-8") as f:
        f.write(format_compact_json(final_object))
