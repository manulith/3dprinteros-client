#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import time
import signal
import logging
import logging.handlers

import utils
import config
import version
import usb_detect
import network_detect
import http_client
import printer_interface
import command_processor

class App():

    MIN_LOOP_TIME = 2
    READY_TIMEOUT = 10

    @staticmethod
    def get_logger():
        logger = logging.getLogger('app')
        logger.setLevel(logging.DEBUG)
        #formatter = logging.Formatter('%(levelname)s\t%(asctime)s\t%(threadName)s/%(funcName)s\t%(message)s')
        #formatter = logging.Formatter('%(asctime)s\t%(threadName)s/%(funcName)s\t%(message)s')
        stderr_handler = logging.StreamHandler()
        stderr_handler.setLevel(logging.DEBUG)
        #stderr_handler.setFormatter(formatter)
        logger.addHandler(stderr_handler)
        log_file = config.config['log_file']
        if log_file:
            try:
                file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=1024*1024*100, backupCount=1)
                file_handler.setLevel(logging.DEBUG)
                #file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            except Exception as e:
                logger.debug('Could not create log file because' + e.message + '\n.No log mode.')
        return logger

    def __init__(self):
        self.logger = self.get_logger()
        self.logger.info("Welcome to 3DPrinterOS Client version %s_%s" % (version.version, version.build))
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.detected_printers = []
        self.printer_interfaces = []
        self.token_login()
        self.init_interface()
        self.stop_flag = False
        self.quit_flag = False
        self.wait_for_login()
        #self.kill_makerbot_conveyor()
        self.main_loop()

    def init_interface(self):
        if config.config['gui']:
            self.gui_exchange_in = ""
            self.gui_exchange_out = ""
            self.selected_printer_number = None
            import gui as gui_module
            self.gui_module = gui_module
            if self.token:
                self.show_tray()
            else:
                self.show_login_window()

        if config.config['web_interface']:
            import webbrowser
            from web_interface import WebInterface
            self.web_interface = WebInterface(self)
            self.web_interface.start()
            webbrowser.open("http://127.0.0.1:8008", 2, True)

    def show_login_window(self):
        self.gui_module.show_login_window(self)
        token = self.gui_exchange_in.get('token', None)
        utils.write_token(token)

    def show_tray(self):
        self.tray_wrapper = self.gui_module.AppStub(self)
        self.tray_wrapper.show()

    #token_s
    def token_login(self):
        self.logger.debug("Waiting for correct login")
        self.token = None
        token = utils.read_token()
        answer = http_client.send(http_client.token_login, token)
        if answer:
            printer_alias_by_token = answer.get('printer_type_name', None)
            if printer_alias_by_token:
                self.logger.info('Printer type by token: %s' % printer_alias_by_token)
                self.printer_alias_by_token = printer_alias_by_token
                self.printer_name_by_token = self.get_name_by_alias(printer_alias_by_token)
                self.token = token
                return True
        self.logger.error("Login rejected")

    def wait_for_login(self):
        while not self.token or self.stop_flag:
            self.token_login()
            time.sleep(0.1)
            if self.quit_flag:
                self.quit()

    # token s
    def get_name_by_alias(self, printer_alias):
        try:
            printer_type_name = config.config['profiles'][printer_alias]['name']
        except KeyError as e:
            self.logger.error("Wrong printer alias - %s" % printer_alias, exc_info=True)
        else:
            return printer_type_name

    # token s
    def get_alias_by_name(self, printer_name):
        profiles = config.config['profiles']
        for profile_alias in profiles:
            if printer_name == profiles[profile_alias]['name']:
                return profile_alias

    def main_loop(self):
        while not self.stop_flag:
            before = time.time()
            currently_detected = self.detect_printers()
            self.detected_printers = currently_detected # for gui
            self.detect_and_connect(currently_detected)
            time.sleep(0.5)
            self.do_things_with_connected(currently_detected)
            elapsed = time.time() - before
            if elapsed < self.MIN_LOOP_TIME:
                time.sleep(self.MIN_LOOP_TIME - elapsed)
            self.logger.debug("loop_time: %f" % elapsed)
        # this is for quit from web interface(to release server's thread and quit)
        if self.quit_flag:
            self.quit()

    def detect_and_connect(self, currently_detected):
        currently_connected_profiles = [pi.profile for pi in self.printer_interfaces]
        for printer_profile in currently_detected:
            if printer_profile not in currently_connected_profiles:
                name = printer_profile['name']
                if name == self.printer_name_by_token:
                    self.connect_printer(printer_profile)
                else:
                    self.logger.warning("Wrong token for printer type. \
                                            Expecting %s but got %s" % (self.printer_name_by_token, name))

    def do_things_with_connected(self, currently_detected):
        for pi in self.printer_interfaces:
            if pi.profile in currently_detected:
                if pi.is_operational():
                    self.report_state_and_execute_new_job(pi)
                    time.sleep(1) #remove me in release
                    continue
                elif (time.time() - pi.creation_time) < self.READY_TIMEOUT:
                    self.logger.info('Waiting for printer to become operational. %f secs' % (time.time() - pi.creation_time))
                    time.sleep(1) #remove me in release
                    continue
            else:
                self.logger.warning(  "Printer %s %s no longer detected!" % (pi.profile['name'], pi.profile['SNR']))
            self.disconnect_printer(pi)

    def report_state_and_execute_new_job(self, printer):
        answer = http_client.send(http_client.token_job_request, (self.token, self.get_report(printer)))
        if answer:
            command_processor.process_job_request(printer, answer)

    def get_report(self, printer_interface):
        report = printer_interface.report()
        self.logger.debug('%s reporting: %s' % (printer_interface.profile['name'], str(report)))
        return report

    def connect_printer(self, printer_profile):
        if printer_profile['name'] == self.printer_name_by_token:
            new_pi = printer_interface.PrinterInterface(printer_profile)
            self.printer_interfaces.append(new_pi)
        else:
            self.logger.debug("Wrong token prevent creation of interface")

    def disconnect_printer(self, printer_interface=None):
        if not printer_interface:
            printer_interface = self.printer_interfaces[0]
        self.logger.info('Disconnecting %s' % printer_interface.profile['name'])
        self.printer_interfaces.remove(printer_interface)
        printer_interface.close()
        if config.config['gui']:
            self.tray_wrapper.qt_thread.show_notification('Closing ' + printer_interface.profile['name'])

    def kill_makerbot_conveyor(self):
        self.logger.info('Stopping third party software...')
        try:
            from birdwing.conveyor_from_egg import kill_existing_conveyor
            kill_existing_conveyor()
        except ImportError as e:
            self.logger.debug(e)
        else:
            self.logger.info('...done.')

    def check_autoselect(self):
        autoselect = config.config['autoselect']
        if autoselect:
            detected = usb_detect.get_printers() or network_detect.get_printers()
            if autoselect in config.config["profiles"]: # used for debug
                self.logger.info("Force load of driver " + str(autoselect))
                profile = config.config["profiles"][autoselect]
                return profile
            elif detected:
                return detected[0]
            else:
                self.logger.critical("Can't detect printer. Exiting")
                self.quit()

    def detect_printers(self):
        usb_results = usb_detect.get_printers()
        #network_results = network_detect.get_printers()
        return usb_results

    def intercept_signal(self, signal_code, frame):
        self.logger.warning("SIGINT or SIGTERM received. Closing 3DPrinterOS Client version %s_%s" % \
                (version.version, version.build))
        self.quit()

    def quit(self):
        self.stop_flag = True
        for pi in self.printer_interfaces:
            pi.close()
        time.sleep(0.1) #to reduce logging spam in next
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
        self.web_interface.close()
        self.web_interface.server.shutdown()
        self.web_interface.join(1)
        self.logger.info("...everything correctly closed.")
        self.logger.info("Goodbye ;-)")
        sys.exit(0)

if __name__ == '__main__':
    app = App()
