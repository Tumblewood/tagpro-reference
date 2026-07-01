from typing import List
import json
import os
import re
import urllib.request
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup
from django.conf import settings as django_settings
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.db import models, transaction
from django.db.models import Count, F, OuterRef, Subquery, IntegerField, Exists, Sum, FloatField, Value
from django.db.models.functions import Coalesce, Lower
from accounts.decorators import (
    data_entry_required,
    bulk_import_required,
    full_data_permissions_required,
)
from django.contrib import messages
from reference.utils.display_info import (
    aggregate_player_stats,
    get_team_standings,
    get_all_team_standings,
    calculate_match_box_score,
    get_match_team_stats,
    calculate_rate_stats,
    build_playoff_bracket,
)
from reference.utils.data_entry import (
    prepopulate_form,
    enter_confirmed_data,
    process_multiple_eu_links,
    import_json_data_to_db,
    format_compact_json,
    extract_game_data,
)
from reference.utils.stat_collection import (
    update_standings,
    calculate_scar,
    infer_playoff_series,
    process_game_stats,
    reprocess_match,
    STAT_FIELDS,
)
from reference.utils.data_correction import merge_players, merge_player_seasons
from reference.models import (
    Season,
    TeamSeason,
    Player,
    PlayerSeason,
    Match,
    PlayoffSeries,
    Game,
    PlayerGameLog,
    League,
    Franchise,
    AwardType,
    AwardReceived,
    Transaction,
    PlayerRegulationStats,
    PlayerStats,
)


def build_roster_players(team):
    """
    Return the team's PlayerSeason queryset annotated with tc and is_prelim,
    sorted with prelim players first, then by TC descending.
    """
    latest_tc = (
        Transaction.objects.filter(
            player_season=OuterRef("pk"),
            transaction_type__in=["draft", "add"],
        )
        .order_by("-before_week")
        .values("net_tc_spent")[:1]
    )
    has_prelim = Transaction.objects.filter(
        player_season=OuterRef("pk"),
        team=team,
        transaction_type="prelim",
    )
    return (
        team.players.select_related("player")
        .annotate(
            tc=Subquery(latest_tc, output_field=IntegerField()),
            is_prelim=Exists(has_prelim),
        )
        .order_by("-is_prelim", F("tc").desc(nulls_last=True))
    )


PLAYOFF_ORDER = {
    "Upper Bracket QF": "ZZZZ4",
    "Upper Bracket SF": "ZZZZ5",
    "Lower Bracket Round 1": "ZZZZ5",
    "Fibonacci Fifteen": "ZZZZ6",
    "Play-in": "ZZZZ6",
    "Lower Bracket QF": "ZZZZ6",
    "Equidistant Eight": "ZZZZ7",
    "Secant Six": "ZZZZ7",
    "Spherical Six": "ZZZZ7",
    "Upper Bracket Final": "ZZZZ7",
    "Lower Bracket SF": "ZZZZ7",
    "Foci Four": "ZZZZ8",
    "Lower Bracket Final": "ZZZZ8",
    "Super Ball": "ZZZZ9",
    "Muper Ball": "ZZZZ9",
    "Nuper Ball": "ZZZZ9",
    "Buper Ball": "ZZZZ9",
    "Grand Final": "ZZZZ9",
}
STAT_VIEW_OPTIONS = [
    {"value": "basic", "label": "Basic"},
    {"value": "counting", "label": "Counting"},
    {"value": "offense", "label": "Offense"},
    {"value": "defense", "label": "Defense"},
    {"value": "misc", "label": "Misc"},
    {"value": "impact", "label": "Impact"},
]
STAT_COLUMNS = {
    "basic": [
        {"key": "time_played_min", "label": "Min", "type": "number"},
        {"key": "captures", "label": "Caps", "type": "number"},
        {"key": "hold_sec", "label": "Hold", "type": "number"},
        {"key": "returns", "label": "Returns", "type": "number"},
        {"key": "prevent_sec", "label": "Prevent", "type": "number"},
        {"key": "powerups", "label": "Pups", "type": "number"},
        {
            "key": "oscar",
            "label": "OSCAR",
            "type": "number",
            "tooltip": "Offensive Simple Caps Above Replacement",
        },
        {
            "key": "dscar",
            "label": "DSCAR",
            "type": "number",
            "tooltip": "Defensive Simple Caps Above Replacement",
        },
        {
            "key": "tscar",
            "label": "TSCAR",
            "type": "number",
            "tooltip": "Total Simple Caps Above Replacement",
        },
        {
            "key": "teff",
            "label": "TEff",
            "type": "number",
            "tooltip": "Total Efficiency - TSCAR per 10 minutes",
        },
    ],
    "counting": [
        {"key": "time_played_min", "label": "Min", "type": "number"},
        {"key": "tags", "label": "Tags", "type": "number"},
        {"key": "pops", "label": "Pops", "type": "number"},
        {"key": "grabs", "label": "Grabs", "type": "number"},
        {"key": "drops", "label": "Drops", "type": "number"},
        {"key": "returns", "label": "Returns", "type": "number"},
        {"key": "captures", "label": "Caps", "type": "number"},
        {"key": "hold_sec", "label": "Hold", "type": "number"},
        {"key": "prevent_sec", "label": "Prevent", "type": "number"},
        {"key": "powerups", "label": "Pups", "type": "number"},
    ],
    "offense": [
        {"key": "time_played_min", "label": "Min", "type": "number"},
        {
            "key": "grabs_per_10",
            "label": "Grabs/10",
            "type": "number",
            "tooltip": "Grabs per 10 minutes",
        },
        {
            "key": "caps_per_10",
            "label": "Caps/10",
            "type": "number",
            "tooltip": "Captures per 10 minutes",
        },
        {
            "key": "hold_per_10",
            "label": "Hold/10",
            "type": "number",
            "tooltip": "Hold per 10 minutes",
        },
        {
            "key": "hold_per_grab",
            "label": "H/G",
            "type": "number",
            "tooltip": "Hold per Grab",
        },
        {
            "key": "score_percent",
            "label": "Score%",
            "type": "number",
            "tooltip": "% of grabs that result in a cap",
        },
        {
            "key": "out_pct_off",
            "label": "Out%",
            "type": "number",
            "tooltip": "% of grabs that result in an out",
        },
        {
            "key": "prod_pct",
            "label": "Prod%",
            "type": "number",
            "tooltip": "% of grabs that result in an out or a good handoff",
        },
        {
            "key": "free_pct",
            "label": "Free%",
            "type": "number",
            "tooltip": "% of grabs that are uncontested",
        },
        {
            "key": "apo",
            "label": "APO",
            "type": "number",
            "tooltip": "Avg # of preventing opponents when player grabs",
        },
    ],
    "defense": [
        {"key": "time_played_min", "label": "Min", "type": "number"},
        {
            "key": "ret_per_10",
            "label": "Ret/10",
            "type": "number",
            "tooltip": "Returns per 10 minutes",
        },
        {
            "key": "prev_per_10",
            "label": "Prev/10",
            "type": "number",
            "tooltip": "Prevent per 10 minutes",
        },
        {
            "key": "ha_per_10",
            "label": "HA/10",
            "type": "number",
            "tooltip": "Hold against per 10 minutes",
        },
        {
            "key": "out_pct_def",
            "label": "Out%",
            "type": "number",
            "tooltip": "% of grabs against that get out",
        },
        {
            "key": "p_oa",
            "label": "P/OA",
            "type": "number",
            "tooltip": "Prevent / outs against",
        },
        {
            "key": "apt",
            "label": "APT",
            "type": "number",
            "tooltip": "Avg # of preventing teammates when player is preventing",
        },
        {
            "key": "key_returns",
            "label": "KeyRet",
            "type": "number",
            "tooltip": "Returns within 2 seconds before teammate cap",
        },
        {
            "key": "saves",
            "label": "Saves",
            "type": "number",
            "tooltip": "Returns within 6 tiles of enemy flag while team is not holding",
        },
    ],
    "misc": [
        {"key": "time_played_min", "label": "Min", "type": "number"},
        {
            "key": "kd_ratio",
            "label": "K/D",
            "type": "number",
            "tooltip": "Tags / pops",
        },
        {
            "key": "pup_percent",
            "label": "Pup%",
            "type": "number",
            "tooltip": "% of powerups collected",
        },
        {"key": "tp", "label": "TP", "type": "number", "tooltip": "TagPros collected"},
        {"key": "rb", "label": "RB", "type": "number", "tooltip": "Rolling bombs collected"},
        {"key": "jj", "label": "JJ", "type": "number", "tooltip": "Juke juices collected"},
        {
            "key": "non_return_tags",
            "label": "NRTag",
            "type": "number",
            "tooltip": "Non-return tags",
        },
        {
            "key": "non_drop_pops",
            "label": "NDPop",
            "type": "number",
            "tooltip": "Non-drop pops",
        },
        {
            "key": "ntpops",
            "label": "NTPop",
            "type": "number",
            "tooltip": "Non-tag pops",
        },
        {
            "key": "ot_caps",
            "label": "OTCaps",
            "type": "number",
            "tooltip": "Caps in clutch time and OT",
        },
        {
            "key": "kept_flags",
            "label": "Kept",
            "type": "number",
            "tooltip": "Kept flags",
        },
    ],
    "impact": [
        {"key": "time_played_min", "label": "Min", "type": "number"},
        {
            "key": "plus_minus",
            "label": "+/-",
            "type": "number",
            "tooltip": "Plus/Minus",
        },
        {
            "key": "ba_pm",
            "label": "BAPM",
            "type": "number",
            "tooltip": "Blowout-Adjusted Plus/Minus",
        },
        {
            "key": "oscar",
            "label": "OSCAR",
            "type": "number",
            "tooltip": "Offensive Simple Caps Above Replacement",
        },
        {
            "key": "dscar",
            "label": "DSCAR",
            "type": "number",
            "tooltip": "Defensive Simple Caps Above Replacement",
        },
        {
            "key": "tscar",
            "label": "TSCAR",
            "type": "number",
            "tooltip": "Total Simple Caps Above Replacement",
        },
        {
            "key": "oeff",
            "label": "OEff",
            "type": "number",
            "tooltip": "OSCAR per 10 minutes",
        },
        {
            "key": "deff",
            "label": "DEff",
            "type": "number",
            "tooltip": "DSCAR per 10 minutes",
        },
        {
            "key": "teff",
            "label": "TEff",
            "type": "number",
            "tooltip": "TSCAR per 10 minutes",
        },
    ],
}


def homepage(req):
    """Homepage with standings for all leagues."""
    featured_leagues = League.objects.filter(ordering__lt=20, gamemode="CTF").order_by("ordering")

    # Fetch latest season for each featured league in one query
    all_seasons = Season.objects.filter(league__in=featured_leagues).select_related("league").order_by(
        F("end_date").desc(nulls_last=True)
    )
    latest_season_by_league = {}
    for season in all_seasons:
        if season.league_id not in latest_season_by_league:
            latest_season_by_league[season.league_id] = season

    league_standings = []
    for league in featured_leagues:
        latest_season = latest_season_by_league.get(league.id)
        if not latest_season:
            continue

        teams = list(TeamSeason.objects.filter(season=latest_season))
        if not teams:
            continue

        standings = get_all_team_standings(latest_season, teams)
        standings = sorted(standings, key=lambda x: x["team"].seed)
        league_standings.append(
            {
                "league": league,
                "season": latest_season,
                "standings": standings,
            }
        )

    # Other leagues: those not shown in the standings
    other_leagues_qs = League.objects.exclude(id__in=featured_leagues).order_by("ordering")
    other_seasons = Season.objects.filter(league__in=other_leagues_qs).select_related("league").order_by(
        F("end_date").desc(nulls_last=True)
    )
    latest_other_season_by_league = {}
    for season in other_seasons:
        if season.league_id not in latest_other_season_by_league:
            latest_other_season_by_league[season.league_id] = season

    other_leagues = []
    for league in other_leagues_qs:
        latest_season = latest_other_season_by_league.get(league.id)
        if latest_season:
            other_leagues.append({
                "league": league,
                "season": latest_season,
            })

    return render(
        req,
        "reference/homepage.html",
        {
            "league_standings": league_standings,
            "other_leagues": other_leagues,
        },
    )


