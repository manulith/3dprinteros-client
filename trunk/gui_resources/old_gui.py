import sys
import os
import webbrowser
import time
import subprocess
import threading

# for imports from root directory
path = __file__
path = os.path.dirname(path)
up_path = os.path.join(path, "..")
up_path = os.path.abspath(up_path)
sys.path.append(up_path)

import version
import app

from PySide import QtCore, QtGui, QtUiTools

storage_stub_printer = 'test_Ultimaker 2'
storage_stub_camera = 'test_Genius WebCam'

class GUIStarter(threading.Thread):
    def __init__(self):
        self.app = QtGui.QApplication(sys.argv)
        self.window = Window()

    def run(self):
        app.App().gui_ready_condition.acquire()
        app.App().gui_ready_condition.notify_all()
        app.App().gui_ready_condition.release()
        self.app.exec_()

class Printer():
    def __init__(self, profile, gui):
        self.profile = profile
        self.gui = gui
        self.name = profile['name']
        self.port = profile['COM']
        if not self.port:
            self.port = 'USB'
        self.action = QtGui.QAction(self.name + ' : ' + self.port, self.gui, triggered=self.select)
        self.gui.printerPortMenu.addAction(self.action)

    def select(self):
        self.gui._deselect_all_printers()
        self.action.setEnabled(False)
        self.gui.show_notification(self.name + ' is ready!')
        self.gui.set_status('online')
        self.gui.printerPortDisableAction.setEnabled(True)
        self.gui.selected_printer = self

    def deselect(self):
        self.action.setEnabled(True)


