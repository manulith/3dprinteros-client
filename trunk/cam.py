import utils
utils.init_path_to_libs()
import numpy as np
import cv2
import time
import base64
import threading
import logging
import signal
import sys

import http_client
import user_login
import config

class CameraMaster():
    def __init__(self):
        self.logger = utils.get_logger(config.config["camera"]["log_file"])
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.stop_flag = False
        self.cameras = []
        self.logger.info('Camera module login...')
        ul = user_login.UserLogin(self)
        ul.wait_for_login()
        self.user_token = ul.user_token
        if len(self.get_camera_names()) != self.get_number_of_cameras():
            message = "Malfunction in get_camera_names. Number of cameras doesn't equal to number of camera names"
            self.logger.error(message)
            raise RuntimeError(message)
        else:
            self.init_cameras()

    def init_cameras(self):
        cam_names = self.get_camera_names()
        for num in cam_names:
            cap = cv2.VideoCapture(num)
            cam = CameraImageSender(num+1, cam_names[num], cap, self.user_token)
            cam.start()
            self.cameras.append(cam)

    def intercept_signal(self, signal_code, frame):
        self.logger.info("SIGINT or SIGTERM received. Closing Camera Module...")
        self.close()

    def close(self):
        start_time = time.time()
        for sender in self.cameras:
            sender.close()
        if time.time() - start_time < config.config["camera"]["camera_min_loop_time"]:
            time.sleep(1)
        for sender in self.cameras:
            sender.join(1)
            if sender.isAlive():
                self.logger.warning("Failed to close camera %s" % sender.name)
        self.stop_flag = True
        logging.shutdown()
        sys.exit(0)

    def get_camera_names(self):
        cameras_names = {}
        cameras_count = self.get_number_of_cameras()
        if cameras_count > 0:
            for camera_id in range(0, cameras_count):
                cameras_names[camera_id] = 'Camera ' + str(camera_id + 1)

        self.logger.info('Found ' + str(len(cameras_names)) + ' camera(s):')
        if len(cameras_names) > 0:
            for number in range(0,len(cameras_names)):
                self.logger.info(cameras_names[number])
        return  cameras_names

    def get_number_of_cameras(self):
        cameras_count = 0
        while True:
            cam = cv2.VideoCapture(cameras_count)
            is_opened = cam.isOpened()
            cam.release()
            if not is_opened:
                break
            cameras_count += 1
        return cameras_count


class CameraImageSender(threading.Thread):
    def __init__(self, camera_number, camera_name, cap, user_token):
        self.logger = logging.getLogger("app." + __name__)
        self.stop_flag = False
        self.camera_number = camera_number
        self.camera_name = camera_name
        self.cap = cap
        self.token = user_token
        if not self.token:
            self.stop_flag = True
            self.error = 'No_Token'
        self.connection = http_client.connect(http_client.camera_path)
        super(CameraImageSender, self).__init__()

    def take_a_picture(self):
        cap_ret, frame = self.cap.read()
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), config.config["camera"]["img_qual"]]
        try:
            result, image_encode = cv2.imencode(config.config["camera"]["img_ext"], frame, encode_param)
        except Exception as e:
            self.logger.warning(self.camera_name + ' warning: ' + e.message)
            result, image_encode = None, None
        if cap_ret and result:
            data = np.array(image_encode)
            string_data = data.tostring()
            return string_data
        else:
            time.sleep(1)

    def send_picture(self, picture):
        picture = base64.b64encode(str(picture))
        #payload = http_client.package_camera_send(self.token, self.camera_number, self.camera_name, picture)
        #answer = http_client.post_request(self.connection, payload, http_client.camera_path)
        answer =  http_client.send(http_client.package_camera_send, (self.token, self.camera_number, self.camera_name, picture, http_client.MACADDR))
        #self.logger.debug(self.camera_name + ' streaming response: ' + str(answer))

    def close(self):
        self.stop_flag = True

    def run(self):
        while not self.stop_flag and self.cap:
            if self.cap.isOpened():
                picture = self.take_a_picture()
                if picture:
                    self.send_picture(picture)
            else:
                if self.cap:
                    self.cap.release()
                self.cap = None
                time.sleep(1)
        if self.cap:
            self.cap.release()
        self.logger.info("Closing camera %s" % self.camera_name)


if __name__ == '__main__':
    CM = CameraMaster()
    while True:
        try:
            time.sleep(0.1)
        except KeyboardInterrupt:
            CM.close()
            break