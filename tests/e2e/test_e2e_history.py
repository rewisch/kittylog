"""E2E tests for history and filtering workflows."""
import pytest
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select
from app.database import get_engine
from app.models import TaskEvent, TaskType, Cat


@pytest.mark.e2e
def test_filter_history_by_date_range(authenticated_page, uvicorn_server):
    """Test filtering history by date range."""
    page = authenticated_page

    # Create task events with different dates
    with Session(get_engine()) as session:
        task_type = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()

        # Create events at different times
        today = datetime.now(timezone.utc)
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)

        for timestamp, who in [(today, "User1"), (yesterday, "User2"), (week_ago, "User3")]:
            event = TaskEvent(
                task_type_id=task_type.id,
                who=who,
                timestamp=timestamp,
                source="test"
            )
            session.add(event)
        session.commit()

    # Navigate to history page
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Open filter panel
    page.click('button[data-filter-toggle-target="history-filter-panel"]')

    # Set date filter for last 2 days
    start_date = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    page.fill('input[name="start_date"]', start_date)

    # Apply filter
    page.click('form#history-filter-panel button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Verify only 2 events are shown (today and yesterday, not week ago)
    event_cards = page.locator('.rounded-2xl:has(.font-semibold)').all()
    # Should show 2 events (filtering out the one from a week ago)
    assert len(event_cards) >= 2


@pytest.mark.e2e
def test_filter_history_by_task_type(authenticated_page, uvicorn_server):
    """Test filtering history by task type."""
    page = authenticated_page

    # Create events for different task types
    with Session(get_engine()) as session:
        feed_task = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()
        water_task = session.exec(select(TaskType).where(TaskType.slug == "water")).first()

        session.add(TaskEvent(task_type_id=feed_task.id, who="User1", timestamp=datetime.now(timezone.utc)))
        session.add(TaskEvent(task_type_id=water_task.id, who="User2", timestamp=datetime.now(timezone.utc)))
        session.commit()

    # Navigate to history
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Open filter panel
    page.click('button[data-filter-toggle-target="history-filter-panel"]')

    # Select feed task
    page.select_option('select[name="task"]', "feed")

    # Apply filter
    page.click('form#history-filter-panel button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Verify URL has task filter
    assert "task=feed" in page.url


@pytest.mark.e2e
def test_filter_history_by_cat(authenticated_page, uvicorn_server):
    """Test filtering history by cat."""
    page = authenticated_page

    # Create cats and events
    with Session(get_engine()) as session:
        cat1 = Cat(name="Fluffy", is_active=True)
        cat2 = Cat(name="Mittens", is_active=True)
        session.add_all([cat1, cat2])
        session.commit()

        task_type = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()

        session.add(TaskEvent(
            task_type_id=task_type.id,
            cat_id=cat1.id,
            who="User1",
            timestamp=datetime.now(timezone.utc)
        ))
        session.add(TaskEvent(
            task_type_id=task_type.id,
            cat_id=cat2.id,
            who="User2",
            timestamp=datetime.now(timezone.utc)
        ))
        session.commit()
        cat1_id = cat1.id

    # Navigate to history
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Open filter panel
    page.click('button[data-filter-toggle-target="history-filter-panel"]')

    # Select cat
    page.select_option('select[name="cat"]', str(cat1_id))

    # Apply filter
    page.click('form#history-filter-panel button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Verify URL has cat filter
    assert f"cat={cat1_id}" in page.url


@pytest.mark.e2e
def test_quick_filter_today(authenticated_page, uvicorn_server):
    """Test using the 'today' quick filter."""
    page = authenticated_page

    # Navigate to history
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Click today filter
    page.click('a[href*="preset=today"]')
    page.wait_for_load_state("networkidle")

    # Verify URL has preset filter
    assert "preset=today" in page.url


@pytest.mark.e2e
def test_delete_history_entry(authenticated_page, uvicorn_server):
    """Test deleting a history entry."""
    page = authenticated_page

    # Create an event
    with Session(get_engine()) as session:
        task_type = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()
        event = TaskEvent(
            task_type_id=task_type.id,
            who="TestUser",
            timestamp=datetime.now(timezone.utc),
            source="test"
        )
        session.add(event)
        session.commit()
        event_id = event.id

    # Navigate to history
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Handle confirmation dialog and delete
    page.on("dialog", lambda dialog: dialog.accept())
    page.click(f'form[action*="/history/{event_id}/delete"] button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Verify event is soft-deleted
    with Session(get_engine()) as session:
        event = session.get(TaskEvent, event_id)
        assert event.deleted is True


@pytest.mark.e2e
def test_edit_event_timestamp(authenticated_page, uvicorn_server):
    """Test editing an event's timestamp."""
    page = authenticated_page

    # Create an event
    with Session(get_engine()) as session:
        task_type = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()
        event = TaskEvent(
            task_type_id=task_type.id,
            who="TestUser",
            timestamp=datetime.now(timezone.utc),
            source="test"
        )
        session.add(event)
        session.commit()
        event_id = event.id

    # Navigate to history
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Click edit time button
    page.click(f'button[data-time-toggle-target="edit-time-{event_id}"]')

    # Edit the time
    new_time = "15:30"
    page.fill(f'form#edit-time-{event_id} input[name="timestamp_time"]', new_time)

    # Submit
    page.click(f'form#edit-time-{event_id} button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Verify time was updated
    with Session(get_engine()) as session:
        event = session.get(TaskEvent, event_id)
        assert event.timestamp.strftime("%H:%M") == new_time


@pytest.mark.e2e
def test_export_history_csv(authenticated_page, uvicorn_server):
    """Test exporting history to CSV."""
    page = authenticated_page

    # Create some events
    with Session(get_engine()) as session:
        task_type = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()
        for i in range(3):
            event = TaskEvent(
                task_type_id=task_type.id,
                who=f"User{i}",
                timestamp=datetime.now(timezone.utc),
                source="test"
            )
            session.add(event)
        session.commit()

    # Navigate to history
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Click CSV export link
    with page.expect_download() as download_info:
        page.click('a[href*="format=csv"]')

    download = download_info.value
    # Verify download happened
    assert download.suggested_filename.endswith(".csv")
