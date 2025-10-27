# Basic concept

TagPro Reference runs on tagpro-reference.com. It's similar to the sports-reference websites but it is for competitive leages in the video game TagPro. It is designed as a successor to tagproleague.com, which has its flaws but currently catalogs all seasons of NALTP, as well as tagpro.dev, which catalogs all seasons of ELTP.

# File structure

The main app is called `reference`. It contains all logic for entering (views/data_entry.py), processing (views/stat_collection.py), and displaying (data/info_pages.py) league information and stats. Read its models.py to thoroughly understand the data models.

# Leagues and seasons

League and Season are pretty simple. Some examples of leagues are Major League TagPro (MLTP), Minor League TagPro (mLTP), Novice League TagPro (NLTP), Novice League TagPro B (NLTP B), European League TagPro (ELTP), and Neutral Flag TagPro League (NFTL). Each (non-defunct) league runs a new season every so often. Seasons are just numbered: example season names would be MLTP S37 or NLTP B S18. Multiple seasons of the same league can occur per year.

MLTP, mLTP, and NLTP run their seasons at the same time as part of the organization NALTP, which allows for player movement between the leagues. (ELTP and eLTP do the same, as do NFTL and NFTL B). However, there is no need to reflect any of those relationships in the code. If a player is dropped by a majors team and added by a minors team, we can treat those events as completely independent.

Different leagues will have slightly different requirements for how data is processed and displayed, and these requirements can differ for different seasons of a league. So far, the only seasons onboarded to the database are S30-36 of NALTP. As I onboard other leagues and earlier seasons of these leagues, I will have to add logic to accommodate some rules differences between leagues and seasons. Here's a list of all the rules differences I know:

