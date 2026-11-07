"""English / Arabic support and the RTL layout."""

import pytest
from django.utils import translation

pytestmark = pytest.mark.django_db


def test_both_languages_are_configured(settings):
    codes = [code for code, _ in settings.LANGUAGES]
    assert "en" in codes
    assert "ar" in codes


def test_arabic_is_marked_as_bidi(settings):
    assert "ar" in settings.LANGUAGES_BIDI


def test_the_page_switches_to_arabic_and_flips_the_direction(client, manager_user):
    client.force_login(manager_user)
    # Django's set_language only persists the choice on a POST.
    response = client.post("/i18n/setlang/", {"language": "ar", "next": "/"})
    assert response.status_code == 302

    response = client.get("/")
    content = response.content.decode("utf-8")
    assert 'dir="rtl"' in content
    assert 'lang="ar"' in content
    # A translated string must show up.
    assert "نظرة عامة" in content


def test_the_page_falls_back_to_english(client, manager_user):
    client.force_login(manager_user)
    response = client.get("/")
    content = response.content.decode("utf-8")
    assert 'dir="ltr"' in content
    assert "Overview" in content


def test_arabic_translations_are_compiled():
    from django.utils.translation import gettext

    with translation.override("ar"):
        assert gettext("Overview") == "نظرة عامة"
        assert gettext("Defect rate") == "نسبة العيوب"


def test_the_arabic_catalogue_covers_every_string():
    import polib

    catalogue = polib.pofile("locale/ar/LC_MESSAGES/django.po")
    untranslated = [entry.msgid for entry in catalogue if not entry.msgstr]
    assert untranslated == []
