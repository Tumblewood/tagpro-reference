from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib import messages
from .forms import CustomUserCreationForm


def signup(request):
    """User registration view."""
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            login(request, user)  # Automatically log in the new user
            messages.success(request, f'Welcome {username}! Your account has been created and you are now logged in.')
            return redirect('homepage')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'auth/signup.html', {'form': form})