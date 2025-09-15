from typing import List, Dict, Any
import json
import re
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.db import models, transaction
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from reference.utils.display_info import aggregate_player_stats, get_team_standings, calculate_match_box_score, get_match_team_stats
from reference.utils.data_entry import extract_game_data, infer_team, infer_player, prepopulate_form, enter_confirmed_data, infer_season, infer_week
from reference.utils.stat_collection import update_standings
from reference.models import Season, TeamSeason, Player, PlayerSeason, Match, Game, PlayerGameLog, League, PlayoffSeries, Franchise


PLAYOFF_ORDER = {
    'Fibonacci Fifteen': "ZZZZ1",
    'Play-in': "ZZZZ1",
    'Equidistant Eight': "ZZZZ2",
    'Secant Six': "ZZZZ2",
    'Spherical Six': "ZZZZ2",
    'Foci Four': "ZZZZ3",
    'Super Ball': "ZZZZ4",
    'Muper Ball': "ZZZZ4",
    'Nuper Ball': "ZZZZ4",
    'Buper Ball': "ZZZZ4",
}
STAT_VIEW_OPTIONS = [
    { 'value': "basic", 'label': "Basic" },
    { 'value': "offense", 'label': "Offense" },
    { 'value': "defense", 'label': "Defense" },
    { 'value': "offense_rates", 'label': "Offense Rates" },
    { 'value': "defense_rates", 'label': "Defense Rates" },
    { 'value': "miscellaneous", 'label': "Miscellaneous" },
]
STAT_COLUMNS = {
    'basic': [
        {'key': 'time_played_min', 'label': 'Min', 'type': 'number'},
        {'key': 'tags', 'label': 'Tags', 'type': 'number'},
        {'key': 'pops', 'label': 'Pops', 'type': 'number'},
        {'key': 'grabs', 'label': 'Grabs', 'type': 'number'},
        {'key': 'drops', 'label': 'Drops', 'type': 'number'},
        {'key': 'hold_sec', 'label': 'Hold', 'type': 'number'},
        {'key': 'captures', 'label': 'Caps', 'type': 'number'},
        {'key': 'prevent_sec', 'label': 'Prev', 'type': 'number'},
        {'key': 'returns', 'label': 'Ret', 'type': 'number'},
        {'key': 'powerups', 'label': 'Pups', 'type': 'number'},
    ],
    'offense': [
        {'key': 'time_played_min', 'label': 'Min', 'type': 'number'},
        {'key': 'grabs_off_handoffs', 'label': 'GOH', 'type': 'number', 'tooltip': 'Grabs Off Handoffs - grabs within <2 seconds of teammate drop from hold of <3 seconds'},
        {'key': 'caps_off_handoffs', 'label': 'COH', 'type': 'number', 'tooltip': 'Caps Off Handoffs - caps after grabbing within <2 seconds of teammate drop from hold of <3 seconds'},
        {'key': 'grabs_off_regrab', 'label': 'GOR', 'type': 'number', 'tooltip': 'Grabs Off Regrab - grabs within <2 seconds of teammate drop'},
        {'key': 'caps_off_regrab', 'label': 'COR', 'type': 'number', 'tooltip': 'Caps Off Regrab - caps after grabbing within <2 seconds of teammate drop'},
        {'key': 'long_holds', 'label': 'LH', 'type': 'number', 'tooltip': 'Long Holds - holds of >10 seconds'},
        {'key': 'flaccids', 'label': 'FLcd', 'type': 'number', 'tooltip': 'Flaccids - drop after <2 seconds of hold'},
        {'key': 'handoffs', 'label': 'HO', 'type': 'number', 'tooltip': 'Handoffs - hold for <3 seconds and teammate grabs within <2 seconds of the drop'},
        {'key': 'good_handoffs', 'label': 'GH', 'type': 'number', 'tooltip': 'Good Handoffs - handoff resulting in teammate hold of >5 seconds'},
    ],
    'defense': [
        {'key': 'time_played_min', 'label': 'Min', 'type': 'number'},
        {'key': 'quick_returns', 'label': 'QR', 'type': 'number', 'tooltip': 'Quick Returns - return within <2 seconds of opponent hold'},
        {'key': 'returns_in_base', 'label': 'RIB', 'type': 'number', 'tooltip': 'Returns In Base - return within 10 tiles of the team\'s flag'},
        {'key': 'saves', 'label': 'Saves', 'type': 'number', 'tooltip': 'Saves - return within 10 tiles of the enemy flag'},
        {'key': 'key_returns', 'label': 'KR', 'type': 'number', 'tooltip': 'Key Returns - return within <2 seconds before team caps'},
        {'key': 'hold_against_sec', 'label': 'HA', 'type': 'number', 'tooltip': 'Hold Against - hold accumulated by opponents while playing (in seconds)'},
    ],
    'offense_rates': [
        {'key': 'time_played_min', 'label': 'Min', 'type': 'number'},
        {'key': 'gpm', 'label': 'GPM', 'type': 'number', 'tooltip': 'Grabs Per Minute - grabs / minutes played'},
        {'key': 'cpm', 'label': 'CPM', 'type': 'number', 'tooltip': 'Caps Per Minute - captures / minutes played'},
        {'key': 'hpm', 'label': 'HPM', 'type': 'number', 'tooltip': 'Hold Per Minute - hold / minutes played'},
        {'key': 'hold_per_grab', 'label': 'H/G', 'type': 'number', 'tooltip': 'Hold per Grab - hold / grabs'},
        {'key': 'score_percent', 'label': 'Score%', 'type': 'number', 'tooltip': 'Score Percentage - captures / grabs'},
        {'key': 'chain_percent', 'label': 'Chain%', 'type': 'number', 'tooltip': 'Chain Percentage - good handoffs / handoffs'},
        {'key': 'spark_percent', 'label': 'Spark%', 'type': 'number', 'tooltip': 'Spark Percentage - (captures - caps off regrab) / captures'},
        {'key': 'flaccid_percent', 'label': 'Flaccid%', 'type': 'number', 'tooltip': 'Flaccid Percentage - flaccids / grabs'},
    ],
    'defense_rates': [
        {'key': 'time_played_min', 'label': 'Min', 'type': 'number'},
        {'key': 'tpm', 'label': 'TPM', 'type': 'number', 'tooltip': 'Tags Per Minute - tags / minutes played'},
        {'key': 'rpm', 'label': 'RPM', 'type': 'number', 'tooltip': 'Returns Per Minute - returns / minutes played'},
        {'key': 'ppm', 'label': 'PPM', 'type': 'number', 'tooltip': 'Prevent Per Minute - prevent / minutes played'},
        {'key': 'ham', 'label': 'HAM', 'type': 'number', 'tooltip': 'Hold Against Per Minute - hold against / minutes played'},
        {'key': 'prevent_per_return', 'label': 'P/R', 'type': 'number', 'tooltip': 'Prevent per Return - prevent / returns'},
        {'key': 'prevent_per_hold_against', 'label': 'P/HA', 'type': 'number', 'tooltip': 'Prevent per Hold Against - prevent / hold against'},
        {'key': 'rib_percent', 'label': 'RIB%', 'type': 'number', 'tooltip': 'Return In Base Percentage - returns in base / returns'},
        {'key': 'qr_percent', 'label': 'QR%', 'type': 'number', 'tooltip': 'Quick Return Percentage - quick returns / returns'},
    ],
    'miscellaneous': [
        {'key': 'time_played_min', 'label': 'Min', 'type': 'number'},
        {'key': 'plus_minus', 'label': 'PM', 'type': 'number', 'tooltip': 'Plus/Minus - caps for - caps against'},
        {'key': 'kept_flags', 'label': 'KF', 'type': 'number', 'tooltip': 'Kept Flags - times holding flag as the game ends'},
        {'key': 'kd_ratio', 'label': 'K/D', 'type': 'number', 'tooltip': 'Kill/Death Ratio - tags / pops'},
        {'key': 'non_return_tags', 'label': 'NRTags', 'type': 'number', 'tooltip': 'Non-Return Tags - tags - returns'},
        {'key': 'non_drop_pops', 'label': 'NDPops', 'type': 'number', 'tooltip': 'Non-Drop Pops - pops - drops'},
        {'key': 'pup_percent', 'label': 'Pup%', 'type': 'number', 'tooltip': 'Powerup Percentage - powerups / total pups in game'},
    ]
}


