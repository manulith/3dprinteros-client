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
        self.senders = []
        self.logger.info('Camera master is login to server...')
        ul = user_login.UserLogin(self)
        ul.wait_for_login()
        self.logger.info('...got successful login as %s' % ul.login)
        self.user_token = ul.user_token
        self.init()

    def intercept_signal(self, signal_code, frame):
        self.logger.info("SIGINT or SIGTERM received. Closing Camera Module...")
        self.close()

    def init(self):
        self.logger.info("Initialising main detection loop...")
        count = 0
        first_run = True
        while not self.stop_flag:
            try:
                sender = self.senders[count]
            except IndexError:
                sender = None
            if sender:
                state = sender.is_alive()
                if not state:
                    self.senders.remove(sender)
            else:
                try:
                    cap = cv2.VideoCapture(count)
                    is_opened = cap.isOpened()
                except Exception as e:
                    self.logger.warning("OpenCV VideoCapture opening error: " + str(e))
                    is_opened = False
                if is_opened:
                    new_camera_sender = CameraImageSender(cap, count, "Camera" + str(count), self.user_token)
                    new_camera_sender.start()
                    self.senders.append(new_camera_sender)
                else:
                    count = 0
            time.sleep(0.1)
            count += 1
            if first_run:
                self.logger.info("First loop had connected %i cameras" % len(self.senders))
                first_run = False

    def close(self):
        self.stop_flag = True
        start_time = time.time()
        for sender in self.senders:
            sender.close()
        while (time.time() - start_time) < (config.config["camera"]["camera_min_loop_time"] + 1):
            time.sleep(0.1)
        for sender in self.senders:
            sender.join(3)
            if sender.isAlive():
                self.logger.warning("Failed to close camera %s" % sender.name)
        logging.shutdown()
        sys.exit(0)


class CameraImageSender(threading.Thread):
    def __init__(self, camera_number, camera_name, cap, user_token):
        self.logger = logging.getLogger("app." + __name__)
        self.logger.info("Creating new camera image sender %s %s" % (str(self.camera_number), self.camera_name))
        self.stop_flag = False
        self.camera_number = camera_number
        self.camera_name = camera_name
        self.cap = cap
        self.user_token = user_token
        self.host_mac = http_client.MACADDR
        self.connection = http_client.connect(http_client.camera_path)
        super(CameraImageSender, self).__init__()

    def take_a_picture(self):
        try:
            cap_ret, frame = self.cap.read()
        except Exception as e:
            self.logger.warning("Unable to read capture of camera " + self.camera_name)
            self.close()
            return
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
        message = (self.user_token, self.camera_number, self.camera_name, picture, self.host_mac)
        http_client.send(http_client.package_camera_send, message)

    def close(self):
        self.logger.info("Closing camera " + self.camera_name)
        self.stop_flag = True

    def run(self):
        while not self.stop_flag:
            if self.cap.isOpened():
                picture = self.take_a_picture()
                if picture:
                    self.send_picture(picture)
            else:
                self.logger.warning("OpenCV VideoCapture object isn't opened. Stopping camera " + self.camera_name)
                break
        self.cap.release()
        self.logger.info(self.camera_name + " was closed.")


if __name__ == '__main__':
    CM = CameraMaster()