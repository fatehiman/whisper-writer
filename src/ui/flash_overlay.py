from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget, QApplication


class FlashOverlay(QWidget):
    """
    A frameless, click-through, non-activating screen-border flash used as a
    *visual* "transcription complete" cue (Commodore-64 style border blink).

    Why it exists: the audible completion beep (misc.noise_on_completion) gets
    picked up by the microphone and re-transcribed as garbage on the next
    continuous-mode capture. A silent visual cue leaves nothing for the mic to
    hear.

    Focus safety: the window never takes keyboard focus and never intercepts
    mouse input (Qt.WindowTransparentForInput + WA_ShowWithoutActivating +
    WA_TransparentForMouseEvents), so it does not disturb whatever window the
    user is dictating into. The centre is fully transparent — only a coloured
    frame is painted around the screen edge.
    """

    def __init__(self):
        super().__init__(None)

        # No border/titlebar, always on top, no taskbar entry (Tool), and —
        # crucially — transparent to all window-system input so focus and the
        # active window never change (WS_EX_TRANSPARENT on Windows).
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        # Show without stealing activation; paint our own translucent content;
        # let any stray click pass straight through.
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._color = QColor('#00FF00')
        self._thickness = 12
        self._on = False

        # Blink state machine (single-shot timer re-armed for each phase).
        self._blinks_left = 0
        self._on_ms = 90
        self._off_ms = 70
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

    def flash(self, color='#00FF00', thickness=12, blink_count=2,
              on_ms=90, off_ms=70):
        """Trigger the border blink. Safe to call while a blink is in progress."""
        self._color = QColor(color)
        self._thickness = max(1, int(thickness))
        self._blinks_left = max(1, int(blink_count))
        self._on_ms = max(10, int(on_ms))
        self._off_ms = max(10, int(off_ms))

        # Cover the screen holding the mouse cursor; fall back to primary.
        screen = QApplication.screenAt(self.cursor().pos()) or QApplication.primaryScreen()
        self.setGeometry(screen.geometry())

        self._timer.stop()
        self._show_border()

    def _show_border(self):
        self._on = True
        self.update()
        if not self.isVisible():
            self.show()
        self.raise_()
        self._timer.start(self._on_ms)

    def _hide_border(self):
        self._on = False
        self.update()  # repaint to transparent (window stays mapped)
        self._timer.start(self._off_ms)

    def _tick(self):
        if self._on:
            # Just finished an ON phase.
            self._blinks_left -= 1
            if self._blinks_left <= 0:
                self.hide()
                return
            self._hide_border()
        else:
            # Just finished the OFF gap -> start the next ON phase.
            self._show_border()

    def paintEvent(self, event):
        if not self._on:
            return
        painter = QPainter(self)
        pen = QPen(self._color)
        pen.setWidth(self._thickness)
        painter.setPen(pen)
        # Inset by half the pen width so the whole stroke stays on-screen.
        half = self._thickness // 2
        painter.drawRect(self.rect().adjusted(half, half, -half, -half))
