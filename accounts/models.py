from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class CustomUserManager(BaseUserManager):
    """Custom manager for the User model."""
    
    def create_user(self, username, email=None, password=None, **extra_fields):
        """Create and return a regular user."""
        if not username:
            raise ValueError('The Username field must be set')
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        """Create and return a superuser."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(username, email, password, **extra_fields)


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
    
    objects = CustomUserManager()
    
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
        default='none',
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
    
    def can_edit_season(self, season):
        """Check if user can edit data for a specific season."""
        if self.is_superuser or self.permission_tier == 'full':
            return True
        elif self.permission_tier == 'current':
            # Can edit seasons that haven't ended yet
            from datetime import date
            return season.end_date is None or season.end_date >= date.today()
        else:
            return False
    
    def can_enter_new_data_for_season(self, season=None):
        """Check if user can enter new data for a specific season."""
        # For new data entry, all permission levels except 'none' are allowed
        if self.is_superuser or self.permission_tier in ['full', 'current', 'entry']:
            return True
        else:
            return False
    
    def can_bulk_import(self):
        """Check if user can perform bulk import operations."""
        return self.is_superuser or self.permission_tier in ['full', 'current']
    
    def __str__(self):
        if self.player:
            return f"{self.username} ({self.player.name})"
        return self.username
