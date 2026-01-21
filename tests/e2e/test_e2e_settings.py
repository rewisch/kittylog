"""E2E tests for settings page workflows."""
import pytest


@pytest.mark.e2e
def test_navigate_to_settings_page(authenticated_page, uvicorn_server):
    """Test navigating to settings page."""
    page = authenticated_page

    # Click settings link
    page.click('a[href*="/settings"]')
    page.wait_for_url(f"{uvicorn_server}/settings*")

    # Verify we're on settings page
    assert "/settings" in page.url
    # Check for settings content
    assert page.locator('text="Push"').is_visible() or page.locator('[data-push-enable]').count() > 0


@pytest.mark.e2e
def test_change_language_via_header(authenticated_page, uvicorn_server):
    """Test changing language through header toggle."""
    page = authenticated_page

    # Click DE language link
    page.click('a[href*="lang=de"]')
    page.wait_for_load_state("networkidle")

    # Verify URL has lang parameter
    assert "lang=de" in page.url

    # Click EN language link
    page.click('a[href*="lang=en"]')
    page.wait_for_load_state("networkidle")

    # Verify URL has lang parameter
    assert "lang=en" in page.url


@pytest.mark.e2e
def test_settings_page_shows_push_notification_card(authenticated_page, uvicorn_server):
    """Test that settings page displays push notification settings."""
    page = authenticated_page

    # Navigate to settings
    page.click('a[href*="/settings"]')
    page.wait_for_url(f"{uvicorn_server}/settings*")

    # Verify push notification card exists
    push_card = page.locator('#push-card')
    assert push_card.is_visible()

    # Verify buttons exist
    assert page.locator('[data-push-enable]').is_visible()
    assert page.locator('[data-push-disable]').is_visible()


@pytest.mark.e2e
def test_settings_page_shows_log_notification_card(authenticated_page, uvicorn_server):
    """Test that settings page displays log notification toggle."""
    page = authenticated_page

    # Navigate to settings
    page.click('a[href*="/settings"]')
    page.wait_for_url(f"{uvicorn_server}/settings*")

    # Verify log notification card exists
    log_card = page.locator('#log-notify-card')
    assert log_card.is_visible()

    # Verify toggle exists
    assert page.locator('[data-log-toggle]').is_visible()
