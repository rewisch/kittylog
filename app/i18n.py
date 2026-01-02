from __future__ import annotations

from typing import Mapping

from fastapi import Request

from .settings import get_settings

TranslationDict = Mapping[str, Mapping[str, str]]

# English is the default; German is the primary alternate.
TRANSLATIONS: TranslationDict = {
    "en": {
        "app_tagline": "QR-first cat care tracker",
        "dashboard_title": "Cat care dashboard",
        "dashboard_subtitle": "Log chores instantly from here or by scanning a QR.",
        "nav_dashboard": "Dashboard",
        "nav_history": "History",
        "overview_label": "Overview",
        "quick_qr": "Quick QR",
        "confirm_screen": "Confirm screen",
        "auto_log": "Auto log",
        "log_now": "Log now",
        "log_form_who": "Who did it?",
        "log_form_note": "Note (optional)",
        "not_logged_yet": "Not logged yet.",
        "history_title": "Everything that's been logged",
        "history_subtitle": "Filter by task or date range to audit chores.",
        "history_label": "History",
        "export_csv": "Export CSV",
        "quick_ranges": "Quick ranges",
        "range_today": "Today",
        "range_7d": "Last 7 days",
        "range_30d": "Last 30 days",
        "filter_task": "Task",
        "filter_start": "Start",
        "filter_end": "End",
        "filter_preset": "Range",
        "applied_filters": "Applied",
        "prev_page": "Previous",
        "next_page": "Next",
        "page_label": "Page",
        "filters_apply": "Apply",
        "filters_reset": "Reset",
        "history_empty": "No events match the current filters yet.",
        "delete_entry": "Delete",
        "delete_confirm": "Delete this entry? It will stay hidden but remain in the log.",
        "confirm_cta": "Confirm",
        "confirm_hint": "Add ?auto=1 to skip this screen.",
        "confirm_message_logged": "Logged!",
        "toast_logged": "Saved to history",
        "back_to_dashboard": "Back to dashboard",
        "last_logged": "Last logged",
        "all_tasks": "All tasks",
        "start_date": "Start date",
        "end_date": "End date",
        "login_title": "Sign in",
        "login_subtitle": "Only invited users can access KittyLog.",
        "username_label": "Username",
        "password_label": "Password",
        "login_button": "Log in",
        "login_error": "Invalid username or password.",
        "logout_label": "Log out",
        "logged_in_as": "Logged in as",
    },
    "de": {
        "app_tagline": "QR-Tracker für Katzenpflege",
        "dashboard_title": "Katzenpflege-Dashboard",
        "dashboard_subtitle": "Trage Aufgaben hier oder per QR-Scan sofort ein.",
        "nav_dashboard": "Dashboard",
        "nav_history": "Historie",
        "overview_label": "Übersicht",
        "quick_qr": "Schnell-QR",
        "confirm_screen": "Bestätigungsseite",
        "auto_log": "Sofort protokollieren",
        "log_now": "Jetzt eintragen",
        "log_form_who": "Wer war es?",
        "log_form_note": "Notiz (optional)",
        "not_logged_yet": "Noch nichts protokolliert.",
        "history_title": "Alle protokollierten Einträge",
        "history_subtitle": "Nach Aufgabe oder Zeitraum filtern.",
        "history_label": "Historie",
        "export_csv": "Als CSV exportieren",
        "quick_ranges": "Schnellbereich",
        "range_today": "Heute",
        "range_7d": "Letzte 7 Tage",
        "range_30d": "Letzte 30 Tage",
        "filter_task": "Aufgabe",
        "filter_start": "Start",
        "filter_end": "Ende",
        "filter_preset": "Zeitraum",
        "applied_filters": "Aktiv",
        "prev_page": "Zurück",
        "next_page": "Weiter",
        "page_label": "Seite",
        "filters_apply": "Anwenden",
        "filters_reset": "Zurücksetzen",
        "history_empty": "Keine Einträge für diese Filter.",
        "delete_entry": "Löschen",
        "delete_confirm": "Eintrag löschen? Er bleibt verborgen, aber erhalten.",
        "confirm_cta": "Bestätigen",
        "confirm_hint": "Mit ?auto=1 diese Seite überspringen.",
        "confirm_message_logged": "Gespeichert!",
        "toast_logged": "Gespeichert",
        "back_to_dashboard": "Zurück zum Dashboard",
        "last_logged": "Zuletzt protokolliert",
        "all_tasks": "Alle Aufgaben",
        "start_date": "Startdatum",
        "end_date": "Enddatum",
        "login_title": "Anmelden",
        "login_subtitle": "Zugriff nur für eingeladene Nutzer.",
        "username_label": "Benutzername",
        "password_label": "Passwort",
        "login_button": "Einloggen",
        "login_error": "Benutzername oder Passwort ungültig.",
        "logout_label": "Abmelden",
        "logged_in_as": "Angemeldet als",
    },
}


SUPPORTED_LANGS = ("en", "de")
DEFAULT_LANG = "en"


def _default_lang() -> str:
    configured = get_settings().default_language
    return configured if configured in SUPPORTED_LANGS else DEFAULT_LANG


def translate(key: str, lang: str) -> str:
    """Return translated string for key and lang, falling back to English."""
    if lang not in TRANSLATIONS:
        lang = _default_lang()
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS[DEFAULT_LANG].get(key, key))


def resolve_language(request: Request) -> str:
    """Pick language from query param or cookie; default from settings."""
    query_lang = request.query_params.get("lang")
    if query_lang in SUPPORTED_LANGS:
        return query_lang
    cookie_lang = request.cookies.get("lang")
    if cookie_lang in SUPPORTED_LANGS:
        return cookie_lang
    return _default_lang()
