import threading
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
        if self.server.token_was_reset_flag:
            self.send_response(200)
            self.end_headers()
            self.wfile.write("Token was reset\nPlease restart 3DPrinterOS and re-login")
        elif self.path.find('cam') >= 0:
            self.logger.info('Camera')
            self.send_response(503)
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            if self.server.app.token:
                name = 'web_interface/main_loop_form.html'
            else:
                name = 'web_interface/token_form.html'
            with open(name) as f:
                page = f.read()
            self.wfile.write(page)

    def do_POST(self):
        if self.path.find('write_token') >= 0:
            self.process_write_token()
        elif self.path.find('clear_token') >= 0:
            self.process_clear_token()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write('Unknown path')

    def process_clear_token(self):
        result = utils.write_token('')
        if result:
            message = "Token was reset\nPlease restart 3DPrinterOS and re-login"
            self.server.token_was_reset_flag = True
        else:
            message = "Error writing token"
        self.send_response(200)
        self.end_headers()
        self.wfile.write(message)

    def process_write_token(self):
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


class WebInterface(threading.Thread):
    def __init__(self, app):
        self.stop_flag = False
        self.logger = logging.getLogger('app.' + __name__)
        self.app = app
        threading.Thread.__init__(self)

    def close(self):
        self.stop_flag = True

    def run(self):
        try:
            self.logger.info("Web server started")
            self.server = BaseHTTPServer.HTTPServer(("127.0.0.1", 8008), WebInterfaceHandler)
            self.server.app = self.app
            self.server.token_was_reset_flag = False
        except Exception as e:
            self.logger.error(e)
        else:
            self.server.serve_forever()
            #self.server.server_close()
            self.server.app = None
            self.app = None
            self.logger.info("Web server stopped")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    class A:
        pass
    a = A()
    w = WebInterface(a)