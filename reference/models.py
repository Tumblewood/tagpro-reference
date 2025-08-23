from django.db import models

class League(models.Model):
    """
    Represents a competitive league, e.g., MLTP, ELTP.
    """
    name = models.CharField(max_length=255, help_text="Full league name, e.g., Major League TagPro")
    abbr = models.CharField(max_length=10, help_text="Abbreviation for the league, e.g., MLTP")
    region = models.CharField(max_length=3, choices=[('NA', 'North America'), ('EU', 'Europe'), ('OCE', 'Oceania')], blank=True, null=True)
    ordering = models.IntegerField(help_text="Indicates how leagues should be ordered when several are displayed")
    gamemode = models.CharField(max_length=50, help_text="CTF")
    logo = models.CharField(max_length=100, blank=True, null=True, help_text="Link to the league's logo image")
    trophy_icon = models.CharField(max_length=100, blank=True, null=True, help_text="Link to the league's championship trophy image")

    def __str__(self):
        return self.name

class Franchise(models.Model):
    """
    Represents a franchise, e.g., The Land Before Timers.
    """
    name = models.CharField(max_length=255, unique=True)
    abbr = models.CharField(max_length=10)
    logo = models.CharField(max_length=100, blank=True, null=True, help_text="Link to the franchise's logo image")

    def __str__(self):
        return self.name

class Player(models.Model):
    """
    Represents an individual player.
    """
    name = models.CharField(max_length=255, unique=True)
    profile = models.CharField(max_length=255, blank=True, null=True, help_text="TagPro profile ID")

    def __str__(self):
        return self.name

class Season(models.Model):
    """
    Represents a single season of a league.
    """
    name = models.CharField(max_length=255, help_text="e.g., NLTP S36")
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="seasons")
    end_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return self.name

class TeamSeason(models.Model):
    """
    Represents a single season for a single team.
    """
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT, related_name="team_seasons")
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="teams")
    name = models.CharField(max_length=255, help_text="The team's name for this season, which might differ from the franchise name")
    abbr = models.CharField(max_length=10)
    captain = models.ForeignKey(Player, on_delete=models.SET_NULL, related_name="captain_of", blank=True, null=True)
    co_captain = models.ForeignKey(Player, on_delete=models.SET_NULL, related_name="co_captain_of", blank=True, null=True)

    class Meta:
        unique_together = ('franchise', 'season')

    def __str__(self):
        return f"{self.name} ({self.season})"

class PlayerSeason(models.Model):
    """
    Represents a player's participation in a single season.
    """
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="player_seasons")
    team = models.ForeignKey(TeamSeason, on_delete=models.PROTECT, blank=True, null=True, related_name="players", help_text="The team the player ended the season on, if any")
    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="seasons_played")
    playing_as = models.CharField(max_length=255, help_text="The name the player used during this season")
    position = models.CharField(max_length=1, choices=[('O', 'O'), ('D', 'D'), ('N', '—')], default='N')
    other_restrictions = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        unique_together = ('season', 'player')

    def __str__(self):
        return f"{self.player.name} - {self.season.name} (playing as {self.playing_as} on {self.team if self.team else 'no team'})"

class Match(models.Model):
    """
    Represents a match between two teams (which can comprise multiple games).
    """
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="matches")
    date = models.DateField()
    week = models.CharField(max_length=100, help_text="e.g., Week 3, Foci Four")
    team1 = models.ForeignKey(TeamSeason, on_delete=models.CASCADE, related_name="home_matches")
    team2 = models.ForeignKey(TeamSeason, on_delete=models.CASCADE, related_name="away_matches")

    def get_playoff_series(self):
        try:
            return self.playoff_series
        except PlayoffSeries.DoesNotExist:
            return None

    def __str__(self):
        return f"{self.season.name} {self.week}: {self.team1.name} vs {self.team2.name}"

class PlayoffSeries(models.Model):
    """
    Represents a playoff series.
    """
    match = models.OneToOneField(Match, on_delete=models.PROTECT, null=True, blank=True, related_name="playoff_series")
    seed1 = models.IntegerField()
    seed2 = models.IntegerField()
    team1_prev_series = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name="next_series_for_team1")
    team2_prev_series = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name="next_series_for_team2")
    winner = models.ForeignKey(TeamSeason, on_delete=models.SET_NULL, null=True, blank=True, related_name="series_wins")
    team1_game_wins = models.IntegerField(null=True, blank=True)
    team2_game_wins = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"Playoff Series for {self.match}"

