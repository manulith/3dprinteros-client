#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import time
import signal
import logging
import logging.handlers

import utils
utils.init_path_to_libs()
import config
import version
import usb_detect
import http_client
import printer_interface
import user_login

class App:

    MIN_LOOP_TIME = 2
    READY_TIMEOUT = 10

    @staticmethod
    def get_logger():
        logger = logging.getLogger("app")
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        stderr_handler = logging.StreamHandler()
        stderr_handler.setLevel(logging.DEBUG)
        logger.addHandler(stderr_handler)
        log_file = config.config['log_file']
        if log_file:
            try:
                file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=1024*1024*4, backupCount=1)
                file_handler.setFormatter(logging.Formatter('%(levelname)s\t%(asctime)s\t%(threadName)s/%(funcName)s\t%(message)s'))
                file_handler.setLevel(logging.DEBUG)
                logger.addHandler(file_handler)
            except Exception as e:
                logger.debug('Could not create log file because' + e.message + '\n.No log mode.')
        return logger

    def __init__(self):
        self.logger = self.get_logger()
        self.logger.info("Welcome to 3DPrinterOS Client version %s_%s" % (version.version, version.build))
        self.time_stamp()
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.detected_printers = []
        self.printer_interfaces = []
        self.stop_flag = False
        self.quit_flag = False
        self.user_login = user_login.UserLogin(self)
        self.init_interface()
        self.user_login.wait_for_login()
        self.main_loop()

    def init_interface(self):
        if config.config['web_interface']:
            import webbrowser
            from web_interface import WebInterface
            self.web_interface = WebInterface(self)
            self.web_interface.start()
            webbrowser.open("http://127.0.0.1:8008", 2, True)

    def main_loop(self):
        while not self.stop_flag:
            self.time_stamp()
            self.detected_printers = usb_detect.get_printers()
            self.check_and_connect()
            for printer in self.printer_interfaces:
                if printer.usb_info not in self.detected_printers:
                    self.disconnect_printer(printer)
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

    def disconnect_printer(self, pi):
        self.logger.info('Disconnecting %s' % str(pi.usb_info))
        if http_client.send(http_client.package_command_request, (pi.printer_token, pi.state_report('not_detected'))):
            self.printer_interfaces.remove(printer_interface)

    def intercept_signal(self, signal_code, frame):
        self.logger.warning("SIGINT or SIGTERM received. Closing 3DPrinterOS Client version %s_%s" % \
                (version.version, version.build))
        self.quit()

    def quit(self):
        self.stop_flag = True
        for pi in self.printer_interfaces:
            pi.close()
        time.sleep(0.1) #to reduce logging spam in next
        self.time_stamp()
        self.logger.info("Waiting for driver modules to close...")
        while True:
            ready_flag = True
            for pi in self.printer_interfaces:
                if pi.printer:
                    ready_flag = False
                    self.logger.debug("Waiting for driver modules to close %s" % pi.profile['driver'])
                else:
                    pi.join(1)
                    if pi.isAlive():
                        self.printer_interfaces.remove(pi)
                        self.logger.info("Close %s" % str(pi.usb_info))
                    else:
                        ready_flag = False
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
