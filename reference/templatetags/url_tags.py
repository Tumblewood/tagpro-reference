from django import template
from django.urls import reverse

register = template.Library()

@register.simple_tag
def league_url(league):
    """Generate URL for league using abbreviation."""
    if hasattr(league, 'abbr') and league.abbr:
        league_abbr = league.abbr.replace(' ', '-')
        return reverse('league_history_by_abbr', args=[league_abbr])
    else:
        return reverse('league_history', args=[league.id])

@register.simple_tag
def season_url(season, page='home'):
    """Generate URL for season using name."""
    if hasattr(season, 'name') and season.name:
        season_name = season.name.replace(' ', '-')
        if page == 'home':
            return reverse('season_home_by_name', args=[season_name])
        elif page == 'schedule':
            return reverse('season_schedule_by_name', args=[season_name])
        elif page == 'stats':
            return reverse('season_stats_by_name', args=[season_name])
        elif page == 'rosters':
            return reverse('season_rosters_by_name', args=[season_name])
        elif page == 'awards':
            return reverse('season_awards_by_name', args=[season_name])

    # Fallback to ID-based URLs
    if page == 'home':
        return reverse('season_home', args=[season.id])
    elif page == 'schedule':
        return reverse('season_schedule', args=[season.id])
    elif page == 'stats':
        return reverse('season_stats', args=[season.id])
    elif page == 'rosters':
        return reverse('season_rosters', args=[season.id])
    elif page == 'awards':
        return reverse('season_awards', args=[season.id])