from django.db import models, transaction
import json
import re
from datetime import datetime, date
import tagpro_eu
from typing import Optional, List, Dict, Any

from .stat_collection import process_game_stats, update_standings, load_eu_match_object
from .display_info import STAT_FIELDS
from ..models import Franchise, Season, TeamSeason, Player, PlayerSeason, Match, Game, PlayerGameLog, PlayoffSeries, PlayerStats, PlayerRegulationStats


def extract_game_data(eu_url: str) -> Dict:
    """Extract basic game data from the tagpro.eu URL."""
    # Extract game ID from URL
    game_id = re.search(r'(\d{6,7})', eu_url)
    game_id = game_id.group(1) if game_id else "-1"
    m: tagpro_eu.Match = load_eu_match_object(game_id)
    
    # Get the set of players who joined each team
    r_players = set()
    b_players = set()
    for e in m.create_timeline():
        if e[1][:4] == "Join":
            if m.team_red.name in e[1][10:]:
                r_players.add(e[2].name)
            elif m.team_blue.name in e[1][10:]:
                b_players.add(e[2].name)

    # Return all relevant game data
    return {
        'eu_url': eu_url,
        'game_id': game_id,
        'date': m.date.date(),
        'map_name': m.map.name,
        'map_id': m.map_id,
        'team_red': {
            'name': m.team_red.name,
            'score': m.team_red.score,
            'players': r_players
        },
        'team_blue': {
            'name': m.team_blue.name,
            'score': m.team_blue.score,
            'players': b_players
        },
        'players': [
            {'username': p, 'team': m.team_red.name, 'stats': {}}
            for p in r_players
        ] + [
            {'username': p, 'team': m.team_blue.name, 'stats': {}}
            for p in b_players
        ]
    }


def infer_season(season_group: List[Season], team_name_in_group: str) -> Optional[Season]:
    if not team_name_in_group or team_name_in_group in ['Red', 'Blue'] or len(team_name_in_group) < 4:
        return None
    
    league_indicator = team_name_in_group[:1]
    try:
        if league_indicator == "M":
            return [s for s in season_group if s.name.startswith("MLTP")][0]
        elif league_indicator == "N":
            return [s for s in season_group if s.name.startswith("mLTP")][0]
        elif league_indicator == "A":
            return [s for s in season_group if s.name.startswith("NLTP")][0]
        else:
            return None
    except IndexError:
        return None


def infer_team(season_group: List[Season], team_name_in_group: str) -> Optional[TeamSeason]:
    """Try to automatically match team name from group to TeamSeason within the season group."""
    # If the team name doesn't exist, is default, or is too short, return None
    if not team_name_in_group or team_name_in_group in ['Red', 'Blue'] or len(team_name_in_group) < 3:
        return None
    
    team_abbr = team_name_in_group.strip()[-3:]  # strip because sometimes captains add a trailing space by mistake
    season_guess = infer_season(season_group, team_name_in_group)

    # Get all teams with matching abbreviation
    matching_abbr = TeamSeason.objects.filter(abbr=team_abbr)

    # First check if any match from the season we think we should be looking for
    exact_match = matching_abbr.filter(season=season_guess).first()

    # If no match within the season, check other seasons in the season group for an abbr match
    if not exact_match:
        exact_match = matching_abbr.filter(season__in=season_group).first()
    
    return exact_match


def get_existing_match(red: Optional[TeamSeason], blue: Optional[TeamSeason], date: datetime.date) -> Optional[Match]:
    """Search for a match featuring both given teams (in either order) on the given date."""
    return Match.objects.filter(
        date=date
    ).filter(
        models.Q(team1=red, team2=blue) | models.Q(team1=blue, team2=red)
    ).first()


