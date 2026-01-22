"""
Utility script for cleaning up orphaned avatar files.
Can be run manually or scheduled as a cron job.
"""
import asyncio
from pathlib import Path
from sqlalchemy import select
from app.core.database import async_session_maker
from app.models.user import User
from app.services.storage_service import storage_service


async def cleanup_orphaned_avatars():
    """
    Clean up avatar files that no longer have corresponding database records.

    This function:
    1. Scans all avatar directories
    2. Checks if the user exists in the database
    3. Checks if the avatar URL matches the files in storage
    4. Removes orphaned files

    Returns:
        Tuple of (users_cleaned, files_deleted)
    """
    users_cleaned = 0
    files_deleted = 0

    avatars_dir = Path("media") / "avatars"

    if not avatars_dir.exists():
        print("No avatars directory found")
        return users_cleaned, files_deleted

    # Get all user directories
    user_dirs = [d for d in avatars_dir.iterdir() if d.is_dir()]

    async with async_session_maker() as session:
        for user_dir in user_dirs:
            try:
                # Extract user_id from directory name
                user_id_str = user_dir.name

                # Check if user exists in database
                result = await session.execute(
                    select(User).where(User.id == user_id_str)
                )
                user = result.scalar_one_or_none()

                if not user:
                    # User doesn't exist - delete entire directory
                    for file_path in user_dir.iterdir():
                        if file_path.is_file():
                            file_path.unlink()
                            files_deleted += 1
                    user_dir.rmdir()
                    users_cleaned += 1
                    print(f"Deleted orphaned directory for non-existent user: {user_id_str}")
                    continue

                # User exists - check for orphaned files
                expected_files = set()

                if user.avatar_url:
                    filename = storage_service.extract_filename_from_url(user.avatar_url)
                    if filename:
                        expected_files.add(filename)

                if user.avatar_thumbnail_url:
                    filename = storage_service.extract_filename_from_url(user.avatar_thumbnail_url)
                    if filename:
                        expected_files.add(filename)

                # Check all files in user directory
                actual_files = set()
                for file_path in user_dir.iterdir():
                    if file_path.is_file():
                        actual_files.add(file_path.name)

                # Delete orphaned files (files that exist but aren't referenced)
                orphaned_files = actual_files - expected_files
                for filename in orphaned_files:
                    file_path = user_dir / filename
                    file_path.unlink()
                    files_deleted += 1
                    print(f"Deleted orphaned file: {file_path}")

                # Clean up empty directories
                if not any(user_dir.iterdir()):
                    user_dir.rmdir()
                    print(f"Removed empty directory: {user_dir}")

            except Exception as e:
                print(f"Error processing directory {user_dir}: {e}")
                continue

    return users_cleaned, files_deleted


async def cleanup_rate_limit_cache():
    """
    Clean up old entries from the rate limit cache.
    Should be called periodically to prevent memory bloat.
    """
    from app.services.rate_limit_service import rate_limit_service

    # Clean up entries older than 2 hours
    users_cleaned = rate_limit_service.cleanup_old_entries(max_age_seconds=7200)
    print(f"Cleaned up rate limit cache for {users_cleaned} users")
    return users_cleaned


async def main():
    """Main cleanup function."""
    print("Starting avatar cleanup...")
    users_cleaned, files_deleted = await cleanup_orphaned_avatars()
    print(f"\nCleanup complete:")
    print(f"  - Users cleaned: {users_cleaned}")
    print(f"  - Files deleted: {files_deleted}")

    print("\nCleaning up rate limit cache...")
    rate_limit_users = await cleanup_rate_limit_cache()
    print(f"Rate limit cache cleaned for {rate_limit_users} users")


if __name__ == "__main__":
    asyncio.run(main())
