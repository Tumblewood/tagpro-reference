import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tagproref.settings")
django.setup()

from reference.models import AwardType, AwardReceived


def merge_award_types(source_id, target_id):
    """
    Merge source award type into target award type.
    Updates all AwardReceived records pointing to source to point to target,
    then deletes the source award type.
    """
    try:
        source = AwardType.objects.get(id=source_id)
    except AwardType.DoesNotExist:
        print(f"Error: Source award type with id {source_id} not found")
        return False

    try:
        target = AwardType.objects.get(id=target_id)
    except AwardType.DoesNotExist:
        print(f"Error: Target award type with id {target_id} not found")
        return False

    # Count how many awards will be updated
    awards_to_update = AwardReceived.objects.filter(award=source)
    count = awards_to_update.count()

    print(f"\nMerging award types:")
    print(f"  Source: {source.name} (id={source.id}, abbr={source.abbr})")
    print(f"  Target: {target.name} (id={target.id}, abbr={target.abbr})")
    print(f"\nThis will update {count} AwardReceived record(s)")

    # Ask for confirmation
    confirm = input("\nAre you sure you want to proceed? (yes/no): ")
    if confirm.lower() != "yes":
        print("Merge cancelled")
        return False

    # Update all AwardReceived records
    updated = awards_to_update.update(award=target)
    print(f"\nUpdated {updated} AwardReceived record(s)")

    # Delete the source award type
    source_name = source.name
    source.delete()
    print(f"Deleted award type: {source_name}")

    print("\nMerge complete!")
    return True


def list_award_types():
    """List all award types with their IDs."""
    award_types = AwardType.objects.all().order_by('ordering')
    print("\nAvailable award types:")
    print("-" * 80)
    for award in award_types:
        count = AwardReceived.objects.filter(award=award).count()
        print(f"  ID {award.id:3d}: {award.name:40s} ({award.abbr}) - {count} awards")
    print("-" * 80)


if __name__ == "__main__":
    print("=" * 80)
    print("Award Type Merge Tool")
    print("=" * 80)

    list_award_types()

    print("\nEnter award type IDs to merge:")
    try:
        source_id = int(input("  Source award type ID (will be deleted): "))
        target_id = int(input("  Target award type ID (will receive all awards): "))
    except (ValueError, KeyboardInterrupt):
        print("\nInvalid input. Exiting.")
        exit(1)

    merge_award_types(source_id, target_id)