def infer_week(red: Optional[TeamSeason], blue: Optional[TeamSeason], date: datetime.date) -> str:
    # Get the season based on the teams. If neither team found, return "Week 1"
    if red is not None:
        season = red.season
    elif blue is not None:
        season = blue.season
    else:
        return "Week 1"
    
    # Get the maximum week of all Matches played this Season before this match's date
    # Return "Week 1" if no weeks played before this date in this season
    matches_before = Match.objects.filter(
        season=season,
        date__lte=date
    )
    if len(matches_before) == 0:
        return "Week 1"
    max_week = matches_before.aggregate(models.Max('week'))['week__max']
    
    # If the greatest week wasn't a typical week (wasn't called "Week X" for some number X), return
    # the week as-is
    if not re.match(r"Week \d+", max_week):
        return max_week

    # Otherwise, see if either of these teams already have a match in that week. If so, increment
    # the week number. Otherwise, return max week as-is
    matches_before_by_either_team = matches_before.filter(
        week=max_week
    ).filter(
        models.Q(team1=red) | models.Q(team1=blue) | models.Q(team2=red) | models.Q(team2=blue)
    ).first()
    if matches_before_by_either_team:
        week_num = int(max_week[5:])
        return f"Week {week_num + 1}"
    return max_week


def infer_player_season(username: str, team: Optional[Season]) -> Optional[PlayerSeason]:
    """Try to identify the PlayerSeason corresponding to the given username and team."""
    # If we don't know the team, just return None. We don't want to return a PlayerSeason from the
    # wrong league, and team tells us the league, so we should not guess if we don't know the team.
    if not team:
        return None
    
    # Search for PlayerSeason with matching Season and name
    matching_name = PlayerSeason.objects.filter(
        season=team.season,
        playing_as__iexact=username
    ).first()
    if matching_name:
        return matching_name
    
    # If not found, search for PlayerSeason with matching Season and Player name
    matching_name = PlayerSeason.objects.filter(
        season=team.season,
        player__name__iexact=username
    ).first()
    if matching_name:
        return matching_name
    
    # If all of the above fails, return None
    return None


def infer_player(player_season: Optional[PlayerSeason], username: str) -> Optional[Player]:
    """Try to identify the Player corresponding to the given PlayerSeason and username."""
    # If there is a PlayerSeason, just return its player's name
    if player_season:
        return player_season.player
    
    # Otherwise, search for a Player with matching name
    matching_name = Player.objects.filter(
        name__iexact=username
    ).first()
    if matching_name:
        return matching_name
    
    # If not found, search for a PlayerSeason with matching name and return its player
    matching_name = PlayerSeason.objects.filter(
        playing_as__iexact=username
    ).first()
    if matching_name:
        return matching_name.player
    
    # If not found, search for a PlayerGameLog with matching name and return its player
    matching_name = PlayerGameLog.objects.filter(
        playing_as__iexact=username
    ).first()
    if matching_name:
        return matching_name.player_season.player
    
    # If all of the above fails, return None
    return None


def get_game_number(m: Optional[Match]) -> str:
    """Get the correct game number (as a string like "Game X") of a new game in the given match."""
    if m is None:
        return "Game 1"
    num_other_games = len(
        Game.objects.filter(match=m)
    )
    return f"Game {num_other_games + 1}"


def prepopulate_form(season_filter_string: str, eu_url: str):
    """Return all data needed by the import form."""
    # Can't use QuerySet.filter because sqlite doesn't have case-sensitive LIKE.
    season_group = [s for s in Season.objects.all() if season_filter_string in s.name]
    if len(season_group) == 0:
        raise Exception("No seasons found matching provided season filter string")

    m = extract_game_data(eu_url)
    red_team = infer_team(season_group, m['team_red']['name'])
    blue_team = infer_team(season_group, m['team_blue']['name'])
    existing_match = get_existing_match(red_team, blue_team, m['date'])
    players = []
    for p in m['players']:
        team = red_team if p['team'] == m['team_red']['name'] else blue_team
        player_season = infer_player_season(p['username'], team)
        player = infer_player(player_season, p['username'])
        players.append({
            'player_season': player_season,
            'player': player,
            'player_username': player.name if player else p['username'],
            'season_username': player_season.playing_as if player_season else p['username'],
            'season_team': player_season.team if player_season else team,
            'game_username': p['username'],
            'game_team': p['team']
        })
    
    return {
        'red_team': red_team,
        'blue_team': blue_team,
        'match': existing_match,
        'week': existing_match.week if existing_match else infer_week(red_team, blue_team, m['date']),
        'game_in_match': get_game_number(get_existing_match(red_team, blue_team, m['date'])),
        'eu_url': eu_url,
        'red_team_raw_name': m['team_red']['name'],
        'blue_team_raw_name': m['team_blue']['name'],
        'red_team_score': m['team_red']['score'],
        'blue_team_score': m['team_blue']['score'],
        'map_name': m['map_name'],
        'map_id': m['map_id'],
        'date': m['date'],
        'players': players
    }


