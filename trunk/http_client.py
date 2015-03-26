import os
import re
#import ssl
import json
import uuid
import httplib
import logging
import tempfile
import requests

streamer_prefix = "/streamerapi"
user_login_path = streamer_prefix + "/user_login"
printer_login_path = streamer_prefix + "/printer_login"
command_path = streamer_prefix + "/command"
camera_path = streamer_prefix + "/camera" #json['image': base64_image ]
cloudsync_path = "/autoupload"
token_send_logs_path = "/oldliveview/sendLogs" #rename me!
#token_send_logs_path = streamer_prefix + '/sendLogs' # TODO: test me
get_last_version_path = '/a/lastclientver/get'

import config

MACADDR = hex(uuid.getnode())
CONNECTION_TIMEOUT = 6
URL = config.config['URL']
AUX_URL = config.config['AUX_URL']
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

#packagers

def package_user_login(username, password, platform, error = None):
    data = { 'login': {'user': username, 'password': password}, 'host_mac': MACADDR, "platform": platform}
    if error:
        data['error'] = error
    return json.dumps(data), user_login_path

def package_printer_login(user_token, printer_profile, error = None):
    data = { 'user_token': user_token, 'printer': printer_profile }
    if error:
        data['error'] = error
    return json.dumps(data), printer_login_path

def package_command_request(printer_token, state, acknowledge=None, error = None):
    data = { 'printer_token': printer_token, 'report': state, 'error': error }
    if acknowledge:
        data['command_ack'] = acknowledge
    if error:
        data['error'] = error
    return json.dumps(data), command_path

def package_camera_send(user_token, camera_number, camera_name, data, error = None):
    data = {'user_token': user_token, 'camera_number': camera_number, 'camera_name': camera_name, 'file_data': data, 'host_mac': MACADDR}
    if error:
        data['error'] = error
    return json.dumps(data), camera_path

def package_cloud_sync_upload(token, file_data, file_name):
    data = { 'user_token': token, 'file_data': file_data}
    return json.dumps(data), cloudsync_path

#senders

def connect(URL, https_mode = config.config['HTTPS']):
    logger = logging.getLogger('app.' +__name__)
    #logger.debug("{ Connecting...")
    try:
        if https_mode:
            #if ssl_has_context:
            #    no_verify_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
            #    no_verify_context.verify_mode = ssl.CERT_NONE
            #else:
            #    no_verify_context = None
            connection = httplib.HTTPSConnection(URL, port = 443, timeout = CONNECTION_TIMEOUT)
        else:
            connection = httplib.HTTPConnection(URL, port = 80, timeout = CONNECTION_TIMEOUT)
    except httplib.error as e:
        logger.info("Error during HTTP connection: " + str(e))
        #logger.debug("...failed }")
        logger.warning("Warning: connection to %s failed." % URL)
    else:
        #logger.debug("...success }")
        return connection

def post_request(connection, payload, path, headers=None):
    if not headers:
        headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))}
    return request(connection, payload, path, 'POST', headers)

def get_request(connection, payload, path, headers={}):
    return request(connection, payload, path, 'GET', headers)

def request(connection, payload, path, method, headers):
    logger = logging.getLogger('app.' +__name__)
    #logger.debug("{ Requesting...")
    try:
        connection.request(method, path, payload, headers)
        resp = connection.getresponse()
    except Exception as e:
        logger.info("Error during HTTP request:" + str(e))
    else:
        #logger.debug("Request status: %s %s" % (resp.status, resp.reason))
        try:
            received = resp.read()
        except httplib.error as e:
            logger.debug("Error reading response: " + str(e))
        else:
            if resp.status == httplib.OK and resp.reason == "OK":
                connection.close()
                #logger.debug("...success }")
                return received
            else:
                logger.warning("Error: server response is not 200 OK\nMessage:%s" % received)
        finally:
            connection.close()
    logger.warning("Warning: http request failed!")

def send(packager, payloads):
    if type(payloads) not in (tuple, list):
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
    logger.info("Downloading payload from " + url)
    try:
        domain, path = match.groups()
    except AttributeError:
        logger.warning("Unparsable link: " + url)
    else:
        https_mode = url.startswith("https")
        connection = connect(domain, https_mode)
        if connection:
            logger.debug("Got connection to download server")
            return get_request(connection, None, path)
        else:
            logger.warning("Error: no connection to download server")


class File_Downloader:
    def __init__(self, base_sender):
        self.max_download_retry = config.config["max_download_retry"]
        self.base_sender = base_sender
        self.percent = None
        self.logger = logging.getLogger('app.' + "file_downloader")

    def get_percent(self):
        return self.percent

    def async_download(self, url):
        self.logger.info("Downloading payload from " + url)
        tmp_file = tempfile.NamedTemporaryFile(mode='wb', delete=False, prefix='3dprinteros-', suffix='.gcode')
        resume_byte_pos = 0
        retry = 0
        while retry < self.max_download_retry:
            resume_header = {'Range': 'bytes=%d-' % resume_byte_pos}
            self.logger.info("Connecting to " + url)
            try:
                r = requests.get(url, headers = resume_header, stream=True, timeout = CONNECTION_TIMEOUT)
            except Exception as e:
                self.logger.warning("Error while connecting to: %s\nError: %s" % (url, str(e)))
                self.base_sender.error_code = 66
                self.base_sender.error_message = "Unable to open download link: " + str(e)
            else:
                self.logger.info("Successful connection to " + url)
                download_length = int(r.headers.get('content-length', 0))
                self.logger.info('Downloading: %d bytes' % download_length)
                if download_length:
                    if not self.percent:
                        self.percent = 0 # percent will be still None if request return an error
                    downloaded_size = self.chunk_by_chunk(r, tmp_file, download_length)
                    r.close()
                    if downloaded_size:
                        resume_byte_pos += downloaded_size
                        self.logger.info("Download length %d bytes" % download_length)
                        self.logger.info("Downloaded %d bytes" % downloaded_size)
                        if downloaded_size == download_length:
                            tmp_file.close()
                            return tmp_file.name
                    else:
                        return None
            retry += 1
            self.logger.warning(str(retry) + " retry/resume attempt to download " + url)
        self.base_sender.error_code = 67
        self.base_sender.error_message = "Max connection retries reached while downloading"
        tmp_file.close()
        os.remove(tmp_file.name)

    def chunk_by_chunk(self, request, tmp_file, download_length):
        # Taking +1 byte with each chunk to compensate file length tail less than 100 bytes when dividing by 100
        percent_length = download_length / 100 + 1
        total_size = 0
        for chunk in request.iter_content(percent_length):
            if not self.base_sender.downloading_flag or self.base_sender.stop_flag:
                self.logger.info('Stopping downloading process')
                return None
            self.percent += 1
            total_size += len(chunk)
            self.logger.info('File downloading : %d%%' % self.percent)
            try:
                tmp_file.write(chunk)
            except Exception as e:
                self.logger.error('Error while downloading file:\n%s' % e.message)
                self.base_sender.error_code = 66
                self.base_sender.error_message = 'Cannot download file' + str(e)
                return
        return total_size

