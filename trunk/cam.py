import numpy as np
import cv2
import time
import base64
import threading
import logging
import requests


class CameraFinder():
    def __init__(self):
        self.logger = logging.getLogger("app." + __name__)
        self.cameras_names = self.get_cameras_names()
        self.cameras_count = len(self.cameras_names)

    def get_cameras_names(self):
        import win32com.client
        str_computer = "."
        cameras_names = {}
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
        for number in range(0,len(cameras_names)):
            self.logger.info(cameras_names[number])
        return  cameras_names


class CameraImageSender(threading.Thread):

    '''
    @staticmethod
    def get_number_of_cameras():
        logger = logging.getLogger("app." + __name__)
        cameras_count = 0
        while True:
            cap = cv2.VideoCapture(cameras_count)
            is_opened = cap.isOpened()
            cap.release()
            if not is_opened:
                break
            cameras_count += 1
        logger.info("Found %i cameras" % cameras_count)
        return cameras_count
    '''

    def __init__(self, token, camera_finder, camera_number = 0 ):
        self.logger = logging.getLogger("app." + __name__)
        self.stop_flag = False
        self.token = token
        self.url = 'https://acorn.3dprinteros.com/oldliveview/setLiveView/'
        self.cap = None
        self.camera_number = camera_number
        self.camera_finder = camera_finder
        self.cameras_count = self.camera_finder.cameras_count
        self.cameras_names = self.camera_finder.cameras_names
        self.image_ready_lock = threading.Lock()
        super(CameraImageSender, self).__init__()


    def init_camera(self):
        if self.cap:
            self.cap.release()
        if self.camera_number < self.cameras_count:
            cap = cv2.VideoCapture(self.camera_number)
            if cap.isOpened():
                self.cap = cap
                return cap
        self.logger.info("Error while initializing camera.")

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
        connection = http_client.connect(http_client.URL)
        if connection:
            encoded_picture = base64.b64encode(str(picture))
            http_client.send(http_client.token_camera_request, (self.token, encoded_picture))

    def alt_send_picture(self, picture):
            #send file alternative way with Requests
            picture = base64.b64encode(str(picture))
            data = {"token": self.token, "data": picture}
            r = requests.post(self.url, data = data)
            s = str(r.text)
            self.logger.debug('Sending response: ' + s)

    def close(self):
        self.stop_flag = True

    def wait_for_camera(self):
        self.logger.debug("Waiting for camera...")
        while not self.cap:
            self.init_camera()
            time.sleep(1)
        self.logger.debug("Got working camera!")

    def run(self):
        self.wait_for_camera()
        while not self.stop_flag:
            if self.cap.isOpened():
                picture = self.take_a_picture()
                if picture != '':
                    self.alt_send_picture(picture)
            else:
                time.sleep(1)
                self.init_camera()
        self.cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    import utils
    cf = CameraFinder()
    cis = CameraImageSender(utils.read_token(), cf)
    cis.start()
    while True:
        try:
            time.sleep(0.1)
        except KeyboardInterrupt:
            cis.close()
            break