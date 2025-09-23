"""
Utilities for correcting data issues and merging duplicate records.
"""

from django.db import transaction
from ..models import PlayerSeason, PlayerGameLog, Player, TeamSeason, Match


@transaction.atomic
def merge_player_seasons(to_merge: PlayerSeason, target: PlayerSeason):
    """
    Merge two player seasons by reassigning all game logs from to_merge to target.
    
    Args:
        to_merge: The PlayerSeason to merge (will be deleted)
        target: The PlayerSeason to merge into (will be kept)
    """
    
    # Reassign all game logs from to_merge to target
    PlayerGameLog.objects.filter(player_season=to_merge).update(player_season=target)
    
    # Store the player for potential cleanup
    player_to_check = to_merge.player
    
    # Delete the to_merge player season
    to_merge.delete()
    
    # Check if the player has any other player seasons
    # If not, delete the player as well
    if not PlayerSeason.objects.filter(player=player_to_check).exists():
        player_to_check.delete()
        
    print(f"Merged player season {to_merge} into {target}")
    if not PlayerSeason.objects.filter(player=player_to_check).exists():
        print(f"Deleted player {player_to_check} (no remaining seasons)")


@transaction.atomic
def merge_players(to_merge: Player, target: Player):
    """
    Merge two players by reassigning all player seasons from to_merge to target.
    If target already has a player season in the same season, merge those player seasons.
    
    Args:
        to_merge: The Player to merge (will be deleted)
        target: The Player to merge into (will be kept)
    """
    
    # Get all player seasons for the player being merged
    player_seasons_to_merge = PlayerSeason.objects.filter(player=to_merge)
    
    for ps_to_merge in player_seasons_to_merge:
        # Check if target already has a player season in this season
        existing_target_ps = PlayerSeason.objects.filter(
            player=target, 
            season=ps_to_merge.season
        ).first()
        
        if existing_target_ps:
            # Merge the two player seasons
            print(f"Merging player seasons in {ps_to_merge.season.name}: {ps_to_merge} -> {existing_target_ps}")
            merge_player_seasons(ps_to_merge, existing_target_ps)
        else:
            # Just reassign the player season to the target player
            print(f"Reassigning player season {ps_to_merge} to {target}")
            ps_to_merge.player = target
            ps_to_merge.save()
    
    # Update any team captaincies
    captain_teams = TeamSeason.objects.filter(captain=to_merge)
    for team in captain_teams:
        print(f"Updating captain of {team} from {to_merge} to {target}")
        team.captain = target
        team.save()
    
    # Update any team co-captaincies  
    co_captain_teams = TeamSeason.objects.filter(co_captain=to_merge)
    for team in co_captain_teams:
        print(f"Updating co-captain of {team} from {to_merge} to {target}")
        team.co_captain = target
        team.save()
    
    # Delete the merged player
    player_name = str(to_merge)
    to_merge.delete()
    print(f"Deleted player {player_name}")


@transaction.atomic
def flip_sides(m: Match):
    """
    Flip which team is team1 in the match and which team is team2.

    Args:
        m: The Match to flip
    """
    # Swap team1 and team2 in the match
    original_team1 = m.team1
    original_team2 = m.team2
    m.team1 = original_team2
    m.team2 = original_team1
    m.save()
    
    # Process all games in the match
    for game in m.games.all():
        # Swap scores
        original_team1_score = game.team1_score
        original_team2_score = game.team2_score
        game.team1_score = original_team2_score
        game.team2_score = original_team1_score
        
        # Swap standing points
        original_team1_points = game.team1_standing_points
        original_team2_points = game.team2_standing_points
        game.team1_standing_points = original_team2_points
        game.team2_standing_points = original_team1_points
        
        # Flip outcome (outcome is always for team1)
        if game.outcome:
            outcome_flip_map = {
                'W': 'L',
                'L': 'W', 
                'OTW': 'OTL',
                'OTL': 'OTW',
                'T': 'T'  # Ties stay ties
            }
            game.outcome = outcome_flip_map.get(game.outcome, game.outcome)
        
        game.save()