def resources_faq(req):
    """FAQ resource page."""
    return render(req, "reference/resources_faq.html", {})


def resources_glossary(req):
    """Stat glossary resource page."""
    return render(req, "reference/resources_glossary.html", {})


def resources_scar(req):
    """SCAR explainer resource page."""
    return render(req, "reference/resources_scar.html", {})


def resources_legacy(req):
    """Legacy points explainer resource page."""
    return render(req, "reference/resources_legacy.html", {})


def search_results(req, query):
    """
    Search across franchises, teams, and players with substring matching.
    Send user directly to page if there's exactly one match.
    """
    if not query or len(query.strip()) < 1:
        return render(
            req,
            "reference/search_results.html",
            {
                "query": query,
                "leagues": [],
                "franchises": [],
                "teams": [],
                "players": [],
                "no_results": True,
            },
        )

    query = query.strip()
    query_lower = query.lower()

    leagues = League.objects.filter(
        models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
    )
    franchises = Franchise.objects.filter(
        models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
    )
    teams = (
        TeamSeason.objects.filter(
            models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
        )
        .select_related("season", "franchise")
        .order_by("-season__end_date")
    )
    players = Player.objects.filter(name__icontains=query).order_by("name")

    # Check for redirect conditions
    league_exact_matches = [
        l
        for l in leagues
        if l.name.lower() == query_lower or (l.abbr and l.abbr.lower() == query_lower)
    ]
    franchise_exact_matches = [
        f
        for f in franchises
        if f.name.lower() == query_lower or (f.abbr and f.abbr.lower() == query_lower)
    ]
    team_exact_matches = [
        t
        for t in teams
        if t.name.lower() == query_lower or (t.abbr and t.abbr.lower() == query_lower)
    ]
    player_exact_matches = [p for p in players if p.name.lower() == query_lower]

    # Redirect logic - leagues are treated like franchises
    if len(league_exact_matches) == 1 and len(player_exact_matches) == 0:
        return redirect("league_history", league_id=league_exact_matches[0].id)

    if len(franchise_exact_matches) == 1 and len(player_exact_matches) == 0:
        return redirect("franchise_history", franchise_id=franchise_exact_matches[0].id)

    if (
        len(team_exact_matches) == 1
        and len(league_exact_matches) == 0
        and len(franchise_exact_matches) == 0
        and len(player_exact_matches) == 0
    ):
        return redirect("team_season", team_id=team_exact_matches[0].id)

    if (
        len(player_exact_matches) == 1
        and len(league_exact_matches) == 0
        and len(franchise_exact_matches) == 0
        and len(team_exact_matches) == 0
    ):
        return redirect("player_history", player_name=player_exact_matches[0].name)

    # If we have exactly one league match and no players, redirect
    if len(leagues) == 1 and len(players) == 0:
        return redirect("league_history", league_id=leagues[0].id)

    # If we have exactly one franchise match and no players, redirect
    if len(franchises) == 1 and len(players) == 0:
        return redirect("franchise_history", franchise_id=franchises[0].id)

    # If we have exactly one team match and no leagues, franchises or players, redirect
    if (
        len(teams) == 1
        and len(leagues) == 0
        and len(franchises) == 0
        and len(players) == 0
    ):
        return redirect("team_season", team_id=teams[0].id)

    # Search leagues by name and abbreviation (case-insensitive substring)
    leagues = League.objects.filter(
        models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
    ).order_by("name")[:20]

    # Search franchises by name and abbreviation (case-insensitive substring)
    franchises = Franchise.objects.filter(
        models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
    ).order_by("name")[:20]

    # Search teams by name and abbreviation (case-insensitive substring)
    teams = (
        TeamSeason.objects.filter(
            models.Q(name__icontains=query) | models.Q(abbr__icontains=query)
        )
        .select_related("season", "franchise")
        .order_by("-season__end_date")[:20]
    )

    # Search players by name and playing_as (case-insensitive substring)
    # Use distinct to avoid duplicates when a player matches both name and playing_as
    player_matches = set()

    # Search by player name
    players_by_name = Player.objects.filter(name__icontains=query).order_by("name")[:20]
    player_matches.update(players_by_name)

    # Search by playing_as in PlayerSeason
    players_by_playing_as = (
        Player.objects.filter(seasons_played__playing_as__icontains=query)
        .distinct()
        .order_by("name")[:20]
    )
    player_matches.update(players_by_playing_as)

    # Convert to list and limit to 20, maintaining sort order
    players = sorted(list(player_matches), key=lambda p: p.name.lower())[:20]

    return render(
        req,
        "reference/search_results.html",
        {
            "query": query,
            "leagues": leagues,
            "franchises": franchises,
            "teams": teams,
            "players": players,
            "no_results": len(leagues) == 0
            and len(franchises) == 0
            and len(teams) == 0
            and len(players) == 0,
        },
    )


def league_history_by_abbr(req, league_abbr):
    """View league's history by abbreviation."""
    # Convert dashes back to spaces
    league_abbr = league_abbr.replace("-", " ")
    league = get_object_or_404(League, abbr=league_abbr)
    return league_history(req, league.id)


def league_history(req, league_id):
    """View league's history showing all seasons with champions and runners-up."""
    league = get_object_or_404(League, id=league_id)

    # Get all seasons for this league, with null dates last
    seasons = Season.objects.filter(league=league).order_by(
        F("end_date").desc(nulls_last=True)
    )
    season_history = []
    for season in seasons:
        # Count teams in this season
        team_count = TeamSeason.objects.filter(season=season).count()

        # Find champion and runner-up from the final playoff series
        champion = None
        runner_up = None

        # Look for the championship game/series (Super Ball, etc.)
        final_names = ["Super Ball", "Muper Ball", "Nuper Ball", "Buper Ball"]
        championship_matches = (
            Match.objects.filter(
                season=season, week__in=final_names, playoff_series__isnull=False
            )
            .select_related("playoff_series", "team1", "team2")
            .first()
        )

        if championship_matches and championship_matches.playoff_series:
            playoff_series = championship_matches.playoff_series
            if playoff_series.winner:
                champion = playoff_series.winner
                # The other team in the match is the runner-up
                if championship_matches.team1 == champion:
                    runner_up = championship_matches.team2
                else:
                    runner_up = championship_matches.team1

        # Get first place award winners for MVB, OBOS, DBOS
        mvb_winner = None
        obos_winner = None
        dbos_winner = None

        try:
            mvb_award = AwardType.objects.get(abbr="MVB")
            mvb_received = (
                AwardReceived.objects.filter(
                    season=season, award=mvb_award, placement=1
                )
                .select_related("player")
                .first()
            )
            if mvb_received:
                mvb_winner = mvb_received.player
        except AwardType.DoesNotExist:
            pass

        try:
            obos_award = AwardType.objects.get(abbr="OBOS")
            obos_received = (
                AwardReceived.objects.filter(
                    season=season, award=obos_award, placement=1
                )
                .select_related("player")
                .first()
            )
            if obos_received:
                obos_winner = obos_received.player
        except AwardType.DoesNotExist:
            pass

        try:
            dbos_award = AwardType.objects.get(abbr="DBOS")
            dbos_received = (
                AwardReceived.objects.filter(
                    season=season, award=dbos_award, placement=1
                )
                .select_related("player")
                .first()
            )
            if dbos_received:
                dbos_winner = dbos_received.player
        except AwardType.DoesNotExist:
            pass

        season_history.append(
            {
                "season": season,
                "team_count": team_count,
                "champion": champion,
                "runner_up": runner_up,
                "mvb_winner": mvb_winner,
                "obos_winner": obos_winner,
                "dbos_winner": dbos_winner,
            }
        )

    return render(
        req,
        "reference/league_history.html",
        {
            "league": league,
            "season_history": season_history,
        },
    )


def season_home_by_name(req, season_name):
    """View season home by name."""
    # Convert dashes back to spaces
    season_name = season_name.replace("-", " ")
    season = get_object_or_404(Season, name=season_name)
    return season_home(req, season.id)


def season_home(req, season_id):
    """View key season information, namely standings."""
    season = get_object_or_404(Season, id=season_id)
    league_seasons = Season.objects.filter(league=season.league).order_by(
        F("end_date").desc(nulls_last=True)
    )
    teams = list(TeamSeason.objects.filter(season=season))
    standings = get_all_team_standings(season, teams)
    standings = sorted(standings, key=lambda x: x["team"].seed)

    # Build playoff bracket if playoffs exist
    bracket_layout = build_playoff_bracket(season)

    # Check if this is a playoff-only season (has playoffs but no regular season)
    playoff_matches = Match.objects.filter(
        season=season, playoff_series__isnull=False
    ).exists()
    regular_season_matches = Match.objects.filter(
        season=season, playoff_series__isnull=True
    ).exists()
    is_playoff_only = playoff_matches and not regular_season_matches

    return render(
        req,
        "reference/season_home.html",
        {
            "season": season,
            "league_seasons": league_seasons,
            "standings": standings,
            "bracket": bracket_layout,
            "is_playoff_only": is_playoff_only,
        },
    )


def season_schedule_by_name(req, season_name):
    """View season schedule by name."""
    # Convert dashes back to spaces
    season_name = season_name.replace("-", " ")
    season = get_object_or_404(Season, name=season_name)
    return season_schedule(req, season.id)


def season_schedule(req, season_id):
    """View season schedule with match results."""
    season = get_object_or_404(Season, id=season_id)
    league_seasons = Season.objects.filter(league=season.league).order_by(
        F("end_date").desc(nulls_last=True)
    )

    # Get all matches for this season
    matches = (
        Match.objects.filter(season=season)
        .select_related("team1__franchise", "team2__franchise")
        .prefetch_related("games", "playoff_series")
    )

    # Group matches by week
    weeks = {}
    for match in matches:
        week = match.week
        if week not in weeks:
            weeks[week] = []
        weeks[week].append(match)

    # Sort weeks with special playoff ordering
    def week_sort_key(week_name):
        return PLAYOFF_ORDER.get(week_name, week_name)

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
                match_data = calculate_match_box_score(match, games)
            else:
                match_data = {"match": match, "games": [], "has_games": False}

            week_matches.append(match_data)

        schedule_data.append({"week": week, "matches": week_matches})

    return render(
        req,
        "reference/season_schedule.html",
        {
            "season": season,
            "league_seasons": league_seasons,
            "schedule_data": schedule_data,
        },
    )


def season_stats_by_name(req, season_name):
    """View season stats by name."""
    # Convert dashes back to spaces
    season_name = season_name.replace("-", " ")
    season = get_object_or_404(Season, name=season_name)
    return season_stats(req, season.id)


