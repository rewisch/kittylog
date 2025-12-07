from __future__ import annotations

from typing import Mapping

from fastapi import Request


TranslationDict = Mapping[str, Mapping[str, str]]

# English is the default; German is the primary alternate.
TRANSLATIONS: TranslationDict = {
    "en": {
        "app_tagline": "QR-first cat care tracker",
        "dashboard_title": "Cat care dashboard",
        "dashboard_subtitle": "Log chores instantly from here or by scanning a QR.",
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
        "filters_apply": "Apply",
        "filters_reset": "Reset",
        "history_empty": "No events match the current filters yet.",
        "confirm_cta": "Confirm",
        "confirm_hint": "Add ?auto=1 to skip this screen.",
        "confirm_message_logged": "Logged!",
        "back_to_dashboard": "Back to dashboard",
        "last_logged": "Last logged",
        "all_tasks": "All tasks",
        "start_date": "Start date",
        "end_date": "End date",
    },
    "de": {
        "app_tagline": "QR-Tracker für Katzenpflege",
        "dashboard_title": "Katzenpflege-Dashboard",
        "dashboard_subtitle": "Trage Aufgaben hier oder per QR-Scan sofort ein.",
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
        "filters_apply": "Anwenden",
        "filters_reset": "Zurücksetzen",
        "history_empty": "Keine Einträge für diese Filter.",
        "confirm_cta": "Bestätigen",
        "confirm_hint": "Mit ?auto=1 diese Seite überspringen.",
        "confirm_message_logged": "Gespeichert!",
        "back_to_dashboard": "Zurück zum Dashboard",
        "last_logged": "Zuletzt protokolliert",
        "all_tasks": "Alle Aufgaben",
        "start_date": "Startdatum",
        "end_date": "Enddatum",
    },
}


SUPPORTED_LANGS = ("en", "de")
DEFAULT_LANG = "en"


def translate(key: str, lang: str) -> str:
    """Return translated string for key and lang, falling back to English."""
    if lang not in TRANSLATIONS:
        lang = DEFAULT_LANG
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS[DEFAULT_LANG].get(key, key))


def resolve_language(request: Request) -> str:
    """Pick language from query param or cookie; default to English."""
    query_lang = request.query_params.get("lang")
    if query_lang in SUPPORTED_LANGS:
        return query_lang
    cookie_lang = request.cookies.get("lang")
    if cookie_lang in SUPPORTED_LANGS:
        return cookie_lang
    return DEFAULT_LANG