class Game(models.Model):
    """
    Represents a single game within a match.
    """
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="games")
    game_in_match = models.CharField(max_length=100, null=True, blank=True)
    tagpro_eu = models.IntegerField(unique=True, null=True, blank=True)
    paused_time = models.IntegerField(null=True, blank=True, help_text="Time (in seconds from the start) the game was paused, if it was paused and resumed later")
    resumed_tagpro_eu = models.IntegerField(unique=True, null=True, blank=True, help_text="Second tagpro.eu match ID, if the game was paused and resumed later")
    replay = models.CharField(max_length=100, unique=True, null=True, blank=True)
    vod = models.URLField(max_length=255, blank=True, null=True)
    map_name = models.CharField(max_length=255, null=True, blank=True)
    map_id = models.IntegerField(null=True, blank=True)
    red_team = models.ForeignKey(TeamSeason, on_delete=models.CASCADE, related_name="red_games")
    blue_team = models.ForeignKey(TeamSeason, on_delete=models.CASCADE, related_name="blue_games")
    team1_score = models.IntegerField()  # Score for team1 in the match (whether red or blue in this game)
    team2_score = models.IntegerField()  # Score for team2 in the match (whether red or blue in this game)
    OUTCOMES = [
        ('L', 'Loss'),
        ('OTL', 'OT Loss'),
        ('T', 'Tie'),
        ('OTW', 'OT Win'),
        ('W', 'Win'),
    ]
    outcome = models.CharField(max_length=3, choices=OUTCOMES, null=True, blank=True, help_text="Outcome of the game for team1")
    team1_standing_points = models.IntegerField(null=True, blank=True, help_text="Points awarded for standings")
    team2_standing_points = models.IntegerField(null=True, blank=True, help_text="Points awarded for standings")

    class Meta:
        ordering = ['game_in_match']
        unique_together = ('match', 'game_in_match')

    def __str__(self):
        return f"{self.match}, {self.game_in_match} ({self.tagpro_eu})"

class PlayerGameLog(models.Model):
    """
    Represents an individual player's participation in a single game.
    """
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="player_stats")
    team = models.ForeignKey(TeamSeason, on_delete=models.CASCADE)
    player_season = models.ForeignKey(PlayerSeason, on_delete=models.CASCADE, related_name="gamelogs", db_column="player")
    playing_as = models.CharField(max_length=255)

    class Meta:
        unique_together = ('game', 'player_season')

    def __str__(self):
        return f"{self.player_season.playing_as} in {self.game}"

class PlayerGameStats(models.Model):
    """
    Represents an individual player's stats in a single game.
    """
    player_gamelog = models.OneToOneField(PlayerGameLog, on_delete=models.CASCADE, related_name="stats")
    time_played = models.IntegerField(blank=True, null=True, help_text="Time played in ticks (1/60th of a second)")
    tags = models.IntegerField(blank=True, null=True)
    pops = models.IntegerField(blank=True, null=True)
    grabs = models.IntegerField(blank=True, null=True)
    drops = models.IntegerField(blank=True, null=True)
    hold = models.IntegerField(blank=True, null=True, help_text="Hold time in ticks (1/60th of a second)")
    captures = models.IntegerField(blank=True, null=True)
    prevent = models.IntegerField(blank=True, null=True, help_text="Prevent time in ticks (1/60th of a second)")
    returns = models.IntegerField(blank=True, null=True)
    powerups = models.IntegerField(blank=True, null=True)
    caps_for = models.IntegerField(blank=True, null=True)
    caps_against = models.IntegerField(blank=True, null=True)
    total_pups_in_game = models.IntegerField(blank=True, null=True)
    grabs_off_handoffs = models.IntegerField(blank=True, null=True)
    caps_off_handoffs = models.IntegerField(blank=True, null=True)
    grabs_off_regrab = models.IntegerField(blank=True, null=True)
    caps_off_regrab = models.IntegerField(blank=True, null=True)
    long_holds = models.IntegerField(blank=True, null=True)
    flaccids = models.IntegerField(blank=True, null=True)
    handoffs = models.IntegerField(blank=True, null=True)
    good_handoffs = models.IntegerField(blank=True, null=True)
    quick_returns = models.IntegerField(blank=True, null=True)
    returns_in_base = models.IntegerField(blank=True, null=True)
    saves = models.IntegerField(blank=True, null=True)
    key_returns = models.IntegerField(blank=True, null=True)
    hold_against = models.IntegerField(blank=True, null=True)
    kept_flags = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"Stats for {self.player_gamelog}"

