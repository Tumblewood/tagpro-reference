"""
Data plumbing for the custom leaderboard page (/leaders/custom/).

The custom leaderboard is computed entirely in the browser. This module's only job is to
serialize one season's per-gamelog stat rows into a compact JSON payload that the client can
run its formulas over, plus the catalog of stats that can be given a weight.

See reference/static/reference/js/custom-leaders.js for the consuming side.
"""

from typing import Dict, List

from ..models import Game, PlayerGameLog, PlayerRegulationStats, PlayerStats, Season
from .display_info import get_superseded_gamelog_ids, sort_week_names


# The raw stat columns shared by PlayerStats and PlayerRegulationStats, in the order they
# appear in each serialized row. The client indexes into rows by position, so this order is
# part of the payload contract and must not be reshuffled without updating the JS.
RAW_STAT_FIELDS = [
    "time_played",
    "tags",
    "pops",
    "grabs",
    "drops",
    "hold",
    "captures",
    "prevent",
    "returns",
    "powerups",
    "caps_for",
    "caps_against",
    "total_pups_in_game",
    "grabs_off_handoffs",
    "caps_off_handoffs",
    "grabs_off_regrab",
    "caps_off_regrab",
    "long_holds",
    "flaccids",
    "handoffs",
    "good_handoffs",
    "quick_returns",
    "returns_in_base",
    "saves",
    "key_returns",
    "hold_against",
    "kept_flags",
    "near_caps",
    "outs",
    "productive_grabs",
    "grabs_against",
    "outs_against",
    "preventing_opponents",
    "preventing_teammates",
    "tp",
    "rb",
    "jj",
    "ntpops",
    "ot_caps",
]

# Columns stored in ticks (1/60s). The client divides these by 3600 so that weights are
# expressed per minute, which is what makes the SCAR preset weights read naturally
# (0.6 * hold rather than 0.01 * hold).
TICK_FIELDS = ["time_played", "hold", "prevent", "hold_against"]

# Bump whenever the payload's shape changes. The client sends it as a query parameter and the
# server keys its cache on it, so new client code can never be handed an old-shaped payload out
# of the browser cache or the server cache. Keep in step with PAYLOAD_VERSION in
# reference/static/reference/js/custom-leaders.js.
PAYLOAD_VERSION = 4

# The site's own TSCAR rides along per row so the table can show how a custom ranking differs
# from it. Rounded on the way out to keep the payload small: rows are summed per player and then
# only used for ranking, so the error stays far below anything that could reorder anyone.
SCAR_OUTPUT_FIELD = "tscar"

