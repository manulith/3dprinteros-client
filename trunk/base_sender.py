import collections
import logging

class BasePrinter:

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