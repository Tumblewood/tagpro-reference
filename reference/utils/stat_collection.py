from django.db import models, transaction
from typing import Dict, Tuple
from math import ceil
from ..models import Game, PlayerGameLog, PlayerStats, PlayerRegulationStats, PlayerSeason, Season, TeamSeason, Match, PlayoffSeries
from .data_correction import flip_sides
import tagpro_eu
from django.conf import settings
import os
import sys
import json


STAT_FIELDS = [
    "time_played", "tags", "pops", "grabs", "drops",
    "hold", "captures", "prevent", "returns", "powerups",
    "caps_for", "caps_against", "total_pups_in_game", "grabs_off_handoffs", "caps_off_handoffs",
    "grabs_off_regrab", "caps_off_regrab", "long_holds", "flaccids", "handoffs",
    "good_handoffs", "quick_returns", "returns_in_base", "saves", "key_returns",
    "hold_against", "kept_flags"
]
HELPER_FIELDS = [
    "team", "join_time", "grab_time", "prevent_start_time", "last_return_time",
    "last_hold_end", "handed_off_by", "grabbed_off_regrab"
]
stat_defaults = {
    f: 0
    for f in STAT_FIELDS
}
for f in HELPER_FIELDS:
    stat_defaults[f] = None


# In debug mode, load all league matches upfront
all_league_matches = []
if settings.DEBUG:
    i = 1
    with open("data/downloaded_matches.json") as f:
        all_league_matches += [m for m in tagpro_eu.bulk.load_matches(f)]
    with open("tpl_import/league_maps.json", encoding="utf-8") as f:
        bulk_maps = tagpro_eu.bulk.load_maps(f)
    while True:
        try:
            with open(f"tpl_import/league_matches{i}.json") as f:
                all_league_matches += [m for m in tagpro_eu.bulk.load_matches(f, bulk_maps)]
            i += 1
        except FileNotFoundError:
            break


def load_eu_match_object(game_id: str) -> tagpro_eu.Match:
    relevant_matches = all_league_matches
    if not settings.DEBUG:
        try:
            with open(f"tpl_import/league_matches{ceil(int(game_id) / 500000)}.json") as f1, open("tpl_import/league_maps.json", encoding="utf-8") as f2:
                relevant_matches = [m for m in tagpro_eu.bulk.load_matches(
                    f1,
                    tagpro_eu.bulk.load_maps(f2)
                )]
            with open("data/downloaded_matches.json") as f:
                relevant_matches += [m for m in tagpro_eu.bulk.load_matches(f)] 
        except FileNotFoundError:
            pass
    try:
        m: tagpro_eu.Match = [g for g in relevant_matches if str(g.match_id) == str(game_id)][0]
    except IndexError:
        # if no match found in bulkmatches, download from tagpro.eu
        # when we use download_match, map_id field will not be present, so set it to None
        m: tagpro_eu.Match = tagpro_eu.download_match(game_id)
        m.map_id = None
        m.match_id = game_id
        
        # Save downloaded match to appropriate bulk file
        save_match_to_bulk_file(m)
    return m


def save_match_to_bulk_file(m: tagpro_eu.Match):
    """Save a downloaded match to the appropriate bulk file."""
    try:
        # Read existing bulk file
        with open("data/downloaded_matches.json", "r") as f:
            try:
                bulk_data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                bulk_data = {}
        
        # Add the new match to bulk data
        bulk_data[str(m.match_id)] = m.to_dict()
        bulk_data[str(m.match_id)]['mapId'] = m.map_id
        
        # Write back to file
        with open("data/downloaded_matches.json", "w") as f:
            json.dump(bulk_data, f, separators=(",", ":"))
            
    except Exception as e:
        # Don't fail the whole process if we can't save to bulk file
        print(f"Warning: Could not save match {m.match_id} to bulk file: {e}")
        pass


