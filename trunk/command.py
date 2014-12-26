import json
import threading

class Command(threading.Thread):

    #legend: 0 is no printer or unknown state, positive values is "good" states, negative are errors.
    # 15 indicates end of job without errors.

    STATE_UNKNOWN_ERROR = -15
    STATE_PRINTER_INTERNAL_ERROR = -5
    STATE_UNKNOWN_INTERNAL_PRINTER_ERROR = -4
    STATE_COMMUNICATION_WITH_PRINTER_ERROR = -3
    STATE_DRIVERS_BACKEND_ERROR = -2
    STATE_OUR_DRIVER_ERROR = -1
    STATE_UNKNOWN_NO_PRINTER = 0
    STATE_RECIEVED = 1
    STATE_WAITING = 2
    STATE_RUNNING = 3
    STATE_HANG = 4
    STATE_DONE_WITH_ERROR = 14
    STATE_DONE_WITHOUT_ERRORS = 15

    def __init__(self, printer_interface, json_proto_command):
        try:
            proto = json.loads(json_proto_command)
        except: #TODO place json exception here
            self.state = 'JSON_FAULT'
        self.number = proto['number']
        self.command_name = proto['command']
        self.method = printer_interface.getattr(self.command_name)
        self.data = proto['data']
        self.result = None
        self.error_string = ''
        self.state = None

    def run(self):
        self.state = self.STATE_RUNNING
        try:
            result = self.method(self.data)
        except Exception:
            self.error_string = self.printer_interface.get_error()
            self.state = self.STATE_UNKNOWN_ERROR
        else:
            self.state = self.STATE_DONE_WITHOUT_ERRORS
