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


def update_standings(season: Season):
    """
    Calculate and update seed and playoff_finish for all teams in a season.
    """
    teams = TeamSeason.objects.filter(season=season)
    
    # Calculate standings for each team
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
        head_to_head = {}  # team_id -> (wins, losses, caps_for, caps_against)
        
        for game in team_games:
            is_team1 = (team == game.match.team1)
            opponent = game.match.team2 if is_team1 else game.match.team1
            
            if is_team1:
                team_standing_points = game.team1_standing_points or 0
                team_caps = game.team1_score
                opponent_caps = game.team2_score
            else:
                team_standing_points = game.team2_standing_points or 0
                team_caps = game.team2_score
                opponent_caps = game.team1_score
            
            standing_points += team_standing_points
            caps_for += team_caps
            caps_against += opponent_caps
            
            # Track head-to-head records
            if opponent.id not in head_to_head:
                head_to_head[opponent.id] = {'wins': 0, 'losses': 0, 'caps_for': 0, 'caps_against': 0}
            
            h2h = head_to_head[opponent.id]
            h2h['caps_for'] += team_caps
            h2h['caps_against'] += opponent_caps
            
            if team_standing_points > (game.team2_standing_points if is_team1 else game.team1_standing_points):
                h2h['wins'] += 1
            elif team_standing_points < (game.team2_standing_points if is_team1 else game.team1_standing_points):
                h2h['losses'] += 1
        
        standings_data.append({
            'team': team,
            'standing_points': standing_points,
            'cap_differential': caps_for - caps_against,
            'total_caps': caps_for,
            'head_to_head': head_to_head,
        })
    
    # Sort standings using NALTP tiebreaker rules
    def tiebreaker_sort_key(team_data):
        return (
            -team_data['standing_points'],  # Higher standing points first
            -team_data['cap_differential'], # Higher cap differential first
            -team_data['total_caps']        # Higher total caps first
        )
    
    # For more complex tiebreakers (head-to-head, common opponents), we'll need
    # to implement them when we encounter actual ties. For now, use basic sort.
    standings_data.sort(key=tiebreaker_sort_key)
    
    # Assign seeds
    current_rank = 1
    for i, team_data in enumerate(standings_data):
        if i > 0:
            prev_data = standings_data[i-1]
            # Check if tied with previous team
            if (team_data['standing_points'] == prev_data['standing_points'] and
                team_data['cap_differential'] == prev_data['cap_differential'] and
                team_data['total_caps'] == prev_data['total_caps']):
                # Same rank as previous team
                team_data['seed'] = prev_data['seed']
            else:
                # Next rank (skip if there were ties)
                current_rank = i + 1
                team_data['seed'] = current_rank
        else:
            team_data['seed'] = 1
    
    # Calculate playoff finishes
    has_playoffs = Match.objects.filter(
        season=season,
        playoff_series__isnull=False,
        playoff_series__winner__isnull=False
    ).exists()
    
    for team_data in standings_data:
        team = team_data['team']
        
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
        
        # Update the team
        team.seed = team_data['seed']
        team.playoff_finish = playoff_finish
        team.save()
