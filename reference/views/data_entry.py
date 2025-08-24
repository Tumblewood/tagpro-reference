from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import models, transaction
import json
import re
from datetime import datetime, date
import tagpro_eu
from typing import Optional, List, Dict, Any

from .stat_collection import process_game_stats, reaggregate_stats, update_standings
from ..models import Franchise, Season, TeamSeason, Player, PlayerSeason, Match, Game, PlayerGameLog


with open("data/league_matches.json") as f1, open("data/bulkmaps.json", encoding="utf-8") as f2:
    bulkmatches = [m for m in tagpro_eu.bulk.load_matches(
       f1,
        tagpro_eu.bulk.load_maps(f2)
    )]


def extract_game_data(eu_url: str) -> Dict:
    """Extract basic game data from the tagpro.eu URL."""
    # Extract game ID from URL
    game_id = re.search(r'(\d{6,7})', eu_url)
    game_id = game_id.group(1) if game_id else "-1"
    try:
        m: tagpro_eu.Match = [g for g in bulkmatches if g.match_id == game_id][0]
    except IndexError:
        # if no match found in bulkmatches, download from tagpro.eu
        # when we use download_match, map_id field will not be present, so set it to None
        m: tagpro_eu.Match = tagpro_eu.download_match(eu_url)
        m.map_id = None
    
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
    for p in players:
        reaggregate_stats(p['player_season'])


