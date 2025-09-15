from typing import Dict, List, Optional, Union
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import models
from datetime import datetime, date
from ..models import Game, League, PlayerSeason, Season, Franchise, Player, PlayerStats, TeamSeason


def aggregate_player_stats(
    by_player_season=bool,
    league: Optional[League]=None,
    season: Optional[Season]=None,
    franchise: Optional[Franchise]=None,
    player: Optional[Player]=None,
    week: Optional[str]=None
) -> Union[Dict[str, int], List[Dict[str, Union[PlayerSeason, int]]]]:
    """"""
    stats = PlayerStats.objects.all()
    if player:
        stats = stats.filter(player_gamelog__player_season__player=player)
    if week:
        stats = stats.filter(player_gamelog__game__match__week=week)
    if franchise:
        stats = stats.filter(player_gamelog__team__franchise=franchise)
    if season:
        stats = stats.filter(player_gamelog__team__season=season)
    if league:
        stats = stats.filter(player_gamelog__team__season__league=league)
    if by_player_season:
        pass
    else:
        pass


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
