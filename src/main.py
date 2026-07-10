import os
import sys
import time
from audioplayer import AudioPlayer
from pynput.keyboard import Controller
from PyQt5.QtCore import QObject, QProcess
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QMessageBox

from key_listener import KeyListener
from result_thread import ResultThread
from ui.main_window import MainWindow
from ui.settings_window import SettingsWindow
from ui.status_window import StatusWindow
from ui.flash_overlay import FlashOverlay
from transcription import create_local_model
from input_simulation import InputSimulator
from utils import ConfigManager


class WhisperWriterApp(QObject):
    def __init__(self):
        """
        Initialize the application, opening settings window if no configuration file is found.
        """
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setWindowIcon(QIcon(os.path.join('assets', 'ww-logo.png')))

        ConfigManager.initialize()

        self.settings_window = SettingsWindow()
        self.settings_window.settings_closed.connect(self.on_settings_closed)
        self.settings_window.settings_saved.connect(self.restart_app)

        if ConfigManager.config_file_exists():
            self.initialize_components()
        else:
            print('No valid configuration file found. Opening settings window...')
            self.settings_window.show()

    def initialize_components(self):
        """
        Initialize the components of the application.
        """
        self.input_simulator = InputSimulator()

        self.key_listener = KeyListener()
        self.key_listener.add_callback("on_activate", self.on_activation)
        self.key_listener.add_callback("on_deactivate", self.on_deactivation)

        model_options = ConfigManager.get_config_section('model_options')
        model_path = model_options.get('local', {}).get('model_path')
        self.local_model = create_local_model() if not model_options.get('use_api') else None

        self.result_thread = None

        self.main_window = MainWindow()
        self.main_window.openSettings.connect(self.settings_window.show)
        self.main_window.startListening.connect(self.key_listener.start)
        self.main_window.closeApp.connect(self.exit_app)

        if not ConfigManager.get_config_value('misc', 'hide_status_window'):
            self.status_window = StatusWindow()

        # Silent, focus-free "done" cue (replaces the mic-polluting beep).
        self.flash_overlay = FlashOverlay()

        self.create_tray_icon()

        # Auto-start listening so there's no need to click "Start" after launch.
        # The app lives in the system tray; the main window stays hidden.
        self.key_listener.start()

        # Brief confirmation that it launched (it's otherwise invisible in the tray).
        hotkey = ConfigManager.get_config_value('recording_options', 'activation_key')
        self.tray_icon.showMessage(
            'WhisperWriter is running',
            f'Press {hotkey} to start/stop dictation.',
            self.icon_idle,
            4000
        )

    def create_tray_icon(self):
        """
        Create the system tray icon and its context menu.
        """
        # Distinct icons so the tray reflects the current state at a glance.
        self.icon_idle = QIcon(os.path.join('assets', 'ww-logo.png'))
        self.icon_recording = QIcon(os.path.join('assets', 'microphone.png'))
        self.icon_transcribing = QIcon(os.path.join('assets', 'pencil.png'))

        self.tray_icon = QSystemTrayIcon(self.icon_idle, self.app)
        self.tray_icon.setToolTip('WhisperWriter - idle')

        tray_menu = QMenu()

        show_action = QAction('WhisperWriter Main Menu', self.app)
        show_action.triggered.connect(self.main_window.show)
        tray_menu.addAction(show_action)

        settings_action = QAction('Open Settings', self.app)
        settings_action.triggered.connect(self.settings_window.show)
        tray_menu.addAction(settings_action)

        exit_action = QAction('Exit', self.app)
        exit_action.triggered.connect(self.exit_app)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def cleanup(self):
        if self.key_listener:
            self.key_listener.stop()
        if self.input_simulator:
            self.input_simulator.cleanup()

    def exit_app(self):
        """
        Exit the application.
        """
        self.cleanup()
        QApplication.quit()

    def restart_app(self):
        """Restart the application to apply the new settings."""
        self.cleanup()
        QApplication.quit()
        QProcess.startDetached(sys.executable, sys.argv)

    def on_settings_closed(self):
        """
        If settings is closed without saving on first run, initialize the components with default values.
        """
        if not os.path.exists(os.path.join('src', 'config.yaml')):
            QMessageBox.information(
                self.settings_window,
                'Using Default Values',
                'Settings closed without saving. Default values are being used.'
            )
            self.initialize_components()

    def on_activation(self):
        """
        Called when the activation key combination is pressed.
        """
        if self.result_thread and self.result_thread.isRunning():
            recording_mode = ConfigManager.get_config_value('recording_options', 'recording_mode')
            if recording_mode == 'press_to_toggle':
                self.result_thread.stop_recording()
            elif recording_mode == 'continuous':
                self.stop_result_thread()
            return

        self.start_result_thread()

    def on_deactivation(self):
        """
        Called when the activation key combination is released.
        """
        if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'hold_to_record':
            if self.result_thread and self.result_thread.isRunning():
                self.result_thread.stop_recording()

    def start_result_thread(self):
        """
        Start the result thread to record audio and transcribe it.
        """
        if self.result_thread and self.result_thread.isRunning():
            return

        self.result_thread = ResultThread(self.local_model)
        # Always reflect state in the tray icon (works even with the status window hidden).
        self.result_thread.statusSignal.connect(self.update_tray_status)
        if not ConfigManager.get_config_value('misc', 'hide_status_window'):
            self.result_thread.statusSignal.connect(self.status_window.updateStatus)
            self.status_window.closeSignal.connect(self.stop_result_thread)
        self.result_thread.resultSignal.connect(self.on_transcription_complete)
        self.result_thread.start()

    def update_tray_status(self, status):
        """Update the tray icon and tooltip to reflect the current state."""
        if status == 'recording':
            self.tray_icon.setIcon(self.icon_recording)
            self.tray_icon.setToolTip('WhisperWriter - listening...')
        elif status == 'transcribing':
            self.tray_icon.setIcon(self.icon_transcribing)
            self.tray_icon.setToolTip('WhisperWriter - transcribing...')
        else:  # idle, error, cancel
            self.tray_icon.setIcon(self.icon_idle)
            self.tray_icon.setToolTip('WhisperWriter - idle')

    def stop_result_thread(self):
        """
        Stop the result thread.
        """
        if self.result_thread and self.result_thread.isRunning():
            self.result_thread.stop()

    def on_transcription_complete(self, result):
        """
        When the transcription is complete, type the result and start listening for the activation key again.
        """
        self.input_simulator.typewrite(result)

        # Visual "done" cue: a Commodore-64 style border blink. Preferred over
        # the audible beep, which the mic picks up and re-transcribes as junk.
        # Non-blocking (timer-driven), so it adds no delay before recording
        # restarts below.
        if ConfigManager.get_config_value('misc', 'flash_on_completion'):
            self.flash_overlay.flash(
                color=ConfigManager.get_config_value('misc', 'flash_color') or '#00FF00',
                thickness=ConfigManager.get_config_value('misc', 'flash_thickness') or 12,
                blink_count=ConfigManager.get_config_value('misc', 'flash_blink_count') or 2,
            )

        # Kept for anyone who still wants sound, but off by default (see above).
        if ConfigManager.get_config_value('misc', 'noise_on_completion'):
            AudioPlayer(os.path.join('assets', 'beep.wav')).play(block=True)

        if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'continuous':
            self.start_result_thread()
        else:
            self.key_listener.start()

    def run(self):
        """
        Start the application.
        """
        sys.exit(self.app.exec_())


if __name__ == '__main__':
    app = WhisperWriterApp()
    app.run()
