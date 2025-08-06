from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import models
import json
import re
from datetime import datetime, date
from ..models import Season, TeamSeason, Player, PlayerSeason, Match, Game, PlayerGameLog
import tagpro_eu


def homepage(req):
    pass


def search_results(req, query):
    pass


def league_history(req, league_id):
    pass


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
        # Get all games for this team, excluding playoff games
        team_games = Game.objects.filter(
            models.Q(red_team=team) | models.Q(blue_team=team),
            match__season=season
        ).exclude(
            match__playoff_series__isnull=False
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
                elif outcome == 'OTL':
                    ot_losses += 1
                elif outcome == 'L':
                    losses += 1
            else:
                # If no outcome is set, determine by score
                if team_score > opponent_score:
                    wins += 1
                elif team_score < opponent_score:
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
            'Equidistant Eight': 'ZZZZ1',
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
    pass


def season_rosters(req, season_id):
    pass


def player_history(req, player_id):
    pass


def team_season(req, team_id):
    pass


def franchise_history(req, franchise_id):
    pass


def match_view(req, match_id):
    pass


def game_view(req, game_id):
    pass
