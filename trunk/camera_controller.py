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