def homepage(req):
    """Homepage with standings for all leagues."""
    # Get all leagues with ordering < 10
    leagues = League.objects.filter(ordering__lt=10, gamemode="CTF").order_by('ordering')
    league_standings = []
    for league in leagues:
        # Get the most recent season for this league
        latest_season = Season.objects.filter(league=league).order_by('-end_date').first()
        if not latest_season:
            continue
            
        # Get all teams in this season
        teams = TeamSeason.objects.filter(season=latest_season)
        if not teams.exists():
            continue
        
        standings: List[TeamSeason] = [get_team_standings(team) for team in teams]
        standings = sorted(standings, key=lambda x: x['team'].seed)
        league_standings.append({
            'league': league,
            'season': latest_season,
            'standings': standings,
        })
    
    return render(req, 'reference/homepage.html', {
        'league_standings': league_standings,
    })


def search_results(req, query):
    """
    Search across franchises, teams, and players with substring matching.
    Send user directly to page if there's exactly one match.
    """
    if not query or len(query.strip()) < 2:
        return render(req, 'reference/search_results.html', {
            'query': query,
            'leagues': [],
            'franchises': [],
            'teams': [],
            'players': [],
            'no_results': True
        })
    
    query = query.strip()
    query_lower = query.lower()
    
    # Check for redirect conditions
    league_exact_matches = [l for l in leagues if l.name.lower() == query_lower or (l.abbr and l.abbr.lower() == query_lower)]
    franchise_exact_matches = [f for f in franchises if f.name.lower() == query_lower or (f.abbr and f.abbr.lower() == query_lower)]
    team_exact_matches = [t for t in teams if t.name.lower() == query_lower or (t.abbr and t.abbr.lower() == query_lower)]
    player_exact_matches = [p for p in players if p.name.lower() == query_lower]
    
    # Redirect logic - leagues are treated like franchises
    if len(league_exact_matches) == 1 and len(player_exact_matches) == 0:
        return redirect('league_history', league_id=league_exact_matches[0].id)
    
    if len(franchise_exact_matches) == 1 and len(player_exact_matches) == 0:
        return redirect('franchise_history', franchise_id=franchise_exact_matches[0].id)
    
    if len(team_exact_matches) == 1 and len(league_exact_matches) == 0 and len(franchise_exact_matches) == 0 and len(player_exact_matches) == 0:
        return redirect('team_season', team_id=team_exact_matches[0].id)
    
    if len(player_exact_matches) == 1 and len(league_exact_matches) == 0 and len(franchise_exact_matches) == 0 and len(team_exact_matches) == 0:
        return redirect('player_history', player_id=player_exact_matches[0].id)
    
    # If we have exactly one league match and no players, redirect
    if len(leagues) == 1 and len(players) == 0:
        return redirect('league_history', league_id=leagues[0].id)
    
    # If we have exactly one franchise match and no players, redirect
    if len(franchises) == 1 and len(players) == 0:
        return redirect('franchise_history', franchise_id=franchises[0].id)
    
    # If we have exactly one team match and no leagues, franchises or players, redirect  
    if len(teams) == 1 and len(leagues) == 0 and len(franchises) == 0 and len(players) == 0:
        return redirect('team_season', team_id=teams[0].id)
    
    # Search leagues by name and abbreviation (case-insensitive substring)
    leagues = League.objects.filter(
        models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
    ).order_by('name')[:20]
    
    # Search franchises by name and abbreviation (case-insensitive substring)
    franchises = Franchise.objects.filter(
        models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
    ).order_by('name')[:20]
    
    # Search teams by name and abbreviation (case-insensitive substring)
    teams = TeamSeason.objects.filter(
        models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
    ).select_related('season', 'franchise').order_by('-season__end_date')[:20]
    
    # Search players by name and playing_as (case-insensitive substring)
    # Use distinct to avoid duplicates when a player matches both name and playing_as
    player_matches = set()
    
    # Search by player name
    players_by_name = Player.objects.filter(
        name__icontains=query
    ).order_by('name')[:20]
    player_matches.update(players_by_name)
    
    # Search by playing_as in PlayerSeason
    players_by_playing_as = Player.objects.filter(
        seasons_played__playing_as__icontains=query
    ).distinct().order_by('name')[:20]
    player_matches.update(players_by_playing_as)
    
    # Convert to list and limit to 20, maintaining sort order
    players = sorted(list(player_matches), key=lambda p: p.name.lower())[:20]
    
    return render(req, 'reference/search_results.html', {
        'query': query,
        'leagues': leagues,
        'franchises': franchises,
        'teams': teams,
        'players': players,
        'no_results': len(leagues) == 0 and len(franchises) == 0 and len(teams) == 0 and len(players) == 0
    })


