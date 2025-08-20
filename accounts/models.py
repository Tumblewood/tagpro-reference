from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model with Player association and tiered permissions.
    """
    PERMISSION_TIERS = [
        ('full', 'Full Data Editing'),
        ('current', 'Current Season Data Editing'),
        ('entry', 'New Data Entry Only'),
        ('none', 'No Editing'),
    ]
    
    player = models.OneToOneField(
        'reference.Player',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='user_account',
        help_text="Associated TagPro player"
    )
    
    permission_tier = models.CharField(
        max_length=10,
        choices=PERMISSION_TIERS,
        default='entry',
        help_text="Permission level for data entry operations"
    )
    
    def has_full_data_permissions(self):
        """Check if user has full data editing permissions."""
        return self.permission_tier == 'full' or self.is_superuser
    
    def has_current_season_permissions(self):
        """Check if user has current season data editing permissions."""
        return self.permission_tier in ['full', 'current'] or self.is_superuser
    
    def has_new_data_entry_permissions(self):
        """Check if user has new data entry permissions."""
        return self.permission_tier in ['full', 'current', 'entry'] or self.is_superuser
    
    def __str__(self):
        if self.player:
            return f"{self.username} ({self.player.name})"
        return self.username
