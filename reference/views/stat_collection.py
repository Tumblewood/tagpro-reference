from django.db import models, transaction
from typing import Dict, Tuple
from ..models import Game, PlayerGameLog, PlayerGameStats, PlayerRegulationGameStats, PlayerWeekStats, PlayerSeasonStats, Season
import tagpro_eu


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


with open("data/league_matches.json") as f1, open("data/bulkmaps.json", encoding="utf-8") as f2:
    bulkmatches = [m for m in tagpro_eu.bulk.load_matches(
       f1,
        tagpro_eu.bulk.load_maps(f2)
    )]


def parse_stats_from_eu_match(m: tagpro_eu.Match) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]], Dict[str, str], Tuple[int, int]]:
    """
    Takes a tagpro_eu.Match and extracts all counting stats into a dict, and all player teams into another dict.
    Dict keys for both tuple members are player usernames from the game, and values are a dict with their counting stats
    and a dict for the team they played on last in the game.
    As third return value, returns the score at the end of regulation (10 minutes). As a tuple like (red_score, blue_score).
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
    for time, event, player in sorted(m.create_timeline()):
        p = ps[player.name]
        time = time.real

        # Take a snapshot of all stats at the end of regulation (10 minutes)
        if time > 10 * 60 * 60 and not snapshotted:
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
            if p['join_time'] is not None:
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
            if p['join_time'] is not None:
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
            
            if time <= 10 * 60 * 60:
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
            p['prevent'] += time - p['prevent_start_time']
            p['prevent_start_time'] = None

    return ps, ps_before_ot, last_team_played_for, score_before_ot


@transaction.atomic
def process_game_stats(game: Game):
    # Get all existing PlayerGameLogs for the game
    players = {
        p.playing_as: p
        for p in PlayerGameLog.objects.filter(game=game)
    }
    
    try:
        m: tagpro_eu.Match = [g for g in bulkmatches if g.match_id == str(game.tagpro_eu)][0]
    except IndexError:
        # if no tagpro.eu match found in bulkmatches, don't reprocess
        return None

    ps, ps_before_ot, team_mapping, score_before_ot = parse_stats_from_eu_match(m)
    went_to_ot = score_before_ot != (m.team_red.score, m.team_blue.score)
    
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
        game_stats, _ = PlayerGameStats.objects.update_or_create(
            player_gamelog=players[p],
            defaults=player_stat_defaults
        )
        regulation_game_stats, _ = PlayerRegulationGameStats.objects.update_or_create(
            player_gamelog=players[p],
            defaults=player_regulation_stat_defaults
        )
        game_stats.save()
        regulation_game_stats.save()


def reaggregate_stats(game: Game):
    """Re-aggregate week and season stat totals for all players in the game."""
    for pgl in PlayerGameLog.objects.filter(game=game):
        prgs_this_week = PlayerRegulationGameStats.objects.filter(
            player_gamelog__player_season=pgl.player_season,
            player_gamelog__game__match__week=game.match.week
        )
        player_week_stats, _ = PlayerWeekStats.objects.update_or_create(
            player_season=pgl.player_season,
            week=game.match.week,
            defaults=aggregate_stats(prgs_this_week)
        )
        player_week_stats.save()

        pws_this_season = PlayerWeekStats.objects.filter(
            player_season=pgl.player_season,
            week__startswith="Week"
        )
        player_season_stats, _ = PlayerSeasonStats.objects.update_or_create(
            player_season=pgl.player_season,
            defaults=aggregate_stats(pws_this_season)
        )
        player_season_stats.save()


def aggregate_stats(pgs: models.QuerySet[PlayerGameStats]) -> Dict[str, int]:
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
