from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import models
import json
import re
from datetime import datetime, date
from ..models import Season, TeamSeason, Player, PlayerSeason, Match, Game, PlayerGameLog, PlayerGameStats, PlayerWeekStats, PlayerSeasonStats, League, PlayoffSeries, Franchise
import tagpro_eu


def homepage(req):
    """Homepage with standings for all leagues."""
    # Get all leagues with ordering < 10, ordered by ordering field
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
        
        # Calculate standings for each team
        standings = []
        for team in teams:
            # Get all regular season games for the team
            team_games = Game.objects.filter(
                models.Q(red_team=team) | models.Q(blue_team=team),
                match__season=latest_season,
                match__week__startswith="Week"
            )
            
            # Initialize counters
            standing_points = 0
            wins = ot_wins = ot_losses = losses = 0
            caps_for = 0
            caps_against = 0
            
            for game in team_games:
                # Determine if this team is team1 or team2 in the match
                is_team1 = (team == game.match.team1)
                
                # Get team scores and standing points
                if is_team1:
                    team_score = game.team1_score
                    opponent_score = game.team2_score
                    team_standing_points = game.team1_standing_points or 0
                else:
                    team_score = game.team2_score
                    opponent_score = game.team1_score
                    team_standing_points = game.team2_standing_points or 0
                
                # Add to totals
                standing_points += team_standing_points
                caps_for += team_score
                caps_against += opponent_score
                
                # Determine outcome for this team
                if game.outcome:
                    if is_team1:
                        outcome = game.outcome
                    else:
                        # Flip the outcome for team2
                        outcome_map = {'W': 'L', 'OTW': 'OTL', 'L': 'W', 'OTL': 'OTW', 'T': 'T'}
                        outcome = outcome_map.get(game.outcome, game.outcome)
                    
                    if outcome == 'W':
                        wins += 1
                    elif outcome == 'OTW':
                        ot_wins += 1
                    elif outcome == 'OTL':
                        ot_losses += 1
                    elif outcome == 'L':
                        losses += 1
                else:
                    # Determine by score if outcome not set
                    if team_score > opponent_score:
                        wins += 1
                    elif team_score < opponent_score:
                        losses += 1
            
            cap_differential = caps_for - caps_against
            record = f"{wins}-{ot_wins}-{ot_losses}-{losses}"
            
            standings.append({
                'team': team,
                'standing_points': standing_points,
                'record': record,
                'cap_differential': cap_differential,
            })
        
        # Sort by standing points (descending), then by cap differential (descending)
        standings.sort(key=lambda x: (-x['standing_points'], -x['cap_differential']))
        
        # Add rank
        for i, standing in enumerate(standings, 1):
            standing['rank'] = i
        
        league_standings.append({
            'league': league,
            'season': latest_season,
            'standings': standings,
        })
    
    return render(req, 'reference/homepage.html', {
        'league_standings': league_standings,
    })


