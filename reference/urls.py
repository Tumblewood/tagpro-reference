from django.urls import path
from . import views

urlpatterns = [
    path("", views.homepage, name="homepage"),
    path("search/<str:query>/", views.search_results, name="search_results"),
    path("league/<int:league_id>/", views.league_history, name="league_history"),
    path(
        "league/<str:league_abbr>/",
        views.league_history_by_abbr,
        name="league_history_by_abbr",
    ),
    path("season/<int:season_id>/", views.season_home, name="season_home"),
    path(
        "season/<int:season_id>/schedule/",
        views.season_schedule,
        name="season_schedule",
    ),
    path("season/<int:season_id>/stats/", views.season_stats, name="season_stats"),
    path(
        "season/<int:season_id>/rosters/", views.season_rosters, name="season_rosters"
    ),
    path("season/<int:season_id>/awards/", views.season_awards, name="season_awards"),
    path(
        "season/<str:season_name>/",
        views.season_home_by_name,
        name="season_home_by_name",
    ),
    path(
        "season/<str:season_name>/schedule/",
        views.season_schedule_by_name,
        name="season_schedule_by_name",
    ),
    path(
        "season/<str:season_name>/stats/",
        views.season_stats_by_name,
        name="season_stats_by_name",
    ),
    path(
        "season/<str:season_name>/rosters/",
        views.season_rosters_by_name,
        name="season_rosters_by_name",
    ),
    path(
        "season/<str:season_name>/awards/",
        views.season_awards_by_name,
        name="season_awards_by_name",
    ),
    path("resources/faq/", views.resources_faq, name="resources_faq"),
    path("resources/glossary/", views.resources_glossary, name="resources_glossary"),
    path("resources/scar/", views.resources_scar, name="resources_scar"),
    path("resources/legacy/", views.resources_legacy, name="resources_legacy"),
    path("leaders/legacy/", views.legacy_leaders, name="legacy_leaders"),
    path("leaders/career/", views.career_leaders, name="career_leaders"),
    path("player/<path:player_name>", views.player_history, name="player_history"),
    path("team/<int:team_id>/", views.team_season, name="team_season"),
    path(
        "franchise/<int:franchise_id>/",
        views.franchise_history,
        name="franchise_history",
    ),
    path("match/<int:match_id>/", views.match_view, name="match_view"),
    path("import/eu/", views.import_from_eus, name="import_data"),
    path("import/recent-games/", views.recent_league_games, name="recent_league_games"),
    path("import/preprocess/", views.preprocess_eu_links, name="preprocess_eu_links"),
    path("import/json/", views.import_from_json, name="import_from_json"),
    path("import/paste-games/", views.paste_games_import, name="paste_games_import"),
    path("edit/rosters/<int:season_id>/", views.edit_rosters, name="edit_rosters"),
    path(
        "edit/rosters/<str:season_name>/",
        views.edit_rosters_by_name,
        name="edit_rosters_by_name",
    ),
    path("edit/season/<int:season_id>/", views.edit_season, name="edit_season"),
    path(
        "edit/season/<str:season_name>/",
        views.edit_season_by_name,
        name="edit_season_by_name",
    ),
    path("edit/match/<int:match_id>/", views.edit_match, name="edit_match"),
    path("edit/logos/", views.edit_logos, name="edit_logos"),
]
