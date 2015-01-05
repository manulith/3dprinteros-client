import re
import json
import httplib
import logging
import requests
from hashlib import md5

CONNECTION_TIMEOUT = 6
URL = "service1.3dprinteros.com"
user_login_path = "/user_login"
printer_login_path = "/printer_login"
command_path = "/command"
cloudsync_path = "/cloudsync_upload"
token_jobs_path = "/getJobs"
token_login_path = "/sendRequestToken" #json['token': token]
token_camera_path = "/image" #json['image': basebase64_image ]
token_send_logs_path = "/sendLogs"

domain_path_re = re.compile("https?:\/\/(.+)(\/.*)")

def load_json(jdata):
    logger = logging.getLogger('app.' +__name__)
    try:
        data = json.loads(jdata)
    except ValueError as e:
        logger.debug("Received data is not valid json: " + e.message)
    else:
        if type(data) == dict and data:
            return data
        else:
            logger.error("Data should be dictionary: " + str(data))

def md5_hash(text):
    hash = md5(text)
    hex_str_hash = hash.hexdigest()
    return hex_str_hash

def token_login(token):
    data = { 'token': token }
    return json.dumps(data), token_login_path

# at same time it sends status report
def token_job_request(token, state):
    #state = app.App().state
    data = { 'token': token, "fullbuffer": False, "state": state } #TODO get info about fullbuffers
    return json.dumps(data), token_jobs_path

def token_camera_request(token, jpg_image):
    # right now images are base64 encoded. don't ask me why.
    data = { 'token': token, 'image': jpg_image } #TODO get info about fullbuffers
    return json.dumps(data), token_camera_path

def package_users_login(username, password, error=[None,None]):
    user_hash = md5_hash(username)
    pass_hash = md5_hash(password)
    data = { 'login': {'user': user_hash, 'password': pass_hash}, 'error': error}
    return json.dumps(data), user_login_path

def package_printer_login(login_hash, printer_profile, error=[None,None]):
    data = { 'login_hash': login_hash, 'printer': printer_profile, 'error': error }
    return json.dumps(data), printer_login_path

def package_command_request(printer_session_hash, state, error=[None,None]):
    data = { 'printer_session_hash': printer_session_hash, 'state': state, 'error': error }
    return json.dumps(data), command_path

def package_cloud_sync_upload(token, file_data, file_name):
    data = { 'token': token, 'file_data': file_data, 'file_name': file_name }
    return json.dumps(data), cloudsync_path

#TODO turn on https
def connect(URL):
    logger = logging.getLogger('app.' +__name__)
    logger.debug("{ Connecting...")
    try:
        connection = httplib.HTTPSConnection(URL, port = 443, timeout = CONNECTION_TIMEOUT)#, cert_file=utils.cert_file_path)
    except httplib.error as e:
        logger.info("Error during HTTP connection: " + str(e))
        logger.debug("...failed }")
    else:
        logger.debug("...success }")
        return connection

def post_request(connection, payload, path, headers=None):
    if not headers:
        headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))}
    return request(connection, payload, path, 'POST', headers)

def get_request(connection, payload, path, headers=""):
    return request(connection, payload, path, 'GET', headers)

def request(connection, payload, path, method, headers):
    logger = logging.getLogger('app.' +__name__)
    logger.debug("{ Requesting...")
    try:
        connection.request(method, path, payload, headers)
        resp = connection.getresponse()
    except Exception as e:
        logger.info(("Error during HTTP request:" + str(e)))
    else:
        logger.debug("Request status: %s %s" % (resp.status , resp.reason))
        if resp.status == httplib.OK and resp.reason == "OK":
            try:
                received = resp.read()
            except httplib.error as e:
                logger.debug("Error reading response: " + str(e))
                connection.close()
            else:
                connection.close()
                logger.debug("...success }")
                return received
    logger.debug("...failed }")

def send(packager, payloads):
    if type(payloads) != tuple:
        payloads = [ payloads ]
    connection = connect(URL)
    print payloads
    if connection:
        request_body, path = packager(*payloads)
        json_answer = post_request(connection, request_body, path)
        if json_answer:
            return load_json(json_answer)

def download(url):
    logger = logging.getLogger('app.' +__name__)
    match = domain_path_re.match(url)
    try:
        domain, path = match.groups()
    except AttributeError:
        logger.warning("Unparsable link: " + url)
    else:
        connection = connect(domain)
        if connection:
            return post_request(connection, "", path)

def multipart_upload(url, payload, file_obj=None):
    if file_obj:
        f = {"file": file_obj}
        r = requests.post(url, data=payload, files=f)
    else:
        r = requests.post(url, data=payload)
    print 'Response: ' + r.text
    return r.status_code == 200

if __name__ == '__main__':
    import command_processor
    import printer_interface
    from app import App
    App.get_logger()
    user = "Nobody"
    password = "qwert"
    profile = json.loads('{"extruder_count": 1, "baudrate": [250000, 115200], "vids_pids": [["16C0", "0483"], ["2341", "0042"]], "name": "Marlin Firmware", "VID": "2341", "PID": "0042", "end_gcodes": [], "driver": "printrun_printer", "reconnect_on_cancel": false, "Product": null, "SNR": null, "COM": "/dev/ttyACM0", "Manufacturer": null, "force_port_close": false, "print_from_binary": false}')
    pr_int = printer_interface.PrinterInterface(profile)
    while True:
        user_login = ""
        printer_login = ""
        user_choice = raw_input('Welcome to test menu:\n' \
                                'Type 1 for - User login\n' \
                                'Type 2 for - Printer login\n' \
                                'Type 3 for - Command request\n')
        if  '1' in user_choice:
            answer = send(package_users_login, (user, password))
            if answer:
                processor = command_processor.process_user_login
                result = processor(answer)
                user_login = result
            else:
                print 'No answer'
        elif '2' in user_choice:
            if not user_login:
                print "!First you need to login as user"
            else:
                answer = send(package_printer_login, (user_login, profile))
                if answer:
                    processor = command_processor.process_printer_login
                    result = processor(answer)
                    printer_login = result
                else:
                    print 'No answer'
        elif '3' in user_choice:
            if not printer_login:
                print "!First you need to login printer"
            else:
                answer = send(package_command_request, printer_login)
                if answer:
                    processor = command_processor.process_command_request
                    result = processor(user_choice)
                else:
                    print 'No answer'
        else:
            print 'Invalid choice'

        try:
            print 'Raw answer: ' + str(answer)
            print 'Processed answer: ' + str(result)
        except:
            pass