def parse_stats_from_eu_match(
        m: tagpro_eu.Match,
        stats_count_until: int = 10 * 60
    ) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]], Dict[str, str], Tuple[int, int], Tuple[int, int]]:
    """
    Takes a tagpro_eu.Match and extracts all counting stats into a dict, and all player teams into another dict.
    Dict keys for both tuple members are player usernames from the game, and values are a dict with their counting stats
    and a dict for the team they played on last in the game.
    Returns: (ps, ps_before_ot, team_mapping, score_before_ot, total_score)
    score_before_ot: score at end of regulation (red_score, blue_score)
    total_score: total caps scored during this entire period (red_caps, blue_caps)
    """
    # Locate red and blue flags
    red_flag = None
    blue_flag = None
    for y, row in enumerate(m.map.tiles):
        for x, tile in enumerate(row):
            if tile == tagpro_eu.Tile.flag_red:
                red_flag = (x + 19.5 / 40, y + 19.5 / 40)  # Tiles are 40 pixels wide, so this is the center of the tile
            if tile == tagpro_eu.Tile.flag_blue:
                blue_flag = (x + 19.5 / 40, y + 19.5 / 40)

    last_team_played_for = {
        p.name: None
        for p in m.players
    }
    ps: Dict[str, Dict[str, int]] = {
        p.name: { **stat_defaults }
        for p in m.players
    }
    ps_before_ot = {
        p.name: { **stat_defaults }
        for p in m.players
    }
    snapshotted = False
    score_before_ot = (0, 0)
    total_score = (0, 0)
    for time, event, player in sorted(m.create_timeline()):
        p = ps[player.name]
        time = time.real

        # Take a snapshot of all stats at the end of regulation (10 minutes)
        if time > stats_count_until * 60 and not snapshotted:
            ps_before_ot = { player_name: ps[player_name].copy() for player_name in ps }
            snapshotted = True
            for p2 in ps_before_ot.values():  # don't overwrite value of p
                if p2['join_time'] is not None:
                    p2['time_played'] += time - p2['join_time']

                if p2['prevent_start_time'] is not None:
                    p2['prevent'] += time - p2['prevent_start_time']
                
                if p2['grab_time'] is not None and p2['last_hold_end'] is None:
                    hold_length = time - p2['grab_time']
                    p2['hold'] += hold_length
                    if hold_length > 10 * 60:
                        p2['long_holds'] += 1
                    if hold_length > 5 * 60 and p2['handed_off_by'] is not None:
                        ps_before_ot[p2['handed_off_by']]['good_handoffs'] += 1
                    for p3 in ps_before_ot.values():
                        if p3['team'] is not None and p3['team'] != p2['team']:
                            p3['hold_against'] += hold_length
        
        # Process event
        if event[:4] == "Join":
            p['team'] = event[10:]
            p['join_time'] = time
            last_team_played_for[player.name] = event[10:]
        elif event[:9] == "Game ends":
            # Only add time if we haven't already processed a Leave event for this player
            if p['join_time'] is not None and p['team'] is not None:
                p['time_played'] += time - p['join_time']

            if p['prevent_start_time'] is not None:
                p['prevent'] += time - p['prevent_start_time']
            
            if p['grab_time'] is not None and p['last_hold_end'] is None:
                p['kept_flags'] += 1
                ps_before_ot[player.name]['kept_flags'] += 1  # kept flags count even in OT
                hold_length = time - p['grab_time']
                p['hold'] += hold_length
                if hold_length > 10 * 60:
                    p['long_holds'] += 1
                if hold_length > 5 * 60 and p['handed_off_by'] is not None:
                    ps[p['handed_off_by']]['good_handoffs'] += 1
                for p2 in ps.values():
                    if p2['team'] is not None and p2['team'] != p['team']:
                        p2['hold_against'] += hold_length
        elif event[:5] == "Leave":
            if p['join_time'] is not None and time < m.duration.real:
                p['time_played'] += time - p['join_time']
            
            if p['prevent_start_time'] is not None:
                p['prevent'] += time - p['prevent_start_time']

            if p['grab_time'] is not None and p['last_hold_end'] is None:
                hold_length = time - p['grab_time']
                p['hold'] += hold_length
                if hold_length > 10 * 60:
                    p['long_holds'] += 1
                if hold_length > 5 * 60 and p['handed_off_by'] is not None:
                    ps[p['handed_off_by']]['good_handoffs'] += 1
                for p2 in ps.values():
                    if p2['team'] is not None and p2['team'] != p['team']:
                        p2['hold_against'] += hold_length
                p['last_hold_end'] = time
            
            p['join_time'] = None
            p['team'] = None
            p['prevent_start_time'] = None
            p['handed_off_by'] = None
            p['grabbed_off_regrab'] = None
        elif event[:7] == "Capture":
            p['captures'] += 1
            
            # If the match was paused and resumed, stats_count_until should be <600
            # and we should only count until the pause. Otherwise, count every cap.
            if time <= stats_count_until * 60 or stats_count_until >= 600:
                if p['team'] == m.team_red.name:
                    total_score = (total_score[0] + 1, total_score[1])
                else:
                    total_score = (total_score[0], total_score[1] + 1)
            
            if time <= stats_count_until * 60:
                if p['team'] == m.team_red.name:
                    score_before_ot = (score_before_ot[0] + 1, score_before_ot[1])
                else:
                    score_before_ot = (score_before_ot[0], score_before_ot[1] + 1)

            if p['handed_off_by'] is not None:
                ps[p['handed_off_by']]['good_handoffs'] += 1
                p['caps_off_handoffs'] += 1
            if p['grabbed_off_regrab']:
                p['caps_off_regrab'] += 1

            hold_length = time - p['grab_time']
            p['hold'] += hold_length

            if hold_length > 10 * 60:
                p['long_holds'] += 1
            
            for p2 in ps.values():
                if p2['team'] is not None and p2['team'] != p['team']:
                    p2['hold_against'] += time - p['grab_time']
            
            p['last_hold_end'] = time
            p['handed_off_by'] = None
            p['grabbed_off_regrab'] = None

            for p2 in ps.values():
                if p2['team'] is not None:
                    if p2['team'] == p['team']:
                        p2['caps_for'] += 1
                        if p2['last_return_time'] is not None and time - p2['last_return_time'] < 2 * 60:
                            p2['key_returns'] += 1
                    else:
                        p2['caps_against'] += 1
        elif event == "Grab Opponent flag":
            p['grabs'] += 1
            p['grab_time'] = time
            p['last_hold_end'] = None

            # Check whether the grab was from regrab or a handoff
            for p2_name, p2 in ps.items():
                if p2['team'] == p['team'] and p2['last_hold_end'] is not None:
                    time_since_drop = time - p2['last_hold_end']
                    last_hold_length = p2['last_hold_end'] - p2['grab_time']
                    if time_since_drop < 2 * 60 and last_hold_length < 3 * 60:
                        p2['handoffs'] += 1
                        p['grabs_off_handoffs'] += 1
                        p['handed_off_by'] = p2_name
                    elif time_since_drop < 2 * 60:
                        p['grabs_off_regrab'] += 1
                        p['grabbed_off_regrab'] = True
        elif event == "Drop Temporary flag":
            # This happens when a player grabs and gets popped in the same tick (usually by a TagPro)
            p['grabs'] += 1
            p['drops'] += 1
            p['pops'] += 1
            p['flaccids'] += 1  # only log flaccids for drops, not caps or end of game

            p['grab_time'] = time
            p['last_hold_end'] = time
            p['grabbed_off_regrab'] = None
            p['handed_off_by'] = None
        elif event == "Drop Opponent flag":
            p['drops'] += 1
            p['pops'] += 1

            hold_length = time - p['grab_time']
            p['hold'] += hold_length

            if hold_length > 10 * 60:
                p['long_holds'] += 1
            
            if hold_length > 5 * 60 and p['handed_off_by'] is not None:
                ps[p['handed_off_by']]['good_handoffs'] += 1
            
            if hold_length < 2 * 60:
                p['flaccids'] += 1  # only log flaccids for drops, not caps or end of game
            
            for p2 in ps.values():
                if p2['team'] is not None and p2['team'] != p['team']:
                    p2['hold_against'] += hold_length

            p['last_hold_end'] = time
            p['grabbed_off_regrab'] = None
            p['handed_off_by'] = None
        elif event[:3] == "Pop":
            p['pops'] += 1
        elif event[:3] == "Tag":
            p['tags'] += 1
        elif event[:6] == "Return":
            p['returns'] += 1
            p['tags'] += 1
            p['last_return_time'] = time

            for p2_name, p2 in ps.items():
                if p2['team'] != p['team'] and p2['last_hold_end'] == time:
                    hold_length = p2['last_hold_end'] - p2['grab_time']
                    if hold_length < 2 * 60:
                        p['quick_returns'] += 1
                    try:
                        splat = [s for s in m.splats if s.time.real == time and s.player.name == p2_name][0]
                    except IndexError:
                        continue  # NO idea why but this happens once in a blue moon (e.g., match 3676097)
                    is_red_team = p['team'] == m.team_red.name
                    if is_red_team:
                        own_flag = red_flag
                        enemy_flag = blue_flag
                    else:
                        own_flag = blue_flag
                        enemy_flag = red_flag
                    distance_from_own_flag = ((splat.x / 40 - own_flag[0]) ** 2 + (splat.y / 40 - own_flag[1]) ** 2) ** 0.5
                    distance_from_enemy_flag = ((splat.x / 40 - enemy_flag[0]) ** 2 + (splat.y / 40 - enemy_flag[1]) ** 2) ** 0.5
                    if distance_from_own_flag < 10:
                        p['returns_in_base'] += 1
                    if distance_from_enemy_flag < 10:
                        own_team_with_flag = [p3 for p3 in ps.values() if p3['grab_time'] is not None and p3['last_hold_end'] is None]
                        if len(own_team_with_flag) == 0:
                            p['saves'] += 1
        elif event[:8] == "Power up" or event == "Grab duplicate powerup":
            p['powerups'] += 1

            for p2 in ps.values():
                if p2['join_time'] is not None:
                    p2['total_pups_in_game'] += 1
        elif event[:16] == "Start preventing":
            p['prevent_start_time'] = time
        elif event[:15] == "Stop preventing":
            if p['prevent_start_time'] is None:
                continue  # happens when someone disconnects in same tick as prevent end
            p['prevent'] += time - p['prevent_start_time']
            p['prevent_start_time'] = None

    # If the game ended in regulation, before-OT stats will be same as full stats
    if not snapshotted:
        ps_before_ot = { player_name: ps[player_name].copy() for player_name in ps }

    return ps, ps_before_ot, last_team_played_for, score_before_ot, total_score


