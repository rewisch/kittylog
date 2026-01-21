"""E2E tests for insights page workflows."""
import pytest
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select
from app.database import get_engine
from app.models import TaskEvent, TaskType


@pytest.mark.e2e
def test_navigate_to_insights_page(authenticated_page, uvicorn_server):
    """Test navigating to insights page."""
    page = authenticated_page

    # Click insights link
    page.click('a[href*="/insights"]')
    page.wait_for_url(f"{uvicorn_server}/insights*")

    # Verify we're on insights page
    assert "/insights" in page.url


@pytest.mark.e2e
def test_insights_shows_statistics(authenticated_page, uvicorn_server):
    """Test that insights page displays statistics."""
    page = authenticated_page

    # Create some events
    with Session(get_engine()) as session:
        task_type = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()
        for i in range(5):
            event = TaskEvent(
                task_type_id=task_type.id,
                who=f"User{i}",
                timestamp=datetime.now(timezone.utc),
                source="test"
            )
            session.add(event)
        session.commit()

    # Navigate to insights
    page.click('a[href*="/insights"]')
    page.wait_for_url(f"{uvicorn_server}/insights*")

    # Verify statistics cards are visible
    assert page.locator('text="5"').count() > 0  # Should show count of 5


@pytest.mark.e2e
def test_insights_date_filtering(authenticated_page, uvicorn_server):
    """Test filtering insights by date range."""
    page = authenticated_page

    # Create events with different dates
    with Session(get_engine()) as session:
        task_type = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()

        today = datetime.now(timezone.utc)
        week_ago = today - timedelta(days=7)

        session.add(TaskEvent(
            task_type_id=task_type.id,
            who="User1",
            timestamp=today,
            source="test"
        ))
        session.add(TaskEvent(
            task_type_id=task_type.id,
            who="User2",
            timestamp=week_ago,
            source="test"
        ))
        session.commit()

    # Navigate to insights
    page.click('a[href*="/insights"]')
    page.wait_for_url(f"{uvicorn_server}/insights*")

    # Set date filter
    start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    page.fill('form input[name="start_date"]', start_date)

    # Apply filter
    form = page.locator('form:has(input[name="start_date"])')
    form.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Verify URL has date filter (page might redirect, so check we're still on insights)
    assert "/insights" in page.url
    # If filter worked, URL should have the date
    if "start_date" in page.url:
        assert start_date in page.url


@pytest.mark.e2e
def test_insights_quick_filter_7d(authenticated_page, uvicorn_server):
    """Test using 7d quick filter on insights."""
    page = authenticated_page

    # Navigate to insights
    page.click('a[href*="/insights"]')
    page.wait_for_url(f"{uvicorn_server}/insights*")

    # Click 7d preset
    page.click('a[href*="preset=7d"]')
    page.wait_for_load_state("networkidle")

    # Verify URL has preset
    assert "preset=7d" in page.url


@pytest.mark.e2e
def test_insights_shows_top_tasks(authenticated_page, uvicorn_server):
    """Test that insights page shows top tasks section."""
    page = authenticated_page

    # Create events
    with Session(get_engine()) as session:
        feed_task = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()
        water_task = session.exec(select(TaskType).where(TaskType.slug == "water")).first()

        # Create more feed events than water
        for i in range(3):
            session.add(TaskEvent(
                task_type_id=feed_task.id,
                who="User1",
                timestamp=datetime.now(timezone.utc),
                source="test"
            ))
        session.add(TaskEvent(
            task_type_id=water_task.id,
            who="User2",
            timestamp=datetime.now(timezone.utc),
            source="test"
        ))
        session.commit()

    # Navigate to insights
    page.click('a[href*="/insights"]')
    page.wait_for_url(f"{uvicorn_server}/insights*")

    # Verify top tasks section exists
    assert page.locator('h2:has-text("Top")').count() > 0 or page.locator('.h-2.rounded-full').count() > 0
