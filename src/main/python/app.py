import logging

import enaml
from PyQt5 import QtWidgets, QtCore
from fbs_runtime._signal import SignalWakeupHandler
from fbs_runtime.application_context import cached_property
from fbs_runtime.application_context.PyQt5 import ApplicationContext
from fbs_runtime.platform import is_windows
from enaml.qt.qt_application import QtApplication
from models import ObsManagerModel


class SystemTrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent, modem_info_view):
        self.modem_info_view = modem_info_view

        QtWidgets.QSystemTrayIcon.__init__(self, parent)
        if icon:
            self.setIcon(icon)
        menu = QtWidgets.QMenu(parent)

        self.show_action = menu.addAction("Show control")

        sparator = menu.addSeparator()
        self.exit_action = menu.addAction("Exit")

        self.setContextMenu(menu)
        self.exit_action.triggered.connect(self.exit)
        self.show_action.triggered.connect(self.show_hide)

    def exit(self):
        QtCore.QCoreApplication.exit()

    def show_hide(self):
        logging.debug("Show\Hide action clicked")
        if self.modem_info_view.visible:
            self.modem_info_view.hide()
            self.show_action.setText("Show control")
        else:
            self.modem_info_view.show()
            self.show_action.setText("Hide control")


class CustomQtApplication(QtApplication):
    """Redirect from Enaml QtApplication to origin one.
    Required by ApplicationContext"""

    def __getattr__(self, item):
        return getattr(self._qapp, item)


class AppContext(ApplicationContext):
    def __init__(self):
        if self.excepthook:
            self.excepthook.install()
        # Many Qt classes require a QApplication to have been instantiated.
        # Do this here, before everything else, to achieve this:
        self.app
        # We don't build as a console app on Windows, so no point in installing
        # the SIGINT handler:
        if not is_windows():
            self._signal_wakeup_handler = SignalWakeupHandler(
                self.app._qapp, self._qt_binding.QAbstractSocket
            )
            self._signal_wakeup_handler.install()
        if self.app_icon:
            self.app.setWindowIcon(self.app_icon)

    @cached_property
    def app(self):
        return CustomQtApplication()

    def run(self):
        with enaml.imports():
            from views.main import MainWindowView

        state_path = self.get_resource("state.json")
        obs_manager = ObsManagerModel(state_path=state_path)

        view = MainWindowView(obs_manager=obs_manager)
        view.show()
        parent = QtWidgets.QWidget()
        tray_icon = SystemTrayIcon(self.app_icon, parent, view)
        tray_icon.show()
        return self.app.exec_()
