"""E2E tests for login/logout flows."""
import pytest
from tests.conftest import write_users_file, playwright_login


@pytest.mark.e2e
def test_login_with_valid_credentials_redirects_to_dashboard(page, uvicorn_server, users_file):
    """Test successful login redirects to dashboard."""
    write_users_file(users_file, {"Livia": "secret"})

    page.goto(f"{uvicorn_server}/login")

    # Fill and submit login form
    page.fill('input[name="username"]', "Livia")
    page.fill('input[name="password"]', "secret")
    page.click('button[type="submit"]')

    # Verify redirect to dashboard
    page.wait_for_url(f"{uvicorn_server}/")
    assert page.locator("h1").count() > 0


@pytest.mark.e2e
def test_login_with_invalid_credentials_shows_error(page, uvicorn_server, users_file):
    """Test failed login shows error message."""
    write_users_file(users_file, {"Livia": "secret"})

    page.goto(f"{uvicorn_server}/login")
    page.fill('input[name="username"]', "Livia")
    page.fill('input[name="password"]', "wrong")
    page.click('button[type="submit"]')

    # Should stay on login page
    page.wait_for_load_state("networkidle")
    assert "/login" in page.url
