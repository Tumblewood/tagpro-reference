import math
import re
from collections import deque
from datetime import date
from functools import lru_cache

from django.db.models import Count, Q, Sum

from ..models import (
    AwardReceived,
    Game,
    PlayerGameLog,
    PlayerRegulationStats,
    PlayoffSeries,
    TeamSeason,
    Transaction,
)

# Placement multipliers for award legacy points
_PLACEMENT_MULTIPLIERS = {1: 1.0, 2: 0.6, 3: 0.4}


def _get_game_prefix(game_in_match):
    """Extract 'Game X' prefix from game_in_match, e.g. 'Game 1 Half 1' -> 'Game 1'."""
    if game_in_match is None:
        return None
    m = re.match(r"(Game \d+)", game_in_match)
    return m.group(1) if m else game_in_match


def _get_playoff_series_and_depths(season):
    """
    Return (all_series, depths) where depths maps series_id -> BFS depth from championship (0).
    Returns ([], {}) if no playoff series or the tree is invalid.
    """
    all_series = list(
        PlayoffSeries.objects.filter(match__season=season).select_related(
            "match__team1", "match__team2", "winner"
        )
    )
    if not all_series:
        return [], {}

    series_ids = {s.id for s in all_series}
    prev_ids = set()
    for s in all_series:
        if s.team1_prev_series_id:
            prev_ids.add(s.team1_prev_series_id)
        if s.team2_prev_series_id:
            prev_ids.add(s.team2_prev_series_id)

    root_ids = series_ids - prev_ids
    if len(root_ids) != 1:
        return None, None  # Invalid tree

    id_to_series = {s.id: s for s in all_series}
    root = id_to_series[next(iter(root_ids))]

    depths = {}
    queue = deque([(root, 0)])
    while queue:
        series, depth = queue.popleft()
        if series.id in depths:
            return None, None  # Cycle
        depths[series.id] = depth
        for prev_id in [series.team1_prev_series_id, series.team2_prev_series_id]:
            if prev_id and prev_id in series_ids:
                queue.append((id_to_series[prev_id], depth + 1))

    if depths.keys() != series_ids:
        return None, None  # Not all series reachable

    return all_series, depths


def _validate_playoff_tree(season):
    all_series, depths = _get_playoff_series_and_depths(season)
    return depths is not None  # {} means no playoffs (valid); None means invalid


@lru_cache(maxsize=None)
def _season_minutes(season_id):
    """
    Return the total regulation regular-season minutes available in a season.
    Computed as max games played by any team × 10 minutes per game.
    Each Game object is always 10 minutes (halves and full games alike).
    OT periods are excluded via non_regulation=False (OT games should be marked non_regulation=True).
    """
    t1_counts = dict(
        Game.objects.filter(
            match__season_id=season_id,
            match__week__startswith="Week",
            non_regulation=False,
        )
        .values("match__team1_id")
        .annotate(cnt=Count("id"))
        .values_list("match__team1_id", "cnt")
    )
    t2_counts = dict(
        Game.objects.filter(
            match__season_id=season_id,
            match__week__startswith="Week",
            non_regulation=False,
        )
        .values("match__team2_id")
        .annotate(cnt=Count("id"))
        .values_list("match__team2_id", "cnt")
    )
    all_team_ids = set(t1_counts.keys()) | set(t2_counts.keys())
    if not all_team_ids:
        return 0
    max_games = max(t1_counts.get(tid, 0) + t2_counts.get(tid, 0) for tid in all_team_ids)
    return max_games * 10


def _roster_bonus(player_season):
    return 5.0 if player_season.team is not None else 0.0


def _rs_tscar(player_season, season):
    agg = PlayerRegulationStats.objects.filter(
        player_gamelog__player_season=player_season,
        player_gamelog__game__match__season=season,
        player_gamelog__game__non_regulation=False,
        player_gamelog__game__match__week__startswith="Week",
    ).aggregate(
        total_time=Sum("time_played"),
        total_oscar=Sum("oscar"),
        total_dscar=Sum("dscar"),
    )

    total_time = agg["total_time"] or 0
    tscar = (agg["total_oscar"] or 0.0) + (agg["total_dscar"] or 0.0)
    minutes_played = total_time / 3600.0

    if minutes_played == 0:
        return 0.0

    season_mins = _season_minutes(season.id)
    if season_mins > 0:
        tscar = tscar * 300 / season_mins

    return tscar


def _playoff_tscar(player_season, season):
    qs = PlayerRegulationStats.objects.filter(
        player_gamelog__player_season=player_season,
        player_gamelog__game__match__season=season,
        player_gamelog__game__non_regulation=False,
    ).exclude(player_gamelog__game__match__week__startswith="Week")

    agg = qs.aggregate(
        total_time=Sum("time_played"),
        total_oscar=Sum("oscar"),
        total_dscar=Sum("dscar"),
    )

    total_time = agg["total_time"] or 0
    tscar = (agg["total_oscar"] or 0.0) + (agg["total_dscar"] or 0.0)
    minutes_played = total_time / 3600.0

    if minutes_played == 0:
        return 0.0

    match_count = (
        qs.values("player_gamelog__game__match").distinct().count()
    )
    cap = 50.0 if match_count == 1 else 100.0

    if minutes_played > cap:
        tscar = tscar * cap / minutes_played

    return tscar


