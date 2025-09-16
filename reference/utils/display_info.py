from typing import Dict, List, Optional, Union
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import models
from datetime import datetime, date
from ..models import Game, League, PlayerRegulationStats, PlayerSeason, Season, Franchise, Player, PlayerStats, TeamSeason, PlayerGameLog


STAT_FIELDS = [
    'time_played', 'tags', 'pops', 'grabs', 'drops', 'hold', 'captures', 
    'prevent', 'returns', 'powerups', 'caps_for', 'caps_against', 
    'total_pups_in_game', 'grabs_off_handoffs', 'caps_off_handoffs',
    'grabs_off_regrab', 'caps_off_regrab', 'long_holds', 'flaccids',
    'handoffs', 'good_handoffs', 'quick_returns', 'returns_in_base',
    'saves', 'key_returns', 'hold_against', 'kept_flags'
]


def aggregate_player_stats(
    league: Optional[League]=None,
    season: Optional[Season]=None,
    franchise: Optional[Franchise]=None,
    player: Optional[Player]=None,
    week: Optional[str]=None
) -> List[Dict[str, Union[PlayerSeason, int]]]:
    """
    Aggregate player stats from PlayerStats through PlayerGameLog, grouped by PlayerSeason.
    
    Args:
        league: Filter to specific league
        season: Filter to specific season
        franchise: Filter to specific franchise
        player: Filter to specific player
        week: Filter to specific week (can be special values like 'all_regular_season', 'all_playoffs', 'all_season')
    
    Returns:
        List of dictionaries containing aggregated stats for each PlayerSeason
    """
    from django.db import models
    
    # Start with base query
    stats_query = PlayerRegulationStats.objects.select_related(
        'player_gamelog__player_season__player',
        'player_gamelog__player_season__team',
        'player_gamelog__game__match'
    )
    
    # Apply filters
    if player:
        stats_query = stats_query.filter(player_gamelog__player_season__player=player)
    if franchise:
        stats_query = stats_query.filter(player_gamelog__team__franchise=franchise)
    if season:
        stats_query = stats_query.filter(player_gamelog__team__season=season)
    if league:
        stats_query = stats_query.filter(player_gamelog__team__season__league=league)
    
    # Handle week filtering
    if week and week not in ['all_regular_season', 'all_playoffs', 'all_season']:
        stats_query = stats_query.filter(player_gamelog__game__match__week=week)
    elif week == 'all_regular_season':
        stats_query = stats_query.filter(player_gamelog__game__match__week__startswith="Week")
    elif week == 'all_playoffs':
        stats_query = stats_query.exclude(player_gamelog__game__match__week__startswith="Week")
    # 'all_season' doesn't need additional filtering
    
    # Only include regulation games (exclude games on home maps, etc.)
    stats_query = stats_query.filter(player_gamelog__game__non_regulation=False)
    
    # Create aggregation dictionary dynamically
    aggregation_dict = {field: models.Sum(field) for field in STAT_FIELDS}
    
    # Group by PlayerSeason and aggregate
    aggregated_stats = stats_query.values(
        'player_gamelog__player_season',
        'player_gamelog__player_season__player',
        'player_gamelog__player_season__team',
        'player_gamelog__player_season__playing_as'
    ).annotate(**aggregation_dict).order_by('-time_played')
    
    # Convert to list of dictionaries with proper objects
    result = []
    for stat in aggregated_stats:
        player_season = PlayerSeason.objects.get(id=stat['player_gamelog__player_season'])
        
        stat_dict = {
            'player_season': player_season,
            'player': player_season.player,
            'team': player_season.team,
            'playing_as': stat['player_gamelog__player_season__playing_as'],
        }
        
        # Add all the stat fields, converting time fields to readable units
        for field in STAT_FIELDS:
            raw_value = stat.get(field) or 0
            
            # Convert time fields to more usable units, otherwise use raw value
            if field == 'time_played':
                stat_dict['time_played_min'] = round(raw_value / 3600) if raw_value else 0
            elif field == 'hold':
                stat_dict['hold_sec'] = round(raw_value / 60) if raw_value else 0
            elif field == 'prevent':
                stat_dict['prevent_sec'] = round(raw_value / 60) if raw_value else 0
            elif field == 'hold_against':
                stat_dict['hold_against_sec'] = round(raw_value / 60) if raw_value else 0
            else:
                stat_dict[field] = raw_value
        
        result.append(stat_dict)
    
    return result