# Every stat the user can weight, grouped for the UI. Each group mixes counting stats with the
# derived stats that belong to the same side of the game, so the form reads the way the season
# stats pages do rather than splitting on how a number happens to be produced.
#
# Three columns in RAW_STAT_FIELDS are deliberately absent because they are only meaningful as
# the denominator of a derived stat: total_pups_in_game (Pup%), preventing_opponents (APO) and
# preventing_teammates (APT). They are still sent in the payload so those can be computed.
#
# "derived" marks a stat computed by calculate_rate_stats rather than summed from the database.
# Derived stats are unavailable under SCAR, which is a per-game linear model: a ratio taken from
# a single game is undefined whenever its denominator is zero.
#
# "hide_in_scar" marks a counting stat SCAR already accounts for. Minutes are paid out by the
# replacement level, and caps for/against are team outcomes that the per-game regression already
# pins to the blowout-adjusted cap differential. Weighting either would double-count.
STAT_GROUPS = [
    {
        "label": "Basic",
        "stats": [
            {"key": "time_played", "label": "Minutes", "hide_in_scar": True},
            {"key": "captures", "label": "Caps"},
            {"key": "hold", "label": "Hold (min)"},
            {"key": "grabs", "label": "Grabs"},
            {"key": "returns", "label": "Returns"},
            {"key": "prevent", "label": "Prevent (min)"},
            {"key": "tags", "label": "Tags"},
            {"key": "pops", "label": "Pops"},
            {"key": "drops", "label": "Drops"},
            {"key": "powerups", "label": "Powerups"},
        ],
    },
    {
        "label": "Offense",
        "stats": [
            {"key": "grabs_off_handoffs", "label": "Grabs off Handoffs"},
            {"key": "caps_off_handoffs", "label": "Caps off Handoffs"},
            {"key": "grabs_off_regrab", "label": "Grabs off Regrab"},
            {"key": "caps_off_regrab", "label": "Caps off Regrab"},
            {"key": "long_holds", "label": "Long Holds"},
            {"key": "flaccids", "label": "Flaccids"},
            {"key": "handoffs", "label": "Handoffs"},
            {"key": "good_handoffs", "label": "Good Handoffs"},
            {"key": "productive_grabs", "label": "Productive Grabs"},
            {"key": "outs", "label": "Outs"},
            {"key": "near_caps", "label": "Near Caps"},
            {"key": "kept_flags", "label": "Kept Flags"},
            {"key": "grabs_per_10", "label": "Grabs / 10", "derived": True},
            {"key": "caps_per_10", "label": "Caps / 10", "derived": True},
            {"key": "hold_per_10", "label": "Hold / 10 (sec)", "derived": True},
            {"key": "hold_per_grab", "label": "Hold / Grab", "derived": True},
            {
                "key": "score_percent",
                "label": "Score %",
                "derived": True,
                "tooltip": "% of grabs that result in a cap",
            },
            {
                "key": "out_pct_off",
                "label": "Out %",
                "derived": True,
                "tooltip": "% of grabs that result in an out",
            },
            {
                "key": "prod_pct",
                "label": "Productive %",
                "derived": True,
                "tooltip": "% of grabs that result in an out or a good handoff",
            },
            {
                "key": "free_pct",
                "label": "Free %",
                "derived": True,
                "tooltip": "% of grabs that are uncontested",
            },
            {
                "key": "apo",
                "label": "Avg Preventing Opponents",
                "derived": True,
                "tooltip": "Avg # of preventing opponents when player grabs",
            },
            {
                "key": "flaccid_percent",
                "label": "Flaccid %",
                "derived": True,
                "tooltip": "% of grabs that are flaccid",
            },
            {
                "key": "spark_percent",
                "label": "Spark %",
                "derived": True,
                "tooltip": "% of caps that are not off a regrab",
            },
            {
                "key": "chain_percent",
                "label": "Chain %",
                "derived": True,
                "tooltip": "% of handoffs that are good handoffs",
            },
        ],
    },
    {
        "label": "Defense",
        "stats": [
            {"key": "saves", "label": "Saves"},
            {"key": "key_returns", "label": "Key Returns"},
            {"key": "quick_returns", "label": "Quick Returns"},
            {"key": "returns_in_base", "label": "Returns in Base"},
            {"key": "hold_against", "label": "Hold Against (min)"},
            {"key": "grabs_against", "label": "Grabs Against"},
            {"key": "outs_against", "label": "Outs Against"},
            {"key": "ret_per_10", "label": "Returns / 10", "derived": True},
            {"key": "prev_per_10", "label": "Prevent / 10 (sec)", "derived": True},
            {"key": "ha_per_10", "label": "Hold Against / 10 (sec)", "derived": True},
            {
                "key": "out_pct_def",
                "label": "Out % Against",
                "derived": True,
                "tooltip": "% of grabs against that get out",
            },
            {"key": "p_oa", "label": "Prevent / Out Against", "derived": True},
            {
                "key": "apt",
                "label": "Avg Preventing Teammates",
                "derived": True,
                "tooltip": "Avg # of preventing teammates when player is preventing",
            },
            {
                "key": "rib_percent",
                "label": "Returns in Base %",
                "derived": True,
                "tooltip": "% of returns made in base",
            },
            {
                "key": "qr_percent",
                "label": "Quick Return %",
                "derived": True,
                "tooltip": "% of returns that are quick returns",
            },
            {"key": "prevent_per_return", "label": "Prevent / Return", "derived": True},
            {
                "key": "prevent_per_hold_against",
                "label": "Prevent / Hold Against",
                "derived": True,
            },
        ],
    },
    {
        "label": "Misc",
        "stats": [
            {"key": "caps_for", "label": "Caps For", "hide_in_scar": True},
            {"key": "caps_against", "label": "Caps Against", "hide_in_scar": True},
            {"key": "tp", "label": "TagPros"},
            {"key": "rb", "label": "Rolling Bombs"},
            {"key": "jj", "label": "Juke Juices"},
            {"key": "ntpops", "label": "Non-Tag Pops"},
            {"key": "ot_caps", "label": "OT Caps", "tooltip": "Caps in clutch time and OT"},
            {"key": "plus_minus", "label": "Plus/Minus", "derived": True},
            {"key": "kd_ratio", "label": "Tags / Pop", "derived": True},
            {
                "key": "pup_percent",
                "label": "Powerup %",
                "derived": True,
                "tooltip": "% of powerups collected",
            },
            {"key": "non_return_tags", "label": "Non-Return Tags", "derived": True},
            {
                "key": "nrt_per_10",
                "label": "Non-Return Tags / 10",
                "derived": True,
                "tooltip": "Tags that were not returns, per 10 minutes",
            },
            {"key": "non_drop_pops", "label": "Non-Drop Pops", "derived": True},
        ],
    },
]

