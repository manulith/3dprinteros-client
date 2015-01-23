import time
import logging
import serial
import threading

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
        self.printer = None
        self.creation_time = time.time()
        self.logger = logging.getLogger('app.' + __name__)
        self.usb_info = usb_info
        self.logger.info('New printer interface for %s' + str(usb_info))

    def connect_printer(self):
        http_client.token_login()
        printer_driver = __import__(self.profile['driver'])
        self.logger.info("Connecting with profile: " + str(self.profile))
        try:
            printer = printer_driver.Printer(self.profile)
        except Exception as e:
            self.logger.warning("Error connecting to %s" % self.profile['name'], exc_info=True)
        else:
            self.printer = printer
            self.logger.info("Successful connection to %s!" % (self.profile['name']))

    def wait_operational(self, timeout=30):
        elapsed = 0
        while elapsed < timeout:
            state = self.is_operational()
            if state:
                return state
            else:
                time.sleep(0.5)
                elapsed += 0.5
        self.logger.warning('Error. Timeout while waiting for printer to become operational.')

    def run(self):
        if not self.printer:
            self.connect_printer()
        else:
            if self.printer.is_operational():
                self.excecute(self.get_command())
            else:
                if time.time() - self.creation_time < self.profile.get('start_timeout', self.DEFAULT_TIMEOUT):
                    time.sleep(0.1)
                else:
                    self.printer()


    def get_command(self):
        pass

    # @protection
    # def is_operational(self):
    #     if self.printer:
    #         return self.printer.is_operational()
    #     self.logger.warning("No printer in printer_interface " + str(self.profile['name']))
    #     return False

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
                    time.sleep(0.5)
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
