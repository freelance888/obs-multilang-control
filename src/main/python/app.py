import logging

import enaml
from PyQt5 import QtWidgets, QtCore
from fbs_runtime._signal import SignalWakeupHandler
from fbs_runtime.application_context import cached_property
from fbs_runtime.application_context.PyQt5 import ApplicationContext
from fbs_runtime.platform import is_windows
from enaml.qt.qt_application import QtApplication
from models import ObsManagerModel, ObsConfigurationModel, Profile


class ShowHideWindowTray(object):
    def __init__(self, view_name, view):
        self.view_name = view_name
        self.view = view
        self.action = None

    @property
    def display_text(self):
        if not self.view.visible:
            return f"Show {self.view_name}"
        else:
            return f"Hide {self.view_name}"

    def show_hide_window(self):
        logging.debug("Show\Hide action clicked")
        if self.view.visible:
            self.view.hide()
        else:
            self.view.show()
        self.action.setText(self.display_text)


class SystemTrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent, obs_control_view, obs_manage_view):
        self.obs_control_view = obs_control_view

        QtWidgets.QSystemTrayIcon.__init__(self, parent)
        if icon:
            self.setIcon(icon)
        menu = QtWidgets.QMenu(parent)
        obs_control = ShowHideWindowTray("OBS control", obs_control_view)
        obs_manage = ShowHideWindowTray("OBS manage", obs_manage_view)

        obs_control.action = menu.addAction(obs_control.display_text)
        obs_manage.action = menu.addAction(obs_manage.display_text)
        self.sparator = menu.addSeparator()
        self.exit_action = menu.addAction("Exit")

        self.setContextMenu(menu)

        self.exit_action.triggered.connect(self.exit)

        obs_control.action.triggered.connect(obs_control.show_hide_window)
        obs_manage.action.triggered.connect(obs_manage.show_hide_window)
        # need to be connected to self for prevent deleting by GC
        self.obs_control = obs_control
        self.obs_manage = obs_manage

    def exit(self):
        QtCore.QCoreApplication.exit()


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
            from views.obs_configuration import ObsConfigurationManager

        state_path = self.get_resource("state.json")
        obs_manager = ObsManagerModel(state_path=state_path)

        obs_control_view = MainWindowView(obs_manager=obs_manager)
        obs_control_view.show()

        profile_path = self.get_resource("profile-base")
        scene_path = self.get_resource("scene-base.json")

        obs_config = ObsConfigurationModel(
            template_profile_path=profile_path, template_scene_path=scene_path
        )
        new_profile = Profile()
        obs_config.update_available_profiles()
        obs_configuration_view = ObsConfigurationManager(
            obs_config=obs_config, profile=new_profile
        )
        obs_configuration_view.show()
        parent = QtWidgets.QWidget()
        tray_icon = SystemTrayIcon(
            self.app_icon, parent, obs_control_view, obs_configuration_view
        )
        tray_icon.show()
        return self.app.exec_()
