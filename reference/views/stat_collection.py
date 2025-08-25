from django.db import models, transaction
from typing import Dict, Tuple
from ..models import Game, PlayerGameLog, PlayerGameStats, PlayerRegulationGameStats, PlayerSeason, PlayerWeekStats, PlayerSeasonStats, Season, TeamSeason, Match, PlayoffSeries
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


def parse_stats_from_eu_match(
        m: tagpro_eu.Match,
        stats_count_until: int = 10 * 60
    ) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]], Dict[str, str], Tuple[int, int]]:
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
            if p['prevent_start_time'] is None:
                continue  # happens when someone disconnects in same tick as prevent end
            p['prevent'] += time - p['prevent_start_time']
            p['prevent_start_time'] = None

    # If the game ended in regulation, before-OT stats will be same as full stats
    if not snapshotted:
        ps_before_ot = ps

    return ps, ps_before_ot, last_team_played_for, score_before_ot


@transaction.atomic
def process_game_stats(game: Game):
    # Get all existing PlayerGameLogs for the game
    players = {
        p.playing_as: p
        for p in PlayerGameLog.objects.filter(game=game)
    }
    
    m, m2 = None, None
    try:
        m: tagpro_eu.Match = [g for g in bulkmatches if g.match_id == str(game.tagpro_eu)][0]
        if game.resumed_tagpro_eu:
            m2: tagpro_eu.match = [g for g in bulkmatches if g.match_id == str(game.resumed_tagpro_eu)][0]
    except IndexError:
        # if no tagpro.eu match found in bulkmatches, don't process
        return None

    ps, ps_before_ot, team_mapping, score_before_ot = parse_stats_from_eu_match(m, game.paused_time or 600)
    went_to_ot = score_before_ot != (m.team_red.score, m.team_blue.score)
    
    # Set the winner based on the score
    team1_is_red = game.red_team == game.match.team1
    game.team1_score = m.team_red.score if team1_is_red else m.team_blue.score
    game.team2_score = m.team_blue.score if team1_is_red else m.team_red.score

    if game.resumed_tagpro_eu:
        ps2, ps2_before_ot, team_mapping2, score2_before_ot = parse_stats_from_eu_match(
            m2,
            stats_count_until=game.resumed_stats_count_until or 0
        )
        is_ot_period = not game.resumed_stats_count_until
        went_to_ot = is_ot_period or\
            score_before_ot[0] + score2_before_ot[0] == score_before_ot[1] + score2_before_ot[1]
        
        # Add stats from the resumed part to the first part
        for p in ps2:
            if p not in ps:
                ps[p] = ps2[p]
                ps_before_ot[p] = ps2_before_ot[p]
            else:
                for stat in STAT_FIELDS:
                    ps[p][stat] = ps_before_ot[p][stat] + ps2[p][stat]
                    ps_before_ot[p][stat] += ps2_before_ot[p][stat]
            
        for p in team_mapping2:
            team_mapping[p] = team_mapping2[p]
        
        # Update the score
        if is_ot_period:
            game.team1_score += m2.team_red.score if team1_is_red else m2.team_blue.score
            game.team2_score += m2.team_blue.score if team1_is_red else m2.team_red.score
        else:
            # if not OT period, score at start of 2nd game should be what it was when 1st was paused
            game.team1_score = m2.team_red.score if team1_is_red else m2.team_blue.score
            game.team2_score = m2.team_blue.score if team1_is_red else m2.team_red.score

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


def reaggregate_stats(player_season: PlayerSeason):
    """Re-aggregate week and season stat totals for all players in the game."""
    weeks_in_season = Match.objects.filter(
        season=player_season.season
    ).values_list('week', flat=True).distinct()
    for week in weeks_in_season:
        prgs_this_week = PlayerRegulationGameStats.objects.filter(
            player_gamelog__player_season=player_season,
            player_gamelog__game__match__week=week
        )
        player_week_stats, _ = PlayerWeekStats.objects.update_or_create(
            player_season=player_season,
            week=week,
            defaults=aggregate_stats(prgs_this_week)
        )
        player_week_stats.save()

        pws_this_season = PlayerWeekStats.objects.filter(
            player_season=player_season,
            week__startswith="Week"
        )
        player_season_stats, _ = PlayerSeasonStats.objects.update_or_create(
            player_season=player_season,
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
    print(teams_data)
    
    result = []
    i = 0
    while i < len(teams_data):
        current_pct = teams_data[i]['_h2h_win_pct']
        tied_group = []
        while i < len(teams_data) and teams_data[i]['_h2h_win_pct'] == current_pct:
            tied_group.append(teams_data[i])
            i += 1
        
        if len(tied_group) > 1:
            print(tied_group)
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


def update_standings(season: Season):
    """
    Calculate and update seed and playoff_finish for all teams in a season.
    """
    teams = TeamSeason.objects.filter(season=season)
    
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
            ).order_by('-date')
            
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
