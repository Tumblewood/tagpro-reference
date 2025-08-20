from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for custom User model."""
    
    fieldsets = BaseUserAdmin.fieldsets + (
        ('TagPro Data', {
            'fields': ('player', 'permission_tier')
        }),
    )
    
    list_display = BaseUserAdmin.list_display + ('player', 'permission_tier')
    list_filter = BaseUserAdmin.list_filter + ('permission_tier',)
    
    search_fields = BaseUserAdmin.search_fields + ('player__name',)