@staff_member_required
def import_from_eus(request):
    """Render page where user can paste a list of tagpro.eus and start importing matches."""
    if request.method == 'GET':
        return render(request, 'reference/data_import.html')
    
    elif request.method == 'POST':
        # Handle initial form submission with season filter and URLs  
        if 'season_filter_string' in request.POST and 'submit_game_data' not in request.POST:
            season_filter_string = request.POST.get('season_filter_string', '').strip()
            eu_urls = [url.strip() for url in request.POST.get('eu_urls', '').strip().split('\n') if url.strip()]
            
            if not season_filter_string:
                messages.error(request, "Please enter a season filter string.")
                return render(request, 'reference/data_import.html')
            
            if not eu_urls:
                messages.error(request, "Please enter at least one tagpro.eu URL.")
                return render(request, 'reference/data_import.html')
            
            try:
                # Get season group
                season_group = [s for s in Season.objects.all() if season_filter_string in s.name]
                if not season_group:
                    messages.error(request, f"No seasons found matching '{season_filter_string}'")
                    return render(request, 'reference/data_import.html')
                
                # Process first URL
                current_url = eu_urls[0]
                remaining_urls = eu_urls[1:]
                
                form_data = prepopulate_form(season_filter_string, current_url)
                
                # Get dropdown options
                team_seasons = TeamSeason.objects.filter(season__in=season_group)
                matches = Match.objects.filter(season__in=season_group)
                player_seasons = PlayerSeason.objects.filter(season__in=season_group)
                all_players = Player.objects.all()
                
                return render(request, 'reference/data_import_form.html', {
                    'form_data': form_data,
                    'team_seasons': team_seasons,
                    'matches': matches,
                    'player_seasons': player_seasons,
                    'all_players': all_players,
                    'season_filter_string': season_filter_string,
                    'current_url': current_url,
                    'remaining_urls': remaining_urls,
                    'total_urls': len(eu_urls),
                    'current_index': 1
                })
                
            except Exception as e:
                messages.error(request, f"Error processing URL: {str(e)}")
                return render(request, 'reference/data_import.html')
        
        # Handle game data submission
        elif 'submit_game_data' in request.POST:
            try:
                # Extract form data
                red_team_id = request.POST.get('red_team')
                blue_team_id = request.POST.get('blue_team')
                match_id = request.POST.get('match')
                week = request.POST.get('week')
                game_in_match = request.POST.get('game_in_match')
                
                # Get objects
                red_team = TeamSeason.objects.get(id=red_team_id) if red_team_id else None
                blue_team = TeamSeason.objects.get(id=blue_team_id) if blue_team_id else None
                match = Match.objects.get(id=match_id) if match_id else None
                
                # Get game data from form
                eu_url = request.POST.get('eu_url')
                red_team_raw_name = request.POST.get('red_team_raw_name')
                blue_team_raw_name = request.POST.get('blue_team_raw_name')
                score_red = int(request.POST.get('red_team_score'))
                score_blue = int(request.POST.get('blue_team_score'))
                map_name = request.POST.get('map_name')
                map_id = int(request.POST.get('map_id'))
                date_str = request.POST.get('date')
                date = datetime.strptime(date_str, '%Y-%m-%d').date()
                
                # Extract player data
                players = []
                player_count = 0
                while f'player_season_{player_count}' in request.POST:
                    player_season_id = request.POST.get(f'player_season_{player_count}')
                    player_id = request.POST.get(f'player_{player_count}')
                    season_team_id = request.POST.get(f'season_team_{player_count}')
                    
                    player_data = {
                        'player_season': PlayerSeason.objects.get(id=player_season_id) if player_season_id else None,
                        'player': Player.objects.get(id=player_id) if player_id else None,
                        'player_username': request.POST.get(f'player_username_{player_count}', ''),
                        'season_username': request.POST.get(f'season_username_{player_count}', ''),
                        'season_team': TeamSeason.objects.get(id=season_team_id) if season_team_id else None,
                        'game_username': request.POST.get(f'game_username_{player_count}', ''),
                        'game_team': request.POST.get(f'game_team_{player_count}', ''),
                    }
                    players.append(player_data)
                    player_count += 1
                
                # Submit data
                enter_confirmed_data(
                    red_team=red_team,
                    blue_team=blue_team,
                    red_team_raw_name=red_team_raw_name,
                    blue_team_raw_name=blue_team_raw_name,
                    match=match,
                    week=week,
                    game_in_match=game_in_match,
                    eu_url=eu_url,
                    score_red=score_red,
                    score_blue=score_blue,
                    map_name=map_name,
                    map_id=map_id,
                    date=date,
                    players=players
                )
                update_standings(red_team.season)
                
                messages.success(request, f"Game data saved successfully for {eu_url}")
                
                # Check if there are more URLs to process
                season_filter_string = request.POST.get('season_filter_string')
                remaining_urls = [url for url in request.POST.get('remaining_urls', '').split('|||') if url.strip()]
                
                if remaining_urls:
                    # Process next URL
                    current_url = remaining_urls[0]
                    remaining_urls = remaining_urls[1:]
                    current_index = int(request.POST.get('current_index', 1)) + 1
                    total_urls = int(request.POST.get('total_urls', 1))
                    
                    form_data = prepopulate_form(season_filter_string, current_url)
                    
                    # Get dropdown options
                    season_group = [s for s in Season.objects.all() if season_filter_string in s.name]
                    team_seasons = TeamSeason.objects.filter(season__in=season_group)
                    matches = Match.objects.filter(season__in=season_group)
                    player_seasons = PlayerSeason.objects.filter(season__in=season_group)
                    all_players = Player.objects.all()
                    
                    return render(request, 'reference/data_import_form.html', {
                        'form_data': form_data,
                        'team_seasons': team_seasons,
                        'matches': matches,
                        'player_seasons': player_seasons,
                        'all_players': all_players,
                        'season_filter_string': season_filter_string,
                        'current_url': current_url,
                        'remaining_urls': remaining_urls,
                        'total_urls': total_urls,
                        'current_index': current_index
                    })
                else:
                    messages.success(request, "All URLs processed successfully!")
                    return redirect('import_data')
                    
            except Exception as e:
                messages.error(request, f"Error saving game data: {str(e)}")
                # Return to form with error
                return render(request, 'reference/data_import_form.html', {
                    'error': str(e),
                    'form_data': request.POST
                })


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


