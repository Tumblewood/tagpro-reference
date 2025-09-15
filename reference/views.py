from typing import List
from django.shortcuts import render, redirect, get_object_or_404
from django.db import models
from reference.utils.display_info import aggregate_player_stats, get_team_standings, calculate_match_box_score, get_match_team_stats
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
