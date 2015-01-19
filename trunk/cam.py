import numpy as np
import cv2
import time
import base64
import threading
import logging

import http_client
import utils


class CameraFinder():

    @staticmethod
    def get_cameras_names():
        logger = logging.getLogger("app." + __name__)
        cameras_names = {}
        import sys
        if sys.platform.startswith('win'):
            import win32com.client
            str_computer = "."
            objWMIService = win32com.client.Dispatch("WbemScripting.SWbemLocator")
            objSWbemServices = objWMIService.ConnectServer(str_computer,"root\cimv2")
            items = objSWbemServices.ExecQuery("SELECT * FROM Win32_PnPEntity")
            count = 0
            for item in items:
                name = item.Name
                if ("web" in name) or ("Web" in name) or ("WEB" in name) or ("cam" in name) or ("Cam" in name) or ("CAM" in name):
                    new_camera = ''
                    if item.Manufacturer != None:
                        new_camera = item.Manufacturer
                    if item.Name != None:
                        new_camera = new_camera + ': ' + item.Name
                    cameras_names[count] = new_camera
                    count += 1

            logger.info('Found ' + str(len(cameras_names)) + ' camera(s):')
            if len(cameras_names) > 0:
                for number in range(0,len(cameras_names)):
                    logger.info(cameras_names[number])
            return  cameras_names

        elif sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
            cameras_count = CameraFinder.get_number_of_cameras()
            if cameras_count > 0:
                for camera_id in range(0, cameras_count):
                    cameras_names[camera_id] = 'Camera ' + str(camera_id + 1)

            logger.info('Found ' + str(len(cameras_names)) + ' camera(s):')
            if len(cameras_names) > 0:
                for number in range(0,len(cameras_names)):
                    logger.info(cameras_names[number])
            return  cameras_names

        else:
            logger.info('Unable to get cameras names on your platform.')
            return cameras_names

    @staticmethod
    def get_number_of_cameras():
        cameras_count = 0
        while True:
            cam = cv2.VideoCapture(cameras_count)
            is_opened = cam.isOpened()
            cam.release()
            if not is_opened:
                break
            cameras_count += 1
        return cameras_count

    @staticmethod
    def get_camera(camera_number = 0):
        logger = logging.getLogger("app." + __name__)
        if camera_number < CameraFinder.get_number_of_cameras():
            cam = cv2.VideoCapture(camera_number)
            if cam.isOpened():
                return cam
        logger.info("Error while getting camera.")


class CameraImageSender(threading.Thread):
    def __init__(self):
        self.logger = logging.getLogger("app." + __name__)
        self.stop_flag = False
        self.token = utils.read_token()
        self.url = 'https://acorn.3dprinteros.com/oldliveview/setLiveView/'
        self.cap = None
        self.image_ready_lock = threading.Lock()
        super(CameraImageSender, self).__init__()

    def init_camera(self):
        if self.cap:
            self.cap.release()
            self.cap = None
        number = CameraFinder.get_number_of_cameras()
        if number:
            self.cap = CameraFinder(number - 1)
        #self.logger.info("Error while initializing camera.")

    def take_a_picture(self):
        cap_ret, frame = self.cap.read()
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        result, image_encode = cv2.imencode('.jpg', frame, encode_param)
        if cap_ret and result:
            data = np.array(image_encode)
            string_data = data.tostring()
            return string_data
        else:
            self.init_camera()

    def send_picture(self, picture):
        picture = base64.b64encode(str(picture))
        data = {"token": self.token, "data": picture}
        http_client.multipart_upload(self.url, data)

    def close(self):
        self.logger.info("Closing camera image sender...")
        self.stop_flag = True

    def wait_for_camera(self):
        self.logger.debug("Waiting for camera...")
        while not self.cap:
            self.init_camera()
            time.sleep(10)
            if self.stop_flag:
                return
        self.logger.debug("Got working camera!")

    def run(self):
        self.wait_for_camera()
        while not self.stop_flag:
            if self.cap.isOpened():
                picture = self.take_a_picture()
                if picture != '':
                    self.send_picture(picture)
            else:
                time.sleep(3)
                self.init_camera()
        if self.cap:
            self.cap.release()
        self.logger.info("...camera image sender is closed.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    utils.init_path_to_libs()
    c = CameraImageSender()
    while True:
        try:
            time.sleep(0.1)
        except KeyboardInterrupt:
            c.close()
            time.sleep(5)
            break