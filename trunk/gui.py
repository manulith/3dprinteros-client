#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import time
import webbrowser
import time
import subprocess
import threading
from PySide import QtCore, QtGui, QtUiTools

import version

HEADER = '3DPrinterOS v' + version.version

class GuiTrayThread(QtCore.QThread):
    show_token_request = QtCore.Signal()
    show_tray = QtCore.Signal()
    set_printer = QtCore.Signal()
    show_notification = QtCore.Signal()
    running_flag = True

    def run(self):
        while self.running_flag:
            time.sleep(1)
        print 'Qt Thread stopped!'


class Printer():
    def __init__(self, profile, gui):
        self.profile = profile
        self.gui = gui
        self.action = QtGui.QAction(self.profile['name'] + ' : ' + self.get_port(), self.gui, triggered=self.select)
        self.gui.printersMenu.addAction(self.action)

    def get_port(self):
        port = self.profile['COM']
        if not port:
            port = 'USB'
        return port

    def select(self):
        #self.gui._deselect_all_printers()
        self.action.setEnabled(False)
        self.gui.selected_printer = self
        self.gui.show_notification(self.profile['name'] + ' is ready!')
        self.gui.set_status('online')
        self.gui.printersDisableAction.setEnabled(True)
        self.gui.app.selected_printer = self.profile

    def deselect(self):
        self.action.setEnabled(True)


class LoginWindow(QtGui.QMainWindow):
    def __init__(self, app=None):
        QtGui.QMainWindow.__init__(self)
        QtGui.QApplication.setQuitOnLastWindowClosed(True)
        self.load_resources()
        self.init_widgets()
        self.setWindowTitle(HEADER)
        self.setFixedSize(500, 600)
        self.app = app
        self.show()

    def load_resources(self):
        self.images = {}
        self.appIcon = QtGui.QPixmap('./gui_resources/icons/128x128.png')
        self.images['button_ok_default'] = QtGui.QPixmap('./gui_resources/images/token/ok1.png')
        self.images['button_ok_hover'] = QtGui.QPixmap('./gui_resources/images/token/ok2.png')
        self.images['button_ok_pressed'] = QtGui.QPixmap('./gui_resources/images/token/ok3.png')
        self.images['button_ok_inactive'] = QtGui.QPixmap('./gui_resources/images/token/ok4.png')

        self.images['button_cancel_default'] = QtGui.QPixmap('./gui_resources/images/token/can1.png')
        self.images['button_cancel_hover'] = QtGui.QPixmap('./gui_resources/images/token/can2.png')
        self.images['button_cancel_pressed'] = QtGui.QPixmap('./gui_resources/images/token/can3.png')
        self.images['button_cancel_inactive'] = QtGui.QPixmap('./gui_resources/images/token/can4.png')

        self.images['getkey'] = QtGui.QPixmap('./gui_resources/images/token/getkey5.png')
        self.images['enter_key'] = QtGui.QPixmap('./gui_resources/images/token/key.png')

    # def set_detected_printers(self):
    #     self.show_notification(self.app.storage['selected_printer'][0]['name'] + ' is ready!')
    #     self.show_detected_printers(self.app.storage['selected_printer'])
    #     self.set_status('online')

    def init_widgets(self):
        loader = QtUiTools.QUiLoader()
        file = QtCore.QFile(os.path.join('./gui_resources/gui.xml'))
        file.open(QtCore.QFile.ReadOnly)
        self.myWidget = loader.load(file, self)
        file.close()
        self.setCentralWidget(self.myWidget)

        self.okButton = self.myWidget.okButton
        self.okButton.clicked.connect(self._okButtonClicked)
        self.okButton.pressed.connect(self._okButtonPressed)
        self.okButton.released.connect(self._okButtonReleased)

        self.cancelButton = self.myWidget.cancelButton
        self.cancelButton.clicked.connect(self._cancelButtonClicked)
        self.cancelButton.pressed.connect(self._cancelButtonPressed)
        self.cancelButton.released.connect(self._cancelButtonReleased)

        self.keyInput = self.myWidget.keyInput
        self.keyInput.textChanged.connect(self._keyInputTextChanged)

    def _keyInputTextChanged(self):
        if self.keyInput.text():
            self.okButton.setIcon(self.images['button_ok_default'])
        else:
            self.okButton.setIcon(self.images['button_ok_inactive'])

    def _okButtonClicked(self):
        token = self.keyInput.text()
        if token:
            try:
                self.app.gui_exchange_in['token'] = token
            except:
                pass
            self.exit()
        #else:
        #    self.trayIcon.showMessage(self.notificateHeader, 'Please input token first')

    def _okButtonPressed(self):
        token = self.keyInput.text()
        if token:
            self.okButton.setIcon(self.images['button_ok_pressed'])

    def _okButtonReleased(self):
        token = self.keyInput.text()
        if token:
            self.okButton.setIcon(self.images['button_ok_default'])

    def _cancelButtonClicked(self):
        self.exit()

    def _cancelButtonPressed(self):
        self.cancelButton.setIcon(self.images['button_cancel_pressed'])

    def _cancelButtonReleased(self):
        self.cancelButton.setIcon(self.images['button_cancel_default'])

    def exit(self):
        # TODO: shutdown http-client here
        #self.running = False
        time.sleep(0.1)
        #app.App.close()
        QtGui.qApp.quit()