def preprocess_eu_links(request):
    """Form where user can paste EU links and get back JSON data."""
    if request.method == 'GET':
        return render(request, 'reference/preprocess_eu_links.html')
    
    elif request.method == 'POST':
        season_filter_string = request.POST.get('season_filter_string', '').strip()
        eu_input = request.POST.get('eu_urls', '').strip()
        
        # Extract all numbers from the input using regex (these should be EU IDs)
        eu_ids = re.findall(r'\b(\d+)\b', eu_input)
        eu_urls = [f"https://tagpro.eu/?match={eu_id}" for eu_id in eu_ids]
        
        if not season_filter_string:
            messages.error(request, "Please enter a season filter string.")
            return render(request, 'reference/preprocess_eu_links.html')
        
        if not eu_urls:
            messages.error(request, "Please enter at least one tagpro.eu URL.")
            return render(request, 'reference/preprocess_eu_links.html')
        
        try:
            json_data = process_multiple_eu_links(season_filter_string,sorted(eu_urls))
            return render(request, 'reference/preprocess_results.html', {
                'json_data': format_compact_json(json_data),
                'url_count': len(eu_urls)
            })
        except Exception as e:
            messages.error(request, f"Error processing URLs: {str(e)}")
            return render(request, 'reference/preprocess_eu_links.html')


