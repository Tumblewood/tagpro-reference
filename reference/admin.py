from django.contrib import admin
from .models import League, Franchise, Player, Season, TeamSeason, PlayerSeason, Match, PlayoffSeries, Game, PlayerGameLog, PlayerGameStats, PlayerWeekStats, PlayerSeasonStats, AwardType, AwardReceived, Transaction
from .views import stat_collection


@admin.action(description="Reprocess stats from the game")
def reprocess(modeladmin, request, queryset):
    for g in queryset:
        stat_collection.process_game_stats(g)


class PlayoffSeriesInline(admin.StackedInline):
    model = PlayoffSeries


class GameInline(admin.TabularInline):
    model = Game


class PlayerGameLogInline(admin.TabularInline):
    model = PlayerGameLog


class MatchAdmin(admin.ModelAdmin):
    list_filter = ["team1", "team2"]
    inlines = [GameInline, PlayoffSeriesInline]


class GameAdmin(admin.ModelAdmin):
    actions = [reprocess]
    inlines = [PlayerGameLogInline]
    search_fields = ['tagpro_eu', 'resumed_tagpro_eu']


class PlayerSeasonAdmin(admin.ModelAdmin):
    search_fields = ['player__name', 'playing_as']
    list_filter = ['season', 'team__franchise__name']


class PlayerGameLogAdmin(admin.ModelAdmin):
    search_fields = ['player_season__playing_as']


admin.site.register([
    League,
    Franchise,
    Player,
    Season,
    TeamSeason,
    PlayoffSeries,
    PlayerGameStats,
    PlayerWeekStats,
    PlayerSeasonStats,
    AwardType,
    AwardReceived,
    Transaction
])

admin.site.register(Match, MatchAdmin)
admin.site.register(Game, GameAdmin)
admin.site.register(PlayerSeason, PlayerSeasonAdmin)
admin.site.register(PlayerGameLog, PlayerGameLogAdmin)