def season_stats(req, season_id):
    """View season player statistics."""
    season = get_object_or_404(Season, id=season_id)

    # Get all seasons from the same league for dropdown
    league_seasons = Season.objects.filter(league=season.league).order_by(
        F("end_date").desc(nulls_last=True)
    )

    # Check if this is a playoff-only season (has playoffs but no regular season)
    playoff_matches = Match.objects.filter(
        season=season, playoff_series__isnull=False
    ).exists()
    regular_season_matches = Match.objects.filter(
        season=season, playoff_series__isnull=True
    ).exists()
    is_playoff_only = playoff_matches and not regular_season_matches

    # Get week filter and stat view from query params
    # Default to 'all_season' for playoff-only seasons, otherwise 'all_regular_season'
    default_week = "all_season" if is_playoff_only else "all_regular_season"
    week_filter = req.GET.get("week", default_week)
    stat_view = req.GET.get("view", "basic")
    if stat_view not in STAT_COLUMNS:
        stat_view = "basic"

    # Get all weeks for this season to build dropdown
    all_weeks = (
        Match.objects.filter(season=season).values_list("week", flat=True).distinct()
    )

    def week_sort_key(week_name):
        return PLAYOFF_ORDER.get(week_name, week_name)

    sorted_weeks = sorted(all_weeks, key=week_sort_key)

    # Build week options
    week_options = [
        {"value": "all_regular_season", "label": "All Regular Season"},
        {"value": "all_playoffs", "label": "All Playoffs"},
        {"value": "all_season", "label": "All RS + Playoffs"},
    ]
    for week in sorted_weeks:
        week_options.append({"value": week, "label": week})

    stats = aggregate_player_stats(season=season, week=week_filter)
    stats = calculate_rate_stats(stats)

    # Sort by TSCAR descending, then by time_played descending as tiebreaker
    stats.sort(
        key=lambda x: (x.get("tscar", 0) or 0, x.get("time_played_min", 0) or 0),
        reverse=True,
    )

    template_stats = []
    for player_stat in stats:
        stat_row = {
            "player": player_stat["player"],
            "player_season": player_stat.get("player_season"),
            "team": player_stat.get("team"),
            "playing_as": player_stat["playing_as"],
            "column_values": [],
        }

        for column in STAT_COLUMNS[stat_view]:
            value = player_stat.get(column["key"], 0)
            # Format float values
            if column["key"] in ["oeff", "deff", "teff"]:
                value = f"{value:.2f}" if value is not None else "0.00"
            elif column["key"] in ["oscar", "dscar", "tscar", "ba_pm"]:
                value = f"{value:.1f}" if value is not None else "0.0"
            stat_row["column_values"].append(value)

        template_stats.append(stat_row)

    return render(
        req,
        "reference/season_stats.html",
        {
            "season": season,
            "league_seasons": league_seasons,
            "player_stats": template_stats,
            "week_options": week_options,
            "current_week": week_filter,
            "stat_view_options": STAT_VIEW_OPTIONS,
            "current_stat_view": stat_view,
            "stat_columns": STAT_COLUMNS[stat_view],
        },
    )


def season_rosters_by_name(req, season_name):
    """View season rosters by name."""
    # Convert dashes back to spaces
    season_name = season_name.replace("-", " ")
    season = get_object_or_404(Season, name=season_name)
    return season_rosters(req, season.id)


def season_rosters(req, season_id):
    """View season rosters with each team's players."""
    season = get_object_or_404(Season, id=season_id)

    # Get all seasons from the same league for dropdown
    league_seasons = Season.objects.filter(league=season.league).order_by(
        F("end_date").desc(nulls_last=True)
    )

    # Get all teams in this season with their players
    teams = (
        TeamSeason.objects.filter(season=season)
        .prefetch_related("franchise")
        .order_by("name")
    )

    # Build roster data
    rosters = []
    for team in teams:
        players = build_roster_players(team)
        rosters.append({"team": team, "players": players})

    has_transactions = Transaction.objects.filter(team__season=season).exists()

    return render(
        req,
        "reference/season_rosters.html",
        {
            "season": season,
            "league_seasons": league_seasons,
            "rosters": rosters,
            "has_transactions": has_transactions,
        },
    )


def season_awards_by_name(req, season_name):
    """View season awards by name."""
    # Convert dashes back to spaces
    season_name = season_name.replace("-", " ")
    season = get_object_or_404(Season, name=season_name)
    return season_awards(req, season.id)


def season_awards(req, season_id):
    """View season awards with recipients."""
    from reference.models import AwardReceived, AwardType

    season = get_object_or_404(Season, id=season_id)

    # Get all seasons from the same league for dropdown
    league_seasons = Season.objects.filter(league=season.league).order_by(
        F("end_date").desc(nulls_last=True)
    )

    # Get all award types that have awards in this season
    award_types_with_awards = (
        AwardType.objects.filter(awardreceived__season=season)
        .distinct()
        .order_by("ordering")
    )

    # Build awards data
    awards_data = []
    for award_type in award_types_with_awards:
        recipients = (
            AwardReceived.objects.filter(season=season, award=award_type)
            .select_related("player", "team__franchise")
            .order_by("placement")
        )

        awards_data.append({"award_type": award_type, "recipients": recipients})

    return render(
        req,
        "reference/season_awards.html",
        {
            "season": season,
            "league_seasons": league_seasons,
            "awards_data": awards_data,
        },
    )


def player_history(req, player_name):
    """View player's career history across all seasons."""
    player = get_object_or_404(Player, name=player_name)

    # Get league filter from query params
    league_filter = req.GET.get("league", "all")

    # Get all leagues for the filter dropdown
    all_leagues = League.objects.filter(gamemode="CTF").order_by("ordering")

    # Determine which league to filter by
    selected_league = None
    if league_filter != "all":
        try:
            league_id = int(league_filter)
            selected_league = League.objects.get(id=league_id)
        except (ValueError, League.DoesNotExist):
            pass

    # Build history data with league filter
    history_data = aggregate_player_stats(
        player=player, league=selected_league, week="all_regular_season"
    )

    # Get awards for this player
    from reference.models import AwardReceived

    awards_query = AwardReceived.objects.filter(player=player).select_related(
        "season__league", "award"
    )

    # Apply league filter to awards
    if selected_league:
        awards_query = awards_query.filter(season__league=selected_league)
    else:
        # Filter to CTF leagues only
        awards_query = awards_query.filter(season__league__gamemode="CTF")

    # Order awards by season.league.ordering, award.ordering, season.end_date
    awards = awards_query.order_by(
        "season__league__ordering",
        "award__ordering",
        F("season__end_date").desc(nulls_last=True),
    )

    return render(
        req,
        "reference/player_history.html",
        {
            "player": player,
            "history_data": history_data,
            "leagues": all_leagues,
            "current_league": league_filter,
            "awards": awards,
        },
    )


def team_season(req, team_id):
    """View team season information, roster, stats, and schedule."""
    team = get_object_or_404(TeamSeason, id=team_id)
    season = team.season
    franchise = team.franchise

    # Get team rank and playoff finish from pre-calculated fields
    rank = team.seed if team.seed else "—"
    playoff_finish = team.playoff_finish if team.playoff_finish else "—"

    # Get team standings data (includes record)
    team_standings = get_team_standings(team)
    record = team_standings["record"]

    # Get roster
    players = build_roster_players(team)

    # Get player stats
    player_stats = aggregate_player_stats(season=season, franchise=team.franchise)

    # Get schedule data
    matches = (
        Match.objects.filter(models.Q(team1=team) | models.Q(team2=team), season=season)
        .select_related("team1__franchise", "team2__franchise")
        .prefetch_related("games", "playoff_series")
        .order_by("date")
    )

    # Build schedule data
    schedule_data = []
    for match in matches:
        # Get games for this match
        games = list(match.games.all())

        # Build box score data
        if games:
            match_data = calculate_match_box_score(match, games)
        else:
            match_data = {"match": match, "games": [], "has_games": False}

        schedule_data.append(match_data)

    has_transactions = Transaction.objects.filter(team__season=season).exists()

    return render(
        req,
        "reference/team_season.html",
        {
            "team": team,
            "season": season,
            "franchise": franchise,
            "rank": rank,
            "playoff_finish": playoff_finish,
            "record": record,
            "players": players,
            "team_stats": player_stats,
            "schedule_data": schedule_data,
            "has_transactions": has_transactions,
        },
    )


def legacy_leaders(req):
    """Leaderboard of legacy points across all player seasons."""
    season_filter = req.GET.get("season", "all")

    seasons_with_points = (
        Season.objects.filter(player_seasons__legacy_points__isnull=False)
        .distinct()
        .select_related("league")
        .order_by(F("league__legacy_weight").desc(), F("end_date").desc(nulls_last=True))
    )

    season_obj = None
    if season_filter != "all":
        try:
            season_obj = Season.objects.get(id=int(season_filter))
        except (ValueError, Season.DoesNotExist):
            pass

    qs = PlayerSeason.objects.filter(legacy_points__isnull=False).select_related(
        "player", "season__league", "team__franchise", "team__captain", "team__co_captain"
    )
    if season_obj:
        qs = qs.filter(season=season_obj)

    leaders = list(qs.order_by("-legacy_points")[:100])
    ps_id_set = {ps.id for ps in leaders}

    seasons_to_query = [season_obj] if season_obj else list({ps.season for ps in leaders})
    rs_tscar_map = {}
    po_tscar_map = {}
    for s in seasons_to_query:
        for row in aggregate_player_stats(week="all_regular_season", season=s):
            if row["player_season"].id in ps_id_set:
                rs_tscar_map[row["player_season"].id] = row["tscar"]
        for row in aggregate_player_stats(week="all_playoffs", season=s):
            if row["player_season"].id in ps_id_set:
                po_tscar_map[row["player_season"].id] = row["tscar"]

    txn_rows = Transaction.objects.filter(
        player_season__in=leaders,
        transaction_type__in=["draft", "prelim"],
    ).values("player_season_id", "net_tc_spent", "transaction_type")
    tc_map = {t["player_season_id"]: t["net_tc_spent"] for t in txn_rows}
    prelim_ps_ids = {t["player_season_id"] for t in txn_rows if t["transaction_type"] == "prelim"}

    for ps in leaders:
        ps.rs_tscar = rs_tscar_map.get(ps.id, 0.0)
        ps.po_tscar = po_tscar_map.get(ps.id, 0.0)
        if ps.id in prelim_ps_ids:
            team = ps.team
            is_captain = team is not None and (
                (team.captain_id and team.captain_id == ps.player_id)
                or (team.co_captain_id and team.co_captain_id == ps.player_id)
            )
            ps.draft_tc = "C" if is_captain else "P"
        else:
            ps.draft_tc = tc_map.get(ps.id, 0)

    return render(
        req,
        "reference/legacy_leaders.html",
        {
            "leaders": leaders,
            "seasons": seasons_with_points,
            "current_season": season_filter,
        },
    )


