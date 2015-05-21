#Copyright (c) 2015 3D Control Systems LTD

#3DPrinterOS client is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

#3DPrinterOS client is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.

#You should have received a copy of the GNU Affero General Public License
#along with 3DPrinterOS client.  If not, see <http://www.gnu.org/licenses/>.

# Author: Oleg Panasevych <panasevychol@gmail.com>

import os
import sys
import logging
import subprocess
import cloud_sync

import config


class CloudSyncController:

    CLOUD_SYNC_MODULE = 'cloud_sync.py'

    def __init__(self):
        self.logger = logging.getLogger("app." + __name__)
        self.cloud_sync_process = None
        self.start_cloud_sync_process()

    def start_cloud_sync_process(self):
        if config.get_settings()['cloud_sync']['enabled'] and self.CLOUD_SYNC_MODULE:
            self.logger.info('Launching CloudSync subprocess')
            cs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), self.CLOUD_SYNC_MODULE)
            try:
                self.cloud_sync_process = subprocess.Popen([sys.executable, cs_path])
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