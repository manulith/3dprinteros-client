import re
import json
import httplib
import logging
import requests
import uuid

import config

MACADDR = hex(uuid.getnode())
CONNECTION_TIMEOUT = 6
URL = config.config['URL']
AUX_URL = config.config['AUX_URL']
HTTPS_FLAG = config.config['HTTPS']
streamer_prefix = "/streamerapi"
user_login_path = streamer_prefix + "/user_login"
printer_login_path = streamer_prefix + "/printer_login"
command_path = streamer_prefix + "/command"
cloudsync_path = "/autoupload"

token_camera_path = "/oldliveview/setLiveView" #json['image': base64_image ]
token_send_logs_path = "/oldliveview/sendLogs"

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

def package_user_login(username, password, error = {}):
    logger = logging.getLogger("app." + __name__)
    logger.debug("Login as %s %s" % (username, password))
    data = {'login': {'user': username, 'password': password}, 'error': error, 'host_mac': MACADDR}
    return json.dumps(data), user_login_path

def package_printer_login(user_token, printer_profile, error):
    data = { 'user_token': user_token, 'printer': printer_profile, 'error': error }
    return json.dumps(data), printer_login_path

def package_command_request(printer_token, state, error={}):
    data = { 'printer_token': printer_token, 'state': state, 'error': error }
    return json.dumps(data), command_path

def package_cloud_sync_upload(token, file_data, file_name):
    data = { 'user_token': token, 'file_data': file_data}
    return json.dumps(data), cloudsync_path

def connect(URL):
    logger = logging.getLogger('app.' +__name__)
    logger.debug("{ Connecting...")
    try:
        if HTTPS_FLAG:
            connection = httplib.HTTPSConnection(URL, port = 443, timeout = CONNECTION_TIMEOUT)
        else:
            connection = httplib.HTTPConnection(URL, port = 80, timeout = CONNECTION_TIMEOUT)
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
        logger.debug("...failed }")
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
    logger.debug("...nothing to do }")

def send(packager, payloads):
    if type(payloads) != tuple:
        payloads = [ payloads ]
    connection = connect(URL)
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
    logger = logging.getLogger('app.' +__name__)
    kwarg = {"data": payload}
    if file_obj:
        kwarg.update({"file": file_obj})
    try:
        r = requests.post(url, **kwarg)
    except Exception as e:
        logger.debug("Error while uploading to server: %s" % str(e))
    else:
        print 'Response: ' + r.text
        return r.status_code == 200