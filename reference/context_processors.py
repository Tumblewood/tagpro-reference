from django.db.models import F
from .models import League, Season


def navigation_leagues(request):
    """
    Context processor to provide navigation leagues with their most recent seasons.
    Returns leagues with ordering <= 10, each linked to their most recent season.
    """
    leagues_with_seasons = []

    # Get leagues with ordering <= 10, ordered by their ordering field
    leagues = League.objects.filter(ordering__lte=10).order_by("ordering")

    for league in leagues:
        # Get the most recent season for this league (null dates are considered earliest)
        most_recent_season = (
            Season.objects.filter(league=league)
            .order_by(F("end_date").desc(nulls_last=True))
            .first()
        )

        if most_recent_season:
            leagues_with_seasons.append(
                {"league": league, "most_recent_season": most_recent_season}
            )

    return {"navigation_leagues": leagues_with_seasons}
