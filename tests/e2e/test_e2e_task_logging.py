"""E2E tests for task logging workflows."""
import pytest
from sqlmodel import Session, select
from app.database import get_engine
from app.models import TaskEvent


@pytest.mark.e2e
def test_task_logging_from_dashboard_creates_event(authenticated_page, uvicorn_server):
    """Test logging a task from dashboard creates database event."""
    page = authenticated_page

    # Find the form with slug="feed" and click its submit button
    page.locator('form:has(input[name="slug"][value="feed"]) button[type="submit"]').click()

    # Wait for any success indication (adjust based on UI)
    page.wait_for_load_state("networkidle")

    # Verify event was created in database
    with Session(get_engine()) as session:
        events = session.exec(select(TaskEvent)).all()
        assert len(events) >= 1
        assert events[0].task_type.slug == "feed"