def search_results(req, query):
    """Search across franchises, teams, and players with substring matching."""
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
    
    # Build season history data
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
        else:
            # If no championship game found, look for any playoff series with latest date
            latest_playoff = Match.objects.filter(
                season=season,
                playoff_series__isnull=False
            ).select_related('playoff_series', 'team1', 'team2').order_by('-date').first()
            
            if latest_playoff and latest_playoff.playoff_series:
                playoff_series = latest_playoff.playoff_series
                if playoff_series.winner:
                    champion = playoff_series.winner
                    # The other team in the match is the runner-up
                    if latest_playoff.team1 == champion:
                        runner_up = latest_playoff.team2
                    else:
                        runner_up = latest_playoff.team1
        
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
    
    # Get all seasons from the same league for dropdown
    league_seasons = Season.objects.filter(league=season.league).order_by('-end_date')
    
    # Get all teams in this season
    teams = TeamSeason.objects.filter(season=season)
    
    # Calculate standings for each team
    standings = []
    for team in teams:
        # Get all regular season games for the team
        team_games = Game.objects.filter(
            models.Q(red_team=team) | models.Q(blue_team=team),
            match__season=season,
            match__week__startswith="Week"  # Non-regular season games should not start with Week
        )
        
        # Initialize counters
        games_played = team_games.count()
        standing_points = 0
        wins = 0
        ot_wins = 0
        ot_losses = 0
        losses = 0
        caps_for = 0
        caps_against = 0
        
        for game in team_games:
            # Determine if this team is team1 or team2 in the match
            is_team1 = (team == game.match.team1)
            
            # Get team scores
            if is_team1:
                team_score = game.team1_score
                opponent_score = game.team2_score
                team_standing_points = game.team1_standing_points or 0
            else:
                team_score = game.team2_score
                opponent_score = game.team1_score
                team_standing_points = game.team2_standing_points or 0
            
            # Add to totals
            standing_points += team_standing_points
            caps_for += team_score
            caps_against += opponent_score
            
            # Determine outcome for this team
            if game.outcome:
                if is_team1:
                    outcome = game.outcome
                else:
                    # Flip the outcome for team2
                    outcome_map = {'W': 'L', 'OTW': 'OTL', 'L': 'W', 'OTL': 'OTW', 'T': 'T'}
                    outcome = outcome_map.get(game.outcome, game.outcome)
                
                if outcome == 'W':
                    wins += 1
                elif outcome == 'OTW':
                    ot_wins += 1
                    caps_for -= 1  # OT caps don't count
                elif outcome == 'OTL':
                    ot_losses += 1
                    caps_against -= 1  # OT caps don't count
                elif outcome == 'L':
                    losses += 1
        
        cap_differential = caps_for - caps_against
        
        standings.append({
            'team': team,
            'games_played': games_played,
            'standing_points': standing_points,
            'wins': wins,
            'ot_wins': ot_wins,
            'ot_losses': ot_losses,
            'losses': losses,
            'caps_for': caps_for,
            'caps_against': caps_against,
            'cap_differential': cap_differential,
        })
    
    # Sort by standing points (descending), then by cap differential (descending)
    standings.sort(key=lambda x: (-x['standing_points'], -x['cap_differential']))
    
    # Add rank
    for i, standing in enumerate(standings, 1):
        standing['rank'] = i
    
    return render(req, 'reference/season_home.html', {
        'season': season,
        'league_seasons': league_seasons,
        'standings': standings,
    })


