import time
import base64
import serial
import logging
import threading
import json

import utils
import http_client


# Warning any runtime modification of profile will cause errors. profiles are used for identification. need to fix this somehow.
class PrinterInterface(threading.Thread):

    DEFAULT_TIMEOUT = 45

    def protection(func):
        def decorator(self, *args, **kwargs):
            name = str(func.__name__)
            self.logger.info('[ Executing: ' + name + "...")
            try:
                result = func(self, *args, **kwargs)
            except Exception as e:
                self.logger.error("!Error in command %s\n[%s]" % (str(func.__name__), str(e)))
            else:
                if result != None:
                    self.logger.info('Result is: ( ' + str(result) + " )")
                self.logger.info('... ' + name + " finished ]")
                return result
        return decorator

    def __init__(self, usb_info, user_token):
        self.usb_info = usb_info
        self.user_token = user_token
        self.printer = None
        self.printer_token = None
        self.creation_time = time.time()
        self.logger = logging.getLogger('app.' + __name__)
        self.logger.info('New printer interface for %s' % str(usb_info))
        super(PrinterInterface, self).__init__()

    def connect_to_server(self):
        self.logger.info("Connecting to server with printer: %s" % str(self.usb_info))
        while True:
            answer = http_client.send(http_client.package_printer_login, (self.user_token, self.usb_info))
            if answer:
                error = answer.get('error', None)
                if error:
                    self.logger.warning("Error while login %s:" % str(self.usb_info))
                    self.logger.warning(str(error['code']) + " " + error["message"])
                    if str(error['code']) == '8':
                        time.sleep(1)
                        continue
                    else:
                        return False
                else:
                    self.logger.info('Successfully connected to server.')
                    self.printer_token = answer['printer_token']
                    self.logger.info('Received answer: ' + str(answer))
                    self.printer_profile = json.loads(answer["printer_profile"])
                    if self.usb_info['COM']:
                        self.printer_profile['COM'] = self.usb_info['COM']
                    self.logger.info('Setting profile: ' + str(self.printer_profile))
                    return True
            else:
                self.logger.warning("Error on printer login. No connection or answer from server.")
                time.sleep(0.1)
                return False

    @protection
    def connect_printer_driver(self):
        printer_driver = __import__(self.printer_profile['driver'])
        self.logger.info("Connecting with profile: " + str(self.printer_profile))
        try:
            printer = printer_driver.Printer(self.printer_profile)
        except Exception as e:
            self.logger.warning("Error connecting to %s" % self.printer_profile['name'], exc_info=True)
        else:
            self.printer = printer
            self.logger.info("Successful connection to %s!" % (self.printer_profile['name']))

    # def wait_operational(self, timeout=30):
    #     elapsed = 0
    #     while elapsed < timeout:
    #         state = self.is_operational()
    #         if state:
    #             return state
    #         else:
    #             time.sleep(0.5)
    #             elapsed += 0.5
    #     self.logger.warning('Error. Timeout while waiting for printer to become operational.')

    def process_command_request(self, data_dict):
        logger = logging.getLogger("app." + __name__)
        number = data_dict.get('number', None)
        if number:
            logger.info("Processing command number %i" % number)
        error = data_dict.get('error', None)
        if error:
            self.logger.warning("Server command came with errors %d %s" % (error['code'], error['message']))
            self.logger.debug("Full answer text: " + str(data_dict))
        else:
            command = data_dict.get('command', None)
            if command:
                if hasattr(self.printer, command):
                    method = self.getattr('command')
                    payload = data_dict.get('payload', None)
                    if data_dict.get('is_link', False):
                        payload = http_client.download(payload)
                    elif "command" in ("gcodes", "binary_file"):
                        payload = base64.b64decode(payload)
                    if payload:
                        method(payload)
                    else:
                        method()
                    return True

    def run(self):
        self.stop_flag = False
        connected = False
        if self.connect_to_server():
            self.connect_printer_driver()
        while not self.stop_flag and self.printer:
            if self.printer.is_operational():
                answer = http_client.send(http_client.package_command_request, (self.printer_token, self.state_report()))
                if answer:
                    self.logger.debug("Got answer: " + str(answer))
                    self.process_command_request(answer)
                    time.sleep(0.5)
            else:
                if time.time() - self.creation_time < self.printer_profile.get('start_timeout', self.DEFAULT_TIMEOUT):
                    time.sleep(0.1)
                else:
                    self.printer.close()
                    self.printer = None

    @protection
    def report(self):
        if self.printer:
            return self.printer.report()
        return {'status': 'no_printer'}

    @protection
    def close(self):
        if self.printer:
            self.logger.info('Closing ' + str(self.printer_profile))
            self.printer.close()
            self.logger.info('...closed.')
            self.printer = None
        else:
            self.logger.debug('Nothing to close')

    @protection
    def close_hanged_port(self):
        self.logger.info("Trying to force close serial port %s" % self.usb_info['COM'])
        if self.printer_profile["force_port_close"] and self.usb_info['COM']:
            try:
                port = serial.Serial(self.usb_info['COM'], self.printer_profile['baudrate'][0], timeout=1)
                if port.isOpen():
                    port.setDTR(1)
                    time.sleep(1)
                    port.setDTR(0)
                    port.close()
                    self.logger.info("Malfunctioning port %s was closed." % self.usb_info['COM'])
            except serial.SerialException as e:
                self.logger.info("Force close serial port failed with error %s" % e.message)
        else:
            self.logger.info("Force close serial port forbidden: \
                                not serial printer or force_port_close disabled in config")

    @protection
    def binary_file(self, data):
        self.printer.binary_file(data)

    @protection
    def gcodes(self, gcodes):
        self.printer.gcodes(gcodes)

    @protection
    def pause(self):
        self.printer.pause()

    @protection
    def cancel(self):
        self.printer.cancel()

    @protection
    def emergency_stop(self):
        self.printer.emergency_stop()

    @protection
    def set_total_gcodes(self, length):
        self.printer.set_total_gcodes(length)

    @protection
    def begin(self, length):
        self.set_total_gcodes(length)

    @protection
    def enqueue(self, gcodes):
        self.printer.enqueue(gcodes)

    @protection
    def end(self):
        self.printer.end()

    @protection
    def resume(self):
        self.printer.resume()

    @protection
    def is_paused(self):
        return self.printer.is_paused()

    def get_printer_state(self):
        if self.printer.is_operational():
            if self.printer.is_printing():
                state = "printing"
            elif self.printer.is_paused():
                state = "paused"
            else:
                state = "ready"
        else:
            state = "error"
        return state

    def state_report(self, outer_state=None):
        if self.printer:
            report = {}
            report["temps"] = self.printer.get_temps()
            report["target_temps"] = self.printer.get_target_temps()
            report["percent"] = self.printer.get_percent()
            if outer_state:
                report["state"] = outer_state
            else:
                report["state"] = self.get_printer_state()
            return report