def calculate_multi_half_match_outcome(match):
    """
    Calculate match outcome for multi-half games based on all halves and overtime periods.
    Sets outcomes and standing points for the first half of each game.
    """
    games = match.games.all().order_by('game_in_match')
    
    # Group games by their base game number (G1, G2, etc.)
    game_groups = {}
    for game in games:
        if "Half" in game.game_in_match or "Overtime" in game.game_in_match:
            # Extract base game number (e.g., "Game 1" from "Game 1 Half 1")
            base_game = game.game_in_match.split()[0] + " " + game.game_in_match.split()[1]
            if base_game not in game_groups:
                game_groups[base_game] = []
            game_groups[base_game].append(game)
    
    for base_game, game_list in game_groups.items():
        # Sort by game_in_match to ensure proper order (Half 1, Half 2, Overtime)
        game_list.sort(key=lambda g: g.game_in_match)
        
        # Calculate total scores across all periods
        total_team1_score = sum(g.team1_score for g in game_list)
        total_team2_score = sum(g.team2_score for g in game_list)
        
        # Check if any period had overtime or if there's an explicit Overtime game
        had_ot = any(g.had_ot for g in game_list) or any("Overtime" in g.game_in_match for g in game_list)
        
        # Determine outcome for team1
        if total_team1_score > total_team2_score:
            outcome = "OTW" if had_ot else "W"
            team1_points = 2 if had_ot else 3
            team2_points = 1 if had_ot else 0
        elif total_team2_score > total_team1_score:
            outcome = "OTL" if had_ot else "L"
            team1_points = 1 if had_ot else 0
            team2_points = 2 if had_ot else 3
        else:
            outcome = "T"
            team1_points = 1
            team2_points = 1
        
        # Set outcome on the first half only (where standing points are counted)
        first_half = next((g for g in game_list if "Half 1" in g.game_in_match), None)
        if first_half:
            first_half.outcome = outcome
            first_half.team1_standing_points = team1_points
            first_half.team2_standing_points = team2_points
            first_half.save()

