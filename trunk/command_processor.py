import re
import sys
import base64
import logging
import http_client

# will return None if no errors (somewhat magical, but will work here)
def check_from_errors(data_dict):
    logger = logging.getLogger("app." + __name__)
    error = data_dict.get('error', None)
    if error:
        logger.warning("Server returned error %s:%s" % (error[0], error[1]))
        return error[0]

def process_user_login(data_dict):
    login = data_dict.get('login_hash', None)
    if not check_from_errors(data_dict):
        if login:
            return login
    logger = logging.getLogger('app.' + __name__)
    logger.warning("Error processing user_login response: " + str(data_dict))

def process_printer_login(data_dict):
    pass

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

def process_job_request(printer_interface, data_dict):
    logger = logging.getLogger("app." + __name__)
    job = data_dict.get('job', None)
    logger.debug("Job=%s" % job)
    if job:
        if 'begin' in job or 'reset' in job:
            match = re.match('.+gcode_count=(\d+)', job)
            if match is not None:
                gcode_count = int(match.group(1))
            else:
                gcode_count = sys.maxint
            printer_interface.begin(gcode_count)
        elif job == '/pause':
            printer_interface.pause()
        elif job == '/resume':
            printer_interface.resume()
        elif job == '/cancel':
            printer_interface.cancel()
        elif job == '/emergency_stop':
            printer_interface.emergency_stop()
        else:
            logger.info('GCodes received')
            if printer_interface.profile['print_from_binary']:
                logger.info('Enqueue binary file')
                printer_interface.enqueue(job)
            else:
                try:
                    lines = base64.b64decode(job).split('\n')
                    logger.info("GCode count: " + str(len(lines)))
                    if len(lines) < 5:
                        logger.info("GCodes:" + str(lines))
                    printer_interface.enqueue(lines)
                except TypeError:
                    logger.critical("Can't decode GCodes, must be base64")
    else:
        logger.warning("Error processing job: " + str(data_dict))

def process_login_request(data_dict):
    logger = logging.getLogger("app." + __name__)
    printer_type = data_dict.get('printer_type_name', None)
    if printer_type:
        return printer_type