def league_history(req, league_id):
    """View league's history showing all seasons with champions and runners-up."""
    league = get_object_or_404(League, id=league_id)
    
    # Get all seasons for this league
    seasons = Season.objects.filter(league=league).order_by('-end_date')
    season_history = []
    for season in seasons:
        # Count teams in this season
        team_count = TeamSeason.objects.filter(season=season).count()
        
        # Find champion and runner-up from the final playoff series
        champion = None
        runner_up = None
        
        # Look for the championship game/series (Super Ball, etc.)
        final_names = ['Super Ball', 'Muper Ball', 'Nuper Ball', 'Buper Ball']
        championship_matches = Match.objects.filter(
            season=season,
            week__in=final_names,
            playoff_series__isnull=False
        ).select_related('playoff_series', 'team1', 'team2').first()
        
        if championship_matches and championship_matches.playoff_series:
            playoff_series = championship_matches.playoff_series
            if playoff_series.winner:
                champion = playoff_series.winner
                # The other team in the match is the runner-up
                if championship_matches.team1 == champion:
                    runner_up = championship_matches.team2
                else:
                    runner_up = championship_matches.team1
        
        season_history.append({
            'season': season,
            'team_count': team_count,
            'champion': champion,
            'runner_up': runner_up,
        })
    
    return render(req, 'reference/league_history.html', {
        'league': league,
        'season_history': season_history,
    })