@transaction.atomic
def process_game_stats(game: Game):
    # Get all existing PlayerGameLogs for the game
    players = {
        p.playing_as: p
        for p in PlayerGameLog.objects.filter(game=game)
    }
    
    m, m2 = None, None
    if not game.tagpro_eu:
        return None
    try:
        m: tagpro_eu.Match = load_eu_match_object(game.tagpro_eu)
        if game.resumed_tagpro_eu:
            m2: tagpro_eu.match = load_eu_match_object(game.resumed_tagpro_eu)
    except IndexError:
        # if no tagpro.eu match found in bulkmatches, don't process
        return None

    ps, ps_before_ot, team_mapping, score_before_ot, total_score = parse_stats_from_eu_match(m, game.paused_time or 600)
    
    # For multi-half games, use period scores (total_score) instead of cumulative scores
    team1_is_red = game.red_team == game.match.team1
    if "Half" in game.game_in_match or "Overtime" in game.game_in_match:
        # Use actual caps scored during this period
        game.team1_score = total_score[0] if team1_is_red else total_score[1]
        game.team2_score = total_score[1] if team1_is_red else total_score[0]
        # Check if this period had overtime
        game.had_ot = score_before_ot != total_score
    else:
        # Single game - use match scores
        game.team1_score = m.team_red.score if team1_is_red else m.team_blue.score
        game.team2_score = m.team_blue.score if team1_is_red else m.team_red.score
        # Check if this game had overtime
        went_to_ot = score_before_ot != (m.team_red.score, m.team_blue.score)
        game.had_ot = went_to_ot

    if game.resumed_tagpro_eu:
        ps2, ps2_before_ot, team_mapping2, score2_before_ot, total_score2 = parse_stats_from_eu_match(
            m2,
            stats_count_until=game.resumed_stats_count_until or 0
        )
        is_ot_period = not game.resumed_stats_count_until
        
        # Add stats from the resumed part to the first part
        for p in ps2:
            if p not in ps:
                ps[p] = ps2[p]
                ps_before_ot[p] = ps2_before_ot[p]
            else:
                for stat in STAT_FIELDS:
                    ps[p][stat] = ps[p][stat] + ps2[p][stat]
                    ps_before_ot[p][stat] += ps2_before_ot[p][stat]
            
        for p in team_mapping2:
            team_mapping[p] = team_mapping2[p]
        
        # Update score and overtime tracking for resumed games
        if "Half" in game.game_in_match or "Overtime" in game.game_in_match:
            # Multi-half: add total caps from both periods
            combined_total = (total_score[0] + total_score2[0], total_score[1] + total_score2[1])
            combined_before_ot = (score_before_ot[0] + score2_before_ot[0], score_before_ot[1] + score2_before_ot[1])
            game.team1_score = combined_total[0] if team1_is_red else combined_total[1]
            game.team2_score = combined_total[1] if team1_is_red else combined_total[0]
            game.had_ot = combined_before_ot != combined_total
        else:
            # Single game: handle paused and resumed
            if is_ot_period:
                game.team1_score += m2.team_red.score if team1_is_red else m2.team_blue.score
                game.team2_score += m2.team_blue.score if team1_is_red else m2.team_red.score
            else:
                # if not OT period, score at start of 2nd game should be what it was when 1st was paused
                game.team1_score = m2.team_red.score if team1_is_red else m2.team_blue.score
                game.team2_score = m2.team_blue.score if team1_is_red else m2.team_red.score
            
            went_to_ot = is_ot_period or\
                score_before_ot[0] + score2_before_ot[0] == score_before_ot[1] + score2_before_ot[1]
            game.had_ot = went_to_ot

    # For multi-half games, don't set outcome until after all halves are added
    if "Half" in game.game_in_match or "Overtime" in game.game_in_match:
        game.outcome = None
        game.team1_standing_points = 0
        game.team2_standing_points = 0
    else:
        # Single game logic
        if game.team1_score > game.team2_score:
            if game.had_ot:
                game.outcome = "OTW"
                game.team1_standing_points = 2
                game.team2_standing_points = 1
            else:
                game.outcome = "W"
                game.team1_standing_points = 3
                game.team2_standing_points = 0
        elif game.team2_score > game.team1_score:
            if game.had_ot:
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

    game.save()

    # Add player stats to the gamelog
    for p in players:
        # Set the player's team for that game
        if team_mapping[p] == m.team_red.name:
            players[p].team = game.match.team1 if team1_is_red else game.match.team2
        elif team_mapping[p] == m.team_blue.name:
            players[p].team = game.match.team2 if team1_is_red else game.match.team1
        else:
            raise Exception("Player {p} has no team")
        players[p].save()

        # Get or create the object for their stats (for both full game and regulation)
        player_stat_defaults = {
            stat: ps[p][stat]
            for stat in STAT_FIELDS
        }
        player_regulation_stat_defaults = {
            stat: ps_before_ot[p][stat]
            for stat in STAT_FIELDS
        }
        game_stats, _ = PlayerStats.objects.update_or_create(
            player_gamelog=players[p],
            defaults=player_stat_defaults
        )
        regulation_game_stats, _ = PlayerRegulationStats.objects.update_or_create(
            player_gamelog=players[p],
            defaults=player_regulation_stat_defaults
        )
        game_stats.save()
        regulation_game_stats.save()


