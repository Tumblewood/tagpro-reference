"""Fix common TSV formatting issues in awards files"""
import os
import re

def fix_line(line, award_name=""):
    """Fix common issues in a TSV line"""
    parts = line.strip().split("\t")

    if len(parts) < 1:
        return line

    # Skip header
    if parts[0] == "Award":
        return line

    # Fix each field
    for i in range(len(parts)):
        if not parts[i]:
            continue

        original = parts[i]
        fixed = parts[i]

        # Remove [Captain] suffix
        fixed = re.sub(r'\s*\[Captain\]', '', fixed)

        # Remove trailing commas
        fixed = fixed.rstrip(',')

        # Remove stray quotes
        fixed = fixed.replace('"', '')

        # Remove leading/trailing slashes
        fixed = fixed.strip('/')
        fixed = fixed.strip()

        replacements = {
            'dodsfaIl': 'dodsfall',
            'fender <3': 'fender',
            'BC Canada': 'BC, Canada',
            'BC_Canada': 'BC, Canada',
            'KateEarl MD': 'KateEarl, MD',
            'GasoI': 'Gasol',
            'no-name': 'no name',
            'IfYouWeakAmy': 'IfYouSeekAmy',
        }

        for old, new in replacements.items():
            if old in fixed:
                fixed = fixed.replace(old, new)

        if 'Curry, refined, mex' in fixed:
            fixed = fixed.replace('Curry, refined, mex', 'Curry // refined // mex')
        if 'IcePlatypus, smoji' in fixed:
            fixed = fixed.replace('IcePlatypus, smoji', 'IcePlatypus // smoji')
        if 'slimegod, soul read, lil mayo, Prime' in fixed:
            fixed = fixed.replace('slimegod, soul read, lil mayo, Prime', 'slimegod // soul read // lil mayo // Prime')
        if 'Catpuke / Flaccid Trip' in fixed:
            fixed = fixed.replace('Catpuke / Flaccid Trip', 'Catpuke // Flaccid Trip')
        if '42 / Crowman' in fixed:
            fixed = fixed.replace('42 / Crowman', '42 // Crowman')

        parts[i] = fixed

    return "\t".join(parts)

def fix_file(filepath):
    """Fix a single TSV file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    fixed_lines = []
    current_award = ""

    for line in lines:
        parts = line.strip().split("\t")
        if len(parts) > 0 and parts[0] and parts[0] != "Award":
            current_award = parts[0]

        fixed = fix_line(line, current_award)
        fixed_lines.append(fixed if fixed.endswith('\n') else fixed + '\n')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)

    return len(lines)

# Process all TSV files
base_dir = "awards_import"
total_files = 0
total_lines = 0

for filename in sorted(os.listdir(base_dir)):
    if filename.endswith('.tsv'):
        filepath = os.path.join(base_dir, filename)
        lines = fix_file(filepath)
        total_files += 1
        total_lines += lines
        print(f"Fixed {filename} ({lines} lines)")

print(f"\nProcessed {total_files} files, {total_lines} total lines")