def career_leaders(req):
    """Career legacy point leaders using 3-norm aggregation."""
    from collections import defaultdict

    # All MLTP player-seasons with positive legacy points
    all_ps = list(
        PlayerSeason.objects.filter(
            legacy_points__isnull=False,
            legacy_points__gt=0,
            season__league__abbr="MLTP",
        )
        .select_related("player", "season__league", "team")
    )

    # Group by player, accumulate cube sums and peaks
    player_cube = defaultdict(float)
    player_peak = defaultdict(float)
    player_name = {}
    for ps in all_ps:
        pid = ps.player_id
        player_name[pid] = ps.player.name
        player_cube[pid] += ps.legacy_points ** 3
        player_peak[pid] = max(player_peak[pid], ps.legacy_points)

    # Build full sorted leaderboard
    all_player_ids = list(player_cube.keys())
    leaderboard = sorted(
        [
            {
                "player_id": pid,
                "name": player_name[pid],
                "career_score": player_cube[pid] ** (1.0 / 3.0),
                "cube_sum": player_cube[pid],
                "peak": player_peak[pid],
            }
            for pid in all_player_ids
        ],
        key=lambda x: x["career_score"],
        reverse=True,
    )

    top_100 = leaderboard[:100]
    top_100_player_ids = [e["player_id"] for e in top_100]

    # MLTP season counts for top-100 players
    mltp_counts = {
        row["player_id"]: row["ct"]
        for row in PlayerSeason.objects.filter(
            player_id__in=top_100_player_ids,
            season__league__abbr="MLTP",
        )
        .values("player_id")
        .annotate(ct=Count("id"))
    }

    # Awards for top-100 players (MLTP seasons only)
    awards_qs = AwardReceived.objects.filter(
        player_id__in=top_100_player_ids,
        award__legacy_value__isnull=False,
        season__league__abbr="MLTP",
    ).select_related("award")

    mvb_map = defaultdict(lambda: [0, 0, 0])  # [gold, silver, bronze]
    allstar_map = defaultdict(int)
    for ar in awards_qs:
        pid = ar.player_id
        if "all-star" in ar.award.name.lower():
            allstar_map[pid] += 1
        elif ar.award.abbr == "MVB":
            if ar.placement == 1:
                mvb_map[pid][0] += 1
            elif ar.placement == 2:
                mvb_map[pid][1] += 1
            elif ar.placement == 3:
                mvb_map[pid][2] += 1

    # Super Ball W-L: find championship series per MLTP season
    champ_winner_team_ids = set()
    champ_finalist_team_ids = set()
    all_series = list(
        PlayoffSeries.objects.filter(match__season__league__abbr="MLTP")
        .select_related("match", "winner")
    )
    season_series_map = defaultdict(list)
    for s in all_series:
        if s.match:
            season_series_map[s.match.season_id].append(s)

    for series_list in season_series_map.values():
        series_ids = {s.id for s in series_list}
        prev_ids = set()
        for s in series_list:
            if s.team1_prev_series_id:
                prev_ids.add(s.team1_prev_series_id)
            if s.team2_prev_series_id:
                prev_ids.add(s.team2_prev_series_id)
        root_ids = series_ids - prev_ids
        if len(root_ids) != 1:
            continue
        root = next(s for s in series_list if s.id in root_ids)
        if not root.match or not root.winner_id:
            continue
        t1, t2 = root.match.team1_id, root.match.team2_id
        winner = root.winner_id
        loser = t1 if winner == t2 else t2
        champ_winner_team_ids.add(winner)
        champ_finalist_team_ids.add(loser)

    # Map top-100 players to their Super Ball results across their MLTP seasons
    top_100_ps = list(
        PlayerSeason.objects.filter(
            player_id__in=top_100_player_ids,
            season__league__abbr="MLTP",
        )
        .only("player_id", "team_id")
    )
    sb_w_map = defaultdict(int)
    sb_l_map = defaultdict(int)
    for ps in top_100_ps:
        if ps.team_id is None:
            continue
        pid = ps.player_id
        if ps.team_id in champ_winner_team_ids:
            sb_w_map[pid] += 1
        elif ps.team_id in champ_finalist_team_ids:
            sb_l_map[pid] += 1

    # Ball of Fame recipients (MLTP only, 1st place) — map player_id to season name
    bof_seasons = {}
    for ar in AwardReceived.objects.filter(
        award__name__icontains="Ball of Fame",
        season__league__abbr="MLTP",
    ).select_related("season"):
        bof_seasons.setdefault(ar.player_id, []).append(ar.season.name)

    # Attach computed data to each top-100 entry
    for i, entry in enumerate(top_100):
        pid = entry["player_id"]
        entry["rank"] = i + 1
        entry["seasons_mltp"] = mltp_counts.get(pid, 0)
        g, s, b = mvb_map[pid]
        entry["mvb_display"] = "🥇" * g + "🥈" * s + "🥉" * b or "—"
        entry["mvb_sort"] = g
        entry["allstar"] = allstar_map.get(pid, 0)
        entry["sb_w"] = sb_w_map.get(pid, 0)
        entry["sb_l"] = sb_l_map.get(pid, 0)
        entry["bof"] = ", ".join(bof_seasons[pid]) if pid in bof_seasons else ""

    # Players with ≥1 MLTP season for the dropdown (alphabetical, including those with no legacy points)
    all_mltp_players = (
        Player.objects.filter(seasons_played__season__league__abbr="MLTP")
        .distinct()
        .order_by(Lower("name"))
    )
    dropdown_players = [
        {
            "name": p.name,
            "cube_sum": player_cube.get(p.id, 0.0),
        }
        for p in all_mltp_players
    ]

    # Leaderboard JSON for JS slider (all players with legacy points)
    leaderboard_json = json.dumps(
        [
            {"name": e["name"], "career_score": round(e["career_score"], 6), "cube_sum": e["cube_sum"]}
            for e in leaderboard
        ]
    )
    dropdown_json = json.dumps(dropdown_players)

    return render(
        req,
        "reference/career_leaders.html",
        {
            "top_100": top_100,
            "leaderboard_json": leaderboard_json,
            "dropdown_json": dropdown_json,
        },
    )


def franchise_history(req, franchise_id):
    """View franchise's history across all seasons."""
    franchise = get_object_or_404(Franchise, id=franchise_id)

    # Get league filter from query params
    league_filter = req.GET.get("league", "all")

    # Get all leagues for the filter dropdown
    all_leagues = League.objects.filter(gamemode="CTF").order_by("ordering")

    # Get all team seasons for this franchise
    team_seasons_query = TeamSeason.objects.filter(franchise=franchise).select_related(
        "season__league", "captain", "co_captain"
    )

    # Apply league filter
    if league_filter != "all":
        try:
            league_id = int(league_filter)
            team_seasons_query = team_seasons_query.filter(season__league_id=league_id)
        except ValueError:
            pass
    else:
        # Filter to CTF leagues only
        team_seasons_query = team_seasons_query.filter(season__league__gamemode="CTF")

    team_seasons = team_seasons_query.order_by("-season__end_date")

    # Build history data
    history_data = []
    for team in team_seasons:
        season = team.season

        # Get team rank and playoff finish from pre-calculated fields
        rank = team.seed if team.seed else "—"
        playoff_finish = team.playoff_finish if team.playoff_finish else "—"

        # Get team record from standings
        team_standings = get_team_standings(team)
        record = team_standings["record"]

        # Find player with highest TSCAR
        team_player_stats = aggregate_player_stats(season=season, franchise=franchise)
        if team_player_stats:
            best_tscar_stat = max(
                team_player_stats, key=lambda x: x.get("tscar", 0) or 0
            )
            best_tscar_player = best_tscar_stat["player"]
            best_tscar_value = best_tscar_stat.get("tscar", 0)
        else:
            best_tscar_player = None
            best_tscar_value = None

        history_data.append(
            {
                "season": season,
                "team": team,
                "rank": rank,
                "playoff_finish": playoff_finish,
                "record": record,
                "captain": team.captain,
                "co_captain": team.co_captain,
                "best_tscar_player": best_tscar_player,
                "best_tscar_value": best_tscar_value,
            }
        )

    # Get all-time player stats for this franchise using aggregate_player_stats
    if league_filter != "all":
        try:
            league_id = int(league_filter)
            league = League.objects.get(id=league_id)
            franchise_stats = aggregate_player_stats(
                franchise=franchise, league=league, week="all_regular_season"
            )
        except (ValueError, League.DoesNotExist):
            franchise_stats = aggregate_player_stats(
                franchise=franchise, week="all_regular_season"
            )
    else:
        franchise_stats = aggregate_player_stats(
            franchise=franchise, week="all_regular_season"
        )

    # Aggregate by player across all their seasons with this franchise
    player_aggregates = {}
    for stat in franchise_stats:
        player = stat["player"]

        if player not in player_aggregates:
            player_aggregates[player] = {
                "player": player,
                "time_played_min": 0,
                "tags": 0,
                "pops": 0,
                "grabs": 0,
                "drops": 0,
                "hold_sec": 0,
                "captures": 0,
                "prevent_sec": 0,
                "returns": 0,
                "powerups": 0,
                "oscar": 0,
                "dscar": 0,
                "tscar": 0,
            }

        # Aggregate each stat field
        agg = player_aggregates[player]
        agg["time_played_min"] += stat["time_played_min"]
        agg["tags"] += stat["tags"]
        agg["pops"] += stat["pops"]
        agg["grabs"] += stat["grabs"]
        agg["drops"] += stat["drops"]
        agg["hold_sec"] += stat["hold_sec"]
        agg["captures"] += stat["captures"]
        agg["prevent_sec"] += stat["prevent_sec"]
        agg["returns"] += stat["returns"]
        agg["powerups"] += stat["powerups"]
        agg["oscar"] += stat.get("oscar", 0) or 0
        agg["dscar"] += stat.get("dscar", 0) or 0
        agg["tscar"] += stat.get("tscar", 0) or 0

    # Convert to list and sort by time played (descending)
    all_time_stats = sorted(
        player_aggregates.values(), key=lambda x: -x["time_played_min"]
    )

    return render(
        req,
        "reference/franchise_history.html",
        {
            "franchise": franchise,
            "history_data": history_data,
            "all_time_stats": all_time_stats,
            "leagues": all_leagues,
            "current_league": league_filter,
        },
    )


def match_view(req, match_id):
    """Detailed view of a specific match with box score and player stats."""
    match = get_object_or_404(Match, id=match_id)
    season = match.season

    # Get all games in the match
    games = (
        Game.objects.filter(match=match)
        .select_related("red_team__franchise", "blue_team__franchise")
        .order_by("game_in_match")
    )

    box_score_data = calculate_match_box_score(match, games, include_details=True)

    # Get player stats for all games (default view)
    selected_game = req.GET.get("game", "all")

    # Filter games based on selection
    if selected_game == "all":
        stats_games = games
        show_map_info = False
    else:
        stats_games = games.filter(game_in_match=selected_game)
        show_map_info = len(stats_games) == 1

    # Get player stats for both teams using utility function
    team1_stats = get_match_team_stats(match, match.team1, selected_game)
    team2_stats = get_match_team_stats(match, match.team2, selected_game)

    # Get available games for dropdown
    game_options = [{"value": "all", "label": "All Games"}]
    for game in games:
        if game.game_in_match:
            # Use full game name as value to support halves/OT
            game_options.append(
                {"value": game.game_in_match, "label": game.game_in_match}
            )

    # Get map info if single game is selected
    map_info = None
    if show_map_info and stats_games:
        game = stats_games.first()
        map_info = {
            "map_name": game.map_name,
            "tagpro_eu_url": (
                f"https://tagpro.eu/?match={game.tagpro_eu}" if game.tagpro_eu else None
            ),
        }
        if game.resumed_tagpro_eu:
            map_info["resumed_tagpro_eu_url"] = (
                f"https://tagpro.eu/?match={game.resumed_tagpro_eu}"
            )

    return render(
        req,
        "reference/match_view.html",
        {
            "match": match,
            "season": season,
            "box_score_games": box_score_data["box_score_games"],
            "team1_total_score": box_score_data["team1_total"],
            "team2_total_score": box_score_data["team2_total"],
            "team1_total_caps": box_score_data["team1_total_caps"],
            "team2_total_caps": box_score_data["team2_total_caps"],
            "match_winner": box_score_data["match_winner"],
            "team1_stats": team1_stats,
            "team2_stats": team2_stats,
            "game_options": game_options,
            "selected_game": selected_game,
            "map_info": map_info,
            "can_edit": (
                req.user.is_authenticated and req.user.can_edit_season(season)
            ),
        },
    )


def _parse_eu_duration_seconds(duration_str):
    """Parse a duration string like '10:09' into total seconds."""
    parts = duration_str.strip().split(":")
    if len(parts) != 2:
        return 0
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return 0


