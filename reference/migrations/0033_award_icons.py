from django.db import migrations, models

# Award name -> base name of its icon (see reference/utils/award_icons.py)
AWARD_ICONS = {
    "Most Valuable Ball": "medal_mvb",
    "Playoffs MVB": "medal_mvb",
    "Offensive Ball of the Season": "medal_obos",
    "Offensive Ball of Playoffs": "medal_obos",
    "Defensive Ball of the Season": "medal_dbos",
    "Defensive Ball of Playoffs": "medal_dbos",
    "Well Rounded": "medal_well_rounded",
    "Most Well-Rounded": "medal_well_rounded",
    "Best Offense Pair": "medal_best_offense_pair",
    "Best Offensive Pair": "medal_best_offense_pair",
    "Best Defense Pair": "medal_best_defense_pair",
    "Best Defensive Pair": "medal_best_defense_pair",
    "Rookie of the Season": "medal_ros",
    "Offensive Rookie of the Season": "medal_oros",
    "Defensive Rookie of the Season": "medal_dros",
    "Most Improved": "medal_most_improved",
    "Best Valued": "medal_best_valued",
    "FU GASP": "medal_fu_gasp",
    "Position Change": "medal_position_change",
    "Best Call-up": "medal_best_call_up",
    "Best Callup": "medal_best_call_up",
    "Best 5th Ball": "medal_best_5th_ball",
    "Best Offensive Team Ball": "medal_team_ball_o",
    "Best Defensive Team Ball": "medal_team_ball_d",
    "Best Veteran": "medal_best_veteran",
    "Forget MLTP": "medal_forget_mltp",
    "All-Star (Offense)": "medal_all_star_o",
    "All-Stars [Offense]": "medal_all_star_o",
    "All-Star (Defense)": "medal_all_star_d",
    "All-Stars [Defense]": "medal_all_star_d",
    "Best Offensive Performance": "medal_best_offensive_performance",
    "Best Defensive Performance": "medal_best_defensive_performance",
    "Most Notable Disappearance": "medal_notable_disappearance",
    "Deceiving Record": "medal_deceiving_record",
    "Random Stat": "medal_random_stat",
    "Ball of Fame": "medal_ball_of_fame",
    "Best Western Captain": "ribbon_best_captain",
    "Best Eastern Captain": "ribbon_best_captain",
    "Best Overall Captain": "ribbon_best_captain",
    "Best S10 Captain": "ribbon_best_captain",
    "Behind the Scenes": "ribbon_behind_the_scenes",
    "Best Behind the Scenes": "ribbon_behind_the_scenes",
    "Best Streamer": "ribbon_best_streamer",
    "Best Commentator": "ribbon_best_commentator",
    "Best Roster Moves": "ribbon_best_roster_moves",
    "Community Contributor": "ribbon_community_contributor",
    "Heart": "ribbon_heart",
    "Heart Award": "ribbon_heart",
}

# Award name prefix -> icon, for families of awards split by region, team color, or map
AWARD_ICON_PREFIXES = {
    "Best Captain": "ribbon_best_captain",
    "Best Co-Captain": "ribbon_best_co_captain",
    "Most Cohesive Unit": "medal_most_cohesive_unit",
    "Best Performance [": "medal_best_individual_performance",
}

LEAGUE_TROPHIES = {
    "MLTP": "awards/trophy_mltp.svg",
    "mLTP": "awards/trophy_mltp_minors.svg",
    "NLTP": "awards/trophy_nltp.svg",
    "NLTP B": "awards/trophy_nltp_b.svg",
    "OLTP": "awards/trophy_oltp.svg",
    "oLTP": "awards/trophy_oltp_minors.svg",
    "ELTP": "awards/trophy_eltp.svg",
    "eLTP": "awards/trophy_eltp_minors.svg",
    "ENLTP": "awards/trophy_enltp.svg",
    "FB": "awards/trophy_frozen_balls.svg",
    "FG": "awards/trophy_generic.svg",
}


def icon_for_award(name):
    """Looks up an award's icon by exact name, then by name prefix."""
    if name in AWARD_ICONS:
        return AWARD_ICONS[name]
    for prefix, icon in AWARD_ICON_PREFIXES.items():
        if name.startswith(prefix):
            return icon
    return None


def set_icons(apps, schema_editor):
    AwardType = apps.get_model("reference", "AwardType")
    League = apps.get_model("reference", "League")
    for award_type in AwardType.objects.all():
        icon = icon_for_award(award_type.name)
        if icon:
            award_type.icon = icon
            award_type.save(update_fields=["icon"])
    for abbr, trophy in LEAGUE_TROPHIES.items():
        League.objects.filter(abbr=abbr).update(trophy_icon=trophy)


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0032_remove_old_stats_add_preventing_stats"),
    ]

    operations = [
        migrations.AlterField(
            model_name="awardtype",
            name="icon",
            field=models.CharField(
                blank=True,
                help_text="Base name of the award's icon in static/reference/awards, e.g. medal_mvb or ribbon_heart",
                max_length=100,
                null=True,
            ),
        ),
        migrations.RunPython(set_icons, migrations.RunPython.noop),
    ]