def season_schedule(req, season_id):
    """View season schedule with match results."""
    season = get_object_or_404(Season, id=season_id)
    
    # Get all seasons from the same league for dropdown
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
        playoff_order = {
            'Fibonacci Fifteen': 'ZZZZ1',
            'Equidistant Eight': 'ZZZZ2',
            'Secant Six': 'ZZZZ2',
            'Foci Four': 'ZZZZ3',
            'Super Ball': 'ZZZZ4',
            'Muper Ball': 'ZZZZ4',
            'Nuper Ball': 'ZZZZ4',
            'Buper Ball': 'ZZZZ4',
        }
        return playoff_order.get(week_name, week_name)
    
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
                # Calculate totals
                team1_total = 0
                team2_total = 0
                is_playoff = hasattr(match, 'playoff_series') and match.playoff_series
                
                game_results = []
                for game in games:
                    # Determine scores and winner
                    team1_score = game.team1_score
                    team2_score = game.team2_score
                    
                    # Check if overtime
                    is_overtime = game.outcome in ['OTW', 'OTL'] if game.outcome else False
                    
                    # Determine game winner
                    if team1_score > team2_score:
                        game_winner = 'team1'
                        if not is_playoff:
                            team1_total += game.team1_standing_points or 0
                            team2_total += game.team2_standing_points or 0
                        else:
                            team1_total += 1
                    elif team2_score > team1_score:
                        game_winner = 'team2'
                        if not is_playoff:
                            team1_total += game.team1_standing_points or 0
                            team2_total += game.team2_standing_points or 0
                        else:
                            team2_total += 1
                    else:
                        game_winner = 'tie'
                        if not is_playoff:
                            team1_total += game.team1_standing_points or 0
                            team2_total += game.team2_standing_points or 0
                    
                    game_results.append({
                        'team1_score': team1_score,
                        'team2_score': team2_score,
                        'winner': game_winner,
                        'is_overtime': is_overtime,
                        'game_number': game.game_in_match
                    })
                
                # Determine match winner
                if is_playoff:
                    match_winner = 'team1' if team1_total > team2_total else 'team2' if team2_total > team1_total else 'tie'
                else:
                    match_winner = 'team1' if team1_total > team2_total else 'team2' if team2_total > team1_total else 'tie'
                
                match_data = {
                    'match': match,
                    'games': game_results,
                    'team1_total': team1_total,
                    'team2_total': team2_total,
                    'match_winner': match_winner,
                    'is_playoff': is_playoff,
                    'has_games': True
                }
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
    
    # Get all player stats from regular season games only
    player_stats = PlayerStats.objects.filter(
        player_gamelog__game__match__season=season,
        player_gamelog__game__match__week__startswith="Week"  # Regular season only
    ).select_related(
        'player_gamelog__player_season__player',
        'player_gamelog__player_season__team'
    )
    
    # Aggregate stats by player
    player_aggregates = {}
    for stat in player_stats:
        player_season = stat.player_gamelog.player_season
        key = (player_season.player.id, player_season.team.id if player_season.team else None)
        
        if key not in player_aggregates:
            player_aggregates[key] = {
                'player': player_season.player,
                'player_season': player_season,
                'team': player_season.team,
                'playing_as': player_season.playing_as,
                'time_played': 0,
                'tags': 0,
                'pops': 0,
                'grabs': 0,
                'drops': 0,
                'hold': 0,
                'captures': 0,
                'prevent': 0,
                'returns': 0,
                'powerups': 0,
            }
        
        # Aggregate each stat field
        agg = player_aggregates[key]
        agg['time_played'] += stat.time_played or 0
        agg['tags'] += stat.tags or 0
        agg['pops'] += stat.pops or 0
        agg['grabs'] += stat.grabs or 0
        agg['drops'] += stat.drops or 0
        agg['hold'] += stat.hold or 0
        agg['captures'] += stat.captures or 0
        agg['prevent'] += stat.prevent or 0
        agg['returns'] += stat.returns or 0
        agg['powerups'] += stat.powerups or 0
    
    # Convert time fields and prepare final stats list
    stats_list = []
    for agg in player_aggregates.values():
        # Convert time fields
        agg['time_played_min'] = round(agg['time_played'] / 60) if agg['time_played'] else 0
        agg['hold_sec'] = round(agg['hold'] / 60) if agg['hold'] else 0
        agg['prevent_sec'] = round(agg['prevent'] / 60) if agg['prevent'] else 0
        
        stats_list.append(agg)
    
    # Sort by time played (descending)
    stats_list.sort(key=lambda x: -x['time_played'])
    
    return render(req, 'reference/season_stats.html', {
        'season': season,
        'league_seasons': league_seasons,
        'player_stats': stats_list,
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
    
    player_seasons = player_seasons_query.order_by('-season__end_date')
    
    # Build history data
    history_data = []
    for ps in player_seasons:
        season = ps.season
        team = ps.team
        
        # Calculate team rank in standings (if team exists)
        rank = "—"
        if team:
            # Get all teams in season and calculate standings
            season_teams = TeamSeason.objects.filter(season=season)
            standings = []
            
            for season_team in season_teams:
                # Calculate standing points for this team
                team_games = Game.objects.filter(
                    models.Q(red_team=season_team) | models.Q(blue_team=season_team),
                    match__season=season,
                    match__week__startswith="Week"
                )
                
                standing_points = 0
                caps_for = 0
                caps_against = 0
                
                for game in team_games:
                    is_team1 = (season_team == game.match.team1)
                    if is_team1:
                        standing_points += game.team1_standing_points or 0
                        caps_for += game.team1_score
                        caps_against += game.team2_score
                    else:
                        standing_points += game.team2_standing_points or 0
                        caps_for += game.team2_score
                        caps_against += game.team1_score
                
                standings.append({
                    'team': season_team,
                    'standing_points': standing_points,
                    'cap_differential': caps_for - caps_against
                })
            
            # Sort standings
            standings.sort(key=lambda x: (-x['standing_points'], -x['cap_differential']))
            
            # Find rank
            for i, standing in enumerate(standings, 1):
                if standing['team'].id == team.id:
                    rank = i
                    break
        
        # Calculate playoff finish
        playoff_finish = "—"
        if team and season.end_date and season.end_date <= date.today():
            # Season is over, determine playoff result
            # Check if team played in any playoff series
            playoff_matches = Match.objects.filter(
                season=season,
                playoff_series__isnull=False
            ).filter(
                models.Q(team1=team) | models.Q(team2=team)
            ).order_by('-date')
            
            if not playoff_matches.exists():
                playoff_finish = "Missed playoffs"
            else:
                # Find the last series this team played
                last_series = None
                for match in playoff_matches:
                    series = match.get_playoff_series()
                    if series:
                        last_series = series
                        break
                
                if last_series:
                    if last_series.winner == team:
                        # Check if this was the final (Super Ball, etc.)
                        final_names = ['Super Ball', 'Muper Ball', 'Nuper Ball', 'Buper Ball']
                        if match.week in final_names:
                            playoff_finish = "Won championship"
                        else:
                            playoff_finish = f"Won {match.week}"
                    else:
                        playoff_finish = f"Lost {match.week}"
        
        # Get player stats for this season
        player_stats = PlayerStats.objects.filter(
            player_gamelog__player_season=ps,
            player_gamelog__game__match__season=season
        )
        
        # Aggregate stats
        total_time = sum(stat.time_played or 0 for stat in player_stats)
        total_caps = sum(stat.captures or 0 for stat in player_stats) 
        total_hold = sum(stat.hold or 0 for stat in player_stats)
        total_prevent = sum(stat.prevent or 0 for stat in player_stats)
        total_returns = sum(stat.returns or 0 for stat in player_stats)
        
        # Convert time units
        minutes_played = round(total_time / 60) if total_time else 0
        hold_sec = round(total_hold / 60) if total_hold else 0
        prevent_sec = round(total_prevent / 60) if total_prevent else 0
        
        history_data.append({
            'season': season,
            'team': team,
            'rank': rank,
            'playoff_finish': playoff_finish,
            'minutes_played': minutes_played,
            'captures': total_caps,
            'hold_sec': hold_sec,
            'prevent_sec': prevent_sec,
            'returns': total_returns,
        })
    
    return render(req, 'reference/player_history.html', {
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
    
    # Calculate team rank in standings
    season_teams = TeamSeason.objects.filter(season=season)
    standings = []
    
    for season_team in season_teams:
        # Calculate standing points for this team
        team_games = Game.objects.filter(
            models.Q(red_team=season_team) | models.Q(blue_team=season_team),
            match__season=season,
            match__week__startswith="Week"
        )
        
        standing_points = 0
        caps_for = 0
        caps_against = 0
        
        for game in team_games:
            is_team1 = (season_team == game.match.team1)
            if is_team1:
                standing_points += game.team1_standing_points or 0
                caps_for += game.team1_score
                caps_against += game.team2_score
            else:
                standing_points += game.team2_standing_points or 0
                caps_for += game.team2_score
                caps_against += game.team1_score
        
        standings.append({
            'team': season_team,
            'standing_points': standing_points,
            'cap_differential': caps_for - caps_against
        })
    
    # Sort standings
    standings.sort(key=lambda x: (-x['standing_points'], -x['cap_differential']))
    
    # Find rank
    rank = "—"
    for i, standing in enumerate(standings, 1):
        if standing['team'].id == team.id:
            rank = i
            break
    
    # Calculate playoff finish
    playoff_finish = "—"
    if season.end_date and season.end_date <= date.today():
        playoff_matches = Match.objects.filter(
            season=season,
            playoff_series__isnull=False
        ).filter(
            models.Q(team1=team) | models.Q(team2=team)
        ).order_by('-date')
        
        if not playoff_matches.exists():
            playoff_finish = "Missed playoffs"
        else:
            last_series = None
            for match in playoff_matches:
                series = match.get_playoff_series()
                if series:
                    last_series = series
                    break
            
            if last_series:
                if last_series.winner == team:
                    final_names = ['Super Ball', 'Muper Ball', 'Nuper Ball', 'Buper Ball']
                    if match.week in final_names:
                        playoff_finish = "Won championship"
                    else:
                        playoff_finish = f"Won {match.week}"
                else:
                    playoff_finish = f"Lost {match.week}"
    
    # Calculate team record (W-OTW-OTL-L)
    team_games = Game.objects.filter(
        models.Q(red_team=team) | models.Q(blue_team=team),
        match__season=season,
        match__week__startswith="Week"
    )
    
    wins = ot_wins = ot_losses = losses = 0
    for game in team_games:
        is_team1 = (team == game.match.team1)
        
        if game.outcome:
            if is_team1:
                outcome = game.outcome
            else:
                outcome_map = {'W': 'L', 'OTW': 'OTL', 'L': 'W', 'OTL': 'OTW', 'T': 'T'}
                outcome = outcome_map.get(game.outcome, game.outcome)
            
            if outcome == 'W':
                wins += 1
            elif outcome == 'OTW':
                ot_wins += 1
            elif outcome == 'OTL':
                ot_losses += 1
            elif outcome == 'L':
                losses += 1
        else:
            # Determine by score if outcome not set
            team_score = game.team1_score if is_team1 else game.team2_score
            opponent_score = game.team2_score if is_team1 else game.team1_score
            
            if team_score > opponent_score:
                wins += 1
            elif team_score < opponent_score:
                losses += 1
    
    record = f"{wins}-{ot_wins}-{ot_losses}-{losses}"
    
    # Get roster
    players = team.players.all().order_by('player__name')
    
    # Get player stats for this team
    player_stats = PlayerStats.objects.filter(
        player_gamelog__team=team,
        player_gamelog__game__match__week__startswith="Week"  # Regular season only
    ).select_related(
        'player_gamelog__player_season__player'
    )
    
    # Aggregate stats by player
    player_aggregates = {}
    for stat in player_stats:
        player_season = stat.player_gamelog.player_season
        player = player_season.player
        
        if player not in player_aggregates:
            player_aggregates[player] = {
                'player': player,
                'time_played': 0,
                'tags': 0,
                'pops': 0,
                'grabs': 0,
                'drops': 0,
                'hold': 0,
                'captures': 0,
                'prevent': 0,
                'returns': 0,
                'powerups': 0,
            }
        
        # Aggregate each stat field
        agg = player_aggregates[player]
        agg['time_played'] += stat.time_played or 0
        agg['tags'] += stat.tags or 0
        agg['pops'] += stat.pops or 0
        agg['grabs'] += stat.grabs or 0
        agg['drops'] += stat.drops or 0
        agg['hold'] += stat.hold or 0
        agg['captures'] += stat.captures or 0
        agg['prevent'] += stat.prevent or 0
        agg['returns'] += stat.returns or 0
        agg['powerups'] += stat.powerups or 0
    
    # Convert time fields and prepare final stats list
    team_stats = []
    for agg in player_aggregates.values():
        # Convert time fields
        agg['time_played_min'] = round(agg['time_played'] / 60) if agg['time_played'] else 0
        agg['hold_sec'] = round(agg['hold'] / 60) if agg['hold'] else 0
        agg['prevent_sec'] = round(agg['prevent'] / 60) if agg['prevent'] else 0
        
        team_stats.append(agg)
    
    # Sort by time played (descending)
    team_stats.sort(key=lambda x: -x['time_played'])
    
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
            # Calculate totals
            team1_total = 0
            team2_total = 0
            is_playoff = hasattr(match, 'playoff_series') and match.playoff_series
            
            game_results = []
            for game in games:
                # Determine scores and winner
                team1_score = game.team1_score
                team2_score = game.team2_score
                
                # Check if overtime
                is_overtime = game.outcome in ['OTW', 'OTL'] if game.outcome else False
                
                # Determine game winner
                if team1_score > team2_score:
                    game_winner = 'team1'
                    if not is_playoff:
                        team1_total += game.team1_standing_points or 0
                        team2_total += game.team2_standing_points or 0
                    else:
                        team1_total += 1
                elif team2_score > team1_score:
                    game_winner = 'team2'
                    if not is_playoff:
                        team1_total += game.team1_standing_points or 0
                        team2_total += game.team2_standing_points or 0
                    else:
                        team2_total += 1
                else:
                    game_winner = 'tie'
                    if not is_playoff:
                        team1_total += game.team1_standing_points or 0
                        team2_total += game.team2_standing_points or 0
                
                game_results.append({
                    'team1_score': team1_score,
                    'team2_score': team2_score,
                    'winner': game_winner,
                    'is_overtime': is_overtime,
                    'game_number': game.game_in_match
                })
            
            # Determine match winner
            if is_playoff:
                match_winner = 'team1' if team1_total > team2_total else 'team2' if team2_total > team1_total else 'tie'
            else:
                match_winner = 'team1' if team1_total > team2_total else 'team2' if team2_total > team1_total else 'tie'
            
            match_data = {
                'match': match,
                'games': game_results,
                'team1_total': team1_total,
                'team2_total': team2_total,
                'match_winner': match_winner,
                'is_playoff': is_playoff,
                'has_games': True
            }
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
    ).prefetch_related('season__teams')
    
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
        
        # Calculate team rank in standings
        season_teams = TeamSeason.objects.filter(season=season)
        standings = []
        
        for season_team in season_teams:
            # Calculate standing points for this team
            team_games = Game.objects.filter(
                models.Q(red_team=season_team) | models.Q(blue_team=season_team),
                match__season=season,
                match__week__startswith="Week"
            )
            
            standing_points = 0
            caps_for = 0
            caps_against = 0
            
            for game in team_games:
                is_team1 = (season_team == game.match.team1)
                if is_team1:
                    standing_points += game.team1_standing_points or 0
                    caps_for += game.team1_score
                    caps_against += game.team2_score
                else:
                    standing_points += game.team2_standing_points or 0
                    caps_for += game.team2_score
                    caps_against += game.team1_score
            
            standings.append({
                'team': season_team,
                'standing_points': standing_points,
                'cap_differential': caps_for - caps_against
            })
        
        # Sort standings
        standings.sort(key=lambda x: (-x['standing_points'], -x['cap_differential']))
        
        # Find rank
        rank = "—"
        for i, standing in enumerate(standings, 1):
            if standing['team'].id == team.id:
                rank = i
                break
        
        # Calculate playoff finish (same logic as player_history)
        playoff_finish = "—"
        if season.end_date and season.end_date <= date.today():
            playoff_matches = Match.objects.filter(
                season=season,
                playoff_series__isnull=False
            ).filter(
                models.Q(team1=team) | models.Q(team2=team)
            ).order_by('-date')
            
            if not playoff_matches.exists():
                playoff_finish = "Missed playoffs"
            else:
                last_series = None
                for match in playoff_matches:
                    series = match.get_playoff_series()
                    if series:
                        last_series = series
                        break
                
                if last_series:
                    if last_series.winner == team:
                        final_names = ['Super Ball', 'Muper Ball', 'Nuper Ball', 'Buper Ball']
                        if match.week in final_names:
                            playoff_finish = "Won championship"
                        else:
                            playoff_finish = f"Won {match.week}"
                    else:
                        playoff_finish = f"Lost {match.week}"
        
        # Calculate team record (W-OTW-OTL-L)
        team_games = Game.objects.filter(
            models.Q(red_team=team) | models.Q(blue_team=team),
            match__season=season,
            match__week__startswith="Week"
        )
        
        wins = ot_wins = ot_losses = losses = 0
        for game in team_games:
            is_team1 = (team == game.match.team1)
            
            if game.outcome:
                if is_team1:
                    outcome = game.outcome
                else:
                    outcome_map = {'W': 'L', 'OTW': 'OTL', 'L': 'W', 'OTL': 'OTW', 'T': 'T'}
                    outcome = outcome_map.get(game.outcome, game.outcome)
                
                if outcome == 'W':
                    wins += 1
                elif outcome == 'OTW':
                    ot_wins += 1
                elif outcome == 'OTL':
                    ot_losses += 1
                elif outcome == 'L':
                    losses += 1
            else:
                # Determine by score if outcome not set
                team_score = game.team1_score if is_team1 else game.team2_score
                opponent_score = game.team2_score if is_team1 else game.team1_score
                
                if team_score > opponent_score:
                    wins += 1
                elif team_score < opponent_score:
                    losses += 1
        
        record = f"{wins}-{ot_wins}-{ot_losses}-{losses}"
        
        # Find player with most minutes
        player_stats = PlayerStats.objects.filter(
            player_gamelog__team=team,
            player_gamelog__game__match__season=season
        ).select_related('player_gamelog__player_season__player')
        
        # Aggregate minutes by player
        player_minutes = {}
        for stat in player_stats:
            player = stat.player_gamelog.player_season.player
            player_minutes[player] = player_minutes.get(player, 0) + (stat.time_played or 0)
        
        most_minutes_player = None
        if player_minutes:
            most_minutes_player = max(player_minutes.keys(), key=lambda p: player_minutes[p])
        
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
    
    # Get all-time player stats for this franchise (with same league filtering)
    franchise_team_ids = [ts.id for ts in team_seasons]
    
    if franchise_team_ids:
        all_player_stats = PlayerStats.objects.filter(
            player_gamelog__team__id__in=franchise_team_ids,
            player_gamelog__game__match__week__startswith="Week"  # Regular season only
        ).select_related(
            'player_gamelog__player_season__player'
        )
        
        # Aggregate stats by player across all seasons for this franchise
        player_aggregates = {}
        for stat in all_player_stats:
            player_season = stat.player_gamelog.player_season
            player = player_season.player
            
            if player not in player_aggregates:
                player_aggregates[player] = {
                    'player': player,
                    'time_played': 0,
                    'tags': 0,
                    'pops': 0,
                    'grabs': 0,
                    'drops': 0,
                    'hold': 0,
                    'captures': 0,
                    'prevent': 0,
                    'returns': 0,
                    'powerups': 0,
                }
            
            # Aggregate each stat field
            agg = player_aggregates[player]
            agg['time_played'] += stat.time_played or 0
            agg['tags'] += stat.tags or 0
            agg['pops'] += stat.pops or 0
            agg['grabs'] += stat.grabs or 0
            agg['drops'] += stat.drops or 0
            agg['hold'] += stat.hold or 0
            agg['captures'] += stat.captures or 0
            agg['prevent'] += stat.prevent or 0
            agg['returns'] += stat.returns or 0
            agg['powerups'] += stat.powerups or 0
        
        # Convert time fields and prepare final stats list
        all_time_stats = []
        for agg in player_aggregates.values():
            # Convert time fields
            agg['time_played_min'] = round(agg['time_played'] / 60) if agg['time_played'] else 0
            agg['hold_sec'] = round(agg['hold'] / 60) if agg['hold'] else 0
            agg['prevent_sec'] = round(agg['prevent'] / 60) if agg['prevent'] else 0
            
            all_time_stats.append(agg)
        
        # Sort by time played (descending)
        all_time_stats.sort(key=lambda x: -x['time_played'])
    else:
        all_time_stats = []
    
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
    
    # Calculate box score data
    team1_total_score = 0
    team2_total_score = 0
    team1_total_caps = 0
    team2_total_caps = 0
    
    box_score_games = []
    for game in games:
        # Determine if team1 was red or blue in this game
        team1_is_red = (game.red_team == match.team1)
        team1_is_blue = (game.blue_team == match.team1)
        
        # Determine winner and if OT
        is_overtime = game.outcome in ['OTW', 'OTL']
        if game.team1_score > game.team2_score:
            winner = 'team1'
        elif game.team2_score > game.team1_score:
            winner = 'team2'
        else:
            winner = 'tie'
        
        # Add to totals
        team1_total_score += game.team1_standing_points
        team2_total_score += game.team2_standing_points
        
        # Calculate caps (scores) for the series
        team1_total_caps += game.team1_score
        team2_total_caps += game.team2_score
        
        box_score_games.append({
            'game': game,
            'team1_score': game.team1_score,
            'team2_score': game.team2_score,
            'team1_is_red': team1_is_red,
            'team1_is_blue': team1_is_blue,
            'winner': winner,
            'is_overtime': is_overtime,
        })
    
    # Determine match winner
    if team1_total_score > team2_total_score:
        match_winner = 'team1'
    elif team2_total_score > team1_total_score:
        match_winner = 'team2'
    else:
        match_winner = 'tie'
    
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
    
    # Get player stats for both teams
    def get_team_stats(team, games_filter):
        player_logs = PlayerGameLog.objects.filter(
            game__in=games_filter,
            team=team
        ).select_related('player_season__player').values(
            'player_season__player__id',
            'player_season__player__name',
            'player_season__playing_as',
        ).annotate(
            time_played=models.Sum('stats__time_played'),
            tags=models.Sum('stats__tags'),
            pops=models.Sum('stats__pops'),
            grabs=models.Sum('stats__grabs'),
            drops=models.Sum('stats__drops'),
            hold=models.Sum('stats__hold'),
            captures=models.Sum('stats__captures'),
            prevent=models.Sum('stats__prevent'),
            returns=models.Sum('stats__returns'),
            powerups=models.Sum('stats__powerups'),
        ).order_by('-time_played')
        
        team_stats = []
        for log in player_logs:
            # Convert time fields from seconds to minutes
            log['time_played_min'] = round(log['time_played'] / 60) if log['time_played'] else 0
            log['hold_sec'] = round(log['hold'] / 60) if log['hold'] else 0
            log['prevent_sec'] = round(log['prevent'] / 60) if log['prevent'] else 0
            team_stats.append(log)
        
        return team_stats
    
    team1_stats = get_team_stats(match.team1, stats_games)
    team2_stats = get_team_stats(match.team2, stats_games)
    
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
    
    return render(req, 'reference/match_view.html', {
        'match': match,
        'season': season,
        'box_score_games': box_score_games,
        'team1_total_score': team1_total_score,
        'team2_total_score': team2_total_score,
        'team1_total_caps': team1_total_caps,
        'team2_total_caps': team2_total_caps,
        'match_winner': match_winner,
        'team1_stats': team1_stats,
        'team2_stats': team2_stats,
        'game_options': game_options,
        'selected_game': selected_game,
        'map_info': map_info,
    })