def aggregate_stats(pgs: models.QuerySet[PlayerStats]) -> Dict[str, int]:
    """
    Return a dict usable as default for a PlayerGameStats model where the values are the totals of all
    the stats in the records in pgs.
    """
    aggregate_fields = {
        f'{field}_sum': models.Sum(field) for field in STAT_FIELDS
    }
    totals = pgs.aggregate(**aggregate_fields)
    return {
        key.replace('_sum', ''): value for key, value in totals.items()
    }


def rank_by_standing_points(teams_data):
    """Rank teams by standing points, then apply head-to-head tiebreaker"""
    teams_data.sort(key=lambda x: -x['standing_points'])
    
    result = []
    i = 0
    while i < len(teams_data):
        current_points = teams_data[i]['standing_points']
        tied_group = []
        while i < len(teams_data) and teams_data[i]['standing_points'] == current_points:
            tied_group.append(teams_data[i])
            i += 1
        
        if len(tied_group) > 1:
            tied_group = rank_by_head_to_head(tied_group)
        result.extend(tied_group)
    
    return result


def rank_by_head_to_head(teams_data):
    """Rank teams by head-to-head win percentage (standing points earned / total possible)"""
    if len(teams_data) <= 1:
        return teams_data
    
    # Calculate h2h win percentage for each team against other teams in this group
    for team_data in teams_data:
        tied_team_ids = [t['team'].id for t in teams_data if t != team_data]
        team_h2h_points = 0
        total_h2h_points = 0
        
        for opp_id in tied_team_ids:
            if opp_id in team_data['head_to_head']:
                team_h2h_points += team_data['head_to_head'][opp_id]['team_standing_points']
                total_h2h_points += team_data['head_to_head'][opp_id]['total_standing_points']
        
        h2h_win_pct = team_h2h_points / total_h2h_points if total_h2h_points > 0 else 0
        team_data['_h2h_win_pct'] = h2h_win_pct
    
    teams_data.sort(key=lambda x: -x['_h2h_win_pct'])
    
    result = []
    i = 0
    while i < len(teams_data):
        current_pct = teams_data[i]['_h2h_win_pct']
        tied_group = []
        while i < len(teams_data) and teams_data[i]['_h2h_win_pct'] == current_pct:
            tied_group.append(teams_data[i])
            i += 1
        
        if len(tied_group) > 1:
            tied_group = rank_by_common_opponents_record(tied_group)
        result.extend(tied_group)
    
    return result


def rank_by_common_opponents_record(teams_data):
    """Rank teams by record against common opponents"""
    if len(teams_data) <= 1:
        return teams_data
    
    # Find common opponents (teams that ALL teams in tied group have played)
    all_opponents = set(teams_data[0]['head_to_head'].keys())
    for team_data in teams_data[1:]:
        all_opponents &= set(team_data['head_to_head'].keys())
    
    # Remove tied teams from common opponents
    tied_team_ids = {t['team'].id for t in teams_data}
    common_opponents = all_opponents - tied_team_ids
    
    if not common_opponents:
        return rank_by_common_opponents_cap_diff(teams_data)  # Skip to next tiebreaker
    
    # Calculate win percentage against common opponents
    for team_data in teams_data:
        common_team_points = 0
        common_total_points = 0
        
        for opp_id in common_opponents:
            common_team_points += team_data['head_to_head'][opp_id]['team_standing_points']
            common_total_points += team_data['head_to_head'][opp_id]['total_standing_points']
        
        common_win_pct = common_team_points / common_total_points if common_total_points > 0 else 0
        team_data['_common_win_pct'] = common_win_pct
    
    teams_data.sort(key=lambda x: -x['_common_win_pct'])
    
    result = []
    i = 0
    while i < len(teams_data):
        current_pct = teams_data[i]['_common_win_pct']
        tied_group = []
        while i < len(teams_data) and teams_data[i]['_common_win_pct'] == current_pct:
            tied_group.append(teams_data[i])
            i += 1
        
        if len(tied_group) > 1:
            tied_group = rank_by_common_opponents_cap_diff(tied_group)
        result.extend(tied_group)
    
    return result


def rank_by_common_opponents_cap_diff(teams_data):
    """Rank teams by cap differential against common opponents"""
    if len(teams_data) <= 1:
        return teams_data
    
    # Find common opponents 
    all_opponents = set(teams_data[0]['head_to_head'].keys())
    for team_data in teams_data[1:]:
        all_opponents &= set(team_data['head_to_head'].keys())
    
    tied_team_ids = {t['team'].id for t in teams_data}
    common_opponents = all_opponents - tied_team_ids
    
    if not common_opponents:
        return rank_by_cap_differential(teams_data)  # Skip to next tiebreaker
    
    # Calculate cap differential against common opponents
    for team_data in teams_data:
        common_caps_for = sum(team_data['head_to_head'][opp_id]['caps_for'] for opp_id in common_opponents)
        common_caps_against = sum(team_data['head_to_head'][opp_id]['caps_against'] for opp_id in common_opponents)
        common_cap_diff = common_caps_for - common_caps_against
        
        team_data['_common_cap_diff'] = common_cap_diff
    
    teams_data.sort(key=lambda x: -x['_common_cap_diff'])
    
    result = []
    i = 0
    while i < len(teams_data):
        current_diff = teams_data[i]['_common_cap_diff']
        tied_group = []
        while i < len(teams_data) and teams_data[i]['_common_cap_diff'] == current_diff:
            tied_group.append(teams_data[i])
            i += 1
        
        if len(tied_group) > 1:
            tied_group = rank_by_cap_differential(tied_group)
        result.extend(tied_group)
    
    return result


