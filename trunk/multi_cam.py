import utils
utils.init_path_to_libs()
import numpy as np
import cv2
import time
import base64
import logging
import signal
import sys
import os
import traceback

import http_client
import user_login
import config

FRAME_RETRY = 5
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

class Camera:
    def __init__(self, device_number, cap, logger):
        self.logger = logger
        self.device_number = device_number
        # Redundant variable for glory and less magic offsets in code
        # Zero value as first opencv device number counts as None at server and we get an error in http response
        self.sequence_number = self.device_number + 1
        self.name = 'Camera %d' % self.sequence_number
        self.frame = None
        self.cap = cap
        # 0 - No resizing, 1 - frame resize, 2 - cap resize
        self.resize_level = 2

    def resize_cap(self):
        try:
            self.cap.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            self.cap.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        except Exception as e:
            self.logger.warning('Error while trying to resize cap : %s' % e.message)
            self.logger.info('Switching to frame resize level')
            self.resize_level = 1

    def resize_frame(self):
        try:
            cv2.resize(self.frame, (FRAME_WIDTH, FRAME_HEIGHT))
        except Exception as e:
            self.logger.warning('Error while trying to resize frame : %s' % e.message)
            self.logger.info('Switching to no resize level')
            self.resize_level = 0

    # We can either resize cap and then get needed frame from it, or get frame from default cap and modify it itself
    # So it will be called twice, when we get cap, and when we get frame
    def resize_check(self):
        if self.resize_level:
            if self.resize_level == 1:
                self.resize_frame()
            elif self.resize_level == 2:
                self.resize_cap()
            else:
                self.logger.warning('Something went wrong with resize leveling values, switching to no resize mode')
                self.resize_level = 0


class CameraMaster:
    def __init__(self):
        self.logger = logging.getLogger('app.' + __name__)
        self.logger.info('Launched camera module: %s' % os.path.basename(__file__))
        signal.signal(signal.SIGINT, self.intercept_signal)  # init signals
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.stop_flag = False  # stop flag to know when end application
        self.cameras = []
        self.logger.info('Camera module login...')
        ul = user_login.UserLogin(self)
        ul.wait_for_login()
        self.user_token = ul.user_token
        self.http_client = http_client.HTTPClient(keep_connection_flag=True)
        self.init_cameras()  # init cameras for the first time

    def init_cameras(self):
        camera_counter = 0
        while True:
            cap = cv2.VideoCapture(camera_counter)
            is_opened = cap.isOpened()
            if is_opened:
                new_cam = Camera(camera_counter, cap, self.logger)
                new_cam.cap.release()
                self.logger.info("Detected: %s" % new_cam.name)
                self.cameras.append(new_cam)
            if not is_opened:
                self.logger.info("All cameras found. Total: %d" % len(self.cameras))
                break
            camera_counter += 1

    def release_all_cameras(self):
        camera_counter = 0
        while True:
            cap = cv2.VideoCapture(camera_counter)
            is_opened = cap.isOpened()
            if is_opened:
                cap.release()
            if not is_opened:
                break
            camera_counter += 1

    def take_pictures(self):
        for camera in self.cameras:
            camera.cap = cv2.VideoCapture(camera.device_number)
            camera.resize_check()
            cap_ret = None
            # cap.read() result occasionally can be false first couple of times after cap creating
            for i in range(FRAME_RETRY):
                cap_ret, camera.frame = camera.cap.read()
                if cap_ret:
                    break
                else:
                    pass
                    #self.logger.info('No result while getting frame!')
            camera.cap.release()
            if not cap_ret:
                self.logger.info('Cannot get camera frame')
                continue
            camera.resize_check()
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), config.config["camera"]["img_qual"]]
            try:
                result, image_encode = cv2.imencode(config.config["camera"]["img_ext"], camera.frame, encode_param)
            except Exception as e:
                self.logger.warning('Error while encoding image : %s' % e.message)
                result, image_encode = None, None
            if result:
                data = np.array(image_encode)
                string_data = data.tostring()
                self.send_picture_short(string_data, camera.sequence_number, camera.name)
            else:
                #self.re_init_needed = True
                self.logger.warning("no result")


    def send_picture_short(self, picture, camera_number, camera_name):
        picture = base64.b64encode(str(picture))
        data = self.user_token, camera_number, camera_name, picture
        answer = self.http_client.pack_and_send('camera', *data)
        self.logger.info(camera_name + ' streaming response: %s' % answer)

    def intercept_signal(self, signal_code, frame):
        self.logger.info("SIGINT or SIGTERM received. Closing Camera Module...")
        self.close()

    def close(self):
        self.stop_flag = True
        self.release_all_cameras()
        self.http_client.close()
        logging.shutdown()
        sys.exit(0)

    def run(self):
        while not self.stop_flag:
            if self.cameras:
                self.take_pictures()
            else:
                self.init_cameras()
                time.sleep(0.5)

if __name__ == '__main__':
    logging.basicConfig(level='INFO')
    try:
        CM = CameraMaster()
        CM.run()
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
        with open(config.config['error_file'], "a") as f:
            f.write(time.ctime() + "\n" + trace + "\n")