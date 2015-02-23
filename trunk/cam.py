import utils
utils.init_path_to_libs()
import numpy as np
import cv2
import time
import base64
import logging
import signal
import sys

import http_client
import user_login
import config

class CameraMaster():
    def __init__(self):
        self.logger = utils.get_logger(config.config["camera"]["log_file"])  # init logger
        signal.signal(signal.SIGINT, self.intercept_signal)  # init signals
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.stop_flag = False  # stop flag to know when end application
        self.re_init_needed = False # if there are less or more cameras, we do re initiatization, not implemented yet
        self.cam_num = 0  # number of detected cameras, -1 for re_init with 0 in the beginning
        self.cam_name = {}  # array with camera names
        self.cap = {}  # reusable array for camera objects
        self.frame = {}  # array of frames, even if there are many cameras later we can send same frames
        self.logger.info('Camera module login...')
        ul = user_login.UserLogin(self)
        ul.wait_for_login()
        self.user_token = ul.user_token
        self.init_cameras()  # init cameras for the first time

    def init_cameras(self, re_init=False):
        if re_init:
            cam_num = self.cam_num
        else:
            cam_num = 1
        while(True):
            self.cap[cam_num] = cv2.VideoCapture(cam_num-1)
            is_opened = self.cap[cam_num].isOpened()
            self.cap[cam_num].release()
            if not is_opened:
                self.logger.info("All cameras found. Total: " + str(cam_num))
                break
            self.cam_name[cam_num] = 'Camera ' + str(cam_num)
            self.logger.info("Detected: " + self.cam_name[cam_num])
            cam_num += 1
        self.cam_num = cam_num

    def take_pictures(self):
        for cam_num in range(1, self.cam_num):
            self.cap[cam_num] = cv2.VideoCapture(cam_num-1)
            self.cap[cam_num].set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, 640)  # 160
            self.cap[cam_num].set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 480)  # 120

            cap_ret, self.frame[cam_num] = self.cap[cam_num].read()
            self.cap[cam_num].release()
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), config.config["camera"]["img_qual"]]
            try:
                result, image_encode = cv2.imencode(config.config["camera"]["img_ext"], self.frame[cam_num], encode_param)
            except Exception as e:
                self.logger.warning(self.cam_name[cam_num] + ' warning: ' + e.message)
                result, image_encode = None, None
            if cap_ret and result:
                data = np.array(image_encode)
                string_data = data.tostring()
                self.send_picture_short(string_data, cam_num, self.cam_name[cam_num])
            else:
                #self.re_init_needed = True
                self.logger.warning("no result")

    def send_picture_short(self, picture, camera_number, camera_name):
        picture = base64.b64encode(str(picture))
        answer =  http_client.send(http_client.package_camera_send, (self.user_token, camera_number, camera_name, picture, http_client.MACADDR))
        self.logger.debug(camera_name + ' streaming response: ' + str(answer))

    def intercept_signal(self, signal_code, frame):
        self.logger.info("SIGINT or SIGTERM received. Closing Camera Module...")
        self.close()

    def close(self):
        for cam in self.cap:
            cam.release()
        self.stop_flag = True
        logging.shutdown()
        sys.exit(0)

    def run(self):
        while not self.stop_flag:
            if self.cam_num >= 1:
                self.take_pictures()
            else:
                self.init_cameras(True)
                time.sleep(0.5)

if __name__ == '__main__':
    CM = CameraMaster()
    CM.run()
    while True:
        try:
            time.sleep(0.1)
        except KeyboardInterrupt:
            CM.close()
            break