def rank_by_cap_differential(teams_data):
    """Rank teams by total cap differential"""
    if len(teams_data) <= 1:
        return teams_data
    
    teams_data.sort(key=lambda x: -x['cap_differential'])
    
    result = []
    i = 0
    while i < len(teams_data):
        current_diff = teams_data[i]['cap_differential']
        tied_group = []
        while i < len(teams_data) and teams_data[i]['cap_differential'] == current_diff:
            tied_group.append(teams_data[i])
            i += 1
        
        if len(tied_group) > 1:
            tied_group = rank_by_total_caps(tied_group)
        result.extend(tied_group)
    
    return result


def rank_by_total_caps(teams_data):
    """Rank teams by total caps scored (final tiebreaker)"""
    teams_data.sort(key=lambda x: -x['total_caps'])
    return teams_data


def set_multi_half_outcomes(match: Match):
    games = Game.objects.filter(match=match).order_by("game_in_match")
    is_regular_season = match.get_playoff_series() is None
    half1 = None
    team1_total_score = 0
    team2_total_score = 0
    has_ot = False

    def save_half1():
        if half1 is not None:
            if team1_total_score > team2_total_score:
                if not has_ot:
                    half1.outcome = "W"
                    half1.team1_standing_points = 3 if is_regular_season else 1
                    half1.team2_standing_points = 0
                else:
                    half1.outcome = "OTW"
                    half1.team1_standing_points = 2 if is_regular_season else 1
                    half1.team2_standing_points = 1 if is_regular_season else 0
            elif team2_total_score > team1_total_score:
                if not has_ot:
                    half1.outcome = "L"
                    half1.team1_standing_points = 0
                    half1.team2_standing_points = 3 if is_regular_season else 1
                else:
                    half1.outcome = "OTL"
                    half1.team1_standing_points = 1 if is_regular_season else 0
                    half1.team2_standing_points = 2 if is_regular_season else 1
            else:
                half1.outcome = "T"
                half1.team1_standing_points = 1 if is_regular_season else 0
                half1.team2_standing_points = 1 if is_regular_season else 0
            half1.save()
    
    for g in games:
        if "Half 1" in g.game_in_match:
            save_half1()
            half1 = g
            team1_total_score = g.team1_score
            team2_total_score = g.team2_score
            has_ot = False
        else:
            team1_total_score += g.team1_score
            team2_total_score += g.team2_score
            if "Overtime" in g.game_in_match or g.had_ot:
                has_ot = True
    
    save_half1()

def update_standings(season: Season):
    """
    Calculate and update seed and playoff_finish for all teams in a season.
    """
    teams = TeamSeason.objects.filter(season=season)

    for m in Match.objects.filter(season=season):
        set_multi_half_outcomes(m)
    
    # Calculate standings data for each team
    standings_data = []
    for team in teams:
        # Get all regular season games for the team
        team_games = Game.objects.filter(
            models.Q(red_team=team) | models.Q(blue_team=team),
            match__season=season,
            match__week__startswith="Week"
        )
        
        standing_points = 0
        caps_for = 0
        caps_against = 0
        head_to_head = {}  # opponent_id -> {'team_standing_points': int, 'total_standing_points': int, 'caps_for': int, 'caps_against': int}
        
        for game in team_games:
            is_team1 = (team == game.match.team1)
            opponent = game.match.team2 if is_team1 else game.match.team1
            
            if is_team1:
                team_standing_points = game.team1_standing_points or 0
                opponent_standing_points = game.team2_standing_points or 0
                team_caps = game.team1_score
                opponent_caps = game.team2_score
            else:
                team_standing_points = game.team2_standing_points or 0
                opponent_standing_points = game.team1_standing_points or 0
                team_caps = game.team2_score
                opponent_caps = game.team1_score
            
            standing_points += team_standing_points
            caps_for += team_caps
            caps_against += opponent_caps
            
            # Track head-to-head records
            if opponent.id not in head_to_head:
                head_to_head[opponent.id] = {'team_standing_points': 0, 'total_standing_points': 0, 'caps_for': 0, 'caps_against': 0}
            
            h2h = head_to_head[opponent.id]
            h2h['caps_for'] += team_caps
            h2h['caps_against'] += opponent_caps
            h2h['team_standing_points'] += team_standing_points
            h2h['total_standing_points'] += team_standing_points + opponent_standing_points
        
        standings_data.append({
            'team': team,
            'standing_points': standing_points,
            'cap_differential': caps_for - caps_against,
            'total_caps': caps_for,
            'head_to_head': head_to_head,
        })
    
    # Apply NALTP tiebreakers
    standings_data = rank_by_standing_points(standings_data)
    
    # Assign seeds and update teams
    for i, team_data in enumerate(standings_data):
        team = team_data['team']
        team.seed = i + 1
        
        # Calculate playoff finishes
        has_playoffs = PlayoffSeries.objects.filter(match__season=season).exclude(winner__isnull=True).exists()
        if not has_playoffs:
            playoff_finish = "—"
        else:
            # Check if team played in any playoff series
            playoff_matches = Match.objects.filter(
                season=season,
                playoff_series__isnull=False
            ).filter(
                models.Q(team1=team) | models.Q(team2=team)
            ).order_by('date')
            
            if not playoff_matches.exists():
                playoff_finish = "Missed playoffs"
            else:
                # Find their final result
                last_loss_week = None
                last_win_week = None
                
                for match in playoff_matches:
                    series = match.playoff_series
                    if series and series.winner:
                        if series.winner == team:
                            last_win_week = match.week
                        else:
                            # They lost this series
                            if last_loss_week is None:  # First loss we encounter (most recent)
                                last_loss_week = match.week
                
                # Check if they won the championship
                final_names = ['Super Ball', 'Muper Ball', 'Nuper Ball', 'Buper Ball']
                if last_win_week in final_names:
                    playoff_finish = "Won championship"
                elif last_loss_week:
                    playoff_finish = f"Lost {last_loss_week}"
                elif last_win_week:
                    playoff_finish = f"Won {last_win_week}"
                else:
                    playoff_finish = "Missed playoffs"
        
        team.playoff_finish = playoff_finish
        team.save()


