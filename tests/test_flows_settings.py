import os
from typing import Callable

from unittest.mock import PropertyMock, patch

# Must import test base before the Controller
from base import FlowTest, FlowStep

from seedsigner.models.settings import Settings
from seedsigner.models.settings_definition import SettingsDefinition, SettingsConstants
from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON, ButtonOption
from seedsigner.hardware.microsd import MicroSD
from seedsigner.views.view import MainMenuView
from seedsigner.views import scan_views, settings_views



class TestSettingsFlows(FlowTest):
    def test_persistent_settings(self):
        """ Basic flow from MainMenuView to enable/disable persistent settings """
        # Which option are we testing?
        settings_entry = SettingsDefinition.get_settings_entry(SettingsConstants.SETTING__PERSISTENT_SETTINGS)

        # No settings file should exist before we enable persistent settings
        assert os.path.exists(Settings.SETTINGS_FILENAME) == False

        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SETTINGS),
            FlowStep(settings_views.SettingsMenuView, button_data_selection=ButtonOption(settings_entry.display_name)),
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, button_data_selection=ButtonOption(settings_entry.get_selection_option_display_name_by_value(SettingsConstants.OPTION__ENABLED))),
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(settings_views.SettingsMenuView),
        ])

        # Settings file should now exist
        assert os.path.exists(Settings.SETTINGS_FILENAME) == True


    def test_multiselect(self):
        """
        Multiselect Settings options should stay in-place; requires BACK to exit. If no
        selections are made, route to the warning screen and return the user to the
        settings entry until at least one option is selected.
        """
        # Which option are we testing?
        settings_entry = SettingsDefinition.get_settings_entry(SettingsConstants.SETTING__SIG_TYPES)

        # Enable all options to start
        self.settings.set_value(settings_entry.attr_name, [option[0] for option in settings_entry.selection_options])

        # Sanity check, we only expect two options for this setting
        assert len(settings_entry.selection_options) == 2

        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SETTINGS),
            FlowStep(settings_views.SettingsMenuView, button_data_selection=settings_views.SettingsMenuView.ADVANCED),
            FlowStep(settings_views.SettingsMenuView, button_data_selection=ButtonOption(settings_entry.display_name)),
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, screen_return_value=0),  # deselect first option
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, screen_return_value=1),  # deselect second option
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, screen_return_value=1),  # select second option
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, screen_return_value=1),  # deselect second option
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, screen_return_value=RET_CODE__BACK_BUTTON),  # BACK to exit

            # Both options were deselected, should route to the warning screen
            FlowStep(settings_views.SettingsSelectionRequiredWarningView),
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, screen_return_value=0),  # select first option

            # Now we can exit
            FlowStep(settings_views.SettingsEntryUpdateSelectionView, screen_return_value=RET_CODE__BACK_BUTTON),  # BACK to exit
            FlowStep(settings_views.SettingsMenuView),
        ])


    def test_io_test(self):
        """ Basic flow from MainMenuView to I/O Test View """
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SETTINGS),
            FlowStep(settings_views.SettingsMenuView, button_data_selection=settings_views.SettingsMenuView.IO_TEST),
            FlowStep(settings_views.IOTestView),
            FlowStep(settings_views.SettingsMenuView),
        ])


    def test_donate(self):
        """ Basic flow from MainMenuView to Donate View """        
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SETTINGS),
            FlowStep(settings_views.SettingsMenuView, button_data_selection=settings_views.SettingsMenuView.DONATE),
            FlowStep(settings_views.DonateView),
            FlowStep(settings_views.SettingsMenuView),
        ])


    def test_settingsqr(self):
        """ 
        Scanning a SettingsQR should present the success screen and then return to
        MainMenuView.
        """
        def load_persistent_settingsqr_into_decoder(view: scan_views.ScanView):
            settingsqr_data_persistent: str = "settings::v1 name=Total_noob_mode persistent=E xpub_qr=urca,sta denom=thr network=M qr_density=M sigs=ss scripts=nat xpub_details=E passphrase=E camera=0 compact_seedqr=E bip85=D priv_warn=E dire_warn=E partners=E"
            view.decoder.add_data(settingsqr_data_persistent)

        def load_not_persistent_settingsqr_into_decoder(view: scan_views.ScanView):
            settingsqr_data_not_persistent: str = "settings::v1 name=Ephemeral_noob_mode persistent=D xpub_qr=urca,sta denom=thr network=M qr_density=M sigs=ss scripts=nat xpub_details=E passphrase=E camera=0 compact_seedqr=E bip85=D priv_warn=E dire_warn=E partners=E"
            view.decoder.add_data(settingsqr_data_not_persistent)

        def _run_test(initial_setting_state: str, load_settingsqr_into_decoder: Callable, expected_setting_state: str):
            self.settings.set_value(SettingsConstants.SETTING__PERSISTENT_SETTINGS, initial_setting_state)
            self.run_sequence([
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SCAN),
                FlowStep(scan_views.ScanView, before_run=load_settingsqr_into_decoder),  # simulate read message QR; ret val is ignored
                FlowStep(settings_views.SettingsIngestSettingsQRView),   # ret val is ignored
                FlowStep(MainMenuView),
            ])

            assert self.settings.get_value(SettingsConstants.SETTING__PERSISTENT_SETTINGS) == expected_setting_state


        # First load a SettingsQR that enables persistent settings
        self.mock_microsd.is_inserted = True
        assert MicroSD.get_instance().is_inserted is True

        _run_test(
            initial_setting_state=SettingsConstants.OPTION__DISABLED,
            load_settingsqr_into_decoder=load_persistent_settingsqr_into_decoder,
            expected_setting_state=SettingsConstants.OPTION__ENABLED
        )

        # Then one that disables it
        _run_test(
            initial_setting_state=SettingsConstants.OPTION__ENABLED,
            load_settingsqr_into_decoder=load_not_persistent_settingsqr_into_decoder,
            expected_setting_state=SettingsConstants.OPTION__DISABLED
        )

        # Now try to enable persistent settings when the SD card is not inserted
        self.mock_microsd.is_inserted = False
        assert MicroSD.get_instance().is_inserted is False

        # Have to jump through some hoops to completely simulate the SD card being
        # removed; we need Settings to restrict Persistent Settings to only allow
        # DISABLED.
        with patch('seedsigner.models.settings.Settings.HOSTNAME', new_callable=PropertyMock) as mock_hostname:
            # Must identify itself as SeedSigner OS to trigger the SD card removal logic
            mock_hostname.return_value = Settings.SEEDSIGNER_OS
            Settings.handle_microsd_state_change(MicroSD.ACTION__REMOVED)
        
        selection_options = SettingsDefinition.get_settings_entry(SettingsConstants.SETTING__PERSISTENT_SETTINGS).selection_options
        assert len(selection_options) == 1
        assert selection_options[0][0] == SettingsConstants.OPTION__DISABLED
        assert self.settings.get_value(SettingsConstants.SETTING__PERSISTENT_SETTINGS) == SettingsConstants.OPTION__DISABLED

        _run_test(
            initial_setting_state=SettingsConstants.OPTION__DISABLED,
            load_settingsqr_into_decoder=load_persistent_settingsqr_into_decoder,
            expected_setting_state=SettingsConstants.OPTION__DISABLED
        )


    def test_simple_setup_collapses_the_xpub_export_prompts(self):
        """
            Applying Simple Setup should narrow the three multiselect settings that drive
            the xpub export flow, so that all three of its option prompts skip themselves.

            This is the whole point of the preset: fewer questions, same destination.
        """
        from seedsigner.models.seed import Seed
        from seedsigner.views import seed_views

        seed = Seed(mnemonic="blush twice taste dawn feed second opinion lazy thumb play neglect impact".split())
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()

        # This fork ships already narrowed, so widen the settings first to establish the
        # "before" state that each of the three Views renders its own prompt in.
        for attr_name, value in settings_views.SettingsSimpleSetupView.FULL_VALUES.items():
            self.settings.set_value(attr_name, list(value))
            assert len(self.settings.get_value(attr_name)) > 1

        # Walk the whole flow to prove each of the three Views really renders a prompt:
        # a View that redirected instead of running its Screen would raise here.
        native_segwit = ButtonOption(
            dict(SettingsConstants.ALL_SCRIPT_TYPES)[SettingsConstants.NATIVE_SEGWIT],
            return_data=SettingsConstants.NATIVE_SEGWIT,
        )
        animated_qr = ButtonOption(
            dict(SettingsConstants.ALL_XPUB_QR_FORMATS)[SettingsConstants.XPUB_QR_FORMAT__UR_CRYPTO_ACCOUNT],
            return_data=SettingsConstants.XPUB_QR_FORMAT__UR_CRYPTO_ACCOUNT,
        )
        self.run_sequence(
            initial_destination_view_args=dict(seed=seed),
            sequence=[
                FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                FlowStep(seed_views.SeedExportXpubSigTypeView, button_data_selection=seed_views.SeedExportXpubSigTypeView.SINGLE_SIG),
                FlowStep(seed_views.SeedExportXpubScriptTypeView, button_data_selection=native_segwit),
                FlowStep(seed_views.SeedExportXpubQRFormatView, button_data_selection=animated_qr),
                FlowStep(seed_views.SeedExportXpubWarningView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubDetailsView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubQRDisplayView, screen_return_value=0),
                FlowStep(MainMenuView),
            ],
        )

        # Apply the preset from the Settings menu.
        self.run_sequence([
            FlowStep(MainMenuView, button_data_selection=MainMenuView.SETTINGS),
            FlowStep(settings_views.SettingsMenuView, button_data_selection=settings_views.SettingsMenuView.SIMPLE_SETUP),
            FlowStep(settings_views.SettingsSimpleSetupView, button_data_selection=settings_views.SettingsSimpleSetupView.APPLY),
            FlowStep(settings_views.SettingsMenuView),
        ])

        assert self.settings.get_value(SettingsConstants.SETTING__SIG_TYPES) == [SettingsConstants.SINGLE_SIG]
        assert self.settings.get_value(SettingsConstants.SETTING__SCRIPT_TYPES) == [SettingsConstants.NATIVE_SEGWIT]
        assert self.settings.get_value(SettingsConstants.SETTING__XPUB_QR_FORMAT) == [SettingsConstants.XPUB_QR_FORMAT__UR_CRYPTO_ACCOUNT]

        # Now all three prompts skip themselves: `is_redirect` asserts that the View
        # routed onward *without* ever rendering a Screen.
        self.run_sequence(
            initial_destination_view_args=dict(seed=seed),
            sequence=[
                FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.EXPORT_XPUB),
                FlowStep(seed_views.SeedExportXpubSigTypeView, is_redirect=True),
                FlowStep(seed_views.SeedExportXpubScriptTypeView, is_redirect=True),
                FlowStep(seed_views.SeedExportXpubQRFormatView, is_redirect=True),
                FlowStep(seed_views.SeedExportXpubWarningView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubDetailsView, screen_return_value=0),
                FlowStep(seed_views.SeedExportXpubQRDisplayView, screen_return_value=0),
                FlowStep(MainMenuView),
            ],
        )


    def test_simple_setup_ships_on_and_is_reversible_both_ways(self):
        """
            This fork ships with the simple values as the defaults, and the screen must
            be able to widen back to the full option set and narrow again.
        """
        # A fresh device is already in the simple state.
        for attr_name, value in settings_views.SettingsSimpleSetupView.SIMPLE_VALUES.items():
            assert SettingsDefinition.get_settings_entry(attr_name).default_value == value
            assert self.settings.get_value(attr_name) == value

        def apply_preset(button_option):
            self.run_sequence([
                FlowStep(MainMenuView, button_data_selection=MainMenuView.SETTINGS),
                FlowStep(settings_views.SettingsMenuView, button_data_selection=settings_views.SettingsMenuView.SIMPLE_SETUP),
                FlowStep(settings_views.SettingsSimpleSetupView, button_data_selection=button_option),
                FlowStep(settings_views.SettingsMenuView),
            ])

        # Already simple, so the screen offers RESTORE: widen to the full option set.
        apply_preset(settings_views.SettingsSimpleSetupView.RESTORE)
        for attr_name, value in settings_views.SettingsSimpleSetupView.FULL_VALUES.items():
            assert self.settings.get_value(attr_name) == value

        # ...and back again.
        apply_preset(settings_views.SettingsSimpleSetupView.APPLY)
        for attr_name, value in settings_views.SettingsSimpleSetupView.SIMPLE_VALUES.items():
            assert self.settings.get_value(attr_name) == value
