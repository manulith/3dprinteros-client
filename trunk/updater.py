import logging
import zipfile
import os
import urllib
import time

import http_client
import version
import config

class Updater:

    auto_update_flag = config.config['update']['auto_update_enabled']
    check_pause = config.config['update']['check_pause']

    def __init__(self):
        self.logger = logging.getLogger('app.' + __name__)
        self.update_flag = False
        self.http_client = http_client.HTTPClient()
        self.check_time = 0

    def timer_check_for_updates(self):
        current_time = time.time()
        if current_time - self.check_time > self.check_pause:
            self.check_time = current_time
            self.check_for_updates()

    def check_for_updates(self):
        if self.new_version_available():
            self.logger.info('Updates available!')
            self.update_flag = True
            self.auto_update()

    def new_version_available(self):
        if config.config['update']['enabled']:
            self.http_client.connect()
            last_version = self.http_client.request('GET', self.http_client.connection, self.http_client.get_last_version_path, None, headers = {})
            self.http_client.close()
            if last_version:
                reload(version)
                return self.compare_versions(version.version, last_version)

    def compare_versions(self, current_version, available_version):
        current_version = self.version_to_int(current_version)
        available_version = self.version_to_int(available_version)
        if len(current_version) == len(available_version):
            for number in range(0, len(current_version)):
                if current_version[number] > available_version[number]:
                    return False
                elif current_version[number] < available_version[number]:
                    return True
        else:
            self.logger.warning('Error while comparing versions!')

    def version_to_int(self, version):
        version = version.split('.')
        for number in range(0, len(version)):
            version[number] = int(version[number])
        return version

    def auto_update(self):
        if self.auto_update_flag:
            self.update()

    def update(self):
        if self.update_flag:
            self.logger.info('Updating client...')
            update_file_name = config.config['update']['update_file_name']
            try:
                urllib.urlretrieve(config.config['update']['update_file_url'] + update_file_name, update_file_name)
            except Exception as e:
                error = 'Update failed!\nReason: error while downloading.\nDetails: ' + str(e)
                self.logger.error(error, exc_info=True)
                return error
            else:
                error = self.extract_update(update_file_name)
                if error:
                    return error
                self.logger.info('...client successfully updated!')
                self.update_flag = False

    def extract_update(self, update_file_name):
        try:
            z = zipfile.ZipFile(update_file_name)
            z.extractall()
            z.close()
            os.remove(update_file_name)
        except Exception as e:
            return 'Update failed!\nReason: error while extracting.\nDetails: ' + str(e)


if __name__ == '__main__':
    logging.basicConfig(level='INFO')
    u = Updater()
    u.new_version_available()