# The real SCAR weights, offered as a starting preset. Every step of calculate_scar() is
# linear, so OSCAR and DSCAR collapse into this single combined vector: with a replacement
# level of 0.6 these weights reproduce TSCAR. Note powerups is 0.1 because it appears at 0.05
# in both halves of the real formula. Hold and prevent are per minute.
SCAR_PRESET_WEIGHTS = {
    "hold": 0.6,
    "captures": 0.5,
    "caps_off_regrab": -0.1,
    "grabs_off_regrab": -0.05,
    "powerups": 0.1,
    "productive_grabs": 0.025,
    "tags": 0.025,
    "returns": 0.1,
    "saves": 0.2,
    "key_returns": 0.05,
    "pops": -0.05,
    "prevent": 0.05,
    "outs_against": -0.02,
}

# The weights GASP was originally defined with. The original spec is in per-minute terms
# (CPM, RPM, NRTPM); the per-10 equivalents are used here because GASP standardizes every stat
# before weighting it, and a z-score is unchanged by a constant factor -- so per-10 and
# per-minute give identical results.
GASP_PRESET_WEIGHTS = {
    # Offense
    "captures": 5,
    "hold": 4,
    "caps_per_10": 2,
    "score_percent": 2,
    # Defense
    "returns": 4,
    "prevent": 4,
    "ret_per_10": 2,
    "nrt_per_10": 2,
    "kd_ratio": 1,
}

FORMULA_OPTIONS = [
    {"value": "additive", "label": "Additive"},
    {"value": "scar", "label": "SCAR"},
    {"value": "gasp", "label": "GASP"},
]

DEFAULT_REPLACEMENT_LEVEL = 0.6


def get_weight_groups() -> List[Dict]:
    """
    The weightable stat catalog, with each stat's hide_in_scar flag resolved.

    Derived stats are unavailable under SCAR for the reason given above STAT_GROUPS, so they
    collapse into the same flag as the counting stats SCAR already accounts for. That leaves the
    template and the JS with one thing to hide rather than two.
    """
    groups = []
    for group in STAT_GROUPS:
        stats = [
            {**stat, "hide_in_scar": bool(stat.get("hide_in_scar") or stat.get("derived"))}
            for stat in group["stats"]
        ]
        groups.append({**group, "stats": stats})
    return groups


def _row_values(stat_row: Dict) -> List[int]:
    """Pull the raw stat columns out of a .values() row, coercing nulls to 0."""
    return [stat_row[field] or 0 for field in RAW_STAT_FIELDS]


def _build_ot_deltas(
    season: Season,
    regulation_by_gamelog: Dict[int, List[int]],
    row_index_by_gamelog: Dict[int, int],
) -> List[List[int]]:
    """
    Build the sparse list of full-game-minus-regulation stat deltas.

    Only a small share of gamelogs have any overtime, so sending deltas keyed by row index
    costs a kilobyte or two instead of doubling the payload.
    """
    deltas = []
    for full_row in PlayerStats.objects.filter(
        player_gamelog__game__match__season=season,
        player_gamelog__game__non_regulation=False,
    ).values("player_gamelog", *RAW_STAT_FIELDS):
        gamelog_id = full_row["player_gamelog"]
        regulation = regulation_by_gamelog.get(gamelog_id)
        if regulation is None:
            continue

        full = _row_values(full_row)
        if full == regulation:
            continue

        deltas.append(
            [row_index_by_gamelog[gamelog_id]]
            + [f - r for f, r in zip(full, regulation)]
        )

    return deltas


