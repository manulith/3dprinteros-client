import re
import sys
import base64
import string
import logging
import http_client

# will return None if no errors (somewhat magical, but will work here)
def check_from_errors(data_dict):
    logger = logging.getLogger("app." + __name__)
    error = data_dict.get('error', None)
    if error:
        logger.warning("Server returned error %s:%s" % (error[0], error[1]))
        return error[0]

# def process_user_login(data_dict):
#     login = data_dict.get('user_token', None)
#     if not check_from_errors(data_dict):
#         if login:
#             return login
#     logger = logging.getLogger('app.' + __name__)
#     logger.warning("Error processing user_login response: " + str(data_dict))

def process_printer_login(data_dict):
    login = data_dict.get('printer_token', None)
    if not check_from_errors(data_dict):
        if login:
            return login
    logger = logging.getLogger('app.' + __name__)
    logger.warning("Error processing user_login response: " + str(data_dict))

def process_command_request(printer_interface, data_dict):
    logger = logging.getLogger("app." + __name__)
    number = data_dict.get('number', None)
    if number:
        logger.info("Processing command number %i" % number)
    if not check_from_errors(data_dict):
        command = data_dict.get('command', None)
        if command:
            if hasattr(printer_interface.printer, command):
                method = printer_interface.getattr('command')
                payload = data_dict.get('payload', None)
                if data_dict.get('is_link', False):
                    payload = http_client.download(payload)
                if payload:
                    method(payload)
                else:
                    method()
                return True
    logger.warning("Error processing command: " + str(data_dict))

def process_login_request(data_dict):
    logger = logging.getLogger("app." + __name__)
    printer_type = data_dict.get('printer_type_name', None)
    if printer_type:
        return printer_type

def remove_illegal_symbols(data):
    count = 0
    length = len(data)
    while count < len(data):
        if not data[count] in string.printable:
            data.replace(data[count], "")
        count += 1
    return data

def remove_corrupted_lines(lines):
    for line in lines:
        if not line or line in string.whitespace:
            lines.remove(line)
    return lines

if __name__ == "__main__":
    import time
    with open("/tmp/test.gcode", "r") as f:
        gcodes = f.read()
    start_time = time.time()
    result = remove_illegal_symbols(gcodes)
    end_time = time.time()
    print result
    print "process time", end_time - start_time
