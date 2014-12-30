import time
import logging
import serial

# Warning any modification to profile will cause errors. profiles are used for identification. need to fix this somehow.
class PrinterInterface(object):

    RESTART_THREAD_SLEEP = 1
    DEFAULT_TIMEOUT = 15

    def try_protection(func):
        def decorator(self, *args, **kwargs):
            name = str(func.__name__)
            self.logger.info('[ Executing: ' + name + "...")
            try:
                result = func(self, *args, **kwargs)
            except Exception as e:
                self.logger.error("!Error in command %s\n[%s]" % (str(func.__name__), str(e)))
            else:
                self.logger.info('... ' + name + " finished ]")
                return result

        return decorator

    def __init__(self, profile):
        self.printer = None
        self.creation_time = time.time()
        self.logger = logging.getLogger('app.' + __name__)
        # if 'timeout' not in profile:
        #     profile['timeout'] = self.DEFAULT_TIMEOUT
        self.profile = profile
        self.logger.info('Creating interface with package : ' + profile['driver'])
        self.connect_printer()

    def connect_printer(self):
        printer_driver = __import__(self.profile['driver'])
        profile = self.profile
        if 'baudrate' in profile:
            profile = {}
            profile.update(self.profile)
            profile['baudrate'] = self.next_baudrate()
            self.logger.info("Using serial port %s:%i" % (profile['COM'], profile['baudrate']))
        self.logger.info("Connecting with profile: " + str(profile))
        try:
            printer = printer_driver.Printer(profile)
        except Exception as e:
            self.logger.warning("Error connecting to %s. %s" % (self.profile['name'], e.message))
        else:
            self.printer = printer
            self.logger.info("Successful connection to %s!" % (self.profile['name']))

    def next_baudrate(self):
        try:
            current_baudrate = self.printer.profile['baudrate']
            index = self.profile['baudrate'].index(current_baudrate) + 1
            self.profile['baudrate'][index] #this line should raise exception if index too high
        except:
            index = 0
        return self.profile['baudrate'][index]

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

    @try_protection
    def is_operational(self):
        if self.printer:
            return self.printer.is_operational()
        self.logger.warning("No printer in printer_interface " + str(self.profile['name']))
        return False

    @try_protection
    def report(self):
        if self.printer:
            return self.printer.report()
        return {'status': 'no_printer'}

    @try_protection
    def close(self):
        if self.printer:
            self.logger.info('Closing ' + str(self.profile))
            self.printer.close()
            self.logger.info('...closed.')
            self.printer = None
        else:
            self.logger.debug('Nothing to close')

    @try_protection
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

    @try_protection
    def binary_file(self, data):
        self.printer.binary_file(data)

    @try_protection
    def gcodes(self, gcodes):
        self.printer.gcodes(gcodes)

    @try_protection
    def pause(self):
        self.printer.pause()

    @try_protection
    def cancel(self):
        self.printer.cancel()

    @try_protection
    def emergency_stop(self):
        self.printer.emergency_stop()

    @try_protection
    def set_total_gcodes(self, length):
        self.printer.set_total_gcodes(length)

    @try_protection
    def begin(self, length):
        self.set_total_gcodes(length)

    @try_protection
    def enqueue(self, gcodes):
        self.printer.enqueue(gcodes)

    @try_protection
    def end(self):
        self.printer.end()

    @try_protection
    def resume(self):
        self.printer.resume()

    @try_protection
    def is_paused(self):
        return self.printer.is_paused()