@transaction.atomic
def enter_confirmed_data(
        red_team: TeamSeason,
        blue_team: TeamSeason,
        red_team_raw_name: str,
        blue_team_raw_name: str,
        match: Match,
        week: str,
        game_in_match: str,
        eu_url: str,
        score_red: int,
        score_blue: int,
        map_name: str,
        map_id: int,
        date: datetime.date,
        players: List[Dict]
    ) -> None:
    """Enter a game's worth of data from the data import form into the database."""
    # Error handling for if teams are not selected or from different seasons
    if red_team is None:
        raise Exception("Red team not selected")
    if blue_team is None:
        raise Exception("Blue team not selected")
    if red_team.season != blue_team.season:
        raise Exception("Red and blue teams are from different seasons")
    
    # Create Match if no Match can be found even after user corrects the teams
    match = get_existing_match(red_team, blue_team, date)
    if match is None:
        match = Match.objects.create(
            season=red_team.season,
            team1=red_team,
            team2=blue_team,
            week=week,
            date=date
        )

    team1_is_red = red_team == match.team1
    
    # Create Game
    game = Game.objects.create(
        match=match,
        red_team=red_team,
        blue_team=blue_team,
        team1_score=score_red if team1_is_red else score_blue,
        team2_score=score_blue if team1_is_red else score_red,
        map_name=map_name,
        map_id=map_id,
        game_in_match=game_in_match,
        tagpro_eu=int(eu_url.split("=")[1])
    )

    # Create PlayerGameLogs for all players in the game
    for p in players:
        played_on = red_team if p['game_team'] == red_team_raw_name else blue_team

        # If the player has a PlayerSeason in that season, set it to that
        exact_player_season_match = PlayerSeason.objects.filter(
            season=red_team.season,
            player=p['player']
        ).first()
        if exact_player_season_match is not None:
            p['player_season'] = exact_player_season_match

        # If Player and PlayerSeason are both None, create a new Player
        if p['player'] is None and p['player_season'] is None:
            p['player'] = Player.objects.create(name=p['player_username'])
        
        # If PlayerSeason is None, create a new PlayerSeason
        if p['player_season'] is None:
            p['player_season'] = PlayerSeason.objects.create(
                season=red_team.season,
                player=p['player'],
                team=p['season_team'],
                playing_as=p['season_username']
            )
        
        # Add the PlayerGameLog
        PlayerGameLog.objects.create(
            game=game,
            player_season=p['player_season'],
            playing_as=p['game_username'],
            team=played_on
        )
    
    # Collect and store stats from the game
    process_game_stats(game)


