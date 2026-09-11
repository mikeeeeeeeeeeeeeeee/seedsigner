import os
from unittest.mock import patch

from base import BaseTest
from seedsigner.models.settings_definition import SettingsConstants


class TestSettingsDefinition(BaseTest):
    @classmethod
    def setup_class(cls):
        super().setup_class()


    def test__get_detected_languages(self):
        """ Should auto-detect onboard languages based on the supported locales list """
        detected_languages = [lang_tuple[0] for lang_tuple in SettingsConstants.get_detected_languages()]

        # Find an unused language code; avoiding hard coding a language code to keep
        # this test future proof.
        absent_language_code = None
        for language_code in SettingsConstants.ALL_LOCALES.keys():
            if language_code not in detected_languages:
                absent_language_code = language_code
                break
        
        # Should only fail if we've absolutely crushed the global translations!!!
        assert absent_language_code is not None

        root = os.path.join(os.getcwd(), "src", "seedsigner", "resources", "seedsigner-translations", "l10n")

        # We're going to mock the `root` results to include the absent language code's .mo file
        mocked_results = [(os.path.join(root, "en", "LC_MESSAGES"), [], ["messages.po", "messages.mo"])]
        mocked_results.append((os.path.join(root, absent_language_code, "LC_MESSAGES"), [], ["messages.po", "messages.mo"]))
        with patch("os.walk", return_value=mocked_results):
            # Recheck w/our mocked dir listing:
            detected_languages = [lang_tuple[0] for lang_tuple in SettingsConstants.get_detected_languages()]
            assert absent_language_code in detected_languages


    def test__every_user_facing_setting_explains_itself(self):
        """
            Each setting the user can reach should carry help_text, which the settings
            screen renders under its name. A setting that only shows a name like "Sig
            types" or "Xpub QR format" tells a newcomer nothing.

            `SettingsEntry` has carried this field all along; it was simply unused. This
            test exists so that adding a setting without help text fails loudly rather
            than quietly reintroducing the gap.
        """
        from seedsigner.models.settings_definition import SettingsDefinition

        # The language picker has its own View (LocaleSelectionView), which never passes
        # help_text to a Screen, and a list of languages in their own scripts needs no
        # explaining.
        exempt = {SettingsConstants.SETTING__LOCALE}

        missing = [
            entry.attr_name
            for entry in SettingsDefinition.settings_entries
            if entry.visibility != SettingsConstants.VISIBILITY__HIDDEN
            and entry.attr_name not in exempt
            and not entry.help_text
        ]

        assert missing == [], f"user-facing settings without help_text: {missing}"
