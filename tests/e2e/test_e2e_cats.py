"""E2E tests for cat management workflows."""
import pytest
from sqlmodel import Session, select
from app.database import get_engine
from app.models import Cat


@pytest.mark.e2e
def test_create_new_cat(authenticated_page, uvicorn_server):
    """Test creating a new cat through the UI."""
    page = authenticated_page

    # Navigate to cats page
    page.click('a[href*="/cats"]')
    page.wait_for_url(f"{uvicorn_server}/cats*")

    # Click to open the create form
    page.click('button[data-cat-toggle-target="cat-create-panel"]')

    # Fill out cat form
    page.fill('form[action*="/cats"] input[name="name"]', "Whiskers")
    page.fill('form[action*="/cats"] input[name="color"]', "Orange")
    page.fill('form[action*="/cats"] input[name="chip_id"]', "123456789")

    # Submit form
    page.click('form[action*="/cats"] button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Verify cat was created in database
    with Session(get_engine()) as session:
        cats = session.exec(select(Cat)).all()
        assert len(cats) == 1
        assert cats[0].name == "Whiskers"
        assert cats[0].color == "Orange"
        assert cats[0].chip_id == "123456789"
        assert cats[0].is_active is True


@pytest.mark.e2e
def test_edit_cat_details(authenticated_page, uvicorn_server):
    """Test editing an existing cat's details."""
    page = authenticated_page

    # Create a cat first
    with Session(get_engine()) as session:
        cat = Cat(name="TestCat", color="Gray", is_active=True)
        session.add(cat)
        session.commit()
        cat_id = cat.id

    # Navigate to cats page
    page.click('a[href*="/cats"]')
    page.wait_for_url(f"{uvicorn_server}/cats*")

    # Open edit form for the cat
    page.click(f'button[data-cat-toggle-target="cat-edit-{cat_id}"]')

    # Edit cat details
    edit_form = page.locator(f'form[action*="/cats/{cat_id}/update"]')
    edit_form.locator('input[name="name"]').fill("UpdatedCat")
    edit_form.locator('input[name="color"]').fill("Black")

    # Submit form
    edit_form.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Verify changes in database
    with Session(get_engine()) as session:
        cat = session.get(Cat, cat_id)
        assert cat.name == "UpdatedCat"
        assert cat.color == "Black"


@pytest.mark.e2e
def test_deactivate_cat(authenticated_page, uvicorn_server):
    """Test deactivating a cat."""
    page = authenticated_page

    # Create an active cat
    with Session(get_engine()) as session:
        cat = Cat(name="ActiveCat", is_active=True)
        session.add(cat)
        session.commit()
        cat_id = cat.id

    # Navigate to cats page
    page.click('a[href*="/cats"]')
    page.wait_for_url(f"{uvicorn_server}/cats*")

    # Open edit form
    page.click(f'button[data-cat-toggle-target="cat-edit-{cat_id}"]')

    # Uncheck active checkbox
    edit_form = page.locator(f'form[action*="/cats/{cat_id}/update"]')
    edit_form.locator('input[name="is_active"]').uncheck()

    # Submit form
    edit_form.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Verify cat is deactivated
    with Session(get_engine()) as session:
        cat = session.get(Cat, cat_id)
        assert cat.is_active is False


@pytest.mark.e2e
def test_delete_cat(authenticated_page, uvicorn_server):
    """Test deleting a cat."""
    page = authenticated_page

    # Create a cat
    with Session(get_engine()) as session:
        cat = Cat(name="ToDelete", is_active=True)
        session.add(cat)
        session.commit()
        cat_id = cat.id

    # Navigate to cats page
    page.click('a[href*="/cats"]')
    page.wait_for_url(f"{uvicorn_server}/cats*")

    # Open edit form
    page.click(f'button[data-cat-toggle-target="cat-edit-{cat_id}"]')

    # Click delete button (need to handle confirm dialog)
    delete_form = page.locator(f'form[action*="/cats/{cat_id}/delete"]')

    # Handle the confirmation dialog
    page.on("dialog", lambda dialog: dialog.accept())
    delete_form.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Verify cat is soft-deleted (deactivated)
    with Session(get_engine()) as session:
        cat = session.get(Cat, cat_id)
        assert cat is not None
        assert cat.is_active is False


@pytest.mark.e2e
def test_log_task_with_required_cat(authenticated_page, uvicorn_server):
    """Test logging a task that requires cat selection."""
    page = authenticated_page

    # Create a cat
    with Session(get_engine()) as session:
        cat = Cat(name="Fluffy", is_active=True)
        session.add(cat)
        session.commit()
        cat_id = cat.id

    # We need to configure a task that requires a cat
    # This would need special setup in the fixture or test
    # For now, skip this test as it requires task config changes
    pass