class PlayerRegulationGameStats(models.Model):
    """
    Represents an individual player's stats in a single game that are considered "regulation".
    Excludes OT stats and games played on "home maps".
    This is what should be used for week and season totals.
    """
    player_gamelog = models.OneToOneField(PlayerGameLog, on_delete=models.CASCADE, related_name="regulation_stats")
    time_played = models.IntegerField(blank=True, null=True, help_text="Time played in ticks (1/60th of a second)")
    tags = models.IntegerField(blank=True, null=True)
    pops = models.IntegerField(blank=True, null=True)
    grabs = models.IntegerField(blank=True, null=True)
    drops = models.IntegerField(blank=True, null=True)
    hold = models.IntegerField(blank=True, null=True, help_text="Hold time in ticks (1/60th of a second)")
    captures = models.IntegerField(blank=True, null=True)
    prevent = models.IntegerField(blank=True, null=True, help_text="Prevent time in ticks (1/60th of a second)")
    returns = models.IntegerField(blank=True, null=True)
    powerups = models.IntegerField(blank=True, null=True)
    caps_for = models.IntegerField(blank=True, null=True)
    caps_against = models.IntegerField(blank=True, null=True)
    total_pups_in_game = models.IntegerField(blank=True, null=True)
    grabs_off_handoffs = models.IntegerField(blank=True, null=True)
    caps_off_handoffs = models.IntegerField(blank=True, null=True)
    grabs_off_regrab = models.IntegerField(blank=True, null=True)
    caps_off_regrab = models.IntegerField(blank=True, null=True)
    long_holds = models.IntegerField(blank=True, null=True)
    flaccids = models.IntegerField(blank=True, null=True)
    handoffs = models.IntegerField(blank=True, null=True)
    good_handoffs = models.IntegerField(blank=True, null=True)
    quick_returns = models.IntegerField(blank=True, null=True)
    returns_in_base = models.IntegerField(blank=True, null=True)
    saves = models.IntegerField(blank=True, null=True)
    key_returns = models.IntegerField(blank=True, null=True)
    hold_against = models.IntegerField(blank=True, null=True)
    kept_flags = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"Regulation game stats for {self.player_gamelog}"
    
class PlayerWeekStats(models.Model):
    """
    Represents an individual player's total stats in a single week of a season.
    """
    player_season = models.ForeignKey(PlayerSeason, on_delete=models.CASCADE, related_name="weekly_stats")
    week = models.CharField(max_length=100)
    time_played = models.IntegerField(blank=True, null=True, help_text="Time played in ticks (1/60th of a second)")
    tags = models.IntegerField(blank=True, null=True)
    pops = models.IntegerField(blank=True, null=True)
    grabs = models.IntegerField(blank=True, null=True)
    drops = models.IntegerField(blank=True, null=True)
    hold = models.IntegerField(blank=True, null=True, help_text="Hold time in ticks (1/60th of a second)")
    captures = models.IntegerField(blank=True, null=True)
    prevent = models.IntegerField(blank=True, null=True, help_text="Prevent time in ticks (1/60th of a second)")
    returns = models.IntegerField(blank=True, null=True)
    powerups = models.IntegerField(blank=True, null=True)
    caps_for = models.IntegerField(blank=True, null=True)
    caps_against = models.IntegerField(blank=True, null=True)
    total_pups_in_game = models.IntegerField(blank=True, null=True)
    grabs_off_handoffs = models.IntegerField(blank=True, null=True)
    caps_off_handoffs = models.IntegerField(blank=True, null=True)
    grabs_off_regrab = models.IntegerField(blank=True, null=True)
    caps_off_regrab = models.IntegerField(blank=True, null=True)
    long_holds = models.IntegerField(blank=True, null=True)
    flaccids = models.IntegerField(blank=True, null=True)
    handoffs = models.IntegerField(blank=True, null=True)
    good_handoffs = models.IntegerField(blank=True, null=True)
    quick_returns = models.IntegerField(blank=True, null=True)
    returns_in_base = models.IntegerField(blank=True, null=True)
    saves = models.IntegerField(blank=True, null=True)
    key_returns = models.IntegerField(blank=True, null=True)
    hold_against = models.IntegerField(blank=True, null=True)
    kept_flags = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"Stats for {self.player_season.playing_as} in {self.week} of {self.player_season.season.name}"