@staff_member_required
@transaction.atomic
def import_from_json(request):
    """Form where user can paste JSON data to import into database."""
    if request.method == 'GET':
        return render(request, 'reference/import_json.html')
    
    elif request.method == 'POST':
        json_data_str = request.POST.get('json_data', '').strip()
        
        if not json_data_str:
            messages.error(request, "Please enter JSON data.")
            return render(request, 'reference/import_json.html')
        
        try:
            json_data = json.loads(json_data_str)
            
            # Import data idempotently
            import_results = import_json_data_to_db(json_data)
            
            messages.success(request, f"Import completed: {import_results['created_count']} new games, {import_results['skipped_count']} already existed")
            return render(request, 'reference/import_json.html')
            
        except json.JSONDecodeError as e:
            messages.error(request, f"Invalid JSON: {str(e)}")
            return render(request, 'reference/import_json.html')
        except Exception as e:
            messages.error(request, f"Error importing JSON: {str(e)}")
            return render(request, 'reference/import_json.html')


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
        
        # Get or create team season
        team_season, _ = TeamSeason.objects.get_or_create(
            season=season,
            name=ts_data['name'],
            defaults={
                'franchise': franchises_cache[franchise_name],
                'abbr': ts_data['abbr']
            }
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

            # Create game
            game = Game.objects.create(
                match=match,
                red_team=red_team,
                blue_team=blue_team,
                team1_score=game_data['team1_score'],
                team2_score=game_data['team2_score'],
                map_name=game_data['map_name'],
                map_id=game_data['map_id'] if game_data['map_id'] else None,
                game_in_match=f"Game {game_in_match}",
                tagpro_eu=game_data['tagpro_eu']
            )

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
                    PlayerGameLog.objects.create(
                        game=game,
                        player_season=player_season,
                        playing_as=player_data['playing_as'],
                        team=team
                    )
            
            # Process game stats
            created_count += 1
    
    return {'created_count': created_count, 'skipped_count': skipped_count}


def format_compact_json(data):
    """Format JSON with scalar fields on one line, arrays/objects multi-line."""
    def format_value(obj, indent_level=0):
        indent = "  " * indent_level
        
        if isinstance(obj, dict):
            # Check if this object has any array/object values
            has_complex_values = any(isinstance(v, (list, dict)) for v in obj.values())
            
            if not has_complex_values:
                # All scalar values - put on one line
                pairs = [f'"{k}": {json.dumps(v)}' for k, v in obj.items()]
                return "{ " + ", ".join(pairs) + " }"
            else:
                # Has complex values - use multi-line format
                lines = ["{"]
                for k, v in obj.items():
                    if isinstance(v, (list, dict)):
                        lines.append(f'{indent}  "{k}": {format_value(v, indent_level + 1)},')
                    else:
                        # Scalar field - format inline
                        scalar_pairs = [(k, v)]
                        # Collect consecutive scalar fields
                        items = list(obj.items())
                        current_idx = items.index((k, v))
                        while (current_idx + 1 < len(items) and 
                               not isinstance(items[current_idx + 1][1], (list, dict))):
                            current_idx += 1
                            scalar_pairs.append(items[current_idx])
                        
                        if len(scalar_pairs) > 1:
                            # Multiple scalars - put them together on one line
                            formatted_pairs = [f'"{pk}": {json.dumps(pv)}' for pk, pv in scalar_pairs]
                            lines.append(f'{indent}  {", ".join(formatted_pairs)},')
                            # Skip the ones we just processed
                            for _ in range(len(scalar_pairs) - 1):
                                next(iter(obj.items()))
                        else:
                            lines.append(f'{indent}  "{k}": {json.dumps(v)},')
                
                # Remove trailing comma from last line
                if lines[-1].endswith(','):
                    lines[-1] = lines[-1][:-1]
                lines.append(indent + "}")
                return "\n".join(lines)
                
        elif isinstance(obj, list):
            if not obj:
                return "[]"
            lines = ["["]
            for i, item in enumerate(obj):
                comma = "," if i < len(obj) - 1 else ""
                formatted_item = format_value(item, indent_level + 1)
                if isinstance(item, dict):
                    lines.append(f"{indent}  {formatted_item}{comma}")
                else:
                    lines.append(f"{indent}  {json.dumps(item)}{comma}")
            lines.append(indent + "]")
            return "\n".join(lines)
        else:
            return json.dumps(obj)
    
    # Simplified approach - format each top-level section
    result_lines = ["{"]
    
    # teamSeasons - each on one line
    if data.get('teamSeasons'):
        result_lines.append('  "teamSeasons": [')
        for i, ts in enumerate(data['teamSeasons']):
            comma = "," if i < len(data['teamSeasons']) - 1 else ""
            pairs = [f'"{k}": {json.dumps(v)}' for k, v in ts.items()]
            result_lines.append(f'    {{ {", ".join(pairs)} }}{comma}')
        result_lines.append('  ],')
    
    # playerSeasons - each on one line  
    if data.get('playerSeasons'):
        result_lines.append('  "playerSeasons": [')
        for i, ps in enumerate(data['playerSeasons']):
            comma = "," if i < len(data['playerSeasons']) - 1 else ""
            pairs = [f'"{k}": {json.dumps(v)}' for k, v in ps.items()]
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
            scalar_pairs = [f'"{k}": {json.dumps(v)}' for k, v in scalar_fields.items()]
            result_lines.append(f'      {", ".join(scalar_pairs)},')
            
            # Games array
            result_lines.append('      "games": [')
            for j, game in enumerate(match['games']):
                game_comma = "," if j < len(match['games']) - 1 else ""
                result_lines.append('        {')
                
                # Game scalar fields on one line
                game_scalar_fields = {k: v for k, v in game.items() if k != 'players'}
                game_scalar_pairs = [f'"{k}": {json.dumps(v)}' for k, v in game_scalar_fields.items()]
                result_lines.append(f'          {", ".join(game_scalar_pairs)},')
                
                # Players array - each player on one line
                result_lines.append('          "players": [')
                for p_idx, player in enumerate(game['players']):
                    player_comma = "," if p_idx < len(game['players']) - 1 else ""
                    player_pairs = [f'"{k}": {json.dumps(v)}' for k, v in player.items()]
                    result_lines.append(f'            {{ {", ".join(player_pairs)} }}{player_comma}')
                result_lines.append('          ]')
                
                result_lines.append(f'        }}{game_comma}')
            result_lines.append('      ]')
            result_lines.append(f'    }}{comma}')
        result_lines.append('  ]')
    
    result_lines.append('}')
    return '\n'.join(result_lines)
