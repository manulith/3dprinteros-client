import collections

class BaseSender:

    def __init__(self, profile, usb_info):
        self.stop_flag = False
        self.profile = profile
        self.usb_info = usb_info
        self.error_code = None
        self.error_message = ''
        self.temps = [0,0]
        self.target_temps = [0,0]
        self.total_gcodes = None
        self.buffer = collections.deque()
        #self._position = [0.00,0.00,0.00]

    def get_temps(self):
        return self.temps

    def get_target_temps(self):
        return self.target_temps

    def pause(self):
        self.pause_flag = True

    def unpause(self):
        self.pause_flag = False

    def close(self):
        self.stop_flag = True

    def get_error_code(self):
        return self.error_code

    def get_error_message(self):
        return self.error_message

    def is_error(self):
        return self.error_code != None

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

    def is_operational(self):
        return False