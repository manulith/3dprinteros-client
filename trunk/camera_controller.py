import os
import sys
import logging
import subprocess

from config import Config


class CameraController:

    CAMERA_MODULES = { "Dual camera": "dual_cam.py", "Multi camera": "multi_cam.py", "Disable camera": None }
    CURRENT_PATH = os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        self.logger = logging.getLogger("app." + __name__)
        self.start_camera_process()

    def start_camera_process(self, camera_name=None):
        self.logger.info('Launching camera subprocess')
        if not camera_name:
            camera_name = Config.instance().settings['camera']['default_module_name']
        module_name = self.CAMERA_MODULES[camera_name]
        cam_path = os.path.join(self.CURRENT_PATH, module_name)
        if module_name and Config.instance().settings["camera"]["enabled"]:
            try:
                self.camera_process = subprocess.Popen([sys.executable, cam_path])
            except Exception as e:
                self.logger.warning('Could not launch camera due to error:\n' + str(e))
                self.camera_process = None
                self.current_camera_name = "Disable camera"
                return
        self.current_camera_name = camera_name

    def switch_camera(self, new_camera_name):
        self.logger.info('Switching camera module from %s to %s' % (self.current_camera_name, new_camera_name))
        self.close()
        self.start_camera_process(new_camera_name)

    def close(self):
        if self.camera_process:
            self.camera_process.terminate()


