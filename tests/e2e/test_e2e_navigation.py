"""E2E tests for navigation."""
import pytest


@pytest.mark.e2e
def test_navigation_to_history_page(authenticated_page, uvicorn_server):
    """Test navigation to history page works."""
    page = authenticated_page

    # Click history link (href includes lang param, so use partial match)
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Verify we're on history page
    assert "/history" in page.url
