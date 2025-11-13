#!/usr/bin/env python3
"""
Test script to verify notification creation fixes.

This script tests:
1. Company notifications when user swipes RIGHT (user_id=NULL, company_id set)
2. User notifications when company updates application status (user_id set, company_id=NULL)
3. Proper relationship loading in repositories
"""

import asyncio
import os
import sys
from uuid import UUID

# Add app to path
sys.path.insert(0, '/app')

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import settings
from app.repositories.application_repository import ApplicationRepository
from app.repositories.job_repository import JobRepository
from app.services.notification_service import NotificationService
from sqlalchemy import select, text


async def test_notification_fixes():
    """Test all notification creation scenarios."""
    print("=" * 80)
    print("NOTIFICATION FIX VERIFICATION TEST")
    print("=" * 80)
    print()

    # Create async engine and session
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        notification_service = NotificationService()
        app_repo = ApplicationRepository()
        job_repo = JobRepository()

        # Test 1: Check database schema
        print("Test 1: Verifying database schema")
        print("-" * 80)
        result = await db.execute(text("""
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'notifications'
            AND column_name IN ('user_id', 'company_id')
            ORDER BY column_name;
        """))
        columns = result.fetchall()
        for col in columns:
            nullable_str = "✓ NULLABLE" if col[1] == "YES" else "✗ NOT NULL"
            print(f"  {col[0]}: {nullable_str}")

        if all(col[1] == "YES" for col in columns):
            print("\n✓ PASSED: Both user_id and company_id are nullable")
        else:
            print("\n✗ FAILED: user_id and company_id should both be nullable")
            return False
        print()

        # Test 2: Find a test application
        print("Test 2: Finding test application with relationships")
        print("-" * 80)
        result = await db.execute(text("""
            SELECT a.id, a.user_id, a.job_id, a.status, a.stage
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            JOIN users u ON a.user_id = u.id
            WHERE a.status != 'REJECTED' AND a.status != 'HIRED'
            LIMIT 1;
        """))
        row = result.fetchone()

        if not row:
            print("✗ No test application found. Please create an application first.")
            return False

        app_id = row[0]
        user_id = row[1]
        job_id = row[2]
        print(f"  Found application: {app_id}")
        print(f"  User ID: {user_id}")
        print(f"  Job ID: {job_id}")
        print(f"  Status: {row[3]}")
        print(f"  Stage: {row[4]}")
        print()

        # Test 3: Test ApplicationRepository.get() loads relationships
        print("Test 3: Testing ApplicationRepository.get() loads relationships")
        print("-" * 80)
        application = await app_repo.get(db, app_id)

        if not application:
            print("✗ FAILED: Application not found")
            return False

        print(f"  Application loaded: {application.id}")

        # Check if user relationship is loaded
        try:
            user_email = application.user.email
            print(f"  ✓ User relationship loaded: {user_email}")
        except Exception as e:
            print(f"  ✗ User relationship not loaded: {e}")
            return False

        # Check if job relationship is loaded
        try:
            job_title = application.job.title
            print(f"  ✓ Job relationship loaded: {job_title}")
        except Exception as e:
            print(f"  ✗ Job relationship not loaded: {e}")
            return False

        # Check if job.company relationship is loaded
        try:
            company_name = application.job.company.name
            company_id = application.job.company.id
            print(f"  ✓ Job.Company relationship loaded: {company_name} ({company_id})")
        except Exception as e:
            print(f"  ✗ Job.Company relationship not loaded: {e}")
            return False

        print("\n✓ PASSED: All relationships loaded correctly")
        print()

        # Test 4: Test JobRepository.get() loads company
        print("Test 4: Testing JobRepository.get() loads company relationship")
        print("-" * 80)
        job = await job_repo.get(db, job_id)

        if not job:
            print("✗ FAILED: Job not found")
            return False

        print(f"  Job loaded: {job.id}")

        try:
            job_company_name = job.company.name
            print(f"  ✓ Company relationship loaded: {job_company_name}")
        except Exception as e:
            print(f"  ✗ Company relationship not loaded: {e}")
            return False

        print("\n✓ PASSED: Job company relationship loaded correctly")
        print()

        # Test 5: Create company notification (user swipes RIGHT scenario)
        print("Test 5: Testing company notification creation (user_id=NULL, company_id set)")
        print("-" * 80)

        # First, clear existing notifications for this application
        await db.execute(text("""
            DELETE FROM notifications WHERE application_id = :app_id
        """), {"app_id": app_id})
        await db.commit()

        try:
            # Create notification for company about new application
            notification = await notification_service.create_new_application_notification(
                db=db,
                application_id=app_id
            )
            await db.commit()

            print(f"  ✓ Notification created: {notification.id}")
            print(f"  Title: {notification.title}")
            print(f"  Type: {notification.type}")
            print(f"  user_id: {notification.user_id}")
            print(f"  company_id: {notification.company_id}")

            if notification.user_id is None and notification.company_id is not None:
                print("\n✓ PASSED: Company notification has NULL user_id and non-NULL company_id")
            else:
                print("\n✗ FAILED: Company notification should have NULL user_id and non-NULL company_id")
                return False

        except Exception as e:
            print(f"\n✗ FAILED: Could not create company notification: {e}")
            import traceback
            traceback.print_exc()
            return False

        print()

        # Test 6: Create user notification (company updates status scenario)
        print("Test 6: Testing user notification creation (user_id set, company_id=NULL)")
        print("-" * 80)

        # Clear notifications again
        await db.execute(text("""
            DELETE FROM notifications WHERE application_id = :app_id
        """), {"app_id": app_id})
        await db.commit()

        try:
            # Create notification for user about status change
            notification = await notification_service.create_application_status_notification(
                db=db,
                application_id=app_id,
                old_stage=application.stage,
                new_stage="REVIEW"
            )
            await db.commit()

            print(f"  ✓ Notification created: {notification.id}")
            print(f"  Title: {notification.title}")
            print(f"  Type: {notification.type}")
            print(f"  user_id: {notification.user_id}")
            print(f"  company_id: {notification.company_id}")

            if notification.user_id is not None and notification.company_id is None:
                print("\n✓ PASSED: User notification has non-NULL user_id and NULL company_id")
            else:
                print("\n✗ FAILED: User notification should have non-NULL user_id and NULL company_id")
                return False

        except Exception as e:
            print(f"\n✗ FAILED: Could not create user notification: {e}")
            import traceback
            traceback.print_exc()
            return False

        print()

        # Test 7: Verify notifications in database
        print("Test 7: Verifying notifications persisted in database")
        print("-" * 80)
        result = await db.execute(text("""
            SELECT id, user_id, company_id, title, type
            FROM notifications
            ORDER BY created_at DESC
            LIMIT 5;
        """))
        notifications = result.fetchall()

        print(f"  Found {len(notifications)} recent notification(s):")
        for notif in notifications:
            user_status = "NULL" if notif[1] is None else str(notif[1])[:8]
            company_status = "NULL" if notif[2] is None else str(notif[2])[:8]
            print(f"    - {notif[4]}: user_id={user_status}, company_id={company_status}")

        if len(notifications) > 0:
            print("\n✓ PASSED: Notifications successfully persisted in database")
        else:
            print("\n✗ FAILED: No notifications found in database")
            return False

        print()

    return True


async def main():
    """Run all tests."""
    try:
        success = await test_notification_fixes()

        print("=" * 80)
        if success:
            print("ALL TESTS PASSED ✓")
            print()
            print("Summary:")
            print("  1. Database schema correctly allows NULL user_id")
            print("  2. ApplicationRepository.get() loads user, job, and job.company relationships")
            print("  3. JobRepository.get() loads company relationship")
            print("  4. Company notifications created with user_id=NULL, company_id set")
            print("  5. User notifications created with user_id set, company_id=NULL")
            print("  6. Notifications successfully persisted in database")
            return 0
        else:
            print("SOME TESTS FAILED ✗")
            print()
            print("Please review the output above for details.")
            return 1
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        print("=" * 80)


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
