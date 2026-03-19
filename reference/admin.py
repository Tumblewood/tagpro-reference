from django.contrib import admin
from django.contrib import messages
from .models import (
    League,
    Franchise,
    Player,
    Season,
    TeamSeason,
    PlayerSeason,
    Match,
    PlayoffSeries,
    Game,
    PlayerGameLog,
    PlayerStats,
    PlayerRegulationStats,
    AwardType,
    AwardReceived,
    Transaction,
)
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


@admin.action(description="Set season end date to last game date")
def set_end_date_to_last_game(modeladmin, request, queryset):
    """Set the season's end date to the date of the last game, unless already set to a later date."""
    for season in queryset:
        last_match = season.matches.order_by("-date").first()
        if last_match:
            last_game_date = last_match.date
            if season.end_date is None or season.end_date < last_game_date:
                season.end_date = last_game_date
                season.save()


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
    search_fields = ["name"]
    inlines = [TeamSeasonInline]
    actions = [
        recalculate_standings,
        process_season,
        calculate_scar,
        set_end_date_to_last_game,
    ]


class FranchiseAdmin(admin.ModelAdmin):
    search_fields = ["name", "abbr"]
    list_display = ["name", "abbr"]
    actions = [add_logo_path]
    inlines = [TeamSeasonInline]


class TeamSeasonAdmin(admin.ModelAdmin):
    search_fields = ["name"]
    inlines = [PlayerSeasonInline]


class MatchAdmin(admin.ModelAdmin):
    list_filter = ["season"]
    search_fields = ["team1", "team2"]
    inlines = [GameInline, PlayoffSeriesInline]


class GameAdmin(admin.ModelAdmin):
    actions = [reprocess]
    search_fields = ["tagpro_eu", "resumed_tagpro_eu"]
    list_filter = ["match__season"]


@admin.action(description="Calculate legacy points")
def calculate_legacy_points_action(modeladmin, request, queryset):
    from .utils.legacy_points import calculate_legacy_points

    updated = 0
    skipped = 0
    for ps in queryset.select_related("season__league", "player", "team"):
        points = calculate_legacy_points(ps)
        if points is not None:
            ps.legacy_points = points
            ps.save(update_fields=["legacy_points"])
            updated += 1
        else:
            skipped += 1

    messages.success(
        request,
        f"Legacy points calculated: {updated} updated, {skipped} skipped (ineligible).",
    )


class PlayerSeasonAdmin(admin.ModelAdmin):
    search_fields = ["player__name", "playing_as"]
    list_filter = ["season", "team__franchise__name"]
    actions = [calculate_legacy_points_action]


class PlayerGameLogAdmin(admin.ModelAdmin):
    search_fields = ["player_season__playing_as"]


class PlayerRegulationGameStatsAdmin(admin.ModelAdmin):
    search_fields = ["player_gamelog__player_season__playing_as"]
    list_filter = ["player_gamelog__game__match__season"]


class AwardReceivedAdmin(admin.ModelAdmin):
    search_fields = ["player__name", "team__name"]
    list_filter = ["award", "season"]
    list_display = ["season", "award", "player", "team", "placement"]


class AwardTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "abbr", "ordering", "recipient_type"]


admin.site.register([League, Player, PlayoffSeries, PlayerStats, Transaction])

admin.site.register(Season, SeasonAdmin)
admin.site.register(Franchise, FranchiseAdmin)
admin.site.register(TeamSeason, TeamSeasonAdmin)
admin.site.register(Match, MatchAdmin)
admin.site.register(Game, GameAdmin)
admin.site.register(PlayerSeason, PlayerSeasonAdmin)
admin.site.register(PlayerGameLog, PlayerGameLogAdmin)
admin.site.register(PlayerRegulationStats, PlayerRegulationGameStatsAdmin)
admin.site.register(AwardType, AwardTypeAdmin)
admin.site.register(AwardReceived, AwardReceivedAdmin)
