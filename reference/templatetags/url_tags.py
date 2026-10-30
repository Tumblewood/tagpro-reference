from django import template
from django.urls import reverse
from reference.utils.award_icons import award_icon_path, trophy_icon_path
from reference.utils.display_info import CHAMPIONSHIP_FINISHES

register = template.Library()


@register.simple_tag
def logo_url(logo_path):
    """Generate URL for a logo, handling both static and media paths."""
    if not logo_path:
        return ""
    if logo_path.startswith("media/"):
        return f"/{logo_path}"
    return f"/static/reference/{logo_path}"


@register.simple_tag
def award_icon_url(award_type, league, placement=1):
    """URL of the medal or ribbon for placing in an award, or "" if there isn't one."""
    if award_type is None:
        return ""
    return logo_url(award_icon_path(award_type.icon, league.abbr, placement))


@register.simple_tag
def trophy_icon_url(league):
    """URL of the trophy for winning a league's championship."""
    return logo_url(trophy_icon_path(league))


@register.filter
def is_championship(playoff_finish):
    """Whether a TeamSeason.playoff_finish means the team won its league."""
    return playoff_finish in CHAMPIONSHIP_FINISHES


@register.simple_tag
def league_url(league):
    """Generate URL for league using abbreviation."""
    if hasattr(league, "abbr") and league.abbr:
        league_abbr = league.abbr.replace(" ", "-")
        return reverse("league_history_by_abbr", args=[league_abbr])
    else:
        return reverse("league_history", args=[league.id])


def season_url_name(season):
    """Season name as it appears in URLs, with spaces turned into dashes."""
    return season.name.replace(" ", "-")


@register.simple_tag
def player_season_url(player, season):
    """Generate URL for a player's page for a single season."""
    return reverse("player_season", args=[player.name, season_url_name(season)])


@register.simple_tag
def season_url(season, page="home"):
    """Generate URL for season using name."""
    if hasattr(season, "name") and season.name:
        season_name = season_url_name(season)
        if page == "home":
            return reverse("season_home_by_name", args=[season_name])
        elif page == "schedule":
            return reverse("season_schedule_by_name", args=[season_name])
        elif page == "stats":
            return reverse("season_stats_by_name", args=[season_name])
        elif page == "rosters":
            return reverse("season_rosters_by_name", args=[season_name])
        elif page == "awards":
            return reverse("season_awards_by_name", args=[season_name])

    # Fallback to ID-based URLs
    if page == "home":
        return reverse("season_home", args=[season.id])
    elif page == "schedule":
        return reverse("season_schedule", args=[season.id])
    elif page == "stats":
        return reverse("season_stats", args=[season.id])
    elif page == "rosters":
        return reverse("season_rosters", args=[season.id])
    elif page == "awards":
        return reverse("season_awards", args=[season.id])
