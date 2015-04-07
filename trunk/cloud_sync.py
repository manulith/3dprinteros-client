import sys
import os
import logging
import shutil

from os.path import join
from subprocess import Popen, PIPE

import requests
import utils
utils.init_path_to_libs()
import user_login
import http_client

class Cloudsync:

    if sys.platform.startswith('linux'):
        HOME_PATH = os.environ.get('HOME')
    else:
        HOME_PATH = os.environ.get('HOMEPATH')
    PATH = join(HOME_PATH, 'Cloudsync')
    TEMP_PATH = join(PATH, '.temp')
    BIG_FILES_PATH = join(TEMP_PATH, 'big')
    NORMAL_FILES_PATH = join(TEMP_PATH, 'normal')
    SENDED_PATH = join(PATH, 'Sended')
    UNSENDABLE_PATH = join(PATH, 'Unsendable')
    BIG_FILE_SIZE = 10 * 1024 * 1024
    favourites_link_path = join(HOME_PATH, "links\Cloudsync.lnk")
    sendto_link_path = join(HOME_PATH, "AppData\Roaming\Microsoft\Windows\SendTo\Cloudsync.lnk")
    desktop_link_path = join(HOME_PATH, "desktop\CloudSync Folder.lnk")
    URL = 'https://' + http_client.URL + http_client.cloudsync_path
    MAX_SEND_RETRY = 10

    def __init__(self, debug=False):
        self.logger = logging.getLogger('app.' + __name__)
        if debug:
            self.logger.setLevel('DEBUG')
        else:
            self.logger.setLevel('INFO')
        self.stop_flag = False
        self.os = self.get_os()
        self.logger.info('Cloudsync login')
        ul = user_login.UserLogin(self)
        ul.wait_for_login()
        self.user_token = ul.user_token
        self.error_code = None
        self.error_message = ''

    def process_error(self, error_code, error_message):
        self.error_code = error_code
        self.error_message = error_message
        self.logger.warning('Error ' + str(error_code) + ' in Cloudsync. ' + error_message)

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
        paths = [self.PATH, self.TEMP_PATH, self.BIG_FILES_PATH, self.NORMAL_FILES_PATH, self.SENDED_PATH, self.UNSENDABLE_PATH]
        for path in paths:
            if not os.path.exists(path):
                os.mkdir(path)
        if self.os == "win":
            self.create_shortcuts_win()

    def create_shortcuts_win(self):
        Popen(['cscript', 'createLink.vbs', os.path.abspath(self.desktop_link_path), os.path.abspath(self.PATH)])
        Popen(['cscript', 'createLink.vbs', os.path.abspath(self.favourites_link_path), os.path.abspath(self.PATH)])
        Popen(['cscript', 'createLink.vbs', os.path.abspath(self.sendto_link_path), os.path.abspath(self.PATH)])

    def remove_shortcuts_win(self):
        os.remove(self.sendto_link_path)
        os.remove(self.favourites_link_path)
        os.remove(self.desktop_link_path)

    def enable_disk_label(self):
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

    def disable_disk_label(self):
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
            new_file_name = file_name + " (" + str(name_count) + ")" + file_ext
            name_count += 1
        shutil.move(current_path, join(destination_folder_path, new_file_name))
        self.logger.debug(current_path + ' moved to ' + destination_folder_path)

    def get_files_to_send(self):
        names_to_ignore = [os.path.basename(self.SENDED_PATH), os.path.basename(self.UNSENDABLE_PATH), os.path.basename(self.TEMP_PATH)]
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

    def send_file(self, file_path):
        result = ''
        count = 1
        while count <= self.MAX_SEND_RETRY:
            result = requests.post(self.URL, data={'user_token': self.user_token}, files={'file': open(file_path)})
            result = str(result.text)
            if '"result":true' in result:
                self.move_file(file_path, self.SENDED_PATH)
                return
            self.logger.info('Retrying to send ' + file_path)
            count += 1
        self.move_file(file_path, self.UNSENDABLE_PATH)
        return result

    def upload(self):
        files_to_send = self.get_files_to_send()
        if files_to_send:
            error = None
            for file_name in files_to_send:
                error = self.send_file(file_name)
                if error:
                    self.process_error(1, 'Failed to send ' + file_name + ': ' + error)
            if not error:
                self.logger.info('Files successfully uploaded')

    def start(self):
        self.logger.info('Cloudsync started!')
        self.create_folders()
        if self.os == 'windows':
            self.create_shortcuts_win()
            self.enable_disk_label()
        while not self.stop_flag:
            try:
                self.upload()
            except KeyboardInterrupt:
                self.stop()

    def stop(self):
        self.stop_flag = True
        if self.os == 'windows':
            self.disable_disk_label()
        self.logger.info('Cloudsync is stopped')

if __name__ == '__main__':
    logging.basicConfig(level='DEBUG')
    cs = Cloudsync(debug=True)
    cs.start()