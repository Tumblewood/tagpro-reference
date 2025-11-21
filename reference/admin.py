from django.contrib import admin
from .models import League, Franchise, Player, Season, TeamSeason, PlayerSeason, Match, PlayoffSeries, Game, PlayerGameLog, PlayerStats, PlayerRegulationStats, AwardType, AwardReceived, Transaction
from .utils import stat_collection


@admin.action(description="Reprocess stats from the game")
def reprocess(modeladmin, request, queryset):
    for g in queryset:
        stat_collection.process_game_stats(g)


@admin.action(description="Recalculate standings for the season")
def recalculate_standings(modeladmin, request, queryset):
    """Re-aggregate stats for the season."""
    for season in queryset:
        stat_collection.update_standings(season)
        stat_collection.infer_playoff_series(season)
        stat_collection.calculate_scar(season)


@admin.action(description="Calculate SCAR for all players in the season")
def calculate_scar(modeladmin, request, queryset):
    """Calculate OSCAR and DSCAR for all players in the season."""
    for season in queryset:
        stat_collection.calculate_scar(season)


@admin.action(description="Process stats for the season")
def process_season(modeladmin, request, queryset):
    """(Re-)process stats for the season."""
    for season in queryset:
        games = Game.objects.filter(match__season=season)
        for game in games:
            stat_collection.process_game_stats(game)
        stat_collection.update_standings(season)
        stat_collection.infer_playoff_series(season)
        stat_collection.calculate_scar(season)


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
    actions = [recalculate_standings, process_season, calculate_scar]


class FranchiseAdmin(admin.ModelAdmin):
    search_fields = ['name', 'abbr']
    list_display = ["name", "abbr"]
    actions = [add_logo_path]
    inlines = [TeamSeasonInline]


class TeamSeasonAdmin(admin.ModelAdmin):
    search_fields = ['name']
    inlines = [PlayerSeasonInline]


class MatchAdmin(admin.ModelAdmin):
    list_filter = ["season"]
    search_fields = ["team1", "team2"]
    inlines = [GameInline, PlayoffSeriesInline]


class GameAdmin(admin.ModelAdmin):
    actions = [reprocess]
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
    PlayerStats,
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
admin.site.register(PlayerRegulationStats, PlayerRegulationGameStatsAdmin)