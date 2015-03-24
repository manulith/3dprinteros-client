import utils
utils.init_path_to_libs()
import numpy as np
import cv2
import time
import base64
import threading
import logging
import signal
import os
import traceback

import http_client
import user_login
import config

class CameraMaster():
    def __init__(self):
        self.init_logging()
        self.logger.info('Launched camera module: %s' % os.path.basename(__file__))
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.stop_flag = False
        self.cameras = []
        self.logger.info('Camera module login...')
        ul = user_login.UserLogin(self)
        ul.wait_for_login()
        self.user_token = ul.user_token
        self.cameras_count = self.get_number_of_cameras()
        self.camera_names = self.get_camera_names()
        if len(self.camera_names) != self.cameras_count:
            message = "Malfunction in get_camera_names. Number of cameras doesn't equal to number of camera names"
            self.logger.error(message)
            raise RuntimeError(message)
        else:
            self.init_cameras()

    def init_logging(self):
        self.logger = logging.getLogger("camera")
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        log_name = config.config["camera"]["log_file"]
        file_handler = logging.handlers.RotatingFileHandler(log_name, maxBytes=1024 * 1024, backupCount=1)
        file_handler.setFormatter(
            logging.Formatter('%(levelname)s\t%(asctime)s\t%(threadName)s/%(funcName)s\t%(message)s'))
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)

    def init_cameras(self):
        for num in self.camera_names:
            cap = cv2.VideoCapture(num)
            cam = CameraImageSender(num+1, self.camera_names[num], cap, self.user_token)
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
        os._exit(0)

    def get_camera_names(self):
        cameras_names = {}
        if self.cameras_count > 0:
            for camera_id in range(0, self.cameras_count):
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
        message = (self.token, self.camera_number, self.camera_name, picture, http_client.MACADDR)
        answer = http_client.send(http_client.package_camera_send, message)
        self.logger.info(self.camera_name + ' streaming response: %s' % answer)

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
    try:
        CM = CameraMaster()
        while True:
            try:
                time.sleep(0.1)
            except KeyboardInterrupt:
                CM.close()
                break
    except SystemExit:
        pass
    except:
        trace = traceback.format_exc()
        print trace
        with open("critical_error.log", "a") as f:
            f.write(time.ctime() + "\n" + trace + "\n")