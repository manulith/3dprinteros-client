#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import time
import signal
import logging
from subprocess import Popen

import utils
utils.init_path_to_libs()
import config
import version
import usb_detect
import http_client
import printer_interface
import user_login
import updater


class App:

    MIN_LOOP_TIME = 2
    READY_TIMEOUT = 10

    def __init__(self):
        self.logger = utils.get_logger(config.config["log_file"])
        self.logger.info("Welcome to 3DPrinterOS Client version %s_%s" % (version.version, version.build))
        self.time_stamp()
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.detected_printers = []
        self.printer_interfaces = []
        self.stop_flag = False
        self.quit_flag = False
        self.cam = None
        self.updater = updater.Updater()
        self.updater.check_for_updates()
        self.user_login = user_login.UserLogin(self)
        self.init_interface()
        self.user_login.wait_for_login()
        self.start_camera()
        self.main_loop()

    def start_camera(self):
        if config.config["camera"]["enabled"] == True:
            self.logger.info('Launching camera subprocess')
            client_dir = os.path.dirname(os.path.abspath(__file__))
            cam_path = os.path.join(client_dir, 'cam.py')
            try:
                self.cam = Popen([sys.executable, cam_path])
            except Exception as e:
                self.logger.warning('Could not launch camera due to error:\n' + e.message)

    def init_interface(self):
        if config.config['web_interface']:
            import webbrowser
            from web_interface import WebInterface
            self.web_interface = WebInterface(self)
            self.web_interface.start()
            self.logger.debug("Waiting for webserver to start...")
            while not self.web_interface.server:
                time.sleep(0.01)
            self.logger.debug("...server is up and running. Connecting browser...")
            webbrowser.open("http://127.0.0.1:8008", 2, True)
            self.logger.debug("...done")

    def main_loop(self):
        while not self.stop_flag:
            self.updater.auto_update()
            self.time_stamp()
            self.detected_printers = usb_detect.get_printers()
            self.check_and_connect()
            for pi in self.printer_interfaces:
                if pi.usb_info not in self.detected_printers:
                    self.disconnect_printer(pi, 'not_detected')
                elif not pi.is_alive():
                    self.disconnect_printer(pi, 'error')
            time.sleep(2)
        # this is for quit from web interface(to release server's thread and quit)
        if self.quit_flag:
            self.quit()

    def time_stamp(self):
        self.logger.debug("Time stamp: " + time.strftime("%d %b %Y %H:%M:%S", time.localtime()))

    def check_and_connect(self):
        currently_connected_usb_info = [pi.usb_info for pi in self.printer_interfaces]
        for usb_info in self.detected_printers:
            if usb_info not in currently_connected_usb_info:
                pi = printer_interface.PrinterInterface(usb_info, self.user_login.user_token)
                pi.start()
                self.printer_interfaces.append(pi)

    def disconnect_printer(self, pi, reason):
        self.logger.info('Disconnecting because of %s %s' % (reason , str(pi.usb_info)))
        if http_client.send(http_client.package_command_request, (pi.printer_token, pi.state_report(reason), pi.acknowledge)):
            self.printer_interfaces.remove(pi)

    def intercept_signal(self, signal_code, frame):
        self.logger.warning("SIGINT or SIGTERM received. Closing 3DPrinterOS Client version %s_%s" % \
                (version.version, version.build))
        self.quit()

    def quit(self):
        self.stop_flag = True
        if self.cam:
            self.cam.terminate()
            self.cam.kill()
        for pi in self.printer_interfaces:
            pi.close()
        time.sleep(0.1) #to reduce logging spam in next
        self.time_stamp()
        self.logger.info("Waiting for driver modules to close...")
        while True:
            ready_flag = True
            for pi in self.printer_interfaces:
                if pi.isAlive():
                    ready_flag = False
                    self.logger.debug("Waiting for driver modules to close %s" % str(pi.usb_info))
                else:
                    self.printer_interfaces.remove(pi)
                    self.logger.info("%s was close" % str(pi.usb_info))
            if ready_flag:
                break
            time.sleep(0.1)
        self.logger.debug("Waiting web interface server to shutdown")
        try:
            self.web_interface.server.shutdown()
            self.web_interface.join(1)
        except Exception as e:
            print e
        self.time_stamp()
        self.logger.info("...everything correctly closed.")
        self.logger.info("Goodbye ;-)")
        logging.shutdown()
        sys.exit(0)

if __name__ == '__main__':
    app = App()
