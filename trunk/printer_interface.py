import time
import json
import base64
import logging
import threading

import http_client


class PrinterInterface(threading.Thread):

    DEFAULT_TIMEOUT = 10
    NO_COMMAND_SLEEP = 3

    def __init__(self, usb_info, user_token, app):
        self.usb_info = usb_info
        self.app = app
        self.user_token = user_token
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
            answer = http_client.send(http_client.package_printer_login, (self.user_token, self.usb_info))
            if answer:
                error = answer.get('error', None)
                # TODO: remove it when server will be okay
                if error and str(error['code']) == '0' and str(error['message']) == 'Unknow Hardware State downloading':
                    self.logger.error('Received wrong state downloading message from server. Stub logic.')
                    error = None
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
        if "baudrate" in self.printer_profile and not self.printer_profile.get("COM", False): # indication of serial printer, but no serial port
            self.sender_error = {"code": 11, "message": "No serial port for serial printer. No senders or printer firmware hanged."}
            return
        try:
            printer = printer_sender.Sender(self.printer_profile, self.usb_info, self.app)
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
        error = data_dict.get('error', None)
        if error:
            self.logger.warning("Server command came with errors %d %s" % (error['code'], error['message']))
        else:
            command = data_dict.get('command', None)
            if command:
                method = getattr(self.printer, command, None)
                if not method:
                    self.logger.warning("Unknown command: " + str(command))
                else:
                    number = data_dict.get('number', None)
                    if not number:
                        self.logger.error("No number field in servers answer")
                        raise RuntimeError("No number field in servers answer")
                    self.logger.info("Excecuting command number %i : %s" % (number, str(command)))
                    payload = data_dict.get('payload', None)
                    arguments = []
                    if payload:
                        arguments.append(payload)
                    if data_dict.get('is_link', False):
                        arguments.append(data_dict.get('is_link'))
                        #payload = http_client.download(payload)
                        #payload_file = http_client.async_download(payload)
                        #self.printer.start_download(payload)
                        #self.logger.info('File has been downloaded.')
                        # with open(payload_file, 'rb') as f:
                        #     payload = f.read()
                        if not payload:
                            self.sender_error = {"code": 777, "message": "Can't download file from storage"}
                            return { "number": number, "result": False }
                    elif "command" in ("gcodes", "binary_file"):
                        payload = base64.b64decode(payload)
                    try:
                        result = method(*arguments)
                    except Exception as e:
                        self.logger.error("Error while executing command %s, number %i.\t%s" % (command, number, e.message), exc_info=True)
                        self.sender_error = {"code": 9, "message": e.message}
                        result = False
                    ack = {"number": number, "result": bool(result or result == None)}
                    # to reduce needless return True, we assume that when method had return None, that is success
                    return ack

    def run(self):
        if self.connect_to_server():
            self.connect_to_printer()
        time.sleep(1)
        self.creation_time = time.time()
        while not self.stop_flag and self.printer:
            report = self.state_report()
            self.report = report # for web_interface
            message = [self.printer_token, report, self.acknowledge, self.sender_error]
            if not message[3] and self.printer and self.printer.error_code:
                message[3] = {"code": self.printer.error_code, "message": self.printer.error_message}
            self.logger.debug("Requesting with: %s" % str(message))
            if self.printer.is_operational():
                answer = http_client.send(http_client.package_command_request, message)
                self.logger.debug("Got answer: " + str(answer))
                if answer:
                    self.acknowledge = self.process_command_request(answer)
                    self.printer.error_code = None
                    self.printer.error_message = None
                    self.sender_error = None
                else:
                    time.sleep(self.NO_COMMAND_SLEEP)
            elif (time.time() - self.creation_time < self.printer_profile.get('start_timeout', self.DEFAULT_TIMEOUT)) and not self.stop_flag:
                time.sleep(0.1)
            else:
                self.logger.warning("Printer has become not operational:\n%s\n%s" % (str(self.usb_info), str(self.printer_profile)))
                answer = None
                while not answer and not self.stop_flag:
                    self.logger.debug("Trying to report error to server...")
                    answer = http_client.send(http_client.package_command_request, message)
                    error = answer.get('error', None)
                    if error:
                        self.logger.error("Server had returned error: " + str(error))
                        return
                    command_number = answer.get("number", False)
                    if command_number:
                        self.acknowledge = {"number": command_number, "result": False}
                    self.logger.debug("Could not execute command: " + str(answer))
                    time.sleep(2)
                self.sender_error = None
                self.acknowledge = None
                self.logger.debug("...done")
                self.stop_flag = True
        self.close_printer_sender()
        self.logger.info('Printer interface stop.')

    def get_printer_state(self):
        if self.printer.is_operational():
            if self.printer.is_paused():
                state = "paused"
            elif self.printer.is_printing():
                state = "printing"
            elif self.printer.is_downloading():
                state = "downloading"
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
            report["temps"] = self.printer.get_temps()
            report["target_temps"] = self.printer.get_target_temps()
            report["percent"] = self.printer.get_percent()
            if outer_state:
                report["state"] = outer_state
            else:
                report["state"] = self.get_printer_state()
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