import os
import sys
import logging
import subprocess
import cloud_sync

import config


class CloudSyncController:

    enabled = config.get_settings()['cloud_sync']['enabled']
    CLOUD_SYNC_MODULE = 'cloud_sync.py'

    def __init__(self):
        self.logger = logging.getLogger("app." + __name__)
        self.cloud_sync_process = None
        self.start_cloud_sync_process()

    def start_cloud_sync_process(self):
        if self.enabled and self.CLOUD_SYNC_MODULE:
            self.logger.info('Launching CloudSync subprocess')
            cs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), self.CLOUD_SYNC_MODULE)
            try:
                self.camera_process = subprocess.Popen([sys.executable, cs_path])
            except Exception as e:
                self.logger.warning('Could not launch CloudSync due to error:\n' + str(e))

    def stop_cloud_sync_process(self):
        if self.cloud_sync_process:
            self.cloud_sync_process.terminate()
            self.logger.info('CloudSync is stopped')

    def open_cloud_sync_folder(self):
        path = os.path.abspath(cloud_sync.Cloudsync.PATH)
        if sys.platform.startswith('darwin'):
            subprocess.Popen(['open', path])
        elif sys.platform.startswith('linux'):
            subprocess.Popen(['xdg-open', path])
        elif sys.platform.startswith('win32'):
            subprocess.Popen(['explorer', path])