def season_home(req, season_id):
    """View key season information, namely standings."""
    season = get_object_or_404(Season, id=season_id)
    league_seasons = Season.objects.filter(league=season.league).order_by('-end_date')
    teams = TeamSeason.objects.filter(season=season)
    standings = [get_team_standings(team) for team in teams]
    standings = sorted(standings, key=lambda x: x['team'].seed)
    
    return render(req, 'reference/season_home.html', {
        'season': season,
        'league_seasons': league_seasons,
        'standings': standings,
    })


def season_schedule(req, season_id):
    """View season schedule with match results."""
    season = get_object_or_404(Season, id=season_id)
    league_seasons = Season.objects.filter(league=season.league).order_by('-end_date')
    
    # Get all matches for this season
    matches = Match.objects.filter(season=season).select_related(
        'team1__franchise', 'team2__franchise'
    ).prefetch_related('games', 'playoff_series')
    
    # Group matches by week
    weeks = {}
    for match in matches:
        week = match.week
        if week not in weeks:
            weeks[week] = []
        weeks[week].append(match)
    
    # Sort weeks with special playoff ordering
    def week_sort_key(week_name):
        return PLAYOFF_ORDER.get(week_name, week_name)
    
    sorted_weeks = sorted(weeks.keys(), key=week_sort_key)
    
    # Build schedule data
    schedule_data = []
    for week in sorted_weeks:
        week_matches = []
        for match in weeks[week]:
            # Get games for this match
            games = list(match.games.all())
            
            # Build box score data
            if games:
                match_data = calculate_match_box_score(match, games)
            else:
                match_data = {
                    'match': match,
                    'games': [],
                    'has_games': False
                }
            
            week_matches.append(match_data)
        
        schedule_data.append({
            'week': week,
            'matches': week_matches
        })
    
    return render(req, 'reference/season_schedule.html', {
        'season': season,
        'league_seasons': league_seasons,
        'schedule_data': schedule_data,
    })


