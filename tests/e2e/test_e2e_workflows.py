"""E2E tests for complex user workflows."""
import pytest
from sqlmodel import Session, select
from app.database import get_engine
from app.models import Cat


@pytest.mark.e2e
def test_workflow_create_cat_edit_then_delete(authenticated_page, uvicorn_server):
    """Test creating, editing, then deleting a cat."""
    page = authenticated_page

    # Create cat
    page.click('a[href*="/cats"]')
    page.wait_for_url(f"{uvicorn_server}/cats*")

    page.click('button[data-cat-toggle-target="cat-create-panel"]')
    page.fill('form[action*="/cats"] input[name="name"]', "TempCat")
    page.click('form[action*="/cats"] button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Get cat ID
    with Session(get_engine()) as session:
        cat = session.exec(select(Cat).where(Cat.name == "TempCat")).first()
        assert cat is not None
        cat_id = cat.id

    # Edit cat
    page.click(f'button[data-cat-toggle-target="cat-edit-{cat_id}"]')
    edit_form = page.locator(f'form[action*="/cats/{cat_id}/update"]')
    edit_form.locator('input[name="name"]').fill("EditedCat")
    edit_form.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Verify edit
    with Session(get_engine()) as session:
        cat = session.get(Cat, cat_id)
        assert cat.name == "EditedCat"

    # Delete cat
    page.click(f'button[data-cat-toggle-target="cat-edit-{cat_id}"]')
    delete_form = page.locator(f'form[action*="/cats/{cat_id}/delete"]')
    page.on("dialog", lambda dialog: dialog.accept())
    delete_form.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Verify deletion (soft delete - deactivation)
    with Session(get_engine()) as session:
        cat = session.get(Cat, cat_id)
        assert cat is not None
        assert cat.is_active is False


@pytest.mark.e2e
def test_workflow_navigation_through_all_pages(authenticated_page, uvicorn_server):
    """Test navigating through all main pages in sequence."""
    page = authenticated_page

    # Dashboard -> History
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")
    assert "/history" in page.url

    # History -> Cats
    page.click('a[href*="/cats"]')
    page.wait_for_url(f"{uvicorn_server}/cats*")
    assert "/cats" in page.url

    # Cats -> Insights
    page.click('a[href*="/insights"]')
    page.wait_for_url(f"{uvicorn_server}/insights*")
    assert "/insights" in page.url

    # Insights -> Settings
    page.click('a[href*="/settings"]')
    page.wait_for_url(f"{uvicorn_server}/settings*")
    assert "/settings" in page.url

    # Settings -> Dashboard
    page.click('a[href*="/?"]')
    page.wait_for_url(f"{uvicorn_server}/*")
    assert page.url.rstrip('/') == uvicorn_server or "?" in page.url


@pytest.mark.e2e
def test_workflow_qr_log_then_verify_in_history(authenticated_page, uvicorn_server):
    """Test logging via QR code and verifying in history."""
    page = authenticated_page

    # Log via QR
    page.goto(f"{uvicorn_server}/q/feed?auto=1&note=QRTest")
    page.wait_for_load_state("networkidle")

    # Navigate to history
    page.click('a[href*="/history"]')
    page.wait_for_url(f"{uvicorn_server}/history*")

    # Verify QR log appears
    assert page.locator('text="QRTest"').count() > 0
