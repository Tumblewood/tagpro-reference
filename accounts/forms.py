from django import forms
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm
from .models import User


class CustomUserCreationForm(BaseUserCreationForm):
    """Custom user creation form for the custom User model."""
    
    email = forms.EmailField(
        required=False,
        help_text='Optional. We will not share your email with anyone.'
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')
    
    def save(self, commit=True):
        """Save the user with default permission tier."""
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.permission_tier = 'entry'  # Set default permission tier
        if commit:
            user.save()
        return user