class TDPrinterOSTray(QtGui.QSystemTrayIcon):
    def __init__(self, app=None):
        QtGui.QSystemTrayIcon.__init__(self)
        QtGui.QApplication.setQuitOnLastWindowClosed(False)
        self.app = app
        self.load_resources()
        self.create_actions()
        self.setup_tray_icon()
        self.icon = QtGui.QIcon()
        self.icon.addPixmap(self.appIcon, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.init_additional_windows()
        self.set_status()
        # self.show()
        #self.show_notification('Program started!')

    def set_printer(self):
        self.printer = Printer(None, self)
        self.printer.select()

    def show_tray(self):
        self.show()
        self.show_notification('Program started!')

    def setup_tray_icon(self):
        self.trayIconMenu = QtGui.QMenu()
        self.printersMenu = QtGui.QMenu('Printers')
        self.webcamsMenu = QtGui.QMenu('WebCams')
        self.printersMenu.addAction(self.printersDisableAction)
        self.webcamsMenu.addAction(self.cameraDisableAction)
        self.trayIconMenu.addAction(self.statusAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addMenu(self.webcamsMenu)
        self.trayIconMenu.addMenu(self.printersMenu)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.supportLogsAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.changeKeyAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.settingsAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.liveSupportAction)
        self.trayIconMenu.addAction(self.aboutAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.exitAction)
        self.setContextMenu(self.trayIconMenu)

    def load_resources(self):
        self.images = dict()
        # TODO: find out what are other icons for
        self.images['status_disconnected'] = QtGui.QIcon('./gui_resources/icons/1-0.png')
        self.images['status_online'] = QtGui.QIcon('./gui_resources/icons/1-1.png')
        self.images['status_error'] = QtGui.QIcon('./gui_resources/icons/1-3.png')
        self.appIcon = QtGui.QPixmap('./gui_resources/icons/128x128.png')

    def create_actions(self):
        self.statusAction = QtGui.QAction('Printer offline', self)
        self.statusAction.setEnabled(False)
        self.printersDisableAction = QtGui.QAction('Disable', self, triggered=self._printersDisableMethod)
        self.printersDisableAction.setEnabled(False)
        self.cameraDisableAction = QtGui.QAction('Disable', self, triggered=self._webcamsDisableMethod)
        self.cameraDisableAction.setEnabled(False)
        self.supportLogsAction = QtGui.QAction('Support Logs', self, triggered=self._supportLogsMethod)
        self.changeKeyAction = QtGui.QAction('Change KEY', self, triggered=self._changeKeyMethod)
        self.settingsAction = QtGui.QAction('Settings', self, triggered=self._settingsMethod)
        self.liveSupportAction = QtGui.QAction('Get LiveSupport Help', self, triggered=self._liveSupportMethod)
        self.aboutAction = QtGui.QAction('About', self, triggered=self._aboutMethod)
        self.exitAction = QtGui.QAction("Exit", self, triggered=self.exit)

    def init_additional_windows(self):
        loader = QtUiTools.QUiLoader()
        # About window setup
        self.aboutSection = QtGui.QMainWindow()
        self.aboutSection.setWindowTitle("About")
        self.aboutSection.setFixedSize(500, 300)
        self.aboutSection.hide()
        self.aboutSection.setWindowIcon(self.icon)
        file = QtCore.QFile(os.path.join('./gui_resources/about.xml'))
        file.open(QtCore.QFile.ReadOnly)
        self.about = loader.load(file)
        file.close()
        self.about.softwareLabel.setText(
        '<b><font color=white>3DPrinterOS Software Edition v ' + version.version + \
        '<br><br>3D Control Systems Ltd. 1355, Market Street, San Francisco, CA 94103, USA<br></font></b>')
        self.about.versionLabel.setText(
        '<font color=white><b>Version ' + version.version + '</font></b>')
        self.aboutSection.setCentralWidget(self.about)
        # Token change request dialog window setup
        self.tokenChange = QtGui.QMainWindow()
        self.tokenChange.setWindowTitle("Token Change")
        self.tokenChange.setFixedSize(550, 130)
        self.tokenChange.hide()
        self.tokenChange.setWindowIcon(self.icon)
        file = QtCore.QFile(os.path.join('./gui_resources/token_change.xml'))
        file.open(QtCore.QFile.ReadOnly)
        self.tokenChangeGui = loader.load(file)
        file.close()
        self.tokenChange.setCentralWidget(self.tokenChangeGui)
        self.tokenChangeYesButton = self.tokenChangeGui.yesButton
        self.tokenChangeYesButton.clicked.connect(self._tokenChangeYesMethod)
        self.tokenChangeNoButton = self.tokenChangeGui.noButton
        self.tokenChangeNoButton.clicked.connect(self._tokenChangeNoMethod)
        # Exit confirmation window setup
        self.exitConfirm = QtGui.QMainWindow()
        self.exitConfirm.setWindowTitle('Are you sure?')
        self.exitConfirm.setFixedSize(550, 130)
        file = QtCore.QFile(os.path.join('./gui_resources/exit.xml'))
        file.open(QtCore.QFile.ReadOnly)
        self.exitConfirmGui = loader.load(file)
        file.close()
        self.exitConfirm.setCentralWidget(self.exitConfirmGui)
        self.exitConfirm.hide()
        self.exitConfirm.setWindowIcon(self.icon)
        self.exitConfirmGui.yesButton.clicked.connect(self.confirmed_exit)
        self.exitConfirmGui.noButton.clicked.connect(self.exitConfirm.hide)
        # Settings window setup
        self.settingsWindow = QtGui.QMainWindow()
        self.settingsWindow.setWindowTitle('Settings')
        self.settingsWindow.setFixedSize(400, 300)
        file = QtCore.QFile(os.path.join('./gui_resources/settings.xml'))
        file.open(QtCore.QFile.ReadOnly)
        self.settingsWindowGui = loader.load(file)
        file.close()
        self.settingsWindow.setCentralWidget(self.settingsWindowGui)
        self.settingsWindow.hide()
        self.settingsWindow.setWindowIcon(self.icon)
        self.settingsWindowGui.okButton.clicked.connect(self._saveSettings)
        self.settingsWindowGui.cancelButton.clicked.connect(self.settingsWindow.hide)
        # Notification settings section
        self.settingsNotification = self.settingsWindowGui.notificationSettings
        notificationLayout = QtGui.QGridLayout()
        popupDuration = QtGui.QLabel("Popup duration:")
        popupDurationSpinBox = QtGui.QSpinBox()
        popupDurationSpinBox.setRange(2, 15)
        popupDurationSpinBox.setSuffix(" s")
        popupDurationSpinBox.setValue(5)
        notificationLayout.addWidget(popupDuration, 0, 0)
        notificationLayout.addWidget(popupDurationSpinBox, 0, 1)

        self.settingsNotification.setLayout(notificationLayout)

    def confirmed_exit(self):
        try:
            #pass
            QtGui.qApp.quit()
            #self.app.quit()
        except Exception, e:
            print 'Error in exiting QtApp!'
            print e.message

    # Shows tray popup
    def show_notification(self, message):
        if sys.platform.startswith('darwin'):
            path = __file__
            path = os.path.dirname(path)
            path = os.path.abspath(path)
            mac_path = os.path.join(path, 'gui_resources/mac')
            mac_path = os.path.abspath(mac_path)
            message_path = os.path.join(mac_path, 'message')
            message_path = os.path.abspath(message_path)
            applet_path = os.path.join(mac_path, '3DPrinterOS.app/Contents/MacOS/./applet')
            applet_path = os.path.abspath(applet_path)
            # mac applet magic
            with open(message_path, 'w') as message_file:
                message_file.write(message)
            # TODO: fix bug: every subprocess call there is a Secured3D icon blinks at mac dashboard
            subprocess.Popen(applet_path)
        else:
            self.showMessage(HEADER, message)

    def set_status(self, status='disconnected'):
        try:
            self.setIcon(self.images['status_' + status])
        except KeyError:
            self.show_notification('Wrong status received : ' + status)

    def show_detected_printers(self, printers_list):
        if len(printers_list) == 0:
            self.show_notification('No printer was detected')
        else:
            for printer in printers_list:
                self.printers.append(Printer(printer, self))
            printer_amount = len(printers_list)
            if printer_amount == 1:
                pass
                #self.show_notification(printers_list[0]['name'] + ' is detected!')
            else:
                self.show_notification(str(printer_amount) + ' printers are detected!')

    # earlier version of show_detected_printers for one printer
    # def set_printer(self, printer_name):
    #     self.printer = printer_name
    #     self.show_notification('Printer ' + printer_name + ' is online!')
    #     self.set_status('online')
    #     self.statusAction.setText(printer_name)
    #     self.printer_action = QtGui.QAction(printer_name, self, triggered=self._defaultPrinterMethod)
    #     self.printer_action.setEnabled(False)
    #     self.printersDisableAction.setEnabled(True)
    #     self.printersMenu.addAction(self.printer_action)

    def _settingsMethod(self):
        self.settingsWindow.show()

    def _saveSettings(self):
        self.settingsWindow.hide()

    def set_camera(self, camera_name):
        self.camera = camera_name
        self.show_notification('Camera ' + camera_name + ' is on!')
        self.camera_action = QtGui.QAction(camera_name, self, triggered=self._defaultCameraMethod)
        self.camera_action.setEnabled(False)
        self.cameraDisableAction.setEnabled(True)
        self.webcamsMenu.addAction(self.camera_action)

    def _deselect_all_printers(self):
        # for printer in self.printers:
        #     printer.deselect()
        self.printer.deselect()

    def _defaultPrinterMethod(self):
        # TODO: logic when user chooses printer in list
        self.show_notification(self.printer + ' is ready!')
        self.printer_action.setEnabled(False)
        self.printersDisableAction.setEnabled(True)
        self.set_status('online')
        self.statusAction.setText(self.printer)

    def _defaultCameraMethod(self):
        # TODO: logic when user chooses camera in list
        self.show_notification(self.camera + ' is on!')
        self.camera_action.setEnabled(False)
        self.cameraDisableAction.setEnabled(True)

    def _printersDisableMethod(self):
        if self.printer:
            self.printersDisableAction.setEnabled(False)
            self.set_status('disconnected')
            self.statusAction.setText('Printer offline')
            self.show_notification(self.printer.profile['name'] + ' is off now!')
            self._deselect_all_printers()
            self.selected_printer = None
            #self.statusAction.setIconVisibleInMenu(False)
            # TODO: printer disable logic here

    def _webcamsDisableMethod(self):
        if self.camera_action:
            self.camera_action.setEnabled(True)
            self.cameraDisableAction.setEnabled(False)
            self.show_notification(self.camera + ' is off!')
            # TODO: camera disabling logic?

    def _supportLogsMethod(self):
        # TODO: paste here appdata path getting method + logs directory
        path = 'C:\\Downloads' #stub
        if sys.platform == 'darwin':
            subprocess.Popen(['open', '--', path])
        elif sys.platform == 'linux':
            subprocess.Popen(['gnome-open', '--', path])
        elif sys.platform == 'win32':
            subprocess.Popen(['explorer', path])

    def _changeKeyMethod(self):
        self.tokenChange.show()

    def _liveSupportMethod(self):
        url = 'http://3dprinteros.com'
        webbrowser.open_new_tab(url)

    def _aboutMethod(self):
        self.aboutSection.show()

    def exit(self):
        # TODO: shutdown http-client here
        #self.running = False
        time.sleep(0.1)
        #app.App.close()
        self.exitConfirm.show()

    def _tokenChangeNoMethod(self):
        # TODO: here is a method that clears token file
        self.exit()
        self.tokenChange.hide()

    def _tokenChangeYesMethod(self):
        # TODO: here is a method that clears token file
        self.exit()
        self.tokenChange.hide()


class App_Stub():
    def __init__(self, main_app):
        self.tray = None
        self.init_gui()
        self.main_app = main_app
        while not self.tray:
            time.sleep(0.001)
        self.qt_thread = GuiTrayThread()
        #self.qt_thread.show_token_request.connect(self.tray.show_tray, QtCore.Qt.QueuedConnection)
        #self.qt_thread.show_tray.connect(self.tray.show_tray, QtCore.Qt.QueuedConnection)
        self.qt_thread.set_printer.connect(self.tray.show_tray, QtCore.Qt.QueuedConnection)
        self.qt_thread.show_notification.connect(self.tray.show_tray, QtCore.Qt.QueuedConnection)
        self.qt_thread.start()

    def init_gui(self):
        self.gui_thread = threading.Thread(target=self._gui_init_thread)
        self.gui_thread.start()

    def _gui_init_thread(self):
        self.qt_app = QtGui.QApplication(sys.argv)
        self.tray = TDPrinterOSTray(self.main_app)
        self.qt_app.exec_()

    def show(self):
        self.qt_thread.show_token_request.emit()

    def exit(self):
        self.qt_thread.running_flag = False
        self.qt_thread.wait()
        self.tray.confirmed_exit()
        self.gui_thread.join()
        #QtGui.qApp.quit()


# def show_tray_app(app):
#     qt_app = QtGui.QApplication(sys.argv)
#     window = TDPrinterOSTray(app)
#     # signal_thread = GuiTrayThread(window)
#     # signal_thread.start()
#     qt_app.exec_()
#

def show_login_window(app):
    qt_app = QtGui.QApplication(sys.argv)
    window = LoginWindow(app)
    qt_app.exec_()


if __name__ == '__main__':
    app = App_Stub()
    app.show()
    #app.exit()