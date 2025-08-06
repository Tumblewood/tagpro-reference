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


with open("data/league_matches.json") as f1, open("data/bulkmaps.json", encoding="utf-8") as f2:
    bulkmatches = [m for m in tagpro_eu.bulk.load_matches(
       f1,
        tagpro_eu.bulk.load_maps(f2)
    )]


def process_game_stats(game: Game):
    # Get all existing PlayerGameLogs for the game
    players = {
        p.playing_as: p for p in
        PlayerGameLog.objects.filter(
            game=game
        )
    }
    m: tagpro_eu.Match = [g for g in bulkmatches if g.match_id == str(game.tagpro_eu)][0]

    went_to_ot = False
    for time, desc, p in m.create_timeline():
        # Set all players' team to the team they played on in that game
        if desc[:4] == "Join":
            team = desc[10:]
            players[p.name].team = game.red_team if team == m.team_red.name else game.blue_team
        # If someone
        elif desc[:7] == "Capture" and time.minutes >= 10:
            went_to_ot = True
    
    # Set the winner based on the score
    team1_is_red = game.red_team == game.match.team1
    game.team1_score = m.team_red.score if team1_is_red else m.team_blue.score
    game.team2_score = m.team_blue.score if team1_is_red else m.team_red.score

    if game.team1_score > game.team2_score:
        if went_to_ot:
            game.outcome = "OTW"
            game.team1_standing_points = 2
            game.team2_standing_points = 1
        else:
            game.outcome = "W"
            game.team1_standing_points = 3
            game.team2_standing_points = 0
    elif game.team2_score > game.team1_score:
        if went_to_ot:
            game.outcome = "OTL"
            game.team1_standing_points = 1
            game.team2_standing_points = 2
        else:
            game.outcome = "L"
            game.team1_standing_points = 0
            game.team2_standing_points = 3
    else:
        game.outcome = "T"
        game.team1_standing_points = 1
        game.team2_standing_points = 1

    # Here is where we would set other stats if we were collecting those yet

    game.save()
    for p in players.values():
        p.save()
