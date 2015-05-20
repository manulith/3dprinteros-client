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

# Author: Vladimir Avdeev <another.vic@yandex.ru> 2015

import os
import sys
import logging
import subprocess

import config


class CameraController:

    CAMERA_MODULES = { "Dual camera": "dual_cam.py", "Multi camera": "multi_cam.py", "Disable camera": None }

    def __init__(self):
        self.logger = logging.getLogger("app." + __name__)
        self.camera_process = None
        self.current_camera_name = "Disable camera"
        self.start_camera_process()

    def start_camera_process(self, camera_name=None):
        self.logger.info('Launching camera subprocess')
        if not camera_name:
            camera_name = config.get_settings()['camera']['default']
        module_name = self.CAMERA_MODULES[camera_name]
        if module_name:
            cam_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), module_name)
            try:
                self.camera_process = subprocess.Popen([sys.executable, cam_path])
                self.current_camera_name = camera_name
            except Exception as e:
                self.logger.warning('Could not launch camera due to error:\n' + str(e))

    def switch_camera(self, new_camera_name):
        self.logger.info('Switching camera module from %s to %s' % (self.current_camera_name, new_camera_name))
        self.stop_camera_process()
        self.start_camera_process(new_camera_name)

    def stop_camera_process(self):
        if self.camera_process:
            self.camera_process.terminate()
            self.current_camera_name = "Disable camera"