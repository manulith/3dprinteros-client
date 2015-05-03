import sys
import time
import signal
import base64

import log
import paths
import config
import user_login
import http_client


class DualCameraMaster:

    MAX_CAMERA_INDEX = 99
    FAILS_BEFORE_REINIT = 10

    #@log.log_exception
    def __init__(self):
        self.logger = log.create_logger("app.camera")
        self.stop_flag = False
        paths.init_path_to_libs()
        import numpy as np
        import cv2 as cv2
        self.np = np
        self.cv2 = cv2
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        ul = user_login.UserLogin(self)
        ul.wait_for_login()
        self.http_client = http_client.HTTPClient(keep_connection_flag=True)
        self.user_token = ul.user_token
        self.image_extension =  config.get_settings()["camera"]["img_ext"]
        self.image_quality = config.get_settings()["camera"]["img_qual"]
        self.init_captures()
        self.main_loop()

    def intercept_signal(self, signal_code, frame):
        self.logger.info("SIGINT or SIGTERM received. Closing Camera Module...")
        self.close()

    def close(self):
        self.stop_flag = True

    def init_captures(self):
        self.captures = []
        self.fails = []
        for index in range(0, self.MAX_CAMERA_INDEX):
            if self.stop_flag:
                break
            self.logger.debug("Probing for camera N%d..." % index)
            capture = self.cv2.VideoCapture(index)
            if capture.isOpened():
                self.captures.append(capture)
                self.fails.append(0)
                self.logger.info("...got camera at index %d" % index)
            else:
                del(capture)
        self.logger.info("Got %d cameras" % len(self.captures))

    def make_shot(self, capture):
        self.logger.debug("Capturing frame from " + str(capture))
        state, frame = capture.read()
        if not state:
            print self.fails
            self.fails[self.captures.index(capture)] += 1
        encode_param = [int(self.cv2.IMWRITE_JPEG_QUALITY), self.image_quality]
        try:
            result, encoded_frame = self.cv2.imencode(self.image_extension, frame, encode_param)
        except Exception as e:
            self.logger.warning('Failed to encode camera frame: ' + e.message)
            result, encoded_frame = None, None
        if state and result:
            data = self.np.array(encoded_frame)
            string_data = data.tostring()
            self.logger.debug("Successfully captured and encoded from" + str(capture))
            return string_data

    def send_frame(self, number, frame):
        frame = base64.b64encode(str(frame))
        number = number + 1
        message = self.user_token, number, "Camera" + str(number), frame
        self.logger.debug("Camera %d sending frame to server..." % number)
        answer = self.http_client.pack_and_send('camera', *message)
        if answer:
            self.logger.debug("...success")
        else:
            self.logger.debug("...fail")

    def main_loop(self):
        while not self.stop_flag:
            for number, capture in enumerate(self.captures):
                if self.fails[number] > self.FAILS_BEFORE_REINIT:
                    self.close_captures()
                    self.init_captures()
                    break
                frame = self.make_shot(capture)
                if frame:
                    self.send_frame(number, frame)
                else:
                    time.sleep(1)
            time.sleep(0.1) #to reduce cpu usage when no cameras are available
        self.close_captures()
        sys.exit(0)

    def close_captures(self):
        for capture in self.captures:
            capture.release()
            del (capture)

if __name__ == '__main__':
    DualCameraMaster()