def calculate_blowout_multiplier(cap_differential: int) -> float:
    """
    Calculate the blowout adjustment multiplier for a game.

    The blowout-adjusted cap differential (BACD) is calculated as:
    - First 3 caps count fully (1.0 each)
    - 4th cap counts as 0.8
    - 5th cap counts as 0.6
    - 6th through 9th caps count as 0.4
    - Further caps count as 0.2

    The multiplier is BACD / actual cap differential.
    """
    if cap_differential == 0:
        return 1.0

    abs_cd = abs(cap_differential)
    
    if abs_cd <= 3:
        bacd = abs_cd
    elif abs_cd == 4:
        bacd = 3.8
    elif abs_cd == 5:
        bacd = 4.4
    elif abs_cd <= 9:
        bacd = 2.4 + 0.4 * abs_cd
    else:
        bacd = 4.2 + 0.2 * abs_cd

    return bacd / abs_cd


@transaction.atomic
def calculate_scar(season: Season):
    """
    Calculate OSCAR and DSCAR for all players in a season.

    OSCAR = 0.015 * hold (in seconds) + 0.7 * caps + 0.125 * pups + 0.025 * non-return tags
    DSCAR = 0.005 * prev (in seconds) + 0.1 * returns + 0.1 * returns in base - 0.01 * hold against (in seconds) + 0.125 * pups + 0.025 * non-return tags - 0.05 * non-drop pops

    Process:
    1. Calculate raw OSCAR and DSCAR
    2. Apply blowout multiplier
    3. Normalize to league average (minutes-weighted average = 0)
    4. Apply game-level regression so oscar + dscar = half the BACD
    5. Add 0.035 * minutes * blowout_multiplier to each player's OSCAR and DSCAR
    """
    # Get all regulation stats for the season
    regulation_stats = PlayerRegulationStats.objects.filter(
        player_gamelog__game__match__season=season
    ).select_related('player_gamelog__game__match')

    # Step 1: Calculate raw OSCAR and DSCAR, apply blowout multiplier
    league_oscar_total = 0
    league_dscar_total = 0
    league_minutes_total = 0

    for stat in regulation_stats:
        game = stat.player_gamelog.game
        player_team = stat.player_gamelog.team
        is_team1 = (player_team == game.match.team1)

        # Calculate cap differential and blowout multiplier
        if is_team1:
            cap_differential = game.team1_score - game.team2_score
        else:
            cap_differential = game.team2_score - game.team1_score

        blowout_multiplier = calculate_blowout_multiplier(cap_differential)

        # Convert time from ticks to get values for calculations
        hold_seconds = (stat.hold or 0) / 60  # Convert from ticks to seconds
        prevent_seconds = (stat.prevent or 0) / 60
        hold_against_seconds = (stat.hold_against or 0) / 60
        time_played_minutes = (stat.time_played or 0) / 3600

        # Calculate non-return tags and non-drop pops
        non_return_tags = (stat.tags or 0) - (stat.returns or 0)
        non_drop_pops = (stat.pops or 0) - (stat.drops or 0)

        # OSCAR formula (raw)
        oscar = (
            0.015 * hold_seconds +
            0.7 * (stat.captures or 0) +
            0.15 * (stat.powerups or 0) +
            0.025 * non_return_tags
        )

        # DSCAR formula (raw)
        dscar = (
            0.005 * prevent_seconds +
            0.1 * (stat.returns or 0) +
            0.1 * (stat.returns_in_base or 0) +
            0.15 * (stat.powerups or 0) +
            0.025 * non_return_tags -
            0.05 * non_drop_pops
        )

        # Apply blowout multiplier
        oscar_ba = oscar * blowout_multiplier
        dscar_ba = dscar * blowout_multiplier

        # Store values temporarily
        stat._oscar_ba = oscar_ba
        stat._dscar_ba = dscar_ba
        stat._time_played_minutes = time_played_minutes
        stat._blowout_multiplier = blowout_multiplier

        # Accumulate league totals
        adjusted_minutes = time_played_minutes * blowout_multiplier
        league_oscar_total += oscar_ba
        league_dscar_total += dscar_ba
        league_minutes_total += adjusted_minutes

    # Step 2: Normalize to league average (minutes-weighted average = 0)
    if league_minutes_total > 0:
        league_oscar_per_minute = league_oscar_total / league_minutes_total
        league_dscar_per_minute = league_dscar_total / league_minutes_total

        for stat in regulation_stats:
            adjusted_minutes = stat._time_played_minutes * stat._blowout_multiplier
            stat._oscar_normalized = stat._oscar_ba - (league_oscar_per_minute * adjusted_minutes)
            stat._dscar_normalized = stat._dscar_ba - (league_dscar_per_minute * adjusted_minutes)

    # Step 3: Group stats by game and apply game-level regression
    stats_by_game = {}
    for stat in regulation_stats:
        game_id = stat.player_gamelog.game.id
        if game_id not in stats_by_game:
            stats_by_game[game_id] = []
        stats_by_game[game_id].append(stat)

    for game_id, game_stats in stats_by_game.items():
        game = game_stats[0].player_gamelog.game

        # Calculate team totals for normalized oscar + dscar
        team1_normalized_total = 0
        team2_normalized_total = 0
        team1_minutes_total = 0
        team2_minutes_total = 0

        for stat in game_stats:
            player_team = stat.player_gamelog.team
            is_team1 = (player_team == game.match.team1)

            combined = stat._oscar_normalized + stat._dscar_normalized
            adjusted_minutes = stat._time_played_minutes * stat._blowout_multiplier

            if is_team1:
                team1_normalized_total += combined
                team1_minutes_total += adjusted_minutes
            else:
                team2_normalized_total += combined
                team2_minutes_total += adjusted_minutes

        # Calculate BACD (blowout-adjusted cap differential)
        cap_diff = game.team1_score - game.team2_score
        blowout_mult = calculate_blowout_multiplier(cap_diff)
        bacd = cap_diff * blowout_mult

        # Target for each team: half the BACD
        team1_target = bacd / 2
        team2_target = -bacd / 2  # Other team gets negative

        # Calculate how much to add to each team (distributed by minutes)
        team1_adjustment_total = team1_target - team1_normalized_total
        team2_adjustment_total = team2_target - team2_normalized_total

        # Calculate per-minute adjustment for each team
        team1_adjustment_per_minute = team1_adjustment_total / team1_minutes_total if team1_minutes_total > 0 else 0
        team2_adjustment_per_minute = team2_adjustment_total / team2_minutes_total if team2_minutes_total > 0 else 0

        # Step 4: Apply regression and add baseline
        for stat in game_stats:
            player_team = stat.player_gamelog.team
            is_team1 = (player_team == game.match.team1)

            # Calculate adjustment proportional to minutes
            adjustment_per_minute = team1_adjustment_per_minute if is_team1 else team2_adjustment_per_minute
            adjusted_minutes = stat._time_played_minutes * stat._blowout_multiplier
            adjustment = adjustment_per_minute * adjusted_minutes

            # Apply regression by adding adjustment to both oscar and dscar equally
            # (split the adjustment 50/50 between oscar and dscar)
            oscar_regressed = stat._oscar_normalized + (adjustment / 2)
            dscar_regressed = stat._dscar_normalized + (adjustment / 2)

            # Add 0.035 * minutes * blowout_multiplier to both
            baseline = 0.035 * stat._time_played_minutes * stat._blowout_multiplier

            stat.oscar = oscar_regressed + baseline
            stat.dscar = dscar_regressed + baseline

            # Clean up temporary attributes
            del stat._oscar_ba
            del stat._dscar_ba
            del stat._oscar_normalized
            del stat._dscar_normalized
            del stat._time_played_minutes
            del stat._blowout_multiplier

            stat.save()


