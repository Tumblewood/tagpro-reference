from django.urls import path
from .views import data_entry, info_pages

urlpatterns = [
    path('', info_pages.homepage, name='homepage'),
    path('search/<str:query>/', info_pages.search_results, name='search_results'),
    path('league/<int:league_id>/', info_pages.league_history, name='league_history'),
    path('season/<int:season_id>/', info_pages.season_home, name='season_home'),
    path('season/<int:season_id>/schedule/', info_pages.season_schedule, name='season_schedule'),
    path('season/<int:season_id>/stats/', info_pages.season_stats, name='season_stats'),
    path('season/<int:season_id>/rosters/', info_pages.season_rosters, name='season_rosters'),
    path('player/<int:player_id>/', info_pages.player_history, name='player_history'),
    path('team/<int:team_id>/', info_pages.team_season, name='team_season'),
    path('franchise/<int:franchise_id>/', info_pages.franchise_history, name='franchise_history'),
    path('match/<int:match_id>/', info_pages.match_view, name='match_view'),
    path('data/import/', data_entry.import_from_eus, name='import_data'),
]