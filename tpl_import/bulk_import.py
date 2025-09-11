import os
import sys
import django # type: ignore
import json
import requests
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
import re
import tagpro_eu

# Set up Django environment
sys.path.append(str(Path(__file__).parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tagproref.settings')
django.setup()

from reference.models import Season, TeamSeason
from reference.views.data_entry import infer_team, infer_season, infer_player, format_compact_json

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
    abbr = all_team_seasons[g['team1']]['abbr']
    maps_to = all_team_seasons[g['team1']]['maps_to']
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
            p_is_red = 2 if handler.team.name == red_name else -2
        else:
            p_is_red = 2 if p.team.name == red_name else -2
        if p.name.lower() in [o.lower() for o in t1_roster]:
            t1_is_red += p_is_red
        elif p.name.lower() in [o.lower() for o in t2_roster]:
            t1_is_red -= p_is_red
        t1_is_red += 1/16 * p_is_red * (player_teams[p.name.lower()][g['team1']] - player_teams[p.name.lower()][g['team2']])
    
    return t1_is_red > 0


for season_name in seasons:
    s = seasons[season_name]
    teams = []
    players = []
    matches = []

    match_mapping: Dict[str, Any] = {}
    for g in s:
        match_key = f"{g['team1']} {g['team2']} {g['week']}"
        if match_key not in match_mapping:
            match_mapping[match_key] = []
        match_mapping[match_key].append(g)

    # Approximate season rosters (helps if rosters are missing)
    player_capitalization: Dict[str, Dict[str, int]] = {}
    player_teams = {}
    for games in match_mapping.values():
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
    
    for games in match_mapping.values():
        for g in games:
            m: Optional[tagpro_eu.Match] = match_from_links(g)
            if m is None:
                continue

            # Get team info from all_team_seasons
            t1_abbr, t1_maps_to, t1_roster, t1_captain = get_team_info(g['team1'], season_name)
            t2_abbr, t2_maps_to, t2_roster, t2_captain = get_team_info(g['team2'], season_name)

            t1_is_red = get_t1_is_red(g, player_teams)
            red_name: str = m.team_red.name
            blue_name: str = m.team_blue.name

            for p in m.players:
                if p.team is None:
                    handler = DetectJoinHandler()
                    p.parse_events(handler)
                    p_is_red = handler.team.name == red_name
                else:
                    p_is_red = p.team.name == red_name
            

