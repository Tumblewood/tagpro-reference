from django.urls import path
from . import views

urlpatterns = [
    path('', views.homepage, name='homepage'),
    path('search/<str:query>/', views.search_results, name='search_results'),
    path('league/<int:league_id>/', views.league_history, name='league_history'),
    path('season/<int:season_id>/', views.season_home, name='season_home'),
    path('season/<int:season_id>/schedule/', views.season_schedule, name='season_schedule'),
    path('season/<int:season_id>/stats/', views.season_stats, name='season_stats'),
    path('season/<int:season_id>/rosters/', views.season_rosters, name='season_rosters'),
    path('player/<int:player_id>/', views.player_history, name='player_history'),
    path('team/<int:team_id>/', views.team_season, name='team_season'),
    path('franchise/<int:franchise_id>/', views.franchise_history, name='franchise_history'),
    path('match/<int:match_id>/', views.match_view, name='match_view'),
    path('import/eu/', views.import_from_eus, name='import_data'),
    path('import/preprocess/', views.preprocess_eu_links, name='preprocess_eu_links'),
    path('import/json/', views.import_from_json, name='import_from_json'),
    path('edit/rosters/<int:season_id>/', views.edit_rosters, name='edit_rosters'),
]