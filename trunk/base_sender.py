import collections
import logging

class BaseSender:

    def __init__(self, profile):
        self.profile = profile
        self.buffer = collections.deque()
        self.logger = logging.getLogger('app.' + __name__)
        self.stop_flag = False
        self.pause_flag = False
        self.error_code = 0
        self.error_message = ''
        self.temps = [0,0]
        self.target_temps = [0,0]

    def get_temps(self):
        return self.temps

    def get_target_temps(self):
        return self.target_temps

    def get_percent(self):
        len(self.buffer)

    def pause(self):
        self.pause_flag = True

    def unpause(self):
        self.pause_flag = False

    def get_error_code(self):
        return self.error_code

    def get_error_message(self):
        return self.error_message

    def is_paused(self):
        return self.pause_flag

    # def close_hanged_port(self):
    #     self.logger.info("Trying to force close serial port %s" % self.usb_info['COM'])
    #     if self.printer_profile["force_port_close"] and self.usb_info['COM']:
    #         try:
    #             port = serial.Serial(self.usb_info['COM'], self.printer_profile['baudrate'][0], timeout=1)
    #             if port.isOpen():
    #                 port.setDTR(1)
    #                 time.sleep(1)
    #                 port.setDTR(0)
    #                 port.close()
    #                 self.logger.info("Malfunctioning port %s was closed." % self.usb_info['COM'])
    #         except serial.SerialException as e:
    #             self.logger.info("Force close serial port failed with error %s" % e.message)
    #     else:
    #         self.logger.info("Force close serial port forbidden: \
    #                             not serial printer or force_port_close disabled in config")