def process_multiple_eu_links(season_filter_string: str, eu_urls: List[str]) -> Dict:
    """Process multiple EU links and return JSON according to the schema."""
    # Get season group
    season_group = [s for s in Season.objects.all() if season_filter_string in s.name]
    if not season_group:
        raise Exception(f"No seasons found matching '{season_filter_string}'")

    # Track unique entities to avoid duplicates
    team_seasons: Dict[str, List[Any]] = {}
    player_seasons: Dict[str, List[Any]] = {}
    matches: Dict[str, List[Any]] = {}
    
    extracted_game_data = [extract_game_data(url) for url in eu_urls]
    for game_data in extracted_game_data:
        red_team: Optional[TeamSeason] = infer_team(season_group, game_data['team_red']['name'])
        blue_team: Optional[TeamSeason] = infer_team(season_group, game_data['team_blue']['name'])
        season: Optional[Season] = None
        game_players: List[Dict] = []
        team1_score = game_data['team_red']['score']
        team2_score = game_data['team_blue']['score']
        
        # Add team seasons (include both known and unknown teams)
        for team, raw_name in [(red_team, game_data['team_red']['name']), (blue_team, game_data['team_blue']['name'])]:                
            team_name = team.name if team else raw_name
            if team:
                # Known team
                season = team.season
                team_key = f"{season.name} {team_name}"
                team_seasons[team_key] = {
                    'season': season.name,
                    'franchise': team.franchise.name if team.franchise else team_name,
                    'name': team.name,
                    'abbr': team.abbr
                }
            else:
                # Unknown team - use raw name and infer season and franchise
                season = infer_season(season_group, raw_name) or season_group[0]
                team_abbr = raw_name[-3:]
                team_key = f"{season.name} {team_abbr}"
                team_seasons[team_key] = {
                    'season': season.name,
                    'franchise': raw_name,  # Use raw name as franchise fallback
                    'name': raw_name,  # Use raw name as team name
                    'abbr': team_abbr
                }
        
        # Identify and track players from the game
        for player_data in game_data['players']:
            player_season: Optional[PlayerSeason] = None
            player: Optional[Player] = infer_player(None, player_data['username'])
            if player:
                player_season = PlayerSeason.objects.filter(season=season, player=player).first()
            season_playing_as = player_season.playing_as if player_season else player_data['username']
            player_key = f"{season.name} {season_playing_as}"
            team = red_team if player_data['team'] == game_data['team_red']['name'] else blue_team
            game_players.append({
                'team': team.name if team else player_data['team'],
                'player_season': season_playing_as,
                'playing_as': player_data['username']
            })
            if player_season:
                if player_season.team:
                    season_team_name = player_season.team.name
                else:
                    season_team_name = None
            else:
                if team:
                    season_team_name = team.name
                else:
                    season_team_name = player_data['team']
            player_seasons[player_key] = {
                'season': season.name,
                'team': season_team_name,
                'player': player.name if player else season_playing_as,
                'playing_as': season_playing_as
            }
        
        # Search for the existing match if there is one (either red or blue team could be team1), or create a new match if none found
        match_key = f"{season.name} {game_data['date']} - {red_team.name if red_team else game_data['team_red']['name']} vs. {blue_team.name if blue_team else game_data['team_blue']['name']}"
        reverse_match_key = f"{season.name} {game_data['date']} - {blue_team.name if blue_team else game_data['team_blue']['name']} vs. {red_team.name if red_team else game_data['team_red']['name']}"
        if match_key not in matches:
            if reverse_match_key in matches:
                match_key = reverse_match_key
                team1_score = game_data['team_blue']['score']
                team2_score = game_data['team_red']['score']
            else:
                matches[match_key] = {
                    'season': season.name,
                    'date': str(game_data['date']),
                    'week': infer_week(red_team, blue_team, game_data['date']),
                    'team1': red_team.name if red_team else game_data['team_red']['name'],
                    'team2': blue_team.name if blue_team else game_data['team_blue']['name'],
                    'games': []
                }

        matches[match_key]['games'].append({
            "tagpro_eu": int(game_data['game_id']),
            "map_name": game_data['map_name'],
            "map_id": int(game_data['map_id']) if game_data['map_id'] else None,
            "red_team": red_team.name if red_team else game_data['team_red']['name'],
            "blue_team": blue_team.name if blue_team else game_data['team_blue']['name'],
            "team1_score": team1_score,
            "team2_score": team2_score,
            "players": game_players
        })

    sorted_ts = sorted([team_seasons[ts] for ts in team_seasons], key=lambda ts: (ts['season'], ts['name']))
    sorted_ps = sorted([player_seasons[ps] for ps in player_seasons], key=lambda ps: (ps['season'], ps['team'] or "", ps['playing_as']))
    sorted_matches = [matches[m] for m in sorted(matches.keys())]
    
    return {
        'teamSeasons': sorted_ts,
        'playerSeasons': sorted_ps,
        'matches': sorted_matches
    }