def calculate_rate_stats(player_stats: List[Dict]) -> List[Dict]:
    """Calculate rate stats and add them to player stats dictionaries."""
    for player_stat in player_stats:
        minutes = player_stat['time_played_min']
        grabs = player_stat['grabs']
        captures = player_stat['captures']
        hold_sec = player_stat['hold_sec']
        tags = player_stat['tags']
        pops = player_stat['pops']
        returns = player_stat['returns']
        prevent_sec = player_stat['prevent_sec']
        hold_against_sec = player_stat['hold_against_sec']
        handoffs = player_stat['handoffs']
        good_handoffs = player_stat['good_handoffs']
        flaccids = player_stat['flaccids']
        caps_off_regrab = player_stat['caps_off_regrab']
        quick_returns = player_stat['quick_returns']
        returns_in_base = player_stat['returns_in_base']
        caps_for = player_stat['caps_for']
        caps_against = player_stat['caps_against']
        drops = player_stat['drops']
        powerups = player_stat['powerups']
        total_pups_in_game = player_stat['total_pups_in_game']
        
        # Add calculated rate stats to player_stat dict
        player_stat['gpm'] = round(grabs / minutes, 2) if minutes > 0 else 0
        player_stat['cpm'] = round(captures / minutes, 2) if minutes > 0 else 0
        player_stat['hpm'] = round(hold_sec / minutes, 2) if minutes > 0 else 0
        player_stat['tpm'] = round(tags / minutes, 2) if minutes > 0 else 0
        player_stat['rpm'] = round(returns / minutes, 2) if minutes > 0 else 0
        player_stat['ppm'] = round(prevent_sec / minutes, 2) if minutes > 0 else 0
        player_stat['ham'] = round(hold_against_sec / minutes, 2) if minutes > 0 else 0
        player_stat['hold_per_grab'] = round(hold_sec / grabs, 2) if grabs > 0 else 0
        player_stat['score_percent'] = round((captures / grabs) * 100, 1) if grabs > 0 else 0
        player_stat['chain_percent'] = round((good_handoffs / handoffs) * 100, 1) if handoffs > 0 else 0
        player_stat['flaccid_percent'] = round((flaccids / grabs) * 100, 1) if grabs > 0 else 0
        player_stat['spark_percent'] = round(((captures - caps_off_regrab) / captures) * 100, 1) if captures > 0 else 0
        player_stat['prevent_per_return'] = round(prevent_sec / returns, 2) if returns > 0 else 0
        player_stat['prevent_per_hold_against'] = round(prevent_sec / hold_against_sec, 2) if hold_against_sec > 0 else 0
        player_stat['rib_percent'] = round((returns_in_base / returns) * 100, 1) if returns > 0 else 0
        player_stat['qr_percent'] = round((quick_returns / returns) * 100, 1) if returns > 0 else 0
        player_stat['plus_minus'] = caps_for - caps_against
        player_stat['kd_ratio'] = round(tags / pops, 2) if pops > 0 else 0
        player_stat['non_return_tags'] = tags - returns
        player_stat['non_drop_pops'] = pops - drops
        player_stat['pup_percent'] = round((powerups / total_pups_in_game) * 100, 1) if total_pups_in_game > 0 else 0
    
    return player_stats


def calculate_match_box_score(match, games, include_details=False):
    """Calculate box score data for a match with its games."""
    team1_total = 0
    team2_total = 0
    team1_total_caps = 0
    team2_total_caps = 0
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
        
        # Track total caps (scores) across all games
        team1_total_caps += team1_score
        team2_total_caps += team2_score
        
        game_result = {
            'team1_score': team1_score,
            'team2_score': team2_score,
            'winner': game_winner,
            'is_overtime': is_overtime,
            'game_number': game.game_in_match
        }
        
        # Add extra details for match_view
        if include_details:
            game_result.update({
                'game': game,
                'team1_is_red': (game.red_team == match.team1),
                'team1_is_blue': (game.blue_team == match.team1)
            })
        
        game_results.append(game_result)
    
    # Determine match winner
    match_winner = "team1" if team1_total > team2_total else "team2" if team2_total > team1_total else "tie"
    
    result = {
        'match': match,
        'games': game_results,
        'team1_total': team1_total,
        'team2_total': team2_total,
        'match_winner': match_winner,
        'is_playoff': is_playoff,
        'has_games': len(games) > 0
    }
    
    # Add cap totals when include_details is True
    if include_details:
        result.update({
            'team1_total_caps': team1_total_caps,
            'team2_total_caps': team2_total_caps,
            'box_score_games': game_results  # Alias for match_view compatibility
        })
    
    return result