def season_stats(req, season_id):
    """View season player statistics."""
    season = get_object_or_404(Season, id=season_id)
    
    # Get all seasons from the same league for dropdown
    league_seasons = Season.objects.filter(league=season.league).order_by('-end_date')
    
    # Get week filter and stat view from query params
    week_filter = req.GET.get('week', 'all_regular_season')
    stat_view = req.GET.get('view', 'basic')
    
    # Get all weeks for this season to build dropdown
    all_weeks = Match.objects.filter(season=season).values_list('week', flat=True).distinct()
    def week_sort_key(week_name):
        return PLAYOFF_ORDER.get(week_name, week_name)
    sorted_weeks = sorted(all_weeks, key=week_sort_key)
    
    # Build week options
    week_options = [
        { 'value': "all_regular_season", 'label': "All Regular Season" },
        { 'value': "all_playoffs", 'label': "All Playoffs" },
        { 'value': "all_season", 'label': "All RS + Playoffs" },
    ]
    for week in sorted_weeks:
        week_options.append({ 'value': week, 'label': week })
    
    stats = aggregate_player_stats(season=season, week=week_filter)
    template_stats = []
    for player_stat in stats:
        stat_row = {
            'player': player_stat['player'],
            'player_season': player_stat.get('player_season'),
            'team': player_stat.get('team'),
            'playing_as': player_stat['playing_as'],
            'column_values': []
        }
        
        for column in STAT_COLUMNS[stat_view]:
            value = player_stat.get(column['key'], 0)
            stat_row['column_values'].append(value)
        
        template_stats.append(stat_row)
    
    return render(req, 'reference/season_stats.html', {
        'season': season,
        'league_seasons': league_seasons,
        'player_stats': template_stats,
        'week_options': week_options,
        'current_week': week_filter,
        'stat_view_options': STAT_VIEW_OPTIONS,
        'current_stat_view': stat_view,
        'stat_columns': STAT_COLUMNS[stat_view],
    })


def season_rosters(req, season_id):
    """View season rosters with each team's players."""
    season = get_object_or_404(Season, id=season_id)
    
    # Get all seasons from the same league for dropdown
    league_seasons = Season.objects.filter(league=season.league).order_by('-end_date')
    
    # Get all teams in this season with their players
    teams = TeamSeason.objects.filter(season=season).prefetch_related(
        'players__player'
    ).order_by('name')
    
    # Build roster data
    rosters = []
    for team in teams:
        players = team.players.all().order_by('player__name')
        rosters.append({
            'team': team,
            'players': players
        })
    
    return render(req, 'reference/season_rosters.html', {
        'season': season,
        'league_seasons': league_seasons,
        'rosters': rosters,
    })


def player_history(req, player_id):
    """View player's career history across all seasons."""
    player = get_object_or_404(Player, id=player_id)
    
    # Get league filter from query params
    league_filter = req.GET.get('league', 'all')
    
    # Get all leagues for the filter dropdown
    all_leagues = League.objects.filter(gamemode="CTF").order_by('ordering')
    
    # Get all player seasons for this player
    player_seasons_query = PlayerSeason.objects.filter(player=player).select_related(
        'season__league', 'team'
    ).prefetch_related('season__teams')
    
    # Apply league filter
    if league_filter != 'all':
        try:
            league_id = int(league_filter)
            player_seasons_query = player_seasons_query.filter(season__league_id=league_id)
        except ValueError:
            pass
    else:
        # Filter to CTF leagues only
        player_seasons_query = player_seasons_query.filter(season__league__gamemode="CTF")
    
    # Build history data
    history_data = aggregate_player_stats(player=player)
    
    return render(req, "reference/player_history.html", {
        'player': player,
        'history_data': history_data,
        'leagues': all_leagues,
        'current_league': league_filter,
    })


