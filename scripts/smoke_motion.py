"""Exercise radial motion, deferred dispatch, sheets and calm batch feedback."""
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from bitdeck.app import create_application
from bitdeck.radial import CursorMenu
from bitdeck.desktop import Desktop


def wait(app, predicate):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("UI transition or worker timed out")


def main():
    app = create_application()
    app.setQuitOnLastWindowClosed(False)
    menu = CursorMenu()
    desktop = Desktop(app, single_instance=False, theme_cache=Path('work/motion-theme.json'))
    desktop.watcher.timer.stop()
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda kind, error, tb: errors.append(str(error))
    try:
        desktop.notify('BITDECK IS READY', 'Drag an image, PDF or text file in Explorer. Press Shift while dragging, then drop on an action. All actions are visible on the wheel. Drop in the center to choose after releasing.\n\nDouble-click the tray icon to choose files. The image editor is optional.')
        app.processEvents()
        card = desktop.cards[0]
        snapshot = card.grab().toImage()
        assert snapshot.pixelColor(8, card.height() // 2).alpha() == 255
        assert snapshot.pixelColor(0, 0).alpha() == 0
        assert card.detail.height() >= card.detail.heightForWidth(card.detail.width())
        assert card.detail.geometry().bottom() < card.height() - 10
        card.grab().save('docs/tray-card.png')
        with tempfile.TemporaryDirectory(dir="work") as folder:
            root = Path(folder).resolve()
            from PIL import Image
            source = root / "sample.png"
            Image.new("RGB", (100, 60), "red").save(source)
            with patch('bitdeck.radial.motion_enabled', return_value=True):
                menu.popup(QPoint(350, 350), [str(root / 'sample.pdf')], drag=False)
                wait(app, lambda: menu._reveal == 1)
                original_targets = [menu.action_point(i) for i in range(len(menu.actions))]
                menu.set_hover(0)
                wait(app, lambda: 0 < menu._weights[0] < 1)
                start = menu._weights[0]
                menu.set_hover(1)
                assert menu._weights[0] == start
                wait(app, lambda: menu._weights[1] > .999)
                assert original_targets == [menu.action_point(i) for i in range(len(menu.actions))]
                menu.set_hover(0)
                span = 360 / len(menu.actions)
                def boundary(degrees):
                    angle = math.radians(degrees - 90)
                    return menu.CENTER + QPointF(148 * math.cos(angle), 148 * math.sin(angle))
                # A small boundary movement holds the highlighted choice;
                # deliberate movement into the next wedge changes it.
                assert menu.index_at(boundary(span + 1)) == 1
                assert menu.index_at(boundary(span + 1), sticky=True) == 0
                assert menu.index_at(boundary(span + 4), sticky=True) == 1
            menu.cancel_pending()
            menu.setFixedSize(336, 348)
            assert all(menu.index_at(menu.action_point(i)) == i for i in range(len(menu.actions)))
            routed = []
            menu.actionChosen.connect(lambda key, paths: routed.append(key))
            with patch.dict(os.environ, {"BITDECK_REDUCED_MOTION": "1"}):
                menu.popup(QPoint(350, 350), [str(source)], drag=False)
                assert menu._reveal == 1
                menu.set_hover(0)
                assert menu._weights[0] == 1
                menu.choose(0)
                menu.choose(1)
                assert routed == []
                wait(app, lambda: len(routed) == 1)
                assert routed == ["image:PNG"]
                menu.popup(QPoint(350, 350), [str(source)], drag=False)
                menu.choose(1)
                menu.cancel_pending()
                menu.choose(2)  # A late input event cannot revive a cancelled menu.
                app.processEvents()
                assert len(routed) == 1
            # Configuration is modeless, cancellable, and processing acknowledges
            # the action before the worker has produced a result.
            desktop.choose("resize_image", [str(source)])
            sheet = next(iter(desktop.sheets))
            assert not sheet.isModal() and not desktop.runner.busy
            sheet.reject()
            assert not desktop.sheets and not desktop.runner.busy
            desktop.choose("resize_image", [str(source)])
            sheet = next(iter(desktop.sheets))
            sheet.fields['long_edge'].setValue(30)
            sheet.submit()
            assert desktop.cards[0].processing
            wait(app, lambda: not desktop.runner.busy and bool(desktop.cards[0].result))
            assert desktop.cards[0].result['width'] == 30
            desktop.choose('pdf_protect', [str(root / 'unused.pdf')])
            sheet = next(iter(desktop.sheets))
            sheet.fields['password'].setText('password123')
            sheet.fields['repeat'].setText('different123')
            sheet.submit()
            assert sheet.isVisible() and not desktop.runner.busy
            sheet.reject()
            assert sheet.fields['password'].text() == ''
            # A batch reuses its activity card instead of flashing one per file.
            started = []
            desktop.batch.jobStarted.connect(lambda request: started.append(id(desktop.cards[0])))
            desktop.batch.submit([{'operation': 'export', 'source': str(source), 'output_dir': str(root/'out')},
                                  {'operation': 'export', 'source': str(source), 'output_dir': str(root/'out')}], show=False)
            wait(app, lambda: not desktop.runner.busy and not desktop.queue)
            assert len(started) == 2 and started[0] == started[1]
            assert '2 completed' in desktop.cards[0].detail.text()
            assert desktop.cards[0].result.get('output')
            print('Motion passed: stable radial targets, hover interruption/hysteresis, deferred single dispatch, reduced motion, modeless settings and shared batch activity.')
    finally:
        menu.cancel_pending()
        menu.deleteLater()
        desktop.shutdown()
        desktop.menu.deleteLater()
        for card in desktop.cards:
            card.deleteLater()
        desktop.tray.deleteLater()
        desktop.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        sys.excepthook = old_hook
    assert not errors, errors


if __name__ == '__main__':
    main()