- In early seasons of NALTP, each match was made up of two games, and each game was played across two 2-minute halves. If tied after two halves, the game would have a separate overtime period. In some middle seasons of NALTP, each match was played across two halves, but each half was counted individually towards the standings. Sometime around then, overtime stopped being a separate period. (So you could get a W in G1H1 and an OTL in G1H2.) Then in later seasons of NALTP, the format shifted to be five individual 10-minute games per match, not played in halves.
  
  Playoff series had a similar rule change: they used to be a best-of-3, with each game being two halves, but they switched to a best-of-7 with games not split into halves.
  
  Recent seasons of ELTP have had a different regular season format entirely: Each week, each team plays 1 game against each other team in the league round-robin. ELTP allows ties instead of overtime because they're European.
  
  *How to handle:* Early NALTP should have one Game object for each half and each overtime period. Standing points for the full game should be assigned to only one Game object. (We can detect whether Games are halves of the same game by using their names: "Game 1" is a self-contained game, but "Game 1 Half 1" means it's the first half of G1.) As for ELTP, we should treat each game as being part of its own 1-game match. This approach doesn't require any code changes or special case handling.
- Some seasons of NALTP have had "home maps". Each team got to pick a home map that they would play during some designated games. These games would count toward teams' standings, but they wouldn't count toward individual players' stat totals.
  
  *How to handle:* We can already handle this in the code as-is, using the flag on a Game object for whether it counts toward aggregated stats. I just have to ensure that all games on home maps have that flag set correctly. (It would be conventient to add a function to easily set that flags for all games on a specific map in a given season.
- NFTL and the eggball league are run the same way as NALTP, but because they're played in a different gamemode, they'll need a different set of stats collected.
  
  *How to handle:* Add more stat columns to PlayerGameStats and related models where needed. Then each gamemode should have its own function for extracting stats from a tagpro.eu file, and we should decide which one to use for a game based on its league's gamemode.

# Data entry

The main source for stat data is tagpro.eu. Game logs are stored as JSON objects, which can be loaded from a bulk file or downloaded directly from tagpro.eu. I do not want to send too many requests to tagpro.eu directly, so I load from a bulk file whenever possible and avoid downloading directly in batch operations. The size of the bulk files loaded in memory has to be managed carefully in production, because if all the matches are loaded at once my server tends to run out of memory.

The key information a tagpro.eu game log gives us is:

- When the game was played
- What team each player played on and what stats they recorded
- The (abbreviated) name of each team
- Each team's score in the game
- Whether the game went to overtime and what happened in OT
- What map the game was played on

This data has to be augmented with the following information before it is useful, and how to get it:

- What Season the game was part of. There are two patterns for determining this. One is to input the season name and then process all its tagpro.eu files knowing already what the season is. The other is to specify a group of seasons (e.g., S29 for all NALTP leagues) and inferring the season based on the team names from the game log. The convention is that MLTP team names in the game log should be formatted like MLBT, MOPH, etc.; mLTP team names should be like NABO, NMIA; NLTP team names like AHOH, AODG; and NLTP B team names like BTMD, BFNB. The first letter indicates the league and the last three indicate the team. Some manual correction is needed because captains will sometimes forget to set the team name in the group, or else set it incorrectly.
- What teams played in the game. This can usually be inferred from the team abbr as described above, but if mistakenly entered some correction is needed. The tagproleague.com API says what two teams were playing in a game, but it doesn't say the order. It's easy to manually tell which teams is which based on who was on the roster, but I think this would be more trouble than it's worth to automate.
- What Match the game was a part of. Each match is uniquely identified by the two teams that played and what week of the season it was played (the teams + the date it was played on should also be uniquely identifying). The tagproleague.com API says the teams and the week, but if not using the API it's sufficient to identify a match by the teams and the date, and the week name can be inferred with varying accuracy. (When importing in bulk I just enter week name manually.)
- What the game's index is in the match. It should always be chronologically ordered: Game 1 should come before Game 2, and G1H1 should come before G1H2. For seasons with halves, it would be really annoying to manually enter unless using the game labels from the tagproleague.com API.
- What players correspond to each username used in the game. Players are supposed to use the same username for each game they play in a season. (And most players keep it the same season-to-season.) But sometimes they play under a different username in some games anyway, which has to be manually mapped. (Though if the player has used that username before or capitalization is the only change, we can still map it automatically.) Players' season usernames also have to be mapped to the right Player object, but this only has to be done once for each season.
  
  Going forward, I think the best approach to unknown usernames will be to add a PlayerSeason for each one, and then make it easy to merge PlayerSeasons manually and correct the Player they map to if needed.
- We can also use the team a player played on in a game to roughly infer which team's roster they were on for the season. Players can change teams, so we generally assume it's the last team the player played for in a season, though much manual correction will be needed due to occasional use of substitutes from lower leagues / out of league.

# Major edge cases and gotchas

- Teams usually switch sides (red/blue) between games in a match. Because of this, red and blue do not correspond to the same thing as team1 and team2 in the data model. One team will be team1 for the entire match, and one team will be team2 for the entire match, but either of them could be the red team in a given game.
- Sometimes matches get rescheduled. In rare cases a team's Week 2 match could be played after their Week 3 or even Week 6 match. In other rare cases, individual games of a match can be resumed or replayed on a later date.
- Sometimes individual games are paused before they finish, and usually but not always the game will be continued in a second game log. This is why the Game object supports a second game log and allows a time to be set after which a game log's stats no longer count.
- As far as I know, no league counts overtime stats toward a player's stat totals. They also don't count overtime caps toward a team's cap differential for the season. Also as far as I know, games are 10 minutes long in every league.
- Some games are not recorded in tagpro.eu. In these cases, there should be a paste on pastebin that provides basic stats for each player in the game. These games can be a little manual to enter, but only a little.
- Some games are forfeited and do not have any game log. These can be entered as 1-0 wins (or sometimes 2-0 or 3-0 depending on the season) with no player game logs attached.

# Stat aggregation

Each player typically plays 3-5 games per week and 5-10 weeks per season. We need to be able to display players' stats at the week level and at the season level. This is why there are models for PlayerWeekStats and PlayerSeasonStats. There is also a model for PlayerRegulationGameStats to allow stats from overtimes and home maps to be excluded from stat totals. These need to be updated every time a player's game stats update. Aggregating stats for a single player is not that slow, but for a whole season it can take about a minute (which surprises me; it should be faster). When importing matches in bulk, stat aggregations should not be updated until all matches have been imported, to avoid repeated imports.

Because of the complicated tiebreaker rules, it's also best to memoize calculations of teams' rank in the standings.

# Guidelines for working with me

I will run scripts that you write myself, and I will test features myself. Don't try to execute shell commands to do that for me.

One common mistake I see is, when adding a new Django template, writing new styles from scratch instead of reusing existing HTML/CSS used to serve the same purpose on another page.

Another mistake is when part of a feature is silently left totally unimplemented because it seems complicated.

# Style

- Imports should always be at the top of a file, not in the middle of a function.
- Use " to quote strings, except use ' for dict keys.
- Define big constant objects like lists or dicts at the top of a file, not where they are used.
- Use rem for sizes in CSS.
- Complex or repeated logic should be moved to its own function instead of being written inline.