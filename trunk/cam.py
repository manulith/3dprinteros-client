import numpy as np
import cv2
import time
import base64
import threading
import logging

import http_client

class CameraImageSender(threading.Thread):

    @staticmethod
    def get_number_of_cameras():
        logger = logging.getLogger("app." + __name__)
        cameras_count = -1
        while True:
            cameras_count += 1
            cap = cv2.VideoCapture(cameras_count)
            is_opened = cap.isOpened()
            cap.release()
            if not is_opened:
                break
        logger.info("Found %i cameras" % cameras_count)
        return cameras_count + 1

    def __init__(self, token, camera_number = 0 ):
        self.logger = logging.getLogger("app." + __name__)
        self.stop_flag = False
        self.token = token
        self.cap = None
        self.camera_number = camera_number
        self.image_ready_lock = threading.Lock()
        super(CameraImageSender, self).__init__()

    def init_camera(self):
        if self.cap:
            self.cap.release()
        if self.camera_number < CameraImageSender.get_number_of_cameras():
            cap = cv2.VideoCapture(self.camera_number)
            if cap.isOpened():
                self.cap = cap
                return cap
        self.logger.info("Error while initializing camera.")

    def take_a_picture(self):
        cap_ret, frame = self.cap.read()
        (encode_ret, image) = cv2.imencode('.jpg', frame)
        if cap_ret and encode_ret:
            #gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return image
        else:
            self.init_camera()

    def send_picture(self, picture):
        connection = http_client.connect(http_client.URL)
        if connection:
            encoded_picture = base64.b64encode(str(picture))
            http_client.send(http_client.token_camera_request, (self.token, encoded_picture))

    def close(self):
        self.stop_flag = True

    def wait_for_camera(self):
        self.logger.debug("Waiting for camera..")
        while not self.cap:
            self.init_camera()
            time.sleep(1)
        self.logger.debug("Got working camera!")

    def run(self):
        self.wait_for_camera()
        while not self.stop_flag:
            if self.cap.isOpened():
                picture = self.take_a_picture()
                if picture.any():
                    self.send_picture(picture)
            else:
                time.sleep(1)
                self.init_camera()
        self.cap.release()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    import utils
    c = CameraImageSender(utils.read_token())
    c.start()
    while True:
        try:
            time.sleep(0.1)
        except KeyboardInterrupt:
            c.close()
            break