#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import time
import signal
import logging
import traceback
import platform
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
import cloud_sync


class App:

    MAIN_LOOP_SLEEP = 2
    LOG_FLUSH_TIME = 30

    def __init__(self):
        self.logger = utils.create_logger('app', config.config['log_file'])
        self.logger.info('Operating system: ' + platform.system() + ' ' + platform.release())
        self.logger.info("Welcome to 3DPrinterOS Client version %s_%s" % (version.version, version.build))
        self.time_stamp()
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.detected_printers = []
        self.printer_interfaces = []
        self.stop_flag = False
        self.quit_flag = False
        self.http_client = http_client.HTTPClient()
        self.cam = None
        self.cloud_sync = None
        self.cam_modules = config.config['camera']['modules']
        self.cam_current_module = self.cam_modules[config.config['camera']['default_module_name']]
        self.updater = updater.Updater()
        self.user_login = user_login.UserLogin(self)
        self.init_interface()
        self.user_login.wait_for_login()
        self.start_camera(self.cam_current_module)
        self.start_cloud_sync()
        self.main_loop()

    def start_cloud_sync(self):
        if config.config['cloud_sync']['enabled']:
            self.cloud_sync = utils.launch_suprocess(config.config['cloud_sync']['module'])

    def start_camera(self, module):
        if config.config["camera"]["enabled"]:
            self.cam = utils.launch_suprocess(module)
            self.cam_current_module = module

    def switch_camera(self, module):
        self.logger.info('Switching camera module from %s to %s' % (self.cam_current_module, module))
        if self.cam:
            self.cam.terminate()
        self.cam_current_module = module
        if module:
            self.start_camera(module)

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
        self.last_flush_time = 0
        while not self.stop_flag:
            self.updater.timer_check_for_updates()
            self.time_stamp()
            self.detected_printers = usb_detect.get_printers()
            self.check_and_connect()
            for pi in self.printer_interfaces:
                if pi.usb_info not in self.detected_printers:
                    self.disconnect_printer(pi, 'not_detected')
                elif not pi.is_alive():
                    self.disconnect_printer(pi, 'error')
            if not self.stop_flag:
                time.sleep(self.MAIN_LOOP_SLEEP)
            now = time.time()
            if now - self.last_flush_time > self.LOG_FLUSH_TIME:
                self.last_flush_time = now
                self.logger.info('Flushing logger handlers')
                for handler in self.logger.handlers:
                    handler.flush()
        self.quit()

    def time_stamp(self):
        self.logger.debug("Time stamp: " + time.strftime("%d %b %Y %H:%M:%S", time.localtime()))

    def check_and_connect(self):
        currently_connected_usb_info = [pi.usb_info for pi in self.printer_interfaces]
        for usb_info in self.detected_printers:
            if usb_info not in currently_connected_usb_info:
                pi = printer_interface.PrinterInterface(usb_info, self.user_login.user_token, self)
                pi.start()
                self.printer_interfaces.append(pi)

    def disconnect_printer(self, pi, reason):
        self.logger.info('Disconnecting because of %s %s' % (reason , str(pi.usb_info)))
        if self.http_client.pack_and_send('command', pi.printer_token, pi.state_report(reason), pi.acknowledge, None, None):
            pi.close()
            self.printer_interfaces.remove(pi)
            self.logger.info("Successful disconnection of " + str(pi.usb_info))
        else:
            self.logger.warning("Cant report printer interface closing to server. Not closed.")

    def intercept_signal(self, signal_code, frame):
        self.logger.warning("SIGINT or SIGTERM received. Closing 3DPrinterOS Client version %s_%s" % \
                (version.version, version.build))
        self.stop_flag = True

    def quit(self):
        self.logger.info("Starting exit sequence...")
        for subprocess in self.cam, self.cloud_sync:
            if subprocess:
                subprocess.terminate()
        for pi in self.printer_interfaces:
            pi.close()
        time.sleep(0.1) #to reduce logging spam in next
        self.time_stamp()
        self.logger.info("Waiting for gcode sending modules to close...")
        while True:
            ready_flag = True
            for pi in self.printer_interfaces:
                if pi.isAlive():
                    ready_flag = False
                    self.logger.debug("Waiting for %s" % str(pi.usb_info))
                else:
                    self.printer_interfaces.remove(pi)
                    self.logger.info("Printer on %s was closed." % str(pi.usb_info))
            if ready_flag:
                break
            time.sleep(0.1)
            self.logger.info("...all gcode sending modules closed.")
        self.logger.debug("Waiting web interface server to shutdown")
        try:
            self.web_interface.server.shutdown()
            self.web_interface.join()
        except:
            pass
        self.time_stamp()
        self.logger.info("...all modules were closed correctly.")
        self.logger.info("Goodbye ;-)")
        logging.shutdown()
        sys.exit(0)

if __name__ == '__main__':
    try:
        app = App()
    except SystemExit:
        pass
    except:
        trace = traceback.format_exc()
        print trace
        with open(config.config['error_file'], "a") as f:
            f.write(time.ctime() + "\n" + trace + "\n")
