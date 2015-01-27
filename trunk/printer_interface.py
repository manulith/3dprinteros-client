import time
import base64
import serial
import logging
import threading

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
                if self.profile.get('stop_on_error', False):
                    raise e
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

        self.logger.info('New printer interface for %s'  + str(usb_info))

    def connect_to_server(self):
        self.logger.info("Connecting to server with printer: %s" % str(self.usb_info))
        answer = http_client.send(http_client.package_printer_login, (self.user_token, self.usb_info))
        if answer:
            error_num, error_str = utils.check_for_errors(answer)
            if error_num:
                self.logger.warning("Error while login %s:" % str(self.usb_info))
                self.logger.warning(error_str)
            else:
                self.priner_token = answer['printer_token']
                self.printer_profile = answer["printer_profile"]
        else:
            self.logger.warning("While loggi No connection or false answer")

    @protection
    def connect_printer_driver(self):
        printer_driver = __import__(self.profile['driver'])
        self.logger.info("Connecting with profile: " + str(self.profile))
        try:
            printer = printer_driver.Printer(self.profile)
        except Exception as e:
            self.logger.warning("Error connecting to %s" % self.profile['name'], exc_info=True)
        else:
            self.printer = printer
            self.logger.info("Successful connection to %s!" % (self.profile['name']))

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

    @protection
    def process_command_request(self, data_dict):
        logger = logging.getLogger("app." + __name__)
        number = data_dict.get('number', None)
        if number:
            logger.info("Processing command number %i" % number)
        error = data_dict['error']
        if error:
            error_code = error[0]
            error_str = error[1]
            self.logger.warning("Server command came with errors %d %s", (error_code, error_str))
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
        logger.warning("Error processing command: " + str(data_dict))

    def run(self):
        self.stop_flag = False
        self.connect_to_server()
        self.connect_printer_driver()
        while not self.stop_flag and self.printer:
            if self.printer.is_operational():
                command = http_client.send(http_client.package_command_request, self.report())
                self.process_command_request(self, command)
                time.sleep(1)
            else:
                if time.time() - self.creation_time < self.profile.get('start_timeout', self.DEFAULT_TIMEOUT):
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
            self.logger.info('Closing ' + str(self.profile))
            self.printer.close()
            self.logger.info('...closed.')
            self.printer = None
        else:
            self.logger.debug('Nothing to close')

    @protection
    def close_hanged_port(self):
        self.logger.info("Trying to force close serial port %s" % self.profile['COM'])
        if self.profile["force_port_close"] and self.profile['COM']:
            try:
                port = serial.Serial(self.profile['COM'], self.profile['baudrate'][0], timeout=1)
                if port.isOpen():
                    port.setDTR(1)
                    time.sleep(1)
                    port.setDTR(0)
                    port.close()
                    self.logger.info("Malfunctioning port %s was closed." % self.profile['COM'])
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
        if self.printer_token:
            report = {"printer_token": self.token}
            report["temps"] = self.printer.get_temps()
            report["target_temps"] = self.printer.get_target_temps()
            report["percent"] = self.printer.get_percent()
            if outer_state:
                report["state"] = outer_state
            else:
                report["state"] = self.printer.get_printer_state()
