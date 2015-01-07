import time
import json
import logging
import BaseHTTPServer

import utils

class WebInterfaceHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def setup(self):
        self.logger = logging.getLogger('app.' + __name__)
        BaseHTTPServer.BaseHTTPRequestHandler.setup(self)
        self.request.settimeout(120)

    def address_string(self):
        host, port = self.client_address[:2]
        self.logger.debug("Incoming from %s:%i" % (host, port))
        return host

    def do_GET(self):
        self.logger.info("Server GET")
        if self.path.find('cam') >= 0:
            self.logger.info('Camera')
            self.send_response(503)
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()

            with open('web_interface/loginform.html') as f:
                login_page = f.read()
            self.wfile.write(login_page)

    def do_POST(self):
        if self.path.find('token') >= 0:
            content_length = self.headers.getheader('Content-Length')
            if content_length:
                length = int(content_length)
                body = self.rfile.read(length)
                prefix = "token="
                if prefix in body:
                    token = body.replace(prefix, "")
                    result = utils.write_token(token)
                    if result:
                        message = "Success"
                    else:
                        message = "Error writing token"
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(message)
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write('Invalid body content for this request')
            else:
                self.send_response(411)
                self.end_headers()
                self.wfile.write('Zero Content-Length')

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write('Unknown path')


class WebInterface:
    def __init__(self):
        self.stop_flag = False
        self.logger = logging.getLogger('app.' + __name__)
        try:
            self.logger.info("Web server start")
            self.server = BaseHTTPServer.HTTPServer(("127.0.0.1", 8008), WebInterfaceHandler)
        except Exception as e:
            self.logger.error(e)
        else:
            while not self.stop_flag:
                self.server.handle_request()
            self.server.server_close()
            self.logger.info("Web server stop")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    w = WebInterface()