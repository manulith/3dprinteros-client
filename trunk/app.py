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
import command_processor

class UserLoginer:

    def __init__(self):
        self.logger = "app.UserLogin"

    def login_user(self):
        self.logger.debug("Waiting for correct user login")
        self.errors = set()
        if self.token:
            answer = http_client.send(http_client.user_login, self.token)
            if answer:
                login = answer.get('user_token', None)
                errors = command_processor.check_from_errors(answer)
                if not errors:
                    if login:
                        self.login = login
                        self.errors = set()
                else:
                    self.errors.union(errors)
                    self.logger.warning("Error processing user_login " + str(errors))
            self.logger.error("Login rejected")

    def wait_for_login(self):
        while not self.token or self.stop_flag:
            self.token_login(self.token)
            time.sleep(1)
            if self.quit_flag:
                self.quit()

class App():
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
        self.init_interface()
        self.main_loop()

    def init_interface(self):
        if config.config['web_interface']:
            import webbrowser
            from web_interface import WebInterface
            self.web_interface = WebInterface(self)
            self.web_interface.start()
            webbrowser.open("http://127.0.0.1:8008", 2, True)

    def local_report(self, data):
        pass

    def main_loop(self):
        self.user_token = None
        while not self.stop_flag:
            self.time_stamp()
            if not self.user_token:
                self.user_token = self.login_user()
            else:
                self.logger.debug("START detect_printers")
                self.detected_printers = usb_detect.get_printers()
                self.logger.debug("DONE detect_printers")
                self.check_and_connect()
        # this is for quit from web interface(to release server's thread and quit)
        if self.quit_flag:
            self.quit()

    def time_stamp(self):
        self.logger.debug("Time stamp: " + time.strftime("%d %b %Y %H:%M:%S", time.localtime()))

    def check_and_connect(self):
        currently_connected_usb_info = [pi.usb_info for pi in self.printer_interfaces]
        for usb_info in self.detected_printers:
            if usb_info not in currently_connected_usb_info:
                pi = printer_interface.PrinterInterface(usb_info, self.user_token)
                pi.start()
                self.printer_interfaces.append(pi)

    def disconnect_printer(self, pi):
        self.logger.info('Disconnecting %s' % printer_interface.profile['name'])
        self.printer_interfaces.remove(printer_interface)
        http_client.send(http_client.token_job_request, (self.token, self.get_report(printer_interface)))

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
                    self.printer_interfaces.remove(pi)
                    self.logger.info("%s closed" % pi.profile['driver'])
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
