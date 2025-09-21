from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from reference.models import Season


def data_entry_required(view_func=None, *, season_param='season_id', allow_new_data_only=False):
    """
    Decorator that checks if user has appropriate data entry permissions for a season.
    
    Args:
        season_param: Name of the URL parameter containing the season ID
        allow_new_data_only: If True, 'entry' level users can access this view
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            # Get season from URL parameters
            season_id = kwargs.get(season_param)
            if season_id:
                season = get_object_or_404(Season, id=season_id)
                
                # Check permissions based on the view type
                if allow_new_data_only:
                    # For new data entry views - entry level can access
                    if not request.user.can_enter_new_data_for_season(season):
                        return HttpResponseForbidden("You don't have permission to enter data for this season.")
                else:
                    # For editing views - need edit permissions for the season
                    if not request.user.can_edit_season(season):
                        return HttpResponseForbidden("You don't have permission to edit data for this season.")
            else:
                # If no season specified, check general permissions
                if allow_new_data_only:
                    if not request.user.has_new_data_entry_permissions():
                        return HttpResponseForbidden("You don't have data entry permissions.")
                else:
                    if not request.user.has_current_season_permissions():
                        return HttpResponseForbidden("You don't have data editing permissions.")
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    
    if view_func:
        return decorator(view_func)
    return decorator


def bulk_import_required(view_func):
    """Decorator that checks if user has bulk import permissions."""
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.can_bulk_import():
            return HttpResponseForbidden("You don't have permission to perform bulk import operations.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def full_data_permissions_required(view_func):
    """Decorator that requires full data editing permissions."""
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.has_full_data_permissions():
            return HttpResponseForbidden("You don't have permission to access this feature.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view