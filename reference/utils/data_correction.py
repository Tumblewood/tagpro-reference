"""
Utilities for correcting data issues and merging duplicate records.
"""

from django.db import transaction
from ..models import PlayerSeason, PlayerGameLog, Player, TeamSeason


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