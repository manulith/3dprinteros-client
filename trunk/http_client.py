import os
import re
import json
import uuid
import httplib
import logging
import tempfile
import requests
import time

import config
import version

CONNECTION_TIMEOUT = 6

class HTTPClient:

    URL = config.config['URL']
    HTTPS_MODE = config.config['HTTPS']
    streamer_prefix = "/streamerapi"
    user_login_path = streamer_prefix + "/user_login"
    printer_login_path = streamer_prefix + "/printer_login"
    command_path = streamer_prefix + "/command"
    camera_path = streamer_prefix + "/camera" #json['image': base64_image ]
    cloudsync_path = "/autoupload"
    token_send_logs_path = streamer_prefix + "/sendLogs"
    get_last_version_path = '/a/lastclientver/get'
    domain_path_re = re.compile("https?:\/\/(.+)(\/.*)")
    MACADDR = hex(uuid.getnode())

    MAX_HTTP_FAILS = 5

    def __init__(self, keep_connection_flag = False, debug = False):
        self.logger = logging.getLogger('app.' +__name__)
        if debug:
            self.logger.setLevel('DEBUG')
        else:
            self.logger.setLevel('INFO')
        self.keep_connection_flag = keep_connection_flag
        self.connection = None
        self.http_fails_count = 0
        self.error_code = None
        self.error_message = ''

    def process_error(self, error_code, error_message):
        self.error_code = error_code
        self.error_message = error_message
        self.logger.warning('HTTP Client error ' + str(self.error_code) + ': ' + self.error_message)

    def connect(self):
        self.logger.debug("{ Connecting...")
        try:
            if self.HTTPS_MODE:
                connection = httplib.HTTPSConnection(self.URL, port = 443, timeout = CONNECTION_TIMEOUT)
            else:
                connection = httplib.HTTPConnection(self.URL, port = 80, timeout = CONNECTION_TIMEOUT)
        except httplib.error as e:
            self.process_error(5, "Error during HTTP connection: " + str(e))
            self.logger.debug("...failed }")
            self.logger.warning("Warning: connection to %s failed." % self.URL)
        else:
            self.logger.debug("...success }")
            self.connection = connection
            return self.connection

    def load_json(self, jdata):
        try:
            data = json.loads(jdata)
        except ValueError as e:
            self.process_error(2, "Received data is not valid json: " + e.message)
        else:
            if type(data) == dict and data:
                return data
            else:
                self.process_error(3, "Data should be dictionary: " + str(data))

    def request(self, method, connection, path, payload, headers=None):
        self.logger.debug("{ Requesting...")
        if headers is None:
            headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))}
            if self.keep_connection_flag:
                headers["Connection"] = "keep-alive"
        try:
            connection.request(method, path, payload, headers)
            resp = connection.getresponse()
        except Exception as e:
            self.process_error(6,"Error during HTTP request:" + str(e))
        else:
            #self.logger.debug("Request status: %s %s" % (resp.status, resp.reason))
            try:
                received = resp.read()
            except httplib.error as e:
                self.process_error(7, "Error reading response: " + str(e))
            else:
                if resp.status == httplib.OK and resp.reason == "OK":
                    self.logger.debug("...success }")
                    return received
                else:
                    self.process_error(8, "Error: server response is not 200 OK\nMessage:%s" % received)
        self.logger.debug("...failed }")
        self.logger.warning("Warning: HTTP request failed!")

    def pack_and_send(self, target, *payloads):
        path, packed_message = self.pack(target, *payloads)
        return self.send(path, packed_message)

    def send(self, path, data):
        json_answer = None
        while not json_answer:
            if not self.connection or not self.keep_connection_flag:
                self.connection = self.connect()
            if self.connection:
                json_answer = self.request("POST", self.connection, path, data)
                if json_answer:
                    self.http_fails_count = 0
                    if not self.keep_connection_flag:
                        self.connection.close()
                        self.connection = None
                    return self.load_json(json_answer)
                else:
                    time.sleep(1)
                    self.connection = None
            else:
                time.sleep(0.5)
                self.http_fails_count += 1
                if self.http_fails_count > self.MAX_HTTP_FAILS:
                    self.process_error(9, 'HTTP connection error - max retry.')
                    break
        return None

    def pack(self, target, *payloads):
        if target == 'user_login':
            data = { 'login': {'user': payloads[0], 'password': payloads[1]}, "platform": payloads[2], 'host_mac': self.MACADDR, "version": version.version }
            path = self.user_login_path
        elif target == 'printer_login':
            data = { 'user_token': payloads[0], 'printer': payloads[1], "version": version.version, "data_time": time.ctime() }
            path = self.printer_login_path
        elif target == 'command':
            data = { 'printer_token': payloads[0], 'report': payloads[1], 'command_ack': payloads[2], 'job_id': payloads[3], 'printer_success': payloads[4]}
            if data['command_ack'] == None:
                data.pop('command_ack')
            if data['job_id'] == None:
                data.pop('job_id')
            if data['printer_success'] == None:
                data.pop('printer_success')
            path = self.command_path
        elif target == 'camera':
            data = {'user_token': payloads[0], 'camera_number': payloads[1], 'camera_name': payloads[2], 'file_data': payloads[3], 'host_mac': self.MACADDR }
            path = self.camera_path
        elif target == 'cloudsync':
            data = { 'user_token': payloads[0], 'file_data': payloads[1]}
            path = self.cloudsync_path
        else:
            self.process_error(4, 'No such target for packaging - ' + target)
            data, path = None, None
        if payloads[-1] and "code" in payloads[-1]:
            data['error'] = payloads[-1]
        return path, json.dumps(data)

    def close(self):
        if self.connection:
            self.connection.close()


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

if __name__ == '__main__':
    http_client = HTTPClient()