def build_season_payload(season: Season) -> Dict:
    """
    Serialize a season's per-gamelog regulation stats for client-side leaderboard math.

    The payload is index-based rather than id-based to keep it small: rows point at entries in
    the players and games lists by position, and games point at weeks by position.

    Games flagged non_regulation (home maps) are excluded, matching aggregate_player_stats.
    Gamelogs superseded by a later match in the same season-week are still sent, but flagged,
    so the client can drop them the same way the season stats pages do.

    Every query filters through the season join rather than through a list of ids, both to use
    the existing indexes and to stay clear of SQLite's cap on bound parameters (a big season
    has several thousand gamelogs).
    """
    games = Game.objects.filter(match__season=season, non_regulation=False).values(
        "id", "team1_score", "team2_score", "match__week", "match__team1"
    )

    game_index = {}
    game_rows = []
    team1_by_game = {}
    week_names_seen = set()
    for game in games:
        week_names_seen.add(game["match__week"])
        team1_by_game[game["id"]] = game["match__team1"]
        game_index[game["id"]] = len(game_rows)
        game_rows.append([game["match__week"], game["team1_score"], game["team2_score"]])

    week_names = sort_week_names(week_names_seen)
    week_index = {week: index for index, week in enumerate(week_names)}
    for row in game_rows:
        row[0] = week_index[row[0]]

    gamelogs = {
        row["id"]: row
        for row in PlayerGameLog.objects.filter(
            game__match__season=season, game__non_regulation=False
        ).values(
            "id",
            "game_id",
            "team_id",
            "player_season",
            "player_season__playing_as",
            "player_season__player__name",
            "player_season__team__abbr",
            "player_season__team__id",
        )
    }

    stats_query = PlayerRegulationStats.objects.filter(
        player_gamelog__game__match__season=season,
        player_gamelog__game__non_regulation=False,
    )
    superseded_ids = get_superseded_gamelog_ids(stats_query)

    player_index = {}
    player_rows = []
    rows = []
    tscar_rows = []
    row_index_by_gamelog = {}
    regulation_by_gamelog = {}

    for stat_row in stats_query.values(
        "player_gamelog", *RAW_STAT_FIELDS, SCAR_OUTPUT_FIELD
    ):
        gamelog_id = stat_row["player_gamelog"]
        gamelog = gamelogs.get(gamelog_id)
        if gamelog is None:
            continue

        player_season_id = gamelog["player_season"]
        if player_season_id not in player_index:
            player_index[player_season_id] = len(player_rows)
            player_rows.append(
                [
                    player_season_id,
                    gamelog["player_season__playing_as"],
                    gamelog["player_season__player__name"],
                    gamelog["player_season__team__abbr"],
                    gamelog["player_season__team__id"],
                ]
            )

        game_id = gamelog["game_id"]
        values = _row_values(stat_row)
        regulation_by_gamelog[gamelog_id] = values
        row_index_by_gamelog[gamelog_id] = len(rows)
        tscar_rows.append(round(stat_row[SCAR_OUTPUT_FIELD] or 0, 4))
        rows.append(
            [
                player_index[player_season_id],
                game_index[game_id],
                0 if gamelog["team_id"] == team1_by_game[game_id] else 1,
                1 if gamelog_id in superseded_ids else 0,
            ]
            + values
        )

    return {
        "version": PAYLOAD_VERSION,
        "season": {"id": season.id, "name": season.name},
        "fields": RAW_STAT_FIELDS,
        "weeks": week_names,
        "players": player_rows,
        "games": game_rows,
        "rows": rows,
        "tscar": tscar_rows,
        "ot": _build_ot_deltas(season, regulation_by_gamelog, row_index_by_gamelog),
    }