def import_json_data_to_db(json_data: Dict) -> Dict:
    """Import JSON data into database idempotently."""
    created_count = 0
    skipped_count = 0
    
    # First pass: Create/get all seasons, franchises, players, team seasons, player seasons
    seasons_cache = {}
    franchises_cache = {}
    players_cache = {}
    team_seasons_cache = {}
    player_seasons_cache = {}
    
    # Cache existing seasons
    for season in Season.objects.all():
        seasons_cache[season.name] = season
    
    # Process team seasons
    for ts_data in json_data.get('teamSeasons', []):
        season = seasons_cache.get(ts_data['season'])
        if not season:
            continue
            
        # Get or create franchise
        franchise_name = ts_data['franchise']
        if franchise_name not in franchises_cache:
            franchise, _ = Franchise.objects.get_or_create(name=franchise_name)
            franchises_cache[franchise_name] = franchise
        
        # Handle captain and co_captain
        captain = None
        co_captain = None
        if ts_data.get('captain'):
            captain, _ = Player.objects.get_or_create(name=ts_data['captain'])
            players_cache[ts_data['captain']] = captain
        if ts_data.get('co_captain'):
            co_captain, _ = Player.objects.get_or_create(name=ts_data['co_captain'])
            players_cache[ts_data['co_captain']] = co_captain
        
        # Get or create team season
        defaults = {
            'franchise': franchises_cache[franchise_name],
            'abbr': ts_data['abbr']
        }
        if captain:
            defaults['captain'] = captain
        if co_captain:
            defaults['co_captain'] = co_captain
            
        team_season, _ = TeamSeason.objects.get_or_create(
            season=season,
            name=ts_data['name'],
            defaults=defaults
        )
        team_seasons_cache[f"{season.name}_{ts_data['name']}"] = team_season
    
    # Process player seasons
    for ps_data in json_data.get('playerSeasons', []):
        season = seasons_cache.get(ps_data['season'])
        if not season:
            continue
            
        # Get or create player
        player_name = ps_data['player']
        if player_name not in players_cache:
            player, _ = Player.objects.get_or_create(name=player_name)
            players_cache[player_name] = player
        
        # Get team season (allow null team)
        team_season = None
        if ps_data['team']:
            team_season = team_seasons_cache.get(f"{season.name}_{ps_data['team']}")
            
        # Get or create player season (team can be None)
        player_season, _ = PlayerSeason.objects.get_or_create(
            season=season,
            player=players_cache[player_name],
            playing_as=ps_data['playing_as'],
            defaults={'team': team_season}
        )
        player_seasons_cache[f"{season.name}_{ps_data['playing_as']}"] = player_season
    
    # Process matches and games
    for match_data in json_data.get('matches', []):
        season = seasons_cache.get(match_data['season'])
        if not season:
            continue
            
        team1 = team_seasons_cache.get(f"{season.name}_{match_data['team1']}")
        team2 = team_seasons_cache.get(f"{season.name}_{match_data['team2']}")
        if not team1 or not team2:
            continue
            
        # Get or create match
        match, _ = Match.objects.get_or_create(
            season=season,
            team1=team1,
            team2=team2,
            date=match_data['date'],
            defaults={'week': match_data['week']}
        )

        game_in_match = 0
        
        # Process games in this match
        for game_data in match_data['games']:
            game_in_match += 1
            red_team = team_seasons_cache.get(f"{season.name}_{game_data['red_team']}")
            blue_team = team_seasons_cache.get(f"{season.name}_{game_data['blue_team']}")
            if not red_team or not blue_team:
                continue
                
            # Check if game already exists
            existing_game = Game.objects.filter(tagpro_eu=game_data['tagpro_eu']).first()
            
            if existing_game:
                skipped_count += 1
                continue

            # Create game with additional fields
            game_fields = {
                'match': match,
                'red_team': red_team,
                'blue_team': blue_team,
                'team1_score': game_data.get('team1_score', 0),
                'team2_score': game_data.get('team2_score', 0),
                'map_name': game_data['map_name'],
                'map_id': game_data['map_id'] if game_data['map_id'] else None,
                'game_in_match': f"Game {game_in_match}",
                'tagpro_eu': game_data['tagpro_eu']
            }
            
            # Add optional fields if present
            if game_data.get('second_eu'):
                game_fields['resumed_tagpro_eu'] = game_data['second_eu']
            if game_data.get('switch_time') is not None:
                game_fields['paused_time'] = game_data['switch_time']
                game_fields['resumed_stats_count_until'] = 600 - game_data['switch_time']
            if game_data.get('replay'):
                game_fields['replay'] = game_data['replay']
            if game_data.get('vod'):
                game_fields['vod'] = game_data['vod']
                
            game = Game.objects.create(**game_fields)

            # Create player game logs
            for player_data in game_data['players']:
                player_season = player_seasons_cache.get(f"{season.name}_{player_data['player_season']}")
                if not player_season:
                    continue
                    
                team = team_seasons_cache.get(f"{season.name}_{player_data['team']}")
                if not team:
                    continue
                    
                # Check if player game log already exists
                existing_pgl = PlayerGameLog.objects.filter(
                    game=game,
                    player_season=player_season,
                    playing_as=player_data['playing_as']
                ).first()
                
                if not existing_pgl:
                    pgl = PlayerGameLog.objects.create(
                        game=game,
                        player_season=player_season,
                        playing_as=player_data["playing_as"],
                        team=team
                    )
                    
                    # Create PlayerStats if stats are provided in JSON
                    if "stats" in player_data:
                        stats_data = player_data["stats"]
                        
                        # Create stats dict with 0 defaults for all stat fields
                        player_stats = {field: 0 for field in STAT_FIELDS}
                        
                        # Update with actual values from JSON (only known stat fields)
                        for key, value in stats_data.items():
                            if key in STAT_FIELDS:
                                player_stats[key] = value or 0
                        
                        # Create PlayerStats object
                        PlayerStats.objects.create(
                            player_gamelog=pgl,
                            **player_stats
                        )
                        
                        # Create PlayerRegulationStats (same data for manually entered stats)
                        PlayerRegulationStats.objects.create(
                            player_gamelog=pgl,
                            **player_stats
                        )
            
            # Process game stats
            created_count += 1
    
    return {'created_count': created_count, 'skipped_count': skipped_count}