def get_lowest_seed_from_series(series):
    """Get the lowest (best) seed number from a playoff series and all previous series."""
    if series is None:
        return float('inf')
    
    match = series.match
    team1_seed = match.team1.seed if match.team1.seed else float('inf')
    team2_seed = match.team2.seed if match.team2.seed else float('inf')
    
    # Get lowest seeds from previous series
    team1_prev_lowest = get_lowest_seed_from_series(series.team1_prev_series)
    team2_prev_lowest = get_lowest_seed_from_series(series.team2_prev_series)
    
    return min(team1_seed, team2_seed, team1_prev_lowest, team2_prev_lowest)


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
    
    for m in playoff_matches:
        # Calculate game wins for each team
        team1_wins = 0
        team2_wins = 0
        
        for game in m.games.all():
            if game.outcome in ['W', 'OTW']:
                team1_wins += 1
            elif game.outcome in ['L', 'OTL']:
                team2_wins += 1
        
        # Determine winner (null if tied)
        winner = None
        if team1_wins > team2_wins:
            winner = m.team1
        elif team2_wins > team1_wins:
            winner = m.team2
        
        # Find previous series for each team
        team1_prev_series = PlayoffSeries.objects.filter(
            match__season=season,
            match__date__lt=m.date
        ).filter(
            models.Q(match__team1=m.team1) | models.Q(match__team2=m.team1)
        ).order_by('-match__date').first()
        
        team2_prev_series = PlayoffSeries.objects.filter(
            match__season=season,
            match__date__lt=m.date
        ).filter(
            models.Q(match__team1=m.team2) | models.Q(match__team2=m.team2)
        ).order_by('-match__date').first()

        # If team1's side of the bracket doesn't have a better (lower number) seed
        # than team2's side, swap team1 and team2.
        team1_lowest_seed = get_lowest_seed_from_series(team1_prev_series)
        team2_lowest_seed = get_lowest_seed_from_series(team2_prev_series)
        
        # Also consider the current teams' seeds
        if m.team1.seed:
            team1_lowest_seed = min(team1_lowest_seed, m.team1.seed)
        if m.team2.seed:
            team2_lowest_seed = min(team2_lowest_seed, m.team2.seed)
        
        if team2_lowest_seed < team1_lowest_seed:
            flip_sides(m)
            team1_prev_series, team2_prev_series = team2_prev_series, team1_prev_series
            team1_wins, team2_wins = team2_wins, team1_wins
        
        # Create or update the PlayoffSeries
        playoff_series, created = PlayoffSeries.objects.update_or_create(
            match=m,
            defaults={
                'team1_prev_series': team1_prev_series,
                'team2_prev_series': team2_prev_series,
                'winner': winner,
                'team1_game_wins': team1_wins,
                'team2_game_wins': team2_wins,
            }
        )