def _build_active_season_group_names(season_filter=None):
    """Return a set of valid eu group names (e.g. 'NMRV') from all active seasons.

    If season_filter is given, match seasons by name (same logic as the import page).
    Otherwise, fall back to seasons ending within the past week or with no end date.
    """
    if season_filter:
        active_seasons = Season.objects.filter(name__contains=season_filter).select_related("league")
    else:
        one_week_ago = date.today() - timedelta(days=7)
        active_seasons = Season.objects.filter(
            models.Q(end_date__gte=one_week_ago) | models.Q(end_date__isnull=True)
        ).select_related("league")
    group_names = set()
    for season in active_seasons:
        prefix = season.league.eu_group_prefix
        if not prefix:
            continue
        for team in season.teams.all():
            group_names.add(prefix + team.abbr)
    return group_names


def _fetch_eu_recent_league_games(group_names, url=None):
    """
    Fetch a tagpro.eu matches page and return a list of (match_id, sort_key, flag) tuples
    for games where both teams are in group_names. Defaults to ?matches=group page 1.
    """
    if url is None:
        url = "https://tagpro.eu/?matches=group"
    req = urllib.request.Request(url, headers={"User-Agent": "tagpro-reference/1.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        html = response.read().decode("utf-8")

    soup = BeautifulSoup(html, "html.parser")
    results = []

    for row in soup.select("table tr"):
        id_cell = row.select_one("td:first-child a")
        if not id_cell:
            continue
        href = id_cell.get("href", "")
        if "?match=" not in href:
            continue
        try:
            match_id = int(href.split("?match=")[-1])
        except ValueError:
            continue

        team1_cell = row.select_one("td.matches-team1 a")
        team2_cell = row.select_one("td.matches-team2 a")
        if not team1_cell or not team2_cell:
            continue
        team1 = team1_cell.get_text(strip=True)
        team2 = team2_cell.get_text(strip=True)

        if team1 not in group_names or team2 not in group_names:
            continue

        # Duration is the td immediately before matches-score1; find it by position
        all_tds = row.find_all("td")
        score1_td = row.find("td", class_="matches-score1")
        score2_td = row.find("td", class_="matches-score2")
        if not score1_td or not score2_td:
            continue

        score1_td_index = all_tds.index(score1_td)
        if score1_td_index < 1:
            continue
        duration_td = all_tds[score1_td_index - 1]
        duration_str = duration_td.get_text(strip=True)
        duration_secs = _parse_eu_duration_seconds(duration_str)

        if duration_secs < 60:
            continue

        try:
            score1 = int(score1_td.get_text(strip=True))
            score2 = int(score2_td.get_text(strip=True))
        except ValueError:
            continue

        flagged = duration_secs < 600 or (duration_secs >= 600 and score1 == score2)
        sort_key = min(team1, team2)
        results.append((match_id, sort_key, flagged))

    results.sort(key=lambda x: (x[1], x[0]))
    return results


@data_entry_required(allow_new_data_only=True)
def recent_league_games(request):
    """Return a JSON list of tagpro.eu match IDs for recent league games."""
    try:
        custom_url = request.GET.get("url", "").strip()
        if custom_url and not re.match(r"^https://tagpro\.eu/\?matches=", custom_url):
            return JsonResponse({"error": "Invalid URL: must be a tagpro.eu matches page."}, status=400)
        season_filter = request.GET.get("season", "").strip() or None
        group_names = _build_active_season_group_names(season_filter=season_filter)
        games = _fetch_eu_recent_league_games(group_names, url=custom_url or None)
        ids = [
            f"{match_id} !!!" if flagged else str(match_id)
            for match_id, _sort_key, flagged in games
        ]
        return JsonResponse({"ids": ids})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@data_entry_required(allow_new_data_only=True)
def import_from_eus(request):
    """Render page where user can paste a list of tagpro.eus and start importing matches."""
    if request.method == "GET":
        return render(request, "reference/data_import.html")

    elif request.method == "POST":
        # Handle initial form submission with season filter and URLs
        if (
            "season_filter_string" in request.POST
            and "submit_game_data" not in request.POST
        ):
            season_filter_string = request.POST.get("season_filter_string", "").strip()
            eu_input = request.POST.get("eu_urls", "").strip()

            # Extract all numbers from the input using regex (these should be EU IDs)
            eu_ids = re.findall(r"\b(\d+)\b", eu_input)
            eu_urls = [f"https://tagpro.eu/?match={eu_id}" for eu_id in eu_ids]

            if not season_filter_string:
                messages.error(request, "Please enter a season filter string.")
                return render(request, "reference/data_import.html")

            if not eu_urls:
                messages.error(request, "Please enter at least one tagpro.eu URL.")
                return render(request, "reference/data_import.html")

            try:
                # Get season group
                season_group = [
                    s for s in Season.objects.all() if season_filter_string in s.name
                ]
                if not season_group:
                    messages.error(
                        request, f"No seasons found matching '{season_filter_string}'"
                    )
                    return render(request, "reference/data_import.html")

                # Process first URL
                current_url = eu_urls[0]
                remaining_urls = eu_urls[1:]

                form_data = prepopulate_form(season_filter_string, current_url)

                # Get dropdown options
                team_seasons = TeamSeason.objects.filter(season__in=season_group)
                matches = Match.objects.filter(season__in=season_group)
                player_seasons = PlayerSeason.objects.filter(season__in=season_group)
                all_players = Player.objects.all()

                return render(
                    request,
                    "reference/data_import_form.html",
                    {
                        "form_data": form_data,
                        "team_seasons": team_seasons,
                        "matches": matches,
                        "player_seasons": player_seasons,
                        "all_players": all_players,
                        "season_filter_string": season_filter_string,
                        "current_url": current_url,
                        "remaining_urls": remaining_urls,
                        "total_urls": len(eu_urls),
                        "current_index": 1,
                    },
                )

            except Exception as e:
                messages.error(request, f"Error processing URL: {str(e)}")
                return render(request, "reference/data_import.html")

        # Handle game data submission
        elif "submit_game_data" in request.POST:
            try:
                # Extract form data
                red_team_id = request.POST.get("red_team")
                blue_team_id = request.POST.get("blue_team")
                match_id = request.POST.get("match")
                week = request.POST.get("week", "").strip()
                game_in_match = request.POST.get("game_in_match")

                # Get objects
                red_team = (
                    TeamSeason.objects.get(id=red_team_id) if red_team_id else None
                )
                blue_team = (
                    TeamSeason.objects.get(id=blue_team_id) if blue_team_id else None
                )
                match = Match.objects.get(id=match_id) if match_id else None

                # Validate required fields
                if not week and not match:
                    raise Exception("Week is required when creating a new match")

                # Get game data from form
                eu_url = request.POST.get("eu_url")
                red_team_raw_name = request.POST.get("red_team_raw_name")
                blue_team_raw_name = request.POST.get("blue_team_raw_name")
                score_red = int(request.POST.get("red_team_score"))
                score_blue = int(request.POST.get("blue_team_score"))
                map_name = request.POST.get("map_name")
                map_id_raw = request.POST.get("map_id")
                try:
                    map_id = int(map_id_raw) if map_id_raw else None
                except (ValueError, TypeError):
                    map_id = None
                date_str = request.POST.get("date")
                date = datetime.strptime(date_str, "%Y-%m-%d").date()

                # Extract player data
                players = []
                player_count = 0
                while f"player_season_{player_count}" in request.POST:
                    player_season_id = request.POST.get(f"player_season_{player_count}")
                    player_id = request.POST.get(f"player_{player_count}")
                    season_team_id = request.POST.get(f"season_team_{player_count}")

                    player_data = {
                        "player_season": (
                            PlayerSeason.objects.get(id=player_season_id)
                            if player_season_id
                            else None
                        ),
                        "player": (
                            Player.objects.get(id=player_id) if player_id else None
                        ),
                        "player_username": request.POST.get(
                            f"player_username_{player_count}", ""
                        ),
                        "season_username": request.POST.get(
                            f"season_username_{player_count}", ""
                        ),
                        "season_team": (
                            TeamSeason.objects.get(id=season_team_id)
                            if season_team_id
                            else None
                        ),
                        "game_username": request.POST.get(
                            f"game_username_{player_count}", ""
                        ),
                        "game_team": request.POST.get(f"game_team_{player_count}", ""),
                    }
                    players.append(player_data)
                    player_count += 1

                # Submit data
                enter_confirmed_data(
                    red_team=red_team,
                    blue_team=blue_team,
                    red_team_raw_name=red_team_raw_name,
                    blue_team_raw_name=blue_team_raw_name,
                    match=match,
                    week=week,
                    game_in_match=game_in_match,
                    eu_url=eu_url,
                    score_red=score_red,
                    score_blue=score_blue,
                    map_name=map_name,
                    map_id=map_id,
                    date=date,
                    players=players,
                )

                messages.success(request, f"Game data saved successfully for {eu_url}")

                # Check if there are more URLs to process
                season_filter_string = request.POST.get("season_filter_string")
                remaining_urls = [
                    url
                    for url in request.POST.get("remaining_urls", "").split("|||")
                    if url.strip()
                ]

                if remaining_urls:
                    # Process next URL
                    current_url = remaining_urls[0]
                    remaining_urls = remaining_urls[1:]
                    current_index = int(request.POST.get("current_index", 1)) + 1
                    total_urls = int(request.POST.get("total_urls", 1))

                    form_data = prepopulate_form(season_filter_string, current_url)

                    # Get dropdown options
                    season_group = [
                        s
                        for s in Season.objects.all()
                        if season_filter_string in s.name
                    ]
                    team_seasons = TeamSeason.objects.filter(season__in=season_group)
                    matches = Match.objects.filter(season__in=season_group)
                    player_seasons = PlayerSeason.objects.filter(
                        season__in=season_group
                    )
                    all_players = Player.objects.all()

                    return render(
                        request,
                        "reference/data_import_form.html",
                        {
                            "form_data": form_data,
                            "team_seasons": team_seasons,
                            "matches": matches,
                            "player_seasons": player_seasons,
                            "all_players": all_players,
                            "season_filter_string": season_filter_string,
                            "current_url": current_url,
                            "remaining_urls": remaining_urls,
                            "total_urls": total_urls,
                            "current_index": current_index,
                        },
                    )
                else:
                    update_standings(red_team.season)
                    infer_playoff_series(red_team.season)
                    calculate_scar(red_team.season)
                    messages.success(request, "All URLs processed successfully!")
                    return redirect("import_data")

            except Exception as e:
                messages.error(request, f"Error saving game data: {str(e)}")
                # Return to form with error
                return render(
                    request,
                    "reference/data_import_form.html",
                    {"error": str(e), "form_data": request.POST},
                )


@data_entry_required(allow_new_data_only=True)
def preprocess_eu_links(request):
    """Form where user can paste EU links and get back JSON data."""
    if request.method == "GET":
        return render(request, "reference/preprocess_eu_links.html")

    elif request.method == "POST":
        season_filter_string = request.POST.get("season_filter_string", "").strip()
        eu_input = request.POST.get("eu_urls", "").strip()

        # Extract all numbers from the input using regex (these should be EU IDs)
        eu_ids = re.findall(r"\b(\d+)\b", eu_input)
        eu_urls = [f"https://tagpro.eu/?match={eu_id}" for eu_id in eu_ids]

        if not season_filter_string:
            messages.error(request, "Please enter a season filter string.")
            return render(request, "reference/preprocess_eu_links.html")

        if not eu_urls:
            messages.error(request, "Please enter at least one tagpro.eu URL.")
            return render(request, "reference/preprocess_eu_links.html")

        try:
            json_data = process_multiple_eu_links(season_filter_string, sorted(eu_urls))
            return render(
                request,
                "reference/preprocess_results.html",
                {
                    "json_data": format_compact_json(json_data),
                    "url_count": len(eu_urls),
                },
            )
        except Exception as e:
            messages.error(request, f"Error processing URLs: {str(e)}")
            return render(request, "reference/preprocess_eu_links.html")


@bulk_import_required
@transaction.atomic
def import_from_json(request):
    """Form where user can paste JSON data to import into database."""
    if request.method == "GET":
        return render(request, "reference/import_json.html")

    elif request.method == "POST":
        json_data_str = request.POST.get("json_data", "").strip()

        if not json_data_str:
            messages.error(request, "Please enter JSON data.")
            return render(request, "reference/import_json.html")

        try:
            json_data = json.loads(json_data_str)

            # Import data idempotently
            import_results = import_json_data_to_db(json_data)

            # Process stats for newly created games
            for game in import_results["created_games"]:
                process_game_stats(game)

            # Update standings for affected seasons
            for season in import_results["affected_seasons"]:
                update_standings(season)
                infer_playoff_series(season)
                calculate_scar(season)

            messages.success(
                request,
                f"Import completed: {import_results['created_count']} new games, {import_results['skipped_count']} already existed",
            )
            return render(request, "reference/import_json.html")

        except json.JSONDecodeError as e:
            messages.error(request, f"Invalid JSON: {str(e)}")
            return render(request, "reference/import_json.html")
        except Exception as e:
            messages.error(request, f"Error importing JSON: {str(e)}")
            return render(request, "reference/import_json.html")


@data_entry_required(allow_new_data_only=True)
@transaction.atomic
def paste_games_import(request):
    """Import individual games from pasted JSON into an existing match.

    Accepts a list of game objects (or a single object) in the same format
    used by the bulk JSON import, but only creates Games/PlayerGameLogs/Stats —
    it never creates or modifies Seasons, TeamSeasons, Players, or PlayerSeasons.
    """
    template = "reference/paste_games.html"

    if request.method == "GET":
        return render(request, template)

    match_id_str = request.POST.get("match_id", "").strip()
    games_json_str = request.POST.get("games_json", "").strip()

    if not match_id_str or not games_json_str:
        messages.error(request, "Both match ID and game JSON are required.")
        return render(request, template)

    try:
        match = Match.objects.select_related("season", "team1", "team2").get(id=int(match_id_str))
    except (Match.DoesNotExist, ValueError):
        messages.error(request, f"Match '{match_id_str}' not found.")
        return render(request, template)

    try:
        games_data = json.loads(games_json_str)
        if isinstance(games_data, dict):
            games_data = [games_data]
    except json.JSONDecodeError as e:
        messages.error(request, f"Invalid JSON: {e}")
        return render(request, template)

    season = match.season
    is_regular_season = match.week.startswith("Week")
    stat_field_set = set(STAT_FIELDS)

    player_seasons_by_name = {
        ps.playing_as: ps
        for ps in PlayerSeason.objects.filter(season=season)
    }
    teams_by_name = {
        match.team1.name: match.team1,
        match.team2.name: match.team2,
    }

    created = 0
    skipped = 0
    warnings = []

    for game_data in games_data:
        gim = game_data.get("game_in_match")

        if Game.objects.filter(match=match, game_in_match=gim).exists():
            skipped += 1
            continue

        red_team = teams_by_name.get(game_data.get("red_team", ""))
        blue_team = teams_by_name.get(game_data.get("blue_team", ""))

        if not red_team:
            warnings.append(f"{gim}: red team '{game_data.get('red_team')}' not found in match.")
            continue
        if not blue_team:
            warnings.append(f"{gim}: blue team '{game_data.get('blue_team')}' not found in match.")
            continue

        team1_score = game_data.get("team1_score") or 0
        team2_score = game_data.get("team2_score") or 0

        if team1_score > team2_score:
            outcome = "W"
        elif team2_score > team1_score:
            outcome = "L"
        else:
            outcome = "T"

        t1_sp, t2_sp = _compute_standing_points(outcome, is_regular_season, gim)

        game = Game.objects.create(
            match=match,
            red_team=red_team,
            blue_team=blue_team,
            team1_score=team1_score,
            team2_score=team2_score,
            map_name=game_data.get("map_name"),
            map_id=game_data.get("map_id"),
            game_in_match=gim,
            tagpro_eu=game_data.get("tagpro_eu"),
            outcome=outcome,
            team1_standing_points=t1_sp,
            team2_standing_points=t2_sp,
        )

        for player_data in game_data.get("players", []):
            playing_as = player_data.get("playing_as") or player_data.get("player_season")
            team = teams_by_name.get(player_data.get("team", ""))
            ps = player_seasons_by_name.get(playing_as)

            if not ps:
                warnings.append(f"{gim}: '{playing_as}' has no PlayerSeason in {season.name}.")
                continue
            if not team:
                warnings.append(f"{gim}: team '{player_data.get('team')}' not found for '{playing_as}'.")
                continue

            pgl = PlayerGameLog.objects.create(
                game=game,
                player_season=ps,
                playing_as=playing_as,
                team=team,
            )

            raw_stats = player_data.get("stats", {})
            stat_values = {field: raw_stats.get(field) or 0 for field in STAT_FIELDS if field in stat_field_set}
            PlayerStats.objects.create(player_gamelog=pgl, **stat_values)
            PlayerRegulationStats.objects.create(player_gamelog=pgl, **stat_values)

        created += 1

    update_standings(season)
    infer_playoff_series(season)
    calculate_scar(season)

    summary = f"{created} game(s) created, {skipped} already existed."
    if warnings:
        messages.warning(request, summary + " Warnings: " + " | ".join(warnings))
    else:
        messages.success(request, summary)

    return render(request, template, {"match": match})


@data_entry_required(season_param="season_id")
def edit_rosters_by_name(request, season_name):
    """Edit rosters view by season name."""
    # Convert dashes back to spaces
    season_name = season_name.replace("-", " ")
    season = get_object_or_404(Season, name=season_name)
    return edit_rosters(request, season.id)


@data_entry_required(season_param="season_id")
def edit_rosters(request, season_id):
    """Edit rosters view with player and playerseason management forms."""
    season = get_object_or_404(Season, id=season_id)

    # Handle form submissions
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "merge_players":
            try:
                to_merge_id = request.POST.get("to_merge_player")
                target_id = request.POST.get("target_player")
                to_merge = Player.objects.get(id=to_merge_id)
                target = Player.objects.get(id=target_id)
                merge_players(to_merge, target)
                messages.success(
                    request, f"Successfully merged {to_merge.name} into {target.name}"
                )
            except Exception as e:
                messages.error(request, f"Error merging players: {str(e)}")

        elif action == "merge_playerseasons":
            try:
                to_merge_id = request.POST.get("to_merge_playerseason")
                target_id = request.POST.get("target_playerseason")
                to_merge = PlayerSeason.objects.get(id=to_merge_id)
                target = PlayerSeason.objects.get(id=target_id)
                merge_player_seasons(to_merge, target)
                messages.success(
                    request, f"Successfully merged {to_merge} into {target}"
                )
            except Exception as e:
                messages.error(request, f"Error merging player seasons: {str(e)}")

        elif action == "change_team":
            try:
                playerseason_id = request.POST.get("playerseason_id")
                new_team_id = request.POST.get("new_team_id") or None
                playerseason = PlayerSeason.objects.get(id=playerseason_id)
                old_team = playerseason.team

                if new_team_id:
                    new_team = TeamSeason.objects.get(id=new_team_id)
                    playerseason.team = new_team
                else:
                    new_team = None
                    playerseason.team = None

                playerseason.save()
                old_team_name = old_team.name if old_team else "Unrostered"
                new_team_name = new_team.name if new_team else "Unrostered"
                messages.success(
                    request,
                    f"Changed {playerseason.playing_as} team from {old_team_name} to {new_team_name}",
                )
            except Exception as e:
                messages.error(request, f"Error changing team: {str(e)}")

        elif action == "add_award":
            try:
                playerseason_id = request.POST.get("playerseason_id")
                award_id = request.POST.get("award_id")
                placement = int(request.POST.get("placement"))
                vote_share_str = request.POST.get("vote_share", "").strip()

                playerseason = PlayerSeason.objects.get(id=playerseason_id)
                award_type = AwardType.objects.get(id=award_id)

                # Parse vote share
                vote_share = None
                if vote_share_str:
                    vote_share = float(vote_share_str)

                # Determine the team to associate with this award
                team = None
                if award_type.recipient_type in ["player", "captain"]:
                    # For player and captain awards, associate with their team
                    team = playerseason.team

                    # If no team but they're a captain/co-captain, try to find their team
                    if not team:
                        captain_teams = TeamSeason.objects.filter(
                            season=season, captain=playerseason.player
                        ).first()
                        if captain_teams:
                            team = captain_teams
                        else:
                            co_captain_teams = TeamSeason.objects.filter(
                                season=season, co_captain=playerseason.player
                            ).first()
                            if co_captain_teams:
                                team = co_captain_teams

                # Create the award
                AwardReceived.objects.create(
                    season=season,
                    team=team,
                    player=playerseason.player,
                    award=award_type,
                    placement=placement,
                    vote_share=vote_share,
                )

                messages.success(
                    request,
                    f"Added {award_type.name} (place {placement}) for {playerseason.player.name}",
                )
            except Exception as e:
                messages.error(request, f"Error adding award: {str(e)}")

        elif action == "rename_playerseason":
            try:
                playerseason_id = request.POST.get("playerseason_id")
                new_name = request.POST.get("new_playing_as")
                playerseason = PlayerSeason.objects.get(id=playerseason_id)
                old_name = playerseason.playing_as
                playerseason.playing_as = new_name
                playerseason.save()
                messages.success(
                    request, f"Renamed player season from {old_name} to {new_name}"
                )
            except Exception as e:
                messages.error(request, f"Error renaming player season: {str(e)}")

        elif action == "rename_player":
            try:
                player_id = request.POST.get("player_id")
                new_name = request.POST.get("new_player_name")
                player = Player.objects.get(id=player_id)
                old_name = player.name
                player.name = new_name
                player.save()
                messages.success(
                    request, f"Renamed player from {old_name} to {new_name}"
                )
            except Exception as e:
                messages.error(request, f"Error renaming player: {str(e)}")

        return redirect("edit_rosters", season_id=season.id)

    # Get all player seasons with stats for display
    player_seasons = (
        PlayerSeason.objects.filter(season=season)
        .select_related("player", "team")
        .order_by("team__name", "player__name")
    )

    # Get aggregated stats for minutes played
    stats = aggregate_player_stats(season=season)
    stats_dict = {stat["player_season"].id: stat for stat in stats}

    # Prepare roster data
    roster_data = []
    for ps in player_seasons:
        stat = stats_dict.get(ps.id, {})
        roster_data.append(
            {
                "playerseason": ps,
                "minutes": stat.get("time_played_min", 0),
            }
        )

    # Get all teams for dropdowns
    teams = TeamSeason.objects.filter(season=season).order_by("name")

    # Get all players and playerseasons for merge dropdowns (case-insensitive sort)
    all_players = Player.objects.all().order_by(Lower("name"))
    season_playerseasons = (
        PlayerSeason.objects.filter(season=season)
        .select_related("player")
        .order_by(Lower("playing_as"))
    )

    # Get all award types
    award_types = AwardType.objects.all().order_by("ordering")

    return render(
        request,
        "reference/edit_rosters.html",
        {
            "season": season,
            "all_seasons": Season.objects.all().order_by(
                F("end_date").desc(nulls_last=True)
            ),
            "roster_data": roster_data,
            "teams": teams,
            "all_players": all_players,
            "season_playerseasons": season_playerseasons,
            "award_types": award_types,
        },
    )


@data_entry_required(season_param="season_id")
def edit_season_by_name(request, season_name):
    """Edit season view by season name."""
    # Convert dashes back to spaces
    season_name = season_name.replace("-", " ")
    season = get_object_or_404(Season, name=season_name)
    return edit_season(request, season.id)


@data_entry_required(season_param="season_id")
def edit_season(request, season_id):
    """Edit season view with season, team, and match management forms."""
    season = get_object_or_404(Season, id=season_id)

    # Handle form submissions
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "change_end_date":
            try:
                new_end_date = request.POST.get("end_date")
                if new_end_date:
                    season.end_date = datetime.strptime(new_end_date, "%Y-%m-%d").date()
                else:
                    season.end_date = None
                season.save()
                messages.success(request, f"Updated end date for {season.name}")
            except Exception as e:
                messages.error(request, f"Error changing end date: {str(e)}")

        elif action == "change_captain":
            try:
                team_id = request.POST.get("team_id")
                captain_id = request.POST.get("captain_id") or None
                team = TeamSeason.objects.get(id=team_id)
                if captain_id:
                    team.captain = Player.objects.get(id=captain_id)
                else:
                    team.captain = None
                team.save()
                captain_name = team.captain.name if team.captain else "None"
                messages.success(
                    request, f"Changed {team.name} captain to {captain_name}"
                )
            except Exception as e:
                messages.error(request, f"Error changing captain: {str(e)}")

        elif action == "change_co_captain":
            try:
                team_id = request.POST.get("team_id")
                co_captain_id = request.POST.get("co_captain_id") or None
                team = TeamSeason.objects.get(id=team_id)
                if co_captain_id:
                    team.co_captain = Player.objects.get(id=co_captain_id)
                else:
                    team.co_captain = None
                team.save()
                co_captain_name = team.co_captain.name if team.co_captain else "None"
                messages.success(
                    request, f"Changed {team.name} co-captain to {co_captain_name}"
                )
            except Exception as e:
                messages.error(request, f"Error changing co-captain: {str(e)}")

        elif action == "change_logo":
            try:
                franchise_id = request.POST.get("franchise_id")
                logo_url = request.POST.get("logo_url")
                franchise = Franchise.objects.get(id=franchise_id)
                franchise.logo = logo_url if logo_url else None
                franchise.save()
                messages.success(request, f"Updated logo for {franchise.name}")
            except Exception as e:
                messages.error(request, f"Error changing logo: {str(e)}")

        elif action == "update_matches":
            try:
                updated_count = 0
                # Get all match IDs from the form
                match_ids = [
                    key.split("_")[1]
                    for key in request.POST.keys()
                    if key.startswith("week_")
                ]

                for match_id in match_ids:
                    match = Match.objects.get(id=match_id)
                    new_week = request.POST.get(f"week_{match_id}", "").strip()
                    new_vod = request.POST.get(f"vod_{match_id}", "").strip()

                    # Only update if there's a change
                    changed = False
                    if new_week and new_week != match.week:
                        match.week = new_week
                        changed = True

                    if new_vod != (match.vod or ""):
                        match.vod = new_vod if new_vod else None
                        changed = True

                    if changed:
                        match.save()
                        updated_count += 1

                if updated_count > 0:
                    messages.success(request, f"Updated {updated_count} match(es)")
                else:
                    messages.info(request, "No changes detected")
            except Exception as e:
                messages.error(request, f"Error updating matches: {str(e)}")

        elif action == "schedule_match":
            try:
                week = request.POST.get("week", "").strip()
                team1_id = request.POST.get("team1_id")
                team2_id = request.POST.get("team2_id")
                date_str = request.POST.get("date")
                team1 = TeamSeason.objects.get(id=team1_id, season=season)
                team2 = TeamSeason.objects.get(id=team2_id, season=season)
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
                match = Match.objects.create(
                    season=season, week=week, team1=team1, team2=team2, date=date
                )
                messages.success(request, f"Scheduled match: {match}")
            except Exception as e:
                messages.error(request, f"Error scheduling match: {str(e)}")

        elif action == "create_playoff_series":
            try:
                match_id = request.POST.get("match_id")
                team1_prev_id = request.POST.get("team1_prev_series_id") or None
                team2_prev_id = request.POST.get("team2_prev_series_id") or None
                match = Match.objects.get(id=match_id, season=season)
                team1_prev = (
                    PlayoffSeries.objects.get(id=team1_prev_id)
                    if team1_prev_id
                    else None
                )
                team2_prev = (
                    PlayoffSeries.objects.get(id=team2_prev_id)
                    if team2_prev_id
                    else None
                )
                PlayoffSeries.objects.create(
                    match=match,
                    team1_prev_series=team1_prev,
                    team2_prev_series=team2_prev,
                )
                messages.success(request, f"Created playoff series for {match}")
            except Exception as e:
                messages.error(request, f"Error creating playoff series: {str(e)}")

        return redirect("edit_season", season_id=season.id)

    # Get all teams for display and dropdowns
    teams = (
        TeamSeason.objects.filter(season=season)
        .select_related("franchise", "captain", "co_captain")
        .order_by("name")
    )

    # Get all players for dropdowns (case-insensitive sort)
    all_players = Player.objects.all().order_by(Lower("name"))

    # Get all franchises that have teams in this season
    franchises = (
        Franchise.objects.filter(team_seasons__season=season)
        .distinct()
        .order_by("name")
    )

    # Get all matches for this season, chronologically
    matches = (
        Match.objects.filter(season=season)
        .select_related("team1__franchise", "team2__franchise")
        .prefetch_related("games")
        .order_by("date", "id")
    )

    # Build simplified match data for table display
    matches_data = []
    for match in matches:
        games_count = match.games.count()
        matches_data.append(
            {
                "match": match,
                "games_count": games_count,
            }
        )

    latest_match = matches.last()
    latest_match_date = latest_match.date if latest_match else None
    latest_match_week = latest_match.week if latest_match else ""

    matches_desc = matches.order_by("-date", "-id")

    playoff_series_list = (
        PlayoffSeries.objects.filter(match__season=season)
        .select_related("match__team1", "match__team2")
        .order_by("-match__date", "-match__id")
    )

    return render(
        request,
        "reference/edit_season.html",
        {
            "season": season,
            "all_seasons": Season.objects.all().order_by(
                F("end_date").desc(nulls_last=True)
            ),
            "teams": teams,
            "all_players": all_players,
            "franchises": franchises,
            "matches_data": matches_data,
            "latest_match_date": latest_match_date,
            "latest_match_week": latest_match_week,
            "matches_desc": matches_desc,
            "playoff_series_list": playoff_series_list,
            "is_admin": (
                request.user.is_staff if request.user.is_authenticated else False
            ),
        },
    )


REGULAR_SEASON_STANDING_POINTS = {
    "W":   (3, 0),
    "OTW": (2, 1),
    "T":   (1, 1),
    "OTL": (1, 2),
    "L":   (0, 3),
}

PLAYOFF_STANDING_POINTS = {
    "W":   (1, 0),
    "OTW": (1, 0),
    "T":   (0, 0),
    "OTL": (0, 1),
    "L":   (0, 1),
}


def _compute_standing_points(outcome, is_regular_season, game_in_match):
    """
    Return (team1_standing_points, team2_standing_points) for a game.
    Half 2 and Overtime games return (None, None); their points are assigned
    to Half 1 by set_multi_half_outcomes during update_standings.
    """
    if not outcome:
        return None, None
    if game_in_match and ("Half" in game_in_match or "Overtime" in game_in_match):
        if "Half 1" not in game_in_match:
            return None, None
    table = REGULAR_SEASON_STANDING_POINTS if is_regular_season else PLAYOFF_STANDING_POINTS
    return table.get(outcome, (None, None))


def _parse_int_or_none(val):
    try:
        return int(val) if val and str(val).strip() else None
    except (ValueError, TypeError):
        return None


def _cascade_match_team_changes(match, old_team1, old_team2, new_team1, new_team2):
    if old_team1 != new_team1:
        Game.objects.filter(match=match, red_team=old_team1).update(red_team=new_team1)
        Game.objects.filter(match=match, blue_team=old_team1).update(blue_team=new_team1)
        PlayerGameLog.objects.filter(game__match=match, team=old_team1).update(team=new_team1)
    if old_team2 != new_team2:
        Game.objects.filter(match=match, red_team=old_team2).update(red_team=new_team2)
        Game.objects.filter(match=match, blue_team=old_team2).update(blue_team=new_team2)
        PlayerGameLog.objects.filter(game__match=match, team=old_team2).update(team=new_team2)


def _add_new_game_to_match(match, post):
    """Create a new game for an existing match from POST data. Returns the game or None if no data."""
    gim = post.get("new_game_game_in_match", "").strip() or None
    red_team_id = _parse_int_or_none(post.get("new_game_red_team_id"))
    blue_team_id = _parse_int_or_none(post.get("new_game_blue_team_id"))
    tagpro_eu_val = _parse_int_or_none(post.get("new_game_tagpro_eu"))

    if not gim and not red_team_id and not blue_team_id and not tagpro_eu_val:
        return None

    season = match.season
    red_team = TeamSeason.objects.get(id=red_team_id, season=season) if red_team_id else match.team1
    blue_team = TeamSeason.objects.get(id=blue_team_id, season=season) if blue_team_id else match.team2

    t1_score = _parse_int_or_none(post.get("new_game_team1_score")) or 0
    t2_score = _parse_int_or_none(post.get("new_game_team2_score")) or 0
    outcome = post.get("new_game_outcome") or None
    had_ot = bool(post.get("new_game_had_ot"))
    non_regulation = bool(post.get("new_game_non_regulation"))
    paused_time = _parse_int_or_none(post.get("new_game_paused_time"))
    resumed_tagpro_eu = _parse_int_or_none(post.get("new_game_resumed_tagpro_eu"))
    resumed_stats_count_until = _parse_int_or_none(post.get("new_game_resumed_stats_count_until"))
    is_regular_season = match.week.startswith("Week")

    map_name = None
    map_id = None

    if tagpro_eu_val:
        eu_data = extract_game_data(str(tagpro_eu_val))
        map_name = eu_data.get("map_name")
        map_id = eu_data.get("map_id")
        team1_is_red = red_team == match.team1
        t1_score = eu_data["team_red"]["score"] if team1_is_red else eu_data["team_blue"]["score"]
        t2_score = eu_data["team_blue"]["score"] if team1_is_red else eu_data["team_red"]["score"]

    t1_sp, t2_sp = _compute_standing_points(outcome, is_regular_season, gim)

    game = Game.objects.create(
        match=match,
        red_team=red_team,
        blue_team=blue_team,
        team1_score=t1_score,
        team2_score=t2_score,
        map_name=map_name,
        map_id=map_id,
        game_in_match=gim,
        tagpro_eu=tagpro_eu_val,
        paused_time=paused_time,
        resumed_tagpro_eu=resumed_tagpro_eu,
        resumed_stats_count_until=resumed_stats_count_until,
        outcome=outcome,
        team1_standing_points=t1_sp,
        team2_standing_points=t2_sp,
        had_ot=had_ot,
        non_regulation=non_regulation,
    )

    if tagpro_eu_val:
        player_seasons_by_username = {
            ps.playing_as: ps
            for ps in PlayerSeason.objects.filter(season=season)
        }
        for username in eu_data["team_red"]["players"]:
            ps = player_seasons_by_username.get(username)
            if ps:
                PlayerGameLog.objects.create(
                    game=game, player_season=ps, playing_as=username, team=red_team
                )
        for username in eu_data["team_blue"]["players"]:
            ps = player_seasons_by_username.get(username)
            if ps:
                PlayerGameLog.objects.create(
                    game=game, player_season=ps, playing_as=username, team=blue_team
                )
        process_game_stats(game)

    return game


def _handle_edit_match_update(request, match):
    post = request.POST
    season = match.season

    # Capture old teams before any changes
    old_team1 = match.team1
    old_team2 = match.team2

    new_team1_id = post.get("team1_id")
    new_team2_id = post.get("team2_id")
    new_date_str = post.get("date", "").strip()
    new_week = post.get("week", "").strip()
    new_vod = post.get("vod", "").strip() or None

    if new_team1_id:
        match.team1 = TeamSeason.objects.get(id=new_team1_id, season=season)
    if new_team2_id:
        match.team2 = TeamSeason.objects.get(id=new_team2_id, season=season)
    if new_date_str:
        match.date = datetime.strptime(new_date_str, "%Y-%m-%d").date()
    if new_week:
        match.week = new_week
    match.vod = new_vod
    match.save()

    _cascade_match_team_changes(match, old_team1, old_team2, match.team1, match.team2)

    # Update PlayoffSeries if one exists
    series = match.get_playoff_series()
    if series:
        winner_id = post.get("series_winner_id") or None
        t1_prev_id = post.get("series_team1_prev_id") or None
        t2_prev_id = post.get("series_team2_prev_id") or None
        series.winner = TeamSeason.objects.get(id=winner_id) if winner_id else None
        series.team1_prev_series = PlayoffSeries.objects.get(id=t1_prev_id) if t1_prev_id else None
        series.team2_prev_series = PlayoffSeries.objects.get(id=t2_prev_id) if t2_prev_id else None
        series.team1_game_wins = _parse_int_or_none(post.get("series_team1_game_wins"))
        series.team2_game_wins = _parse_int_or_none(post.get("series_team2_game_wins"))
        series.save()

    is_regular_season = match.week.startswith("Week")

    # Collect per-game updates
    games = list(match.games.all())
    game_updates = []
    for game in games:
        pk = game.pk
        outcome = post.get(f"game_{pk}_outcome") or None
        gim = post.get(f"game_{pk}_game_in_match", "").strip() or None
        t1_sp, t2_sp = _compute_standing_points(outcome, is_regular_season, gim)
        game_updates.append({
            "game": game,
            "game_in_match": gim,
            "tagpro_eu": _parse_int_or_none(post.get(f"game_{pk}_tagpro_eu")),
            "paused_time": _parse_int_or_none(post.get(f"game_{pk}_paused_time")),
            "resumed_tagpro_eu": _parse_int_or_none(post.get(f"game_{pk}_resumed_tagpro_eu")),
            "resumed_stats_count_until": _parse_int_or_none(post.get(f"game_{pk}_resumed_stats_count_until")),
            "red_team_id": _parse_int_or_none(post.get(f"game_{pk}_red_team_id")),
            "blue_team_id": _parse_int_or_none(post.get(f"game_{pk}_blue_team_id")),
            "team1_score": _parse_int_or_none(post.get(f"game_{pk}_team1_score")) or 0,
            "team2_score": _parse_int_or_none(post.get(f"game_{pk}_team2_score")) or 0,
            "outcome": outcome,
            "team1_standing_points": t1_sp,
            "team2_standing_points": t2_sp,
            "had_ot": bool(post.get(f"game_{pk}_had_ot")),
            "non_regulation": bool(post.get(f"game_{pk}_non_regulation")),
        })

    # Two-phase update to avoid unique constraint violations on game_in_match, tagpro_eu,
    # and resumed_tagpro_eu during intermediate states
    with transaction.atomic():
        for gu in game_updates:
            g = gu["game"]
            g.game_in_match = f"__tmp_{g.pk}__"
            g.tagpro_eu = None
            g.resumed_tagpro_eu = None
        Game.objects.bulk_update(
            [gu["game"] for gu in game_updates],
            ["game_in_match", "tagpro_eu", "resumed_tagpro_eu"],
        )

        for gu in game_updates:
            g = gu["game"]
            g.game_in_match = gu["game_in_match"]
            g.tagpro_eu = gu["tagpro_eu"]
            g.paused_time = gu["paused_time"]
            g.resumed_tagpro_eu = gu["resumed_tagpro_eu"]
            g.resumed_stats_count_until = gu["resumed_stats_count_until"]
            if gu["red_team_id"]:
                g.red_team_id = gu["red_team_id"]
            if gu["blue_team_id"]:
                g.blue_team_id = gu["blue_team_id"]
            g.team1_score = gu["team1_score"]
            g.team2_score = gu["team2_score"]
            g.outcome = gu["outcome"]
            g.team1_standing_points = gu["team1_standing_points"]
            g.team2_standing_points = gu["team2_standing_points"]
            g.had_ot = gu["had_ot"]
            g.non_regulation = gu["non_regulation"]
        Game.objects.bulk_update(
            [gu["game"] for gu in game_updates],
            [
                "game_in_match", "tagpro_eu", "paused_time", "resumed_tagpro_eu",
                "resumed_stats_count_until", "red_team", "blue_team",
                "team1_score", "team2_score", "outcome",
                "team1_standing_points", "team2_standing_points", "had_ot", "non_regulation",
            ],
        )

    _add_new_game_to_match(match, post)

    update_standings(season)
    infer_playoff_series(season)


@data_entry_required(match_param="match_id")
def edit_match(request, match_id):
    match = get_object_or_404(
        Match.objects.select_related("season", "team1", "team2"), id=match_id
    )
    season = match.season

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "update":
                _handle_edit_match_update(request, match)
                messages.success(request, "Match updated.")
            elif action == "delete_game":
                game_id = request.POST.get("game_id")
                game = Game.objects.get(id=game_id, match=match)
                label = game.game_in_match or str(game.id)
                game.delete()
                messages.success(request, f"Deleted {label}.")
            elif action == "delete_match":
                match.delete()
                messages.success(request, "Match deleted.")
                return redirect("edit_season", season_id=season.id)
            elif action == "reprocess":
                reprocess_match(match)
                messages.success(request, "Stats reprocessed.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
        return redirect("edit_match", match_id=match_id)

    games = match.games.order_by("game_in_match").select_related("red_team__franchise", "blue_team__franchise")
    teams = TeamSeason.objects.filter(season=season).order_by("name")
    playoff_series = match.get_playoff_series()
    other_series = (
        PlayoffSeries.objects.filter(match__season=season)
        .exclude(match=match)
        .select_related("match__team1", "match__team2")
        .order_by("match__date")
    )

    return render(
        request,
        "reference/edit_match.html",
        {
            "match": match,
            "season": season,
            "games": games,
            "teams": teams,
            "playoff_series": playoff_series,
            "other_series": other_series,
            "outcome_choices": Game.OUTCOMES,
        },
    )


@full_data_permissions_required
def edit_logos(request):
    """Edit logos view for managing franchise logos."""
    static_logos_dir = os.path.join(
        django_settings.BASE_DIR, "reference", "static", "reference", "logos"
    )
    media_logos_dir = os.path.join(django_settings.MEDIA_ROOT, "logos")

    # Ensure media logos directory exists
    os.makedirs(media_logos_dir, exist_ok=True)

    # Handle form submissions
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "upload_logo":
            try:
                uploaded_file = request.FILES.get("logo_file")
                filename = request.POST.get("filename", "").strip()
                if uploaded_file and filename:
                    # Ensure filename has an extension
                    if "." not in filename:
                        _, ext = os.path.splitext(uploaded_file.name)
                        filename = filename + ext
                    # Save to media directory
                    filepath = os.path.join(media_logos_dir, filename)
                    with open(filepath, "wb+") as destination:
                        for chunk in uploaded_file.chunks():
                            destination.write(chunk)
                    messages.success(request, f"Uploaded logo as {filename}")
                else:
                    messages.error(request, "Please provide both a file and filename")
            except Exception as e:
                messages.error(request, f"Error uploading logo: {str(e)}")

        elif action == "set_franchise_logo":
            try:
                franchise_id = request.POST.get("franchise_id")
                logo_path = request.POST.get("logo_path", "").strip()
                franchise = Franchise.objects.get(id=franchise_id)
                franchise.logo = logo_path if logo_path else None
                franchise.save()
                messages.success(request, f"Updated logo for {franchise.name}")
            except Exception as e:
                messages.error(request, f"Error setting logo: {str(e)}")

        elif action == "assign_logo":
            try:
                logo_filename = request.POST.get("logo_filename")
                franchise_id = request.POST.get("franchise_id")
                logo_source = request.POST.get("logo_source")
                if franchise_id and logo_filename:
                    franchise = Franchise.objects.get(id=franchise_id)
                    if logo_source == "media":
                        franchise.logo = f"media/logos/{logo_filename}"
                    else:
                        franchise.logo = f"logos/{logo_filename}"
                    franchise.save()
                    messages.success(
                        request, f"Assigned {logo_filename} to {franchise.name}"
                    )
            except Exception as e:
                messages.error(request, f"Error assigning logo: {str(e)}")

        elif action == "batch_assign_logos":
            assigned_count = 0
            for key, franchise_id in request.POST.items():
                if not franchise_id or not key.startswith("assign["):
                    continue
                # Extract logo path from key like "assign[logos/ABC.png]"
                logo_path = key[7:-1]  # Remove "assign[" and "]"
                try:
                    franchise = Franchise.objects.get(id=franchise_id)
                    franchise.logo = logo_path
                    franchise.save()
                    assigned_count += 1
                except Franchise.DoesNotExist:
                    continue

            if assigned_count > 0:
                messages.success(request, f"Assigned {assigned_count} logo(s)")
            else:
                messages.info(request, "No logos were assigned")

        return redirect("edit_logos")

    # Get all franchises
    franchises = Franchise.objects.all().order_by("name")

    # Get all logo paths currently in use
    used_logo_paths = set(
        Franchise.objects.exclude(logo__isnull=True)
        .exclude(logo="")
        .values_list("logo", flat=True)
    )

    # Scan static logos directory
    static_logos = []
    if os.path.exists(static_logos_dir):
        for filename in os.listdir(static_logos_dir):
            if filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                logo_path = f"logos/{filename}"
                static_logos.append(
                    {
                        "filename": filename,
                        "path": logo_path,
                        "source": "static",
                        "url": f"/static/reference/{logo_path}",
                        "assigned": logo_path in used_logo_paths,
                    }
                )

    # Scan media logos directory
    media_logos = []
    if os.path.exists(media_logos_dir):
        for filename in os.listdir(media_logos_dir):
            if filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                logo_path = f"media/logos/{filename}"
                media_logos.append(
                    {
                        "filename": filename,
                        "path": logo_path,
                        "source": "media",
                        "url": f"/media/logos/{filename}",
                        "assigned": logo_path in used_logo_paths,
                    }
                )

    # Get unassigned logos from both sources
    unassigned_static = [logo for logo in static_logos if not logo["assigned"]]
    unassigned_media = [logo for logo in media_logos if not logo["assigned"]]

    # Sort by filename
    unassigned_static.sort(key=lambda x: x["filename"].lower())
    unassigned_media.sort(key=lambda x: x["filename"].lower())

    return render(
        request,
        "reference/edit_logos.html",
        {
            "franchises": franchises,
            "unassigned_static": unassigned_static,
            "unassigned_media": unassigned_media,
        },
    )
