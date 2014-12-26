import re
import json
import httplib
import logging
from hashlib import md5

CONNECTION_TIMEOUT = 10
URL = "service1.3dprinteros.com"
user_login_uri = "/user_login"
printer_login_uri = "/printer_login"
command_uri = "/command"
cloudsync_uril = "/cloudsync_upload"
token_jobs_path = "/getJobs"
token_login_path = "/sendRequestToken" #json['token': token]
token_camera_path = "/image" #json['image': base64_image ]


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
    return json.dump(data), user_login_uri

def package_printer_login(login_hash, printer_profile, error=[None,None]):
    data = { 'login_hash': login_hash, 'printer': printer_profile, 'error': error }
    return json.dump(data), printer_login_uri

def package_command_request(printer_session_hash, state, error=[None,None]):
    data = { 'printer_session_hash': printer_session_hash, 'state': state, 'error': error }
    return json.dump(data), command_uri

def package_cloud_sync_upload(token, file_data, file_name):
    data = { 'token': token, 'file_data': file_data, 'file_name': file_name }
    return json.dump(data), cloudsync_uril

#TODO turn on https
def connect(URL):
    logger = logging.getLogger('app.' +__name__)
    try:
        connection = httplib.HTTPSConnection(URL, port = 443, timeout = CONNECTION_TIMEOUT)#, cert_file=utils.cert_file_path)
    except httplib.error as e:
        logger.info("Error during HTTP connection: " + str(e))
    else:
        return connection
def post_request(connection, payload, path, headers=None):
    if not headers:
        headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))}
    return request(connection, payload, path, 'POST', headers)

def get_request(connection, payload, path, headers=""):
    return request(connection, payload, path, 'GET', headers)

def request(connection, payload, path, method, headers):
    logger = logging.getLogger('app.' +__name__)
    try:
        connection.request(method, path, payload, headers)
        resp = connection.getresponse()
    except httplib.error as e:
        logger.info("Error during HTTP request:" + str(e))
    else:
        logger.debug("Request status: %s %s" % (resp.status , resp.reason))
        if resp.status == httplib.OK and resp.reason == "OK":
            try:
                received = resp.read()
                connection.close()
            except httplib.error as e:
                logger.debug("Error reading response: " + str(e))
                connection.close()
            else:
                return received

def send(packager, payloads):
    if type(payloads) != tuple:
        payloads = [ payloads ]
    connection = connect(URL)
    if connection:
        request_body, path = packager(*payloads)
        json_answer = post_request(connection, request_body, path)
        if json_answer:
            return load_json(json_answer)

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    import utils
    token = utils.read_token()
    print send(token_login, token)

def download(url):
    logger = logging.getLogger('app.' +__name__)
    domain_path_re = re.compile("https?:\/\/(.+)(\/.*)")
    match = domain_path_re.match(url)
    try:
        domain, path = match.groups()
    except AttributeError:
        logger.warning("Unparsable link: " + url)
    else:
        connection = connect(domain)
        if connection:
            return post_request(connection, "", path)


if __name__ == '__main__':
    import command_processor

    user = ''
    password = ''
    profile = '[{"extruder_count": 1, "baudrate": [250000, 115200], "vids_pids": [["0403", "6001"], ["4745", "0001"],\
        ["2341", "0042"]], "name": "Ultimaker 2", "VID": "2341", "PID": "0042", \
         "end_gcodes": ["M107", "M104 S0", "M140 S0", "G91", "G1 E-5 F300", "G28 X0 Y0 Z0", "M84", "G90", "M25"],\
          "driver": "printrun_printer", "reconnect_on_cancel": true, "Product": null, "SNR": null,\
           "COM": "/dev/ttyACM0", "Manufacturer": null, "force_port_close": true, "print_from_binary": false},\
            {"extruder_count": 1, "baudrate": [250000, 115200], "vids_pids": [["16C0", "0483"], ["2341", "0042"]],\
             "name": "Marlin Firmware", "VID": "2341", "PID": "0042", "end_gcodes": [], "driver": "printrun_printer",\
              "reconnect_on_cancel": false, "Product": null, "SNR": null, "COM": "/dev/ttyACM0", "Manufacturer": null,\
               "force_port_close": true, "print_from_binary": false}]'
    while True:
        user_choice = raw_input('Welcome to test menu:\n' \
                                'Type 1 for - User login\n' \
                                'Type 2 for - Printer login\n' \
                                'Type 3 for - Command request\n')
        if  '1' in user_choice:
            answer = send(package_users_login, user, password)
            processor = command_processor.process_user_login
        elif '2' in user_choice:
            answer = send(package_users_login, profile)
            processor = command_processor.process_printer_login
        elif '3' in user_choice:
            answer = send(package_users_login, profile)
            processor = command_processor.process_command_request
        else:
            answer =  'Invalid choice'
        print user_choice
        print 'Raw answer:' + str(answer)
        print command_processor