def _award_points(player_season, season):
    awards = AwardReceived.objects.filter(
        player=player_season.player,
        season=season,
        award__legacy_value__isnull=False,
    ).select_related("award")

    best = 0.0
    for ar in awards:
        if "all-star" in ar.award.name.lower():
            multiplier = 1.0
        else:
            multiplier = _PLACEMENT_MULTIPLIERS.get(ar.placement, 0.0)
        points = ar.award.legacy_value * multiplier
        best = max(best, points)

    return best


@lru_cache(maxsize=None)
def _season_sp_game_count(season_id):
    """
    Max number of standing-point-awarding regular-season games any team
    participated in for the season. Used to scale team performance to a
    25-game baseline.
    """
    sp_games = Game.objects.filter(
        match__season_id=season_id,
        match__week__startswith="Week",
        non_regulation=False,
    ).filter(
        Q(team1_standing_points__gt=0) | Q(team2_standing_points__gt=0)
    )
    t1_counts = dict(
        sp_games.values("match__team1_id").annotate(cnt=Count("id")).values_list("match__team1_id", "cnt")
    )
    t2_counts = dict(
        sp_games.values("match__team2_id").annotate(cnt=Count("id")).values_list("match__team2_id", "cnt")
    )
    all_team_ids = set(t1_counts.keys()) | set(t2_counts.keys())
    if not all_team_ids:
        return 0
    return max(t1_counts.get(tid, 0) + t2_counts.get(tid, 0) for tid in all_team_ids)


@lru_cache(maxsize=None)
def _team_rs_tscar(team_id, season_id):
    """Cached: total raw RS TSCAR for all players on a team's roster."""
    agg = PlayerRegulationStats.objects.filter(
        player_gamelog__player_season__team_id=team_id,
        player_gamelog__game__match__season_id=season_id,
        player_gamelog__game__non_regulation=False,
        player_gamelog__game__match__week__startswith="Week",
    ).aggregate(total_oscar=Sum("oscar"), total_dscar=Sum("dscar"))
    return (agg["total_oscar"] or 0.0) + (agg["total_dscar"] or 0.0)


@lru_cache(maxsize=None)
def _team_po_tscar(team_id, season_id):
    """Cached: total raw PO TSCAR for all players on a team's roster."""
    agg = PlayerRegulationStats.objects.filter(
        player_gamelog__player_season__team_id=team_id,
        player_gamelog__game__match__season_id=season_id,
        player_gamelog__game__non_regulation=False,
    ).exclude(
        player_gamelog__game__match__week__startswith="Week"
    ).aggregate(total_oscar=Sum("oscar"), total_dscar=Sum("dscar"))
    return (agg["total_oscar"] or 0.0) + (agg["total_dscar"] or 0.0)


@lru_cache(maxsize=None)
def _season_avg_tc(season_id):
    """Cache avg_tc_rounded per season to avoid repeated DB queries."""
    total_tc = (
        Transaction.objects.filter(
            team__season_id=season_id,
            transaction_type__in=["draft", "prelim"],
        ).aggregate(total=Sum("net_tc_spent"))["total"]
        or 0
    )
    num_teams = TeamSeason.objects.filter(season_id=season_id).count()
    if num_teams == 0 or total_tc == 0:
        return 0
    return math.ceil((total_tc / num_teams) / 50) * 50


def _tc_fraction(player_season, season):
    """Return player_tc / avg_tc_rounded, or 0.0 if no TC data."""
    txn = Transaction.objects.filter(
        player_season=player_season,
        transaction_type__in=["draft", "prelim"],
    ).first()

    if txn is None or txn.net_tc_spent is None:
        return 0.0

    avg_tc_rounded = _season_avg_tc(season.id)
    if avg_tc_rounded == 0:
        return 0.0

    return txn.net_tc_spent / avg_tc_rounded


def _tc_value(player_season, season, tc_fraction=None):
    if tc_fraction is None:
        tc_fraction = _tc_fraction(player_season, season)
    return tc_fraction * 5.0


