import sys
import os
import shutil
import signal
import traceback
import time

from os.path import join
from subprocess import Popen, PIPE

import requests
import utils
utils.init_path_to_libs()
import user_login
import http_client
import config

class Cloudsync:

    if sys.platform.startswith('win32'):
        HOME_PATH = os.environ.get('HOMEPATH')
    else:
        HOME_PATH = os.environ.get('HOME')
    PATH = join(HOME_PATH, 'Cloudsync')
    SENDED_PATH = join(PATH, 'Sended')
    UNSENDABLE_PATH = join(PATH, 'Unsendable')
    favourites_link_path = join(HOME_PATH, "links\Cloudsync.lnk")
    sendto_link_path = join(HOME_PATH, "AppData\Roaming\Microsoft\Windows\SendTo\Cloudsync.lnk")
    desktop_link_path = join(HOME_PATH, "desktop\Cloudsync Folder.lnk")
    get_url = http_client.HTTPClient()
    URL = 'https://' + get_url.URL + get_url.cloudsync_path
    CHECK_URL = URL + '/check'
    MAX_SEND_RETRY = config.config['cloud_sync']['max_send_retry']
    CONNECTION_TIMEOUT = 6

    def __init__(self):
        self.logger = utils.create_logger('cloud_sync', config.config['cloud_sync']['log_file'])
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.stop_flag = False
        self.os = self.get_os()
        self.user_token = None
        self.error_code = None
        self.error_message = ''

    def intercept_signal(self, signal_code, frame):
        self.logger.info("SIGINT or SIGTERM received. Closing Cloudsync Module...")
        self.stop()

    def process_error(self, error_code, error_message):
        self.error_code = error_code
        self.error_message = error_message
        self.logger.warning('Error ' + str(error_code) + ' in Cloudsync. ' + error_message)

    def login(self):
        self.logger.info('Cloudsync login')
        ul = user_login.UserLogin(self)
        ul.wait_for_login()
        self.user_token = ul.user_token

    def get_os(self):
        if sys.platform.startswith('win'):
            return "windows"
        elif sys.platform.startswith('linux'):
            return "linux"
        elif sys.platform.startswith('darwin'):
            return "mac"
        else:
            raise EnvironmentError('Could not detect OS. Only GNU/LINUX, MAC OS X and MS WIN VISTA/7/8 are supported.')

    def create_folders(self):
        self.logger.info('Preparing Cloudsync folder: ' + self.PATH)
        paths = [self.PATH, self.SENDED_PATH, self.UNSENDABLE_PATH]
        for path in paths:
            if not os.path.exists(path):
                os.mkdir(path)

    def create_shortcuts_win(self):
        paths = [self.desktop_link_path, self.sendto_link_path, self.favourites_link_path]
        is_paths = []
        for path in paths:
            is_paths.append(os.path.exists(path))
        if any(is_paths):
            return
        for path in paths:
            Popen(['cscript', 'createLink.vbs',
                   os.path.abspath(path),
                   os.path.abspath(self.PATH),
                   os.path.abspath(join(os.getcwd(),config.config['cloud_sync']['icon_file']))])

    def remove_shortcuts_win(self):
        os.remove(self.sendto_link_path)
        os.remove(self.favourites_link_path)
        os.remove(self.desktop_link_path)

    def enable_virtual_drive(self):
        process = Popen(['subst'], stdout = PIPE, stderr = PIPE)
        stdout, stderr = process.communicate()
        if stdout == '':
            abspath = os.path.abspath(self.PATH)
            letters = 'HIJKLMNOPQRSTUVWXYZ'
            for letter in letters:
                process = Popen(['subst', letter + ':', abspath], stdout = PIPE, stderr = PIPE)
                stdout, stderr = process.communicate()
                if stdout == '':
                    self.logger.info("Virtual drive enabled.")
                    break

    def disable_virtual_drive(self):
        process = Popen(['subst'], stdout = PIPE, stderr = PIPE)
        stdout, stderr = process.communicate()
        if stdout != '':
            stdout = stdout[0]
            process = Popen(['subst', stdout + ':', '/d'], stdout = PIPE, stderr = PIPE)
            stdout, stderr = process.communicate()
            if stdout == '':
                self.logger.info("Virtual drive disabled.")

    def move_file(self, current_path, destination_folder_path):
        new_file_name = os.path.basename(current_path)
        file_name, file_ext = os.path.splitext(new_file_name)
        name_count = 1
        while os.path.exists(join(destination_folder_path, new_file_name)):
            new_file_name = file_name + "(" + str(name_count) + ")" + file_ext
            name_count += 1
        shutil.move(current_path, join(destination_folder_path, new_file_name))
        self.logger.debug('Moving ' + os.path.basename(current_path) + ' to ' + os.path.basename(destination_folder_path))

    def get_files_to_send(self):
        names_to_ignore = [os.path.basename(self.SENDED_PATH), os.path.basename(self.UNSENDABLE_PATH)]
        files_to_send = os.listdir(self.PATH)
        for name in names_to_ignore:
            files_to_send.remove(name)
        for position in range(0, len(files_to_send)):
            files_to_send[position] = join(self.PATH, files_to_send[position])
            file = files_to_send[position]
            if os.path.isdir(file):
                self.logger.warning('Folders are not sendable!')
                self.move_file(file, self.UNSENDABLE_PATH)
                files_to_send.remove(file)
        return files_to_send

    def get_file_size(self, file_path):
        file_size = os.path.getsize(file_path)
        while True:
            time.sleep(1)
            if file_size == os.path.getsize(file_path):
                break
            file_size = os.path.getsize(file_path)
        return file_size

    def get_permission_to_send(self, file_path):
        file_ext = file_path.split('.')[-1]
        file_size = self.get_file_size(file_path)
        result = requests.post(self.CHECK_URL, data = {'user_token': self.user_token, 'file_ext': file_ext, 'file_size': file_size}, timeout = self.CONNECTION_TIMEOUT)
        if not '"result":true' in result.text:
            return result.text

    def send_file(self, file_path):
        result = ''
        count = 1
        while count <= self.MAX_SEND_RETRY:
            try:
                error = self.get_permission_to_send(file_path)
                if error:
                    return 'Permission to send denied: ' + error
                result = requests.post(self.URL, data={'user_token': self.user_token}, files={'file': open(file_path, 'rb')}, timeout = self.CONNECTION_TIMEOUT)
                result = str(result.text)
                if '"result":true' in result:
                    return
            except Exception as e:
                result = str(e.message)
            self.logger.info('Retrying to send ' + os.path.basename(file_path))
            count += 1
        return result

    def upload(self):
        files_to_send = self.get_files_to_send()
        if files_to_send:
            error = ''
            for file_path in files_to_send:
                self.logger.info('Uploading ' + os.path.basename(file_path))
                error = self.send_file(file_path)
                if error:
                    self.logger.warning('Failed to upload ' + os.path.basename(file_path) + '. ' + error)
                    self.move_file(file_path, self.UNSENDABLE_PATH)
                else:
                    self.logger.info('Successfully uploaded: ' + os.path.basename(file_path))
                    self.move_file(file_path, self.SENDED_PATH)
            if not error:
                self.logger.info('Files successfully uploaded')

    def start(self):
        self.logger.info('Cloudsync started!')
        self.stop_flag = False
        self.login()
        self.create_folders()
        if self.os == 'windows':
            self.create_shortcuts_win()
            if config.config['cloud_sync']['virtual_drive_enabled']:
                self.enable_virtual_drive()
        self.main_loop()

    def main_loop(self):
        while not self.stop_flag:
            self.upload()
            time.sleep(3)

    def stop(self):
        if self.os == 'windows' and config.config['cloud_sync']['virtual_drive_enabled']:
            self.disable_virtual_drive()
        self.stop_flag = True
        self.logger.info('Cloudsync is stopped')
        os._exit(0)

if __name__ == '__main__':
    try:
        cs = Cloudsync()
        cs.start()
    except SystemExit:
        pass
    except:
        trace = traceback.format_exc()
        print trace
        with open(config.config['error_file'], "a") as f:
            f.write(time.ctime() + "\n" + trace + "\n")