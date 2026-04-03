import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tagproref.settings')
django.setup()

from reference.models import *

season = Season.objects.get(league__abbr='MLTP', name='MLTP S30')
teams = TeamSeason.objects.filter(season=season).order_by('abbr')
for t in teams:
    print(f'TEAM: {t.name} ({t.abbr})')

players = PlayerSeason.objects.filter(season=season).select_related('player', 'team').order_by('team__abbr', 'playing_as')
for ps in players:
    team_abbr = ps.team.abbr if ps.team else 'None'
    print(f'PLAYER: {ps.player.name} / playing_as={ps.playing_as} -> team={team_abbr}')
