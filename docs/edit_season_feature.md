# Edit Season Page Feature Plan

## Completed
- ✅ Moved VOD field from Game model to Match model (migration applied)

## TODO
1. Create `edit_season` view in views.py
2. Create URL pattern (name-based) `/edit/season/<season_name>/`
3. Create `edit_season.html` template

## Template Structure (similar to edit_rosters.html)

### Top Section - Edit Forms
Forms arranged side-by-side with dropdowns:

1. **Change Season End Date**
   - Date input for end_date
   - Submit button

2. **Edit Team Captain**
   - Dropdown: Select Team
   - Dropdown: Select Player (for captain)
   - Submit button

3. **Edit Team Co-Captain**
   - Dropdown: Select Team
   - Dropdown: Select Player (for co-captain)
   - Submit button

4. **Edit Franchise Logo**
   - Dropdown: Select Franchise
   - Text input: Logo URL
   - (Optional: File upload field if possible)
   - Submit button

5. **Edit Match Week**
   - Dropdown: Select Match
   - Text input: New week name
   - Submit button

6. **Set Match VOD**
   - Dropdown: Select Match
   - URL input: VOD URL
   - Submit button

### Middle Section - Teams Display
Table showing:
- Small team logo (from franchise.logo)
- Team name
- Captain
- Co-captain

Sort by team name

### Bottom Section - Match Schedule
Display all matches with box scores exactly like season_schedule.html

## View Handler Actions
- `change_end_date`: Update season.end_date
- `change_captain`: Update team.captain
- `change_co_captain`: Update team.co_captain
- `change_logo`: Update franchise.logo
- `change_week`: Update match.week
- `set_vod`: Update match.vod

## Reusable Styles
- Use `.form-section`, `.form-row`, `.form-col` from edit_rosters.html
- Use schedule box score styles from season_schedule.html
- Use team logo styles from season.css

## Notes
- Franchise logo is on Franchise model, not TeamSeason
- For image upload: Django FileField could be used, but URL field is simpler for now
- Match dropdown should show: "{week}: {team1.name} vs {team2.name}"
