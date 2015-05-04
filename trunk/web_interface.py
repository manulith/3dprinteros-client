import os, sys
import urllib
import logging
import threading
import BaseHTTPServer
import subprocess
from SocketServer import ThreadingMixIn

import utils
import version
import config
import cloud_sync

class WebInterfaceHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    URL = config.config['URL']

    def setup(self):
        self.working_dir = os.path.dirname(os.path.abspath(__file__))
        self.logger = logging.getLogger('app.' + __name__)
        BaseHTTPServer.BaseHTTPRequestHandler.setup(self)
        self.request.settimeout(120)

    def address_string(self):
        host, port = self.client_address[:2]
        self.logger.debug("Incoming connection from %s:%i" % (host, port))
        return host

    def read_file(self, path_in_cwd):
        with open(os.path.join(self.working_dir, path_in_cwd)) as f:
            return f.read()

    def write_with_autoreplace(self, page, response=200):
        try:
            page = page.replace('!!!VERSION!!!', 'Client v.' + version.version + ', build ' + version.build + ', commit ' + version.commit)
            page = page.replace('3DPrinterOS', '3DPrinterOS Client v.' + version.version)
            url = str(self.URL).replace('cli-', '')
            page = page.replace('!!!URL!!!', url)
            self.send_response(response)
            self.end_headers()
            self.wfile.write(page)
        except Exception as e:
            self.logger.error(str(e.message))

    def do_GET(self):
        self.logger.info("Server GET")
        if self.path.find('get_login') >= 0:
            self.process_login()
        elif self.path.find('quit') >= 0:
            self.quit_main_app()
        elif self.path.find('show_logs') >=0:
            self.show_logs()
        elif self.path.find('download_logs') >= 0:
            self.download_logs()
        else:
            page = self.form_main_page()
            self.write_with_autoreplace(page)

    def form_main_page(self):
        page = ''
        if self.server.app:
            if self.server.app.user_login.user_token:
                name = 'web_interface/main_loop_form.html'
            else:
                name = 'web_interface/login.html'
            page = self.read_file(name)
            printers = self.get_printers_payload()
            page = page.replace('!!!PRINTERS!!!', printers)
            login = self.server.app.user_login.login
            if login:
                page = page.replace('!!!LOGIN!!!', login)
            if utils.get_conveyor_pid():
                page = self.read_file('web_interface/conveyor_warning.html')
            if not utils.is_user_groups():
                page = self.read_file('web_interface/groups_warning.html')
            if not self.server.app.updater.auto_update_flag and self.server.app.updater.update_flag:
                page = page.replace('get_updates" style="display:none"', 'get_updates"')
            if config.config['cloud_sync']['enabled']:
                page = page.replace('open_cloudsync_folder" style="display:none"', 'open_cloudsync_folder"')
        return page

    def get_printers_payload(self):
        printers_list = []
        for pi in self.server.app.printer_interfaces:
            snr = pi.usb_info['SNR']
            if not snr:
                snr = ""
            if not getattr(pi, 'printer_profile', False):
                profile = {'alias': "", 'name': 'Awaiting profile %s:%s %s'
                                                % (pi.usb_info['PID'], pi.usb_info['VID'], snr)}
            else:
                profile = pi.printer_profile
            printer = '<b>%s</b> %s' % (profile['name'], snr)
            if not pi.printer_token:
                printer = printer + '<br>' + 'Waiting type selection from server('\
                          + '<a href="http://forum.3dprinteros.com/t/how-to-select-printer-type/143" target="_blank"><font color=blue>?</font></a>)'
            if pi.report:
                report = pi.report
                state = report['state']
                progress = ''
                if state == 'ready':
                    color = 'green'
                elif state == 'printing':
                    color = 'blue'
                    progress = ' | ' + str(report['percent']) + '%'
                elif state == 'paused':
                    color = 'orange'
                    progress = ' | ' + str(report['percent']) + '%'
                elif state == 'downloading':
                    color = 'lightblue'
                else:
                    color = 'red'
                printer = printer + ' - ' + '<font color="' + color + '">' + state + progress + '</font><br>'
                temps = report['temps']
                target_temps = report['target_temps']
                if temps and target_temps:
                    if len(temps) == 3 and len(target_temps) == 3:
                        printer = printer + 'Second Tool: ' + str(temps[2]) + '/' + str(target_temps[2]) + ' | '
                    printer = printer + 'First Tool: ' + str(temps[1]) + '/' + str(target_temps[1]) + ' | ' \
                              + 'Heated Bed: ' + str(temps[0]) + '/' + str(target_temps[0])
            printers_list.append(printer)
        printers = ''.join(map(lambda x: "<p>" + x + "</p>", printers_list))
        if not printers:
            printers = '<p><b>No printers detected</b>\
                <br>Please do a power cycle for printers\
                <br>and then ensure your printers are connected\
                <br>to power outlet and usb cord</p>'
        return printers

    def do_POST(self):
        if self.path.find('login') >= 0:
            self.process_login()
        elif self.path.find('quit') >= 0:
            self.quit_main_app()
        elif self.path.find('send_logs') >= 0:
            self.send_logs()
        elif self.path.find('logout') >= 0:
            self.process_logout()
        elif self.path.find('kill_conveyor') >= 0:
            self.kill_conveyor()
        elif self.path.find('add_user_groups') >= 0:
            self.add_user_groups()
        elif self.path.find('get_updates') >= 0:
            self.get_updates()
        elif self.path.find('update_software') >= 0:
            self.update_software()
        elif self.path.find('choose_cam') >= 0:
            self.choose_cam()
        elif self.path.find('switch_cam') >= 0:
            self.switch_cam()
        elif self.path.find('open_cloudsync_folder') >= 0:
            self.open_cloudsync_folder()
        else:
            self.write_message('Not found', 0, 404)

    def open_cloudsync_folder(self):
        path = os.path.abspath(cloud_sync.Cloudsync.PATH)
        if sys.platform.startswith('darwin'):
            subprocess.Popen(['open', path])
        elif sys.platform.startswith('linux'):
            subprocess.Popen(['xdg-open', path])
        elif sys.platform.startswith('win32'):
            subprocess.Popen(['explorer', path])
        self.do_GET()

    def write_message(self, message, show_time=2, response=200):
        page = self.read_file('web_interface/message.html')
        page = page.replace('!!!MESSAGE!!!', message)
        if show_time:
            page = page.replace('!!!SHOW_TIME!!!', str(show_time))
        else:
            page = page.replace('<meta http-equiv="refresh" content="!!!SHOW_TIME!!!; url=/" />', '')
        self.write_with_autoreplace(page, response)

    def choose_cam(self):
        if self.server.app.cam:
            modules = self.server.app.cam_modules
            modules_select = ''
            for module in modules.keys():
                if modules[module] == self.server.app.cam_current_module:
                    modules_select = modules_select + '<p><input type="radio" disabled> <font color="lightgrey">' + module + '</font></p>'
                else:
                    modules_select = modules_select + '<p><input type="radio" name="module" value="' + module + '"> ' + module + '</p>'
            page = self.read_file('web_interface/choose_cam.html')
            page = page.replace('!!!MODULES_SELECT!!!', modules_select)
            self.write_with_autoreplace(page)
        else:
            self.write_message('Live view feature disabled')

    def switch_cam(self):
        content_length = int(self.headers.getheader('Content-Length'))
        if content_length:
            body = self.rfile.read(content_length)
            body = body.replace("+", "%20")
            body = urllib.unquote(body).decode('utf8')
            body = body.split('module=')[-1]
            self.server.app.switch_camera(self.server.app.cam_modules[body])
            message = 'Live view type switched to ' + body
        else:
            message = 'Live view type not chosen'
        self.write_message(message)

    def get_updates(self):
        page = self.read_file('web_interface/update_software.html')
        self.write_with_autoreplace(page)

    def update_software(self):
        result = self.server.app.updater.update()
        if result:
            message = result
        else:
            message = '<p>Update successful!</p><p>Please restart Client to use all features of new version.</p>'
        self.write_message(message)

    def show_logs(self):
        log_file = config.config['log_file']
        logs = utils.get_file_tail(log_file)
        content = ''
        if not content:
            content = 'No logs'
        for line in logs:
            content = content + line + '<br>'
        page = self.read_file('web_interface/show_logs.html')
        page = page.replace('!!!LOGS!!!', content)
        self.write_with_autoreplace(page)

    def add_user_groups(self):
        utils.add_user_groups()
        self.quit_main_app()

    def kill_conveyor(self):
        result = utils.kill_existing_conveyor()
        if result:
            message = 'Conveyor was successfully stopped.<br><br>Returning...'
        else:
            message = '3DPrinterOS was unable to stop conveyor.'
        self.write_message(message)

    def download_logs(self):
        page = self.read_file('web_interface/download_logs.html')
        self.write_with_autoreplace(page)

    def send_logs(self):
        making_result = utils.make_full_log_snapshot()
        sending_result = utils.send_all_snapshots(self.server.app.user_login.user_token)
        if making_result and sending_result:
            message = 'Logs successfully sent'
        else:
            message = 'Error while sending logs'
        self.write_message(message)

    def quit_main_app(self):
        self.write_message('Goodbye :-)', 0)
        self.server.app.stop_flag = True

    def process_login(self):
        if self.server.app.user_login.user_token:
            self.write_message('Please logout first before re-login')
            return
        body = ''
        if self.path.find('get_login'):
            body = str(self.path)
            body = body.replace('/?get_', '')
        content_length = self.headers.getheader('Content-Length')
        if content_length:
            length = int(content_length)
            body = self.rfile.read(length)
        body = body.replace("+", "%20")
        body = urllib.unquote(body).decode('utf8')
        raw_login, password = body.split("&password=")
        login = raw_login.replace("login=", "")
        password = utils.sha256_hash(password)
        error = self.server.app.user_login.login_as_user(login, password)
        if error:
            message = str(error[1])
        else:
            message = 'Login successful!<br><br>Processing...'
        self.write_message(message)

    def process_logout(self):
        paths = utils.get_paths_to_settings_folder()
        for path in paths:
            login_info_path = os.path.join(path, 'login_info.bin')
            if os.path.isfile(login_info_path):
                try:
                    os.remove(login_info_path)
                except Exception as e:
                    self.logger.error('Failed to logout: ' + e.message)
        page = self.read_file('web_interface/logout.html')
        self.write_with_autoreplace(page)

class ThreadedHTTPServer(ThreadingMixIn, BaseHTTPServer.HTTPServer):
    """ This class allows to handle requests in separated threads.
        No further content needed, don't touch this. """


class WebInterface(threading.Thread):
    def __init__(self, app):
        self.logger = logging.getLogger('app.' + __name__)
        self.app = app
        self.server = None
        threading.Thread.__init__(self)

    def run(self):
        self.logger.info("Starting web server...")
        try:
            self.server = ThreadedHTTPServer(("127.0.0.1", 8008), WebInterfaceHandler)
        except Exception as e:
            self.logger.error(e)
        else:
            self.logger.info("...web server started")
            self.server.app = self.app
            self.server.token_was_reset_flag = False
            self.server.serve_forever()
            self.server.app = None
            self.app = None
            self.logger.info("Web server stop.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    class A:
        pass
    a = A()
    w = WebInterface(a)