"""Keep one Qt core application alive across IPC and process tests."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent


@pytest.fixture(scope="session")
def qt_app():
    application = QCoreApplication.instance() or QCoreApplication([])
    yield application
    application.sendPostedEvents(None, QEvent.DeferredDelete)
    application.processEvents()