def team_season(req, team_id):
    """View team season information, roster, stats, and schedule."""
    team = get_object_or_404(TeamSeason, id=team_id)
    season = team.season
    franchise = team.franchise
    
    # Get team rank and playoff finish from pre-calculated fields
    rank = team.seed if team.seed else "—"
    playoff_finish = team.playoff_finish if team.playoff_finish else "—"
    
    # Get team standings data (includes record)
    team_standings = get_team_standings(team)
    record = team_standings['record']
    
    # Get roster
    players = team.players.all().order_by('player__name')
    
    # Get player season stats for this team using aggregate_player_stats
    team_player_stats = aggregate_player_stats(season=season)
    team_stats = [stat for stat in team_player_stats if stat['team'] == team]
    
    # Get schedule data
    matches = Match.objects.filter(
        models.Q(team1=team) | models.Q(team2=team),
        season=season
    ).select_related('team1__franchise', 'team2__franchise').prefetch_related('games', 'playoff_series').order_by('date')
    
    # Build schedule data
    schedule_data = []
    for match in matches:
        # Get games for this match
        games = list(match.games.all())
        
        # Build box score data
        if games:
            match_data = calculate_match_box_score(match, games)
        else:
            match_data = {
                'match': match,
                'games': [],
                'has_games': False
            }
        
        schedule_data.append(match_data)
    
    return render(req, 'reference/team_season.html', {
        'team': team,
        'season': season,
        'franchise': franchise,
        'rank': rank,
        'playoff_finish': playoff_finish,
        'record': record,
        'players': players,
        'team_stats': team_stats,
        'schedule_data': schedule_data,
    })


def franchise_history(req, franchise_id):
    """View franchise's history across all seasons."""
    franchise = get_object_or_404(Franchise, id=franchise_id)
    
    # Get league filter from query params
    league_filter = req.GET.get('league', 'all')
    
    # Get all leagues for the filter dropdown
    all_leagues = League.objects.filter(gamemode="CTF").order_by('ordering')
    
    # Get all team seasons for this franchise
    team_seasons_query = TeamSeason.objects.filter(franchise=franchise).select_related(
        'season__league', 'captain', 'co_captain'
    )
    
    # Apply league filter
    if league_filter != 'all':
        try:
            league_id = int(league_filter)
            team_seasons_query = team_seasons_query.filter(season__league_id=league_id)
        except ValueError:
            pass
    else:
        # Filter to CTF leagues only
        team_seasons_query = team_seasons_query.filter(season__league__gamemode="CTF")
    
    team_seasons = team_seasons_query.order_by('-season__end_date')
    
    # Build history data
    history_data = []
    for team in team_seasons:
        season = team.season
        
        # Get team rank and playoff finish from pre-calculated fields
        rank = team.seed if team.seed else "—"
        playoff_finish = team.playoff_finish if team.playoff_finish else "—"
        
        # Get team record from standings
        team_standings = get_team_standings(team)
        record = team_standings['record']
        
        # Find player with most minutes
        team_player_stats = aggregate_player_stats(season=season, franchise=franchise)
        most_minutes_player = team_player_stats[0]['player'] if team_player_stats else None
        
        history_data.append({
            'season': season,
            'team': team,
            'rank': rank,
            'playoff_finish': playoff_finish,
            'record': record,
            'captain': team.captain,
            'co_captain': team.co_captain,
            'most_minutes_player': most_minutes_player,
        })
    
    # Get all-time player stats for this franchise using aggregate_player_stats
    if league_filter != 'all':
        try:
            league_id = int(league_filter)
            league = League.objects.get(id=league_id)
            franchise_stats = aggregate_player_stats(franchise=franchise, league=league)
        except (ValueError, League.DoesNotExist):
            franchise_stats = aggregate_player_stats(franchise=franchise)
    else:
        franchise_stats = aggregate_player_stats(franchise=franchise)
    
    # Aggregate by player across all their seasons with this franchise
    player_aggregates = {}
    for stat in franchise_stats:
        player = stat['player']
        
        if player not in player_aggregates:
            player_aggregates[player] = {
                'player': player,
                'time_played_min': 0,
                'tags': 0,
                'pops': 0,
                'grabs': 0,
                'drops': 0,
                'hold_sec': 0,
                'captures': 0,
                'prevent_sec': 0,
                'returns': 0,
                'powerups': 0,
            }
        
        # Aggregate each stat field
        agg = player_aggregates[player]
        agg['time_played_min'] += stat['time_played_min']
        agg['tags'] += stat['tags']
        agg['pops'] += stat['pops']
        agg['grabs'] += stat['grabs']
        agg['drops'] += stat['drops']
        agg['hold_sec'] += stat['hold_sec']
        agg['captures'] += stat['captures']
        agg['prevent_sec'] += stat['prevent_sec']
        agg['returns'] += stat['returns']
        agg['powerups'] += stat['powerups']
    
    # Convert to list and sort by time played (descending)
    all_time_stats = sorted(player_aggregates.values(), key=lambda x: -x['time_played_min'])
    
    return render(req, 'reference/franchise_history.html', {
        'franchise': franchise,
        'history_data': history_data,
        'all_time_stats': all_time_stats,
        'leagues': all_leagues,
        'current_league': league_filter,
    })