def format_compact_json(data):
    """Format JSON with scalar fields on one line, arrays/objects multi-line."""
    # Simplified approach - format each top-level section
    result_lines = ["{"]
    
    # teamSeasons - each on one line
    if data.get('teamSeasons'):
        result_lines.append('  "teamSeasons": [')
        for i, ts in enumerate(data['teamSeasons']):
            comma = "," if i < len(data['teamSeasons']) - 1 else ""
            pairs = [f'"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in ts.items()]
            result_lines.append(f'    {{ {", ".join(pairs)} }}{comma}')
        result_lines.append('  ],')
    
    # playerSeasons - each on one line  
    if data.get('playerSeasons'):
        result_lines.append('  "playerSeasons": [')
        for i, ps in enumerate(data['playerSeasons']):
            comma = "," if i < len(data['playerSeasons']) - 1 else ""
            pairs = [f'"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in ps.items()]
            result_lines.append(f'    {{ {", ".join(pairs)} }}{comma}')
        result_lines.append('  ],')
    
    # matches - scalar fields on one line, games array multi-line
    if data.get('matches'):
        result_lines.append('  "matches": [')
        for i, match in enumerate(data['matches']):
            comma = "," if i < len(data['matches']) - 1 else ""
            result_lines.append('    {')
            
            # Match scalar fields on one line
            scalar_fields = {k: v for k, v in match.items() if k != 'games'}
            scalar_pairs = [f'"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in scalar_fields.items()]
            result_lines.append(f'      {", ".join(scalar_pairs)},')
            
            # Games array
            result_lines.append('      "games": [')
            for j, game in enumerate(match['games']):
                game_comma = "," if j < len(match['games']) - 1 else ""
                result_lines.append('        {')
                
                # Game scalar fields on one line
                game_scalar_fields = {k: v for k, v in game.items() if k != 'players'}
                game_scalar_pairs = [f'"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in game_scalar_fields.items()]
                result_lines.append(f'          {", ".join(game_scalar_pairs)},')
                
                # Players array - each player on one line
                result_lines.append('          "players": [')
                for p_idx, player in enumerate(game['players']):
                    player_comma = "," if p_idx < len(game['players']) - 1 else ""
                    player_pairs = [f'"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in player.items()]
                    result_lines.append(f'            {{ {", ".join(player_pairs)} }}{player_comma}')
                result_lines.append('          ]')
                
                result_lines.append(f'        }}{game_comma}')
            result_lines.append('      ]')
            result_lines.append(f'    }}{comma}')
        result_lines.append('  ]')
    
    result_lines.append('}')
    return '\n'.join(result_lines)


@transaction.atomic
def infer_playoff_series(season: Season):
    """
    Create PlayoffSeries for all playoff matches in the season.
    Sets team1 to the better seeded team and updates games accordingly.
    """
    # Get all playoff matches (week not starting with "Week")
    playoff_matches = Match.objects.filter(
        season=season
    ).exclude(week__startswith="Week").order_by('date')
    
    for match in playoff_matches:
        # Determine which team should be team1 (better seed = lower number)
        team1_seed = match.team1.seed or 999  # Use high number if no seed
        team2_seed = match.team2.seed or 999
        
        # If team2 has better seed, swap the teams
        if team2_seed < team1_seed:
            # Swap teams in the match
            original_team1 = match.team1
            original_team2 = match.team2
            match.team1 = original_team2
            match.team2 = original_team1
            match.save()
            
            # Update all games in this match to reflect the team swap
            for game in match.games.all():
                # Swap team1/team2 scores
                original_team1_score = game.team1_score
                original_team2_score = game.team2_score
                original_team1_standing_points = game.team1_standing_points
                original_team2_standing_points = game.team2_standing_points
                
                game.team1_score = original_team2_score
                game.team2_score = original_team1_score
                game.team1_standing_points = original_team2_standing_points
                game.team2_standing_points = original_team1_standing_points
                
                # Update outcome from team1's perspective
                if game.outcome == 'W':
                    game.outcome = 'L'
                elif game.outcome == 'L':
                    game.outcome = 'W'
                elif game.outcome == 'OTW':
                    game.outcome = 'OTL'
                elif game.outcome == 'OTL':
                    game.outcome = 'OTW'
                # 'T' stays the same
                
                game.save()
        
        # Calculate game wins for each team
        team1_wins = 0
        team2_wins = 0
        
        for game in match.games.all():
            if game.outcome in ['W', 'OTW']:
                team1_wins += 1
            elif game.outcome in ['L', 'OTL']:
                team2_wins += 1
        
        # Determine winner (null if tied)
        winner = None
        if team1_wins > team2_wins:
            winner = match.team1
        elif team2_wins > team1_wins:
            winner = match.team2
        
        # Find previous series for each team
        team1_prev_series = PlayoffSeries.objects.filter(
            match__season=season,
            match__date__lt=match.date
        ).filter(
            models.Q(match__team1=match.team1) | models.Q(match__team2=match.team1)
        ).order_by('-match__date').first()
        
        team2_prev_series = PlayoffSeries.objects.filter(
            match__season=season,
            match__date__lt=match.date
        ).filter(
            models.Q(match__team1=match.team2) | models.Q(match__team2=match.team2)
        ).order_by('-match__date').first()
        
        # Create or update the PlayoffSeries
        playoff_series, created = PlayoffSeries.objects.update_or_create(
            match=match,
            defaults={
                'team1_prev_series': team1_prev_series,
                'team2_prev_series': team2_prev_series,
                'winner': winner,
                'team1_game_wins': team1_wins,
                'team2_game_wins': team2_wins,
            }
        )
