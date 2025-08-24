from django.contrib import admin
from .models import League, Franchise, Player, Season, TeamSeason, PlayerSeason, Match, PlayoffSeries, Game, PlayerGameLog, PlayerGameStats, PlayerRegulationGameStats, PlayerWeekStats, PlayerSeasonStats, AwardType, AwardReceived, Transaction
from .views import stat_collection
from .views.data_entry import infer_playoff_series


@admin.action(description="Reprocess stats from the game")
def reprocess(modeladmin, request, queryset):
    for g in queryset:
        stat_collection.process_game_stats(g)
        
    player_seasons = PlayerGameLog.objects.filter(
        game__in=queryset
    ).values('player_season', flat=True).distinct()
    for ps in player_seasons:
        stat_collection.reaggregate_stats(PlayerSeason.objects.get(id=ps['player_season']))


@admin.action(description="Re-aggregate stats for the season")
def reaggregate_season(modeladmin, request, queryset):
    """Re-aggregate stats for the season."""
    for season in queryset:
        # Get all games for this season
        player_seasons = PlayerSeason.objects.filter(season=season)
        
        # Re-aggregate each game
        for ps in player_seasons:
            stat_collection.reaggregate_stats(ps)
        
        # Update season standings
        stat_collection.update_standings(season)
        
        # Infer playoff series
        infer_playoff_series(season)


@admin.action(description="Re-process stats for the season")
def reprocess_season(modeladmin, request, queryset):
    """Re-aggregate stats for the season."""
    for season in queryset:
        # Get all games for this season
        games = Game.objects.filter(match__season=season)
        
        # Re-aggregate each game
        for game in games:
            stat_collection.process_game_stats(game)
        
        # Update season standings
        stat_collection.update_standings(season)
        
        # Infer playoff series
        infer_playoff_series(season)


@admin.action(description="Add logo path")
def add_logo_path(modeladmin, request, queryset):
    for f in queryset:
        f.logo = f"logos/{f.abbr}.png"
        f.save()


class TeamSeasonInline(admin.TabularInline):
    model = TeamSeason


class PlayerSeasonInline(admin.TabularInline):
    model = PlayerSeason


class PlayoffSeriesInline(admin.StackedInline):
    model = PlayoffSeries


class GameInline(admin.TabularInline):
    model = Game


class PlayerGameLogInline(admin.TabularInline):
    model = PlayerGameLog


class SeasonAdmin(admin.ModelAdmin):
    search_fields = ['name']
    inlines = [TeamSeasonInline]
    actions = [reaggregate_season, reprocess_season]


class FranchiseAdmin(admin.ModelAdmin):
    search_fields = ['name', 'abbr']
    actions = [add_logo_path]
    inlines = [TeamSeasonInline]


class TeamSeasonAdmin(admin.ModelAdmin):
    search_fields = ['name']
    inlines = [PlayerSeasonInline]


class MatchAdmin(admin.ModelAdmin):
    list_filter = ["team1", "team2"]
    inlines = [GameInline, PlayoffSeriesInline]


class GameAdmin(admin.ModelAdmin):
    actions = [reprocess]
    inlines = [PlayerGameLogInline]
    search_fields = ['tagpro_eu', 'resumed_tagpro_eu']
    list_filter = ['match__season']


class PlayerSeasonAdmin(admin.ModelAdmin):
    search_fields = ['player__name', 'playing_as']
    list_filter = ['season', 'team__franchise__name']


class PlayerGameLogAdmin(admin.ModelAdmin):
    search_fields = ['player_season__playing_as']


class PlayerRegulationGameStatsAdmin(admin.ModelAdmin):
    search_fields = ['player_gamelog__player_season__playing_as']
    list_filter = ['player_gamelog__game__match__season']


admin.site.register([
    League,
    Player,
    PlayoffSeries,
    PlayerGameStats,
    PlayerWeekStats,
    PlayerSeasonStats,
    AwardType,
    AwardReceived,
    Transaction
])

admin.site.register(Season, SeasonAdmin)
admin.site.register(Franchise, FranchiseAdmin)
admin.site.register(TeamSeason, TeamSeasonAdmin)
admin.site.register(Match, MatchAdmin)
admin.site.register(Game, GameAdmin)
admin.site.register(PlayerSeason, PlayerSeasonAdmin)
admin.site.register(PlayerGameLog, PlayerGameLogAdmin)
admin.site.register(PlayerRegulationGameStats, PlayerRegulationGameStatsAdmin)