def match_view(req, match_id):
    """Detailed view of a specific match with box score and player stats."""
    match = get_object_or_404(Match, id=match_id)
    season = match.season
    
    # Get all games in the match
    games = Game.objects.filter(match=match).select_related(
        'red_team__franchise', 'blue_team__franchise'
    ).order_by('game_in_match')
    
    box_score_data = calculate_match_box_score(match, games, include_details=True)
    
    # Get player stats for all games (default view)
    selected_game = req.GET.get('game', 'all')
    
    # Filter games based on selection
    if selected_game == 'all':
        stats_games = games
        show_map_info = False
    else:
        try:
            game_number = int(selected_game)
            stats_games = games.filter(game_in_match=f"Game {game_number}")
            show_map_info = len(stats_games) == 1
        except (ValueError, TypeError):
            stats_games = games
            show_map_info = False
    
    # Get player stats for both teams using utility function
    team1_stats = get_match_team_stats(match, match.team1, selected_game)
    team2_stats = get_match_team_stats(match, match.team2, selected_game)
    
    # Get available games for dropdown
    game_options = [{'value': 'all', 'label': 'All Games'}]
    for game in games:
        if game.game_in_match:
            try:
                game_num = game.game_in_match.replace('Game ', '')
                game_options.append({
                    'value': game_num,
                    'label': game.game_in_match
                })
            except:
                pass
    
    # Get map info if single game is selected
    map_info = None
    if show_map_info and stats_games:
        game = stats_games.first()
        map_info = {
            'map_name': game.map_name,
            'tagpro_eu_url': f"https://tagpro.eu/?match={game.tagpro_eu}" if game.tagpro_eu else None,
            'replay': game.replay,
            'vod': game.vod,
        }
        if game.resumed_tagpro_eu:
            map_info['resumed_tagpro_eu_url'] = f"https://tagpro.eu/?match={game.resumed_tagpro_eu}"
    
    return render(req, 'reference/match_view.html', {
        'match': match,
        'season': season,
        'box_score_games': box_score_data['box_score_games'],
        'team1_total_score': box_score_data['team1_total'],
        'team2_total_score': box_score_data['team2_total'],
        'team1_total_caps': box_score_data['team1_total_caps'],
        'team2_total_caps': box_score_data['team2_total_caps'],
        'match_winner': box_score_data['match_winner'],
        'team1_stats': team1_stats,
        'team2_stats': team2_stats,
        'game_options': game_options,
        'selected_game': selected_game,
        'map_info': map_info,
    })


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
        red_team = infer_team(season_group, game_data['team_red']['name'])
        blue_team = infer_team(season_group, game_data['team_blue']['name'])
        season = None
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
            player_season = None
            player = infer_player(None, player_data['username'])
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
                pairs = [f'"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in obj.items()]
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
                            formatted_pairs = [f'"{pk}": {json.dumps(pv, ensure_ascii=False)}' for pk, pv in scalar_pairs]
                            lines.append(f'{indent}  {", ".join(formatted_pairs)},')
                            # Skip the ones we just processed
                            for _ in range(len(scalar_pairs) - 1):
                                next(iter(obj.items()))
                        else:
                            lines.append(f'{indent}  "{k}": {json.dumps(v, ensure_ascii=False)},')
                
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
                    lines.append(f"{indent}  {json.dumps(item, ensure_ascii=False)}{comma}")
            lines.append(indent + "]")
            return "\n".join(lines)
        else:
            return json.dumps(obj, ensure_ascii=False)
    
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