def _rs_team_performance(player_season, season, tc_fraction=None):
    if tc_fraction is None:
        tc_fraction = _tc_fraction(player_season, season)

    rs_gamelogs = list(
        PlayerGameLog.objects.filter(
            player_season=player_season,
            game__match__season=season,
            game__match__week__startswith="Week",
        ).select_related("game__match", "team")
    )

    processed_groups = set()
    total_sp_earned = 0.0
    total_sp_possible = 0.0

    for pgl in rs_gamelogs:
        game = pgl.game
        match = game.match
        prefix = _get_game_prefix(game.game_in_match)
        group_key = (match.id, prefix)

        if group_key in processed_groups:
            continue
        processed_groups.add(group_key)

        is_team1 = pgl.team_id == match.team1_id

        if prefix is None:
            group_games = Game.objects.filter(match=match, game_in_match__isnull=True)
        else:
            group_games = Game.objects.filter(match=match).filter(
                Q(game_in_match=prefix) | Q(game_in_match__startswith=prefix + " ")
            )

        for g in group_games:
            sp1 = g.team1_standing_points or 0
            sp2 = g.team2_standing_points or 0
            if sp1 + sp2 == 0:
                continue
            total_sp_earned += sp1 if is_team1 else sp2
            total_sp_possible += sp1 + sp2

    raw_score = total_sp_earned - (4.0 / 15.0) * total_sp_possible
    raw_score *= 0.2

    sp_games = _season_sp_game_count(season.id)
    raw_score *= 30.0 / sp_games

    tscar_fraction = 0.0
    if player_season.team is not None:
        team_tscar = _team_rs_tscar(player_season.team.id, season.id)
        if team_tscar > 0:
            player_agg = PlayerRegulationStats.objects.filter(
                player_gamelog__player_season=player_season,
                player_gamelog__game__match__season=season,
                player_gamelog__game__non_regulation=False,
                player_gamelog__game__match__week__startswith="Week",
            ).aggregate(total_oscar=Sum("oscar"), total_dscar=Sum("dscar"))
            player_tscar = (player_agg["total_oscar"] or 0.0) + (player_agg["total_dscar"] or 0.0)
            if player_tscar > 0:
                tscar_fraction = player_tscar / team_tscar

    return raw_score * (0.25 + 0.25 * tc_fraction + 0.75 * tscar_fraction)


def _playoff_team_performance(player_season, season, all_series, depths, tc_fraction=None):
    if tc_fraction is None:
        tc_fraction = _tc_fraction(player_season, season)

    team = player_season.team
    if team is None or not all_series:
        return 0.0

    team_series = [
        s
        for s in all_series
        if s.match and (s.match.team1_id == team.id or s.match.team2_id == team.id)
    ]

    if not team_series:
        return 0.0

    best_depth = min(depths[s.id] for s in team_series if s.id in depths)

    if best_depth == 0:
        champ_series = next(s for s in team_series if depths.get(s.id) == 0)
        base = 20.0 if champ_series.winner_id == team.id else 10.0
    elif best_depth == 1:
        base = 5.0
    else:
        # Depth >= 2: only award if at least one team missed playoffs
        playoff_team_ids = set()
        for s in all_series:
            if s.match:
                playoff_team_ids.add(s.match.team1_id)
                playoff_team_ids.add(s.match.team2_id)

        all_team_ids = set(
            TeamSeason.objects.filter(season=season).values_list("id", flat=True)
        )
        if all_team_ids - playoff_team_ids:
            base = 3.0
        else:
            return 0.0

    tscar_fraction = 0.0
    team_tscar = _team_po_tscar(team.id, season.id)
    if team_tscar > 0:
        player_agg = PlayerRegulationStats.objects.filter(
            player_gamelog__player_season=player_season,
            player_gamelog__game__match__season=season,
            player_gamelog__game__non_regulation=False,
        ).exclude(
            player_gamelog__game__match__week__startswith="Week"
        ).aggregate(total_oscar=Sum("oscar"), total_dscar=Sum("dscar"))
        player_tscar = (player_agg["total_oscar"] or 0.0) + (player_agg["total_dscar"] or 0.0)
        if player_tscar > 0:
            tscar_fraction = player_tscar / team_tscar

    return base * (0.25 + 0.75 * tc_fraction + 0.25 * tscar_fraction)


@lru_cache(maxsize=None)
def _season_transaction_count(season_id):
    return Transaction.objects.filter(team__season_id=season_id).count()


def calculate_legacy_points(player_season):
    """
    Calculate legacy points for a PlayerSeason. Returns None if the season is
    ineligible (future end date, zero league weight, fewer than 20 season
    transactions, or invalid playoff tree). Otherwise returns the calculated
    float value.
    """
    season = player_season.season

    if season.league.legacy_weight == 0:
        return None

    if season.end_date is None or season.end_date > date.today():
        return None

    if _season_transaction_count(season.id) < 20:
        return None

    all_series, depths = _get_playoff_series_and_depths(season)
    if depths is None:
        return None  # Invalid playoff tree

    tc_fraction = _tc_fraction(player_season, season)

    components = [
        _roster_bonus(player_season),
        _rs_tscar(player_season, season),
        _playoff_tscar(player_season, season),
        _award_points(player_season, season),
        _rs_team_performance(player_season, season, tc_fraction),
        _playoff_team_performance(player_season, season, all_series, depths, tc_fraction),
        _tc_value(player_season, season, tc_fraction),
    ]

    total = sum(max(0.0, c) for c in components)
    return total * season.league.legacy_weight