class PlayerSeasonStats(models.Model):
    """
    Represents an individual player's total stats in a season.
    """
    player_season = models.OneToOneField(PlayerSeason, on_delete=models.CASCADE, related_name="stats")
    time_played = models.IntegerField(blank=True, null=True, help_text="Time played in ticks (1/60th of a second)")
    tags = models.IntegerField(blank=True, null=True)
    pops = models.IntegerField(blank=True, null=True)
    grabs = models.IntegerField(blank=True, null=True)
    drops = models.IntegerField(blank=True, null=True)
    hold = models.IntegerField(blank=True, null=True, help_text="Hold time in ticks (1/60th of a second)")
    captures = models.IntegerField(blank=True, null=True)
    prevent = models.IntegerField(blank=True, null=True, help_text="Prevent time in ticks (1/60th of a second)")
    returns = models.IntegerField(blank=True, null=True)
    powerups = models.IntegerField(blank=True, null=True)
    caps_for = models.IntegerField(blank=True, null=True)
    caps_against = models.IntegerField(blank=True, null=True)
    total_pups_in_game = models.IntegerField(blank=True, null=True)
    grabs_off_handoffs = models.IntegerField(blank=True, null=True)
    caps_off_handoffs = models.IntegerField(blank=True, null=True)
    grabs_off_regrab = models.IntegerField(blank=True, null=True)
    caps_off_regrab = models.IntegerField(blank=True, null=True)
    long_holds = models.IntegerField(blank=True, null=True)
    flaccids = models.IntegerField(blank=True, null=True)
    handoffs = models.IntegerField(blank=True, null=True)
    good_handoffs = models.IntegerField(blank=True, null=True)
    quick_returns = models.IntegerField(blank=True, null=True)
    returns_in_base = models.IntegerField(blank=True, null=True)
    saves = models.IntegerField(blank=True, null=True)
    key_returns = models.IntegerField(blank=True, null=True)
    hold_against = models.IntegerField(blank=True, null=True)
    kept_flags = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"Stats for {self.player_season.playing_as} in {self.player_season.season.name}"

class AwardType(models.Model):
    """
    Represents a type of award.
    """
    name = models.CharField(max_length=255, help_text="Full name of the award")
    abbr = models.CharField(max_length=100, help_text="Abbreviation for the award name")
    icon = models.CharField(max_length=100, blank=True, null=True, help_text="Link to the award's icon")
    ordering = models.IntegerField()

    def __str__(self):
        return self.name
    
class AwardReceived(models.Model):
    """
    Represents a player or team receiving an award for a season.
    """
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="awards")
    team = models.ForeignKey(TeamSeason, on_delete=models.SET_NULL, null=True, blank=True, help_text="Team awarded or player's team")
    player = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, blank=True, help_text="Player who won the award")
    award = models.ForeignKey(AwardType, on_delete=models.PROTECT)
    placement = models.PositiveIntegerField(default=1, null=True, blank=True, help_text="1 for 1st place, 2 for 2nd, etc.")

    def __str__(self):
        if self.player:
            return f"{self.season.name}: {self.award.name} ({self.placement}) - {self.player.name}"
        return f"{self.season.name}: {self.award.name} ({self.placement}) - {self.team.name}"

class Transaction(models.Model):
    """
    Represents a player transaction, like a draft, add, or drop.
    """
    TRANSACTION_TYPES = [
        ('draft', 'Draft'),
        ('add', 'Add'),
        ('drop', 'Drop'),
    ]
    team = models.ForeignKey(TeamSeason, on_delete=models.CASCADE, related_name="transactions")
    player_season = models.ForeignKey(PlayerSeason, on_delete=models.CASCADE, related_name="transactions", db_column="player")
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    date = models.DateField(null=True, blank=True)
    before_week = models.IntegerField(null=True, blank=True, help_text="The week number this transaction occurred before")
    net_tc_spent = models.IntegerField(null=True, blank=True, help_text="Net TagCoins spent or gained (positive if spent, negative if gained)")
    description = models.TextField(null=True, blank=True)
    # Draft-specific fields
    round = models.IntegerField(null=True, blank=True)
    pick = models.IntegerField(null=True, blank=True)
    was_snake = models.BooleanField(null=True, blank=True)

    def __str__(self):
        return f"{self.date}: {self.team.name} {self.transaction_type.title()}s {self.player_season.playing_as} ({self.team.season.name})"