def get_match_team_stats(match, team, selected_game='all'):
    """Get player stats for a team in a specific match, with optional game filtering."""
    from django.db import models
    
    if selected_game == 'all':
        # Use aggregate_player_stats for the match week, filtered to team and players who played
        match_games = Game.objects.filter(match=match)
        player_seasons_in_match = PlayerGameLog.objects.filter(
            game__in=match_games,
            team=team
        ).values_list('player_season', flat=True).distinct()
        
        # Get week stats for players who actually played in the match
        week_stats = aggregate_player_stats(season=match.season, week=match.week, franchise=team.franchise)
        
        # Filter to only players who played for this team in this match
        team_stats = []
        for stat in week_stats:
            if stat['player_season'].id in player_seasons_in_match:
                team_stats.append({
                    'player_season__player__id': stat['player'].id,
                    'player_season__player__name': stat['player'].name,
                    'player_season__playing_as': stat['playing_as'],
                    'time_played_min': stat['time_played_min'],
                    'tags': stat['tags'],
                    'pops': stat['pops'],
                    'grabs': stat['grabs'],
                    'drops': stat['drops'],
                    'hold_sec': stat['hold_sec'],
                    'captures': stat['captures'],
                    'prevent_sec': stat['prevent_sec'],
                    'returns': stat['returns'],
                    'powerups': stat['powerups'],
                })
        
        # Sort by time played (descending)
        team_stats.sort(key=lambda x: -x['time_played_min'])
    else:
        # For specific games, aggregate from PlayerGameLog
        try:
            game_number = int(selected_game)
            games_filter = Game.objects.filter(
                match=match,
                game_in_match=f"Game {game_number}"
            )
        except (ValueError, TypeError):
            games_filter = Game.objects.filter(match=match)
        
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
            # Convert time fields to readable units (this is the conversion logic you mentioned)
            team_stats.append({
                'player_season__player__id': log['player_season__player__id'],
                'player_season__player__name': log['player_season__player__name'],
                'player_season__playing_as': log['player_season__playing_as'],
                'time_played_min': round(log['time_played'] / 3600) if log['time_played'] else 0,
                'tags': log['tags'] or 0,
                'pops': log['pops'] or 0,
                'grabs': log['grabs'] or 0,
                'drops': log['drops'] or 0,
                'hold_sec': round(log['hold'] / 60) if log['hold'] else 0,
                'captures': log['captures'] or 0,
                'prevent_sec': round(log['prevent'] / 60) if log['prevent'] else 0,
                'returns': log['returns'] or 0,
                'powerups': log['powerups'] or 0,
            })
    
    return team_stats


def get_team_standings(team: TeamSeason) -> Dict[str, Union[TeamSeason, str, int]]:
    team_games = Game.objects.filter(
        models.Q(red_team=team) | models.Q(blue_team=team),
        match__season=team.season,
        match__week__startswith="Week"
    )
    
    # Initialize counters
    standing_points = 0
    wins = ot_wins = ties = ot_losses = losses = 0
    caps_for = 0
    caps_against = 0
    
    for game in team_games:
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
        
        standing_points += team_standing_points
        caps_for += team_score
        caps_against += opponent_score
        
        if game.outcome:
            if is_team1:
                outcome = game.outcome
            else:
                # Flip the outcome for team2
                outcome_map = {'W': 'L', 'OTW': 'OTL', 'L': 'W', 'OTL': 'OTW', 'T': 'T'}
                outcome = outcome_map.get(game.outcome, game.outcome)
            
            if outcome == "W":
                wins += 1
            elif outcome == "OTW":
                ot_wins += 1
            elif outcome == "T":
                ties += 1
            elif outcome == "OTL":
                ot_losses += 1
            elif outcome == "L":
                losses += 1
        else:
            # Determine by score if outcome not set
            if team_score > opponent_score:
                wins += 1
            elif team_score < opponent_score:
                losses += 1
            else:
                ties += 1
    
    cap_differential = caps_for - caps_against
    record = f"{wins}-{ot_wins}-{ot_losses}-{losses}"
    
    return {
        'team': team,
        'games_played': wins + ot_wins + ties + ot_losses + losses,
        'wins': wins,
        'ot_wins': ot_wins,
        'ties': ties,
        'ot_losses': ot_losses,
        'losses': losses,
        'standing_points': standing_points,
        'record': record,
        'caps_for': caps_for,
        'caps_against': caps_against,
        'cap_differential': cap_differential,
    }
