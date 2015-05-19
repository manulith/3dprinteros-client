import time
import json
import logging
import threading

import http_client

class PrinterInterface(threading.Thread):

    DEFAULT_TIMEOUT = 10
    COMMAND_REQUEST_SLEEP = 1.5

    def __init__(self, usb_info, user_token):
        self.usb_info = usb_info
        self.user_token = user_token
        self.http_client = http_client.HTTPClient(True)
        self.printer = None
        self.printer_token = None
        self.acknowledge = None
        self.sender_error = None
        self.stop_flag = False
        self.report = None
        self.logger = logging.getLogger('app.' + __name__)
        self.logger.info('New printer interface for %s' % str(usb_info))
        super(PrinterInterface, self).__init__()

    def connect_to_server(self):
        self.logger.info("Connecting to server with printer: %s" % str(self.usb_info))
        while not self.stop_flag:
            answer = self.http_client.pack_and_send('printer_login', self.user_token, self.usb_info)
            if answer:
                error = answer.get('error')
                if error:
                    self.logger.warning("Error while login %s:" % str((self.user_token, self.usb_info)))
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

    def connect_to_printer(self):
        printer_sender = __import__(self.printer_profile['sender'])
        self.logger.info("Connecting with profile: " + str(self.printer_profile))
        if "baudrate" in self.printer_profile and self.printer_profile.get("baudrate") and not self.printer_profile.get("COM"): # indication of serial printer, but no serial port
            self.logger.warning('No serial port for serial printer')
            self.sender_error = {"code": 11, "message": "No serial port for serial printer. No senders or printer firmware hanged."}
            self.stop_flag = True
            return
        try:
            printer = printer_sender.Sender(self.printer_profile, self.usb_info)
        except RuntimeError as e:
            self.logger.warning("Can't connect to printer %s %s\nReason:%s" % (self.printer_profile['name'], str(self.usb_info), e.message))
            self.sender_error = {"code": 19,
                                 "message": "Error group - Can't connect to printer: " + e.message}
        except Exception as e:
            self.logger.warning("Error connecting to %s" % self.printer_profile['name'], exc_info=True)
            self.sender_error = {"code": 29,
                                 "message": "Error group - unknown error while connecting to printer: " + e.message}
        else:
            self.printer = printer
            self.logger.info("Successful connection to %s!" % (self.printer_profile['name']))

    def process_command_request(self, data_dict):
        error = data_dict.get('error')
        if error:
            self.logger.warning("Server return error on command request. Error code: %d. Message: %s" %
                                (error['code'], error['message']))
        else:
            command = data_dict.get('command')
            if command:
                method = getattr(self.printer, command, None)
                if not method:
                    self.logger.warning("Unknown command: " + str(command))
                    self.sender_error = {"code": 40, "message": "Unknown command " + str(command)}
                else:
                    number = data_dict.get('number')
                    if not number:
                        self.logger.error("No number field in servers answer")
                        raise RuntimeError("No number field in servers answer")
                    self.logger.info("Executing command number %i : %s" % (number, str(command)))
                    payload = data_dict.get('payload')
                    arguments = []
                    if payload:
                        arguments.append(payload)
                    if data_dict.get('is_link'):
                        arguments.append(data_dict.get('is_link'))
                    try:
                        result = method(*arguments)
                    except Exception as e:
                        self.logger.error("Error while executing command %s, number %i.\t%s" % (command, number, e.message), exc_info=True)
                        self.sender_error = {"code": 9, "message": e.message}
                        result = False
                    ack = {"number": number, "result": bool(result or result == None)}
                    # to reduce needless return True, we assume that when method had return None, that is success
                    return ack

    def form_message(self):
        self.report = self.state_report()
        return [self.printer_token, self.report, self.acknowledge, self.sender_error]

    def run(self):
        if self.connect_to_server():
            self.connect_to_printer()
        time.sleep(0.1)
        while not self.stop_flag and self.printer:
            message = self.form_message()
            if self.printer.error_code:
                message[3] = {"code": self.printer.error_code, "message": self.printer.error_message}
            self.printer.error_code = None
            self.printer.error_message = None
            self.sender_error = None
            self.logger.debug("Requesting with: %s" % str(message))
            if self.printer.is_operational():
                answer = self.http_client.pack_and_send('command', *message)
                self.logger.debug("Server answer: " + str(answer))
                if answer:
                    self.acknowledge = self.process_command_request(answer)
            else:
                self.report_error()
            time.sleep(1.5)
        self.close_printer_sender()
        self.logger.info('Printer interface stop.')

    def report_error(self):
        self.logger.warning("Printer has become not operational:\n%s\n%s" % (str(self.usb_info), str(self.printer_profile)))
        answer = None
        while not answer and not self.stop_flag:
            self.logger.debug("Trying to report error to server...")
            answer = self.http_client.pack_and_send('command', *self.form_message())
            error = answer.get('error', None)
            if error:
                self.logger.error("Server had returned error: " + str(error))
                break
            command_number = answer.get("number", False)
            if command_number:
                self.acknowledge = {"number": command_number, "result": False}
            self.logger.debug("Could not execute command: " + str(answer))
            time.sleep(2)
        self.sender_error = None
        self.acknowledge = None
        self.logger.debug("...done")
        self.stop_flag = True

    def get_printer_state(self):
        if self.printer.is_operational():
            if self.printer.is_paused():
                state = "paused"
            elif self.printer.is_downloading():
                state = "downloading"
            elif self.printer.is_printing():
                state = "printing"
            else:
                state = "ready"
        else:
            if self.sender_error or self.printer.error_code:
                state = "error"
            else:
                state = "connecting"
        return state

    def state_report(self, outer_state=None):
        if self.printer:
            report = {}
            if outer_state:
                report["state"] = outer_state
            else:
                report["state"] = self.get_printer_state()
            report["percent"] = self.printer.get_percent()
            report["temps"] = self.printer.get_temps()
            report["target_temps"] = self.printer.get_target_temps()
            report["line_number"] = self.printer.get_current_line_number()
            report["coords"] = self.printer.get_position()
            return report

    def close_printer_sender(self):
        if self.printer:
            self.logger.info('Closing ' + str(self.printer_profile))
            self.printer.close()
            self.printer = None
            self.logger.info('...closed.')

    def close(self):
        self.logger.info('Closing printer interface of: ' + str(self.usb_info))
        self.stop_flag = True