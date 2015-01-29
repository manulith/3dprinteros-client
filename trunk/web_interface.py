import urllib
import logging
import threading
import BaseHTTPServer

import utils
import version

#temporary imports
import os
import time

class WebInterfaceHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def setup(self):
        self.logger = logging.getLogger('app.' + __name__)
        BaseHTTPServer.BaseHTTPRequestHandler.setup(self)
        self.request.settimeout(120)

    def address_string(self):
        host, port = self.client_address[:2]
        self.logger.debug("Incoming from %s:%i" % (host, port))
        return host

    def write_with_autoreplace(self, page):
        page = page.replace('!!!VERSION!!!', 'Client v.' + version.version + ', build ' + version.build + ', commit ' + version.commit)
        page = page.replace('3DPrinterOS', '3DPrinterOS Client v.' + version.version)
        self.wfile.write(page)

    def do_GET(self):
        self.logger.info("Server GET")
        if self.server.token_was_reset_flag:
            self.send_response(200)
            self.end_headers()
            self.write_with_autoreplace("Token was reset\nPlease restart 3DPrinterOS and re-login")
        elif self.path.find('cam') >= 0:
            self.logger.info('Camera')
            self.send_response(503)
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            if self.server.app.user_login.user_token:
                name = 'web_interface/main_loop_form.html'
            else:
                name = 'web_interface/login.html'
            with open(name) as f:
                page = f.read()
            printers_list = []
            for printer in self.server.app.detected_printers:
                if str(printer['SNR']) == 'None':
                    printer_snr = 'Unknown serial number'
                else:
                    printer_snr = str(printer['SNR'])
                printers_list.append('<b>' + printer['VID'] + " " + printer['PID'] + "</b><br>(s/n: " + printer_snr + ')')
            printers = ''.join(map(lambda x: "<p>" + x + "</p>", printers_list))
            page = page.replace('!!!PRINTERS!!!', printers)
            self.write_with_autoreplace(page)

    def do_POST(self):
        if self.path.find('write_token') >= 0:
            self.process_write_token()
        elif self.path.find('login') >= 0:
            self.process_login()
        elif self.path.find('clear_token') >= 0:
            self.process_clear_token()
        elif self.path.find('quit') >= 0:
            self.quit_main_app()
        elif self.path.find('snapshot_log') >= 0:
            self.snapshot_log()
        elif self.path.find('send_log_snapshots') >= 0:
            self.send_log_snapshots()
        elif self.path.find('logs') >= 0:
            self.download_logs()
        else:
            self.send_response(404)
            self.end_headers()
            self.write_with_autoreplace('Not found')

    def download_logs(self):
        page = open('web_interface/download_logs.html').read()
        self.send_response(200)
        self.end_headers()
        self.write_with_autoreplace(page)

    def snapshot_log(self):
        result = utils.make_log_snapshot()
        if result:
            message = open('web_interface/message.html', 'r').read()
            message = message.replace('!!!MESSAGE!!!', 'Success!')
        else:
            message = open('web_interface/message.html', 'r').read()
            message = message.replace('!!!MESSAGE!!!', 'Error!')
        self.send_response(200)
        self.end_headers()
        self.write_with_autoreplace(message)

    def send_log_snapshots(self):
        result = utils.send_all_snapshots()
        if result:
            message = open('web_interface/message.html', 'r').read()
            message = message.replace('!!!MESSAGE!!!', 'Success!')
        else:
            message = open('web_interface/message.html', 'r').read()
            message = message.replace('!!!MESSAGE!!!', 'Error!')
        self.send_response(200)
        self.end_headers()
        self.write_with_autoreplace(message)

    def quit_main_app(self):
        self.send_response(200)
        self.end_headers()
        page = open('web_interface/goodbye.html', 'r').read()
        self.write_with_autoreplace(page)
        self.server.app.stop_flag = True
        self.server.app.quit_flag = True

    # def process_clear_token(self):
    #     result = utils.write_token('')
    #     if result:
    #         message = open('web_interface/token_reset.html', 'r').read()
    #         self.server.token_was_reset_flag = True
    #     else:
    #         message = "Error writing token"
    #     self.send_response(200)
    #     self.end_headers()
    #     self.write_with_autoreplace(message)
    #
    # def process_write_token(self):
    #     content_length = self.headers.getheader('Content-Length')
    #     if content_length:
    #         length = int(content_length)
    #         body = self.rfile.read(length)
    #         prefix = "token="
    #         if prefix in body:
    #             token = body.replace(prefix, "")
    #             result = utils.write_token(token)
    #             if result:
    #                 message = open('web_interface/token_success.html', 'r').read()
    #             else:
    #                 message = open('web_interface/token_error.html', 'r').read()
    #             self.send_response(200)
    #             self.end_headers()
    #             self.write_with_autoreplace(message)
    #         else:
    #             self.send_response(400)
    #             self.end_headers()
    #             self.write_with_autoreplace('Invalid body content for this request')
    #     else:
    #         self.send_response(411)
    #         self.end_headers()
    #         self.write_with_autoreplace('Zero Content-Length')
            
    def process_login(self):
        content_length = self.headers.getheader('Content-Length')
        if content_length:
            length = int(content_length)
            body = self.rfile.read(length)
            body = urllib.unquote(body).decode('utf8')
            raw_login, password = body.split("&password=")
            login = raw_login.replace("login=", "")
        error = self.server.app.user_login.login_as_user(login, password)
        if error:
            message = open('web_interface/message.html').read()
            message = message.replace('!!!MESSAGE!!!', str(error[1]))
        else:
            message = open('web_interface/message.html', 'r').read()
            message = message.replace('!!!MESSAGE!!!', 'Login successful!<br><br>Processing...')
        self.send_response(200)
        self.end_headers()
        self.write_with_autoreplace(message)

        # if content_length:
        #         length = int(content_length)
        #         body = self.rfile.read(length)
        #         prefix = "token="
        #         if prefix in body:
        #             token = body.replace(prefix, "")
        #             result = utils.write_token(token)
        #             if result:
        #                 message = open('web_interface/token_success.html', 'r').read()
        #             else:
        #                 message = open('web_interface/token_error.html', 'r').read()
        #             self.send_response(200)
        #             self.end_headers()
        #             self.write_with_autoreplace(message)


class WebInterface(threading.Thread):
    def __init__(self, app):
        self.logger = logging.getLogger('app.' + __name__)
        self.app = app
        threading.Thread.__init__(self)

    def run(self):
        self.logger.info("Web server started")
        try:
            self.server = BaseHTTPServer.HTTPServer(("127.0.0.1", 8008), WebInterfaceHandler)
        except Exception as e:
            self.logger.error(e)
        else:
            self.server.app = self.app
            self.server.token_was_reset_flag = False
            self.server.serve_forever()
            self.server.app = None
            self.app = None
            self.logger.info("Web server stopped")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    class A:
        pass
    a = A()
    w = WebInterface(a)