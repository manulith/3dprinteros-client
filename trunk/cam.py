import numpy as np
import cv2
import time
import base64
import threading
import logging

import http_client
import utils

class CameraMaster():
    def __init__(self):
        self.logger = logging.getLogger("app." + __name__)
        self.cameras = []
        if len(self.get_camera_names()) != self.get_number_of_cameras():
            message = "Malfunction in get_camera_names. Number of cameras doesn't equal to number of camera names"
            self.logger.error(message)
            raise RuntimeError(message)
        else:
            self.init_cameras()

    def init_cameras(self):
        for num, name in enumerate(self.get_camera_names()):
            cam = CameraImageSender(num, name)
            cam.start()
            self.cameras.append(cam)

    def close(self):
        for sender in self.cameras:
            sender.close()

        time.sleep(1)
        for sender in self.cameras:
            if sender.isAlive():
                self.logger.warning("Failed to close camera %s" % sender.name)


    def get_camera_names(self):
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

            self.logger.info('Found ' + str(len(cameras_names)) + ' camera(s):')
            if len(cameras_names) > 0:
                for number in range(0,len(cameras_names)):
                    self.logger.info(cameras_names[number])
            return  cameras_names

        elif sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
            cameras_count = self.get_number_of_cameras()
            if cameras_count > 0:
                for camera_id in range(0, cameras_count):
                    cameras_names[camera_id] = 'Camera ' + str(camera_id + 1)

            self.logger.info('Found ' + str(len(cameras_names)) + ' camera(s):')
            if len(cameras_names) > 0:
                for number in range(0,len(cameras_names)):
                    self.logger.info(cameras_names[number])
            return  cameras_names

        else:
            self.logger.info('Unable to get cameras names on your platform.')
            return cameras_names

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
    def __init__(self, camera_number, camera_name):
        self.logger = logging.getLogger("app." + __name__)
        self.stop_flag = False
        self.number = camera_number
        self.name = camera_number
        self.token = utils.read_user_token()
        self.url = 'https://acorn.3dprinteros.com/oldliveview/setLiveView/'
        if self.token:
            self.get_camera(self.number)
            self.image_ready_lock = threading.Lock()
            super(CameraImageSender, self).__init__()
        else:
            self.stop_flag = True
            self.error = 'No_Token'

    def take_a_picture(self):
        cap_ret, frame = self.cap.read()
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        result, image_encode = cv2.imencode('.jpg', frame, encode_param)
        if cap_ret and result:
            data = np.array(image_encode)
            string_data = data.tostring()
            return string_data
        else:
            self.sleep(1)

    def send_picture(self, picture):
        picture = base64.b64encode(str(picture))
        data = {"user_token": self.token, "number": self.number, "name": self.name, "data": picture}
        http_client.multipart_upload(self.url, data)

    def close(self):
        self.stop_flag = True

    def run(self):
        while not self.stop_flag:
            if not self.cap:
                self.cap = cv2.VideoCapture(self.camera_number)
            if self.cap.isOpened():
                picture = self.take_a_picture()
                if picture != '':
                    self.send_picture(picture)
            else:
                if self.cap:
                    self.cap.release()
                self.cap = None
                time.sleep(1)
        self.logger.info("Closing camera %s" % self.name)
        self.cap.release()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    CM = CameraMaster()
    while True:
        try:
            time.sleep(0.1)
        except KeyboardInterrupt:
            CM.close()
            break