class Window(QtGui.QMainWindow):
    def __init__(self, *args):
        #super(Window, self).__init__()
        apply(QtGui.QMainWindow.__init__, (self,) + args)
        QtGui.QApplication.setQuitOnLastWindowClosed(True)

        self._resourceLoader()
        self._createActions()
        self._createTrayIcon()
        self._createGUI()

        self.notificateHeader = '3DPrinterOS v' + version.version

        self.setWindowTitle(self.notificateHeader)
        self.setFixedSize(500, 600)

        self.token = None
        # TODO: several cameras and printers
        self.camera = None
        self.camera_action = None
        self.printers = list()
        self.selected_printer = None

        self.set_status()

        # TODO: remove in release, call from app if token does not exist.
        self.show_token_request()
        self.show_tray_icon()

        #test
        #self.show_detected_printers([{'name': 'R2X', 'COM': 'COM3'}, {'name': 'Mini', 'COM': None}])

    # External methods without underscore for calling from app
    # ----------

    def get_selected_printer_profile(self):
        return self.selected_printer.profile

    def is_printer_selected(self):
        return self.printerPortDisableAction.isEnabled()

    def is_camera_selected(self):
        return self.cameraDisableAction.isEnabled()

    # Shows token request window
    def show_token_request(self):
        self.show()

    # Shows tray popup
    def show_notification(self, message):
        if sys.platform.startswith('darwin'):
            path = __file__
            path = os.path.dirname(path)
            path = os.path.abspath(path)
            mac_path = os.path.join(path, 'mac')
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
            self.trayIcon.showMessage(self.notificateHeader, message)

    def show_tray_icon(self):
        self.trayIcon.show()
        QtGui.QApplication.setQuitOnLastWindowClosed(False)
        self.show_notification('Program started!')

    # Set tray status icon.
    # Possible status values:
    # - disconnected
    # - online
    # - error
    def set_status(self, status='disconnected'):
        try:
            self.trayIcon.setIcon(self.images['status_' + status])
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
                self.show_notification(printers_list[0]['name'] + ' is detected!')
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
    #     self.printerPortDisableAction.setEnabled(True)
    #     self.printerPortMenu.addAction(self.printer_action)

    def set_camera(self, camera_name):
        self.camera = camera_name
        self.show_notification('Camera ' + camera_name + ' is on!')
        self.camera_action = QtGui.QAction(camera_name, self, triggered=self._defaultCameraMethod)
        self.camera_action.setEnabled(False)
        self.cameraDisableAction.setEnabled(True)
        self.webcamMenu.addAction(self.camera_action)

    # ----------

    def _deselect_all_printers(self):
        for printer in self.printers:
            printer.deselect()

    def _defaultPrinterMethod(self):
        # TODO: logic when user chooses printer in list
        self.show_notification(self.printer + ' is ready!')
        self.printer_action.setEnabled(False)
        self.printerPortDisableAction.setEnabled(True)
        self.set_status('online')
        self.statusAction.setText(self.printer)

    def _defaultCameraMethod(self):
        # TODO: logic when user chooses camera in list
        self.show_notification(self.camera + ' is on!')
        self.camera_action.setEnabled(False)
        self.cameraDisableAction.setEnabled(True)


    def _resourceLoader(self):
        self.images = dict()
        # TODO: find out what are other icons for
        self.images['status_disconnected'] = QtGui.QIcon('./icons/1-0.png')
        self.images['status_online'] = QtGui.QIcon('./icons/1-1.png')
        self.images['status_error'] = QtGui.QIcon('./icons/1-3.png')

        self.images['button_ok_default'] = QtGui.QPixmap('./images/token/ok1.png')
        self.images['button_ok_hover'] = QtGui.QPixmap('./images/token/ok2.png')
        self.images['button_ok_pressed'] = QtGui.QPixmap('./images/token/ok3.png')
        self.images['button_ok_inactive'] = QtGui.QPixmap('./images/token/ok4.png')

        self.images['button_cancel_default'] = QtGui.QPixmap('./images/token/can1.png')
        self.images['button_cancel_hover'] = QtGui.QPixmap('./images/token/can2.png')
        self.images['button_cancel_pressed'] = QtGui.QPixmap('./images/token/can3.png')
        self.images['button_cancel_inactive'] = QtGui.QPixmap('./images/token/can4.png')

        self.images['getkey'] = QtGui.QPixmap('./images/token/getkey5.png')
        self.images['enter_key'] = QtGui.QPixmap('./images/token/key.png')

        self.appIcon = QtGui.QPixmap('./icons/128x128.png')


    def _createActions(self):
        self.statusAction = QtGui.QAction('Printer offline', self)
        self.statusAction.setEnabled(False)
        self.printerPortDisableAction = QtGui.QAction('Disable', self, triggered=self._printerPortDisableMethod)
        self.printerPortDisableAction.setEnabled(False)
        self.cameraDisableAction = QtGui.QAction('Disable', self, triggered=self._webcamDisableMethod)
        self.cameraDisableAction.setEnabled(False)
        self.supportLogsAction = QtGui.QAction('Support Logs', self, triggered=self._supportLogsMethod)
        self.changeKeyAction = QtGui.QAction('Change KEY', self, triggered=self._changeKeyMethod)
        self.liveSupportAction = QtGui.QAction('Get LiveSupport Help', self, triggered=self._liveSupportMethod)
        self.aboutAction = QtGui.QAction('About', self, triggered=self._aboutMethod)
        self.exitAction = QtGui.QAction("Exit", self, triggered=self._exitMethod)


    def _printerPortDisableMethod(self):
        if self.selected_printer:
            self.printerPortDisableAction.setEnabled(False)
            self.set_status('disconnected')
            self.statusAction.setText('Printer offline')
            self.show_notification(self.selected_printer.name + ' is off now!')
            self._deselect_all_printers()
            #self.statusAction.setIconVisibleInMenu(False)
            # TODO: printer disable logic here

    def _webcamDisableMethod(self):
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
        url = 'secured3d.com'
        webbrowser.open_new_tab(url)

    def _aboutMethod(self):
        self.aboutSection.show()

    def _exitMethod(self):
        # TODO: shutdown http-client here
        #self.running = False
        time.sleep(0.1)
        #app.App.close()
        QtGui.qApp.quit()

    def _createGUI(self):
        # Token request window
        loader = QtUiTools.QUiLoader()
        file = QtCore.QFile(os.path.join('./gui.xml'))
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

        # Icon don't set up via xml file for some reason
        self.icon = QtGui.QIcon()
        self.icon.addPixmap(self.appIcon, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.setWindowIcon(self.icon)

        # About window setup
        self.aboutSection = QtGui.QMainWindow()
        self.aboutSection.setWindowTitle("About")
        self.aboutSection.setFixedSize(500, 300)
        self.aboutSection.hide()
        self.aboutSection.setWindowIcon(self.icon)
        file = QtCore.QFile(os.path.join('./about.xml'))
        file.open(QtCore.QFile.ReadOnly)
        self.about = loader.load(file, self)
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
        file = QtCore.QFile(os.path.join('./token_change.xml'))
        file.open(QtCore.QFile.ReadOnly)
        self.tokenChangeGui = loader.load(file, self)
        file.close()
        self.tokenChange.setCentralWidget(self.tokenChangeGui)
        self.tokenChangeYesButton = self.tokenChangeGui.yesButton
        self.tokenChangeYesButton.clicked.connect(self._tokenChangeYesMethod)
        self.tokenChangeNoButton = self.tokenChangeGui.noButton
        self.tokenChangeNoButton.clicked.connect(self._tokenChangeNoMethod)

    def _tokenChangeYesMethod(self):
        # TODO: here is a method that clears token file
        self._exitMethod()

    def _tokenChangeNoMethod(self):
        self.tokenChange.hide()

    def _keyInputTextChanged(self):
        if self.keyInput.text():
            self.okButton.setIcon(self.images['button_ok_default'])
        else:
            self.okButton.setIcon(self.images['button_ok_inactive'])

    def _okButtonClicked(self):
        self.token = self.keyInput.text()
        if self.token:
            # TODO: pass token to app, not show it
            self.trayIcon.showMessage(self.notificateHeader, 'Token : ' + self.token)
        else:
            self.trayIcon.showMessage(self.notificateHeader, 'Please input token first')

    def _okButtonPressed(self):
        token = self.keyInput.text()
        if token:
            self.okButton.setIcon(self.images['button_ok_pressed'])

    def _okButtonReleased(self):
        token = self.keyInput.text()
        if token:
            self.okButton.setIcon(self.images['button_ok_default'])

    def _cancelButtonClicked(self):
        if self.trayIcon.isVisible():
            self.hide()
        else:
            self._exitMethod()

    def _cancelButtonPressed(self):
        self.cancelButton.setIcon(self.images['button_cancel_pressed'])


    def _cancelButtonReleased(self):
        self.cancelButton.setIcon(self.images['button_cancel_default'])

    def _createTrayIcon(self):
        self.trayIconMenu = QtGui.QMenu(self)

        self.printerPortMenu = QtGui.QMenu('Printer Port', self)
        self.webcamMenu = QtGui.QMenu('WebCams', self)

        self.webcamMenu.addAction(self.cameraDisableAction)

        self.printerPortMenu.addAction(self.printerPortDisableAction)

        self.trayIconMenu.addAction(self.statusAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addMenu(self.webcamMenu)
        self.trayIconMenu.addMenu(self.printerPortMenu)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.supportLogsAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.changeKeyAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.liveSupportAction)
        self.trayIconMenu.addAction(self.aboutAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.exitAction)

        self.trayIcon = QtGui.QSystemTrayIcon(self)
        self.trayIcon.setContextMenu(self.trayIconMenu)

#
# def show_gui(main_app):
#     # temp cwd change for launching gui from main module. Qt uses relative paths in generated xml and resourceLoader too
#     cwd = os.getcwd()
#     path = __file__
#     path = os.path.abspath(path)
#     dir_path = os.path.dirname(path)
#     os.chdir(dir_path)
#
#     app = QtGui.QApplication(sys.argv)
#     window = Window()
#     main_app._set_gui(window)
#
#     # set cwd to initial value
#     os.chdir(cwd)
#     app.exec_()
#     #sys.exit(app.exec_())
#
# if __name__ == '__main__':
#     show_gui()

