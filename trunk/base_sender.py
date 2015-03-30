import collections
import os
import thread
import logging

import utils
import http_client

class BaseSender:

    def __init__(self, profile, usb_info, app):
        self.logger = logging.getLogger('app.' + __name__)
        self.app = app
        self.stop_flag = False
        self.profile = profile
        self.usb_info = usb_info
        self.error_code = None
        self.error_message = ''
        self.temps = [0,0]
        self.target_temps = [0,0]
        self.total_gcodes = None
        self.buffer = collections.deque()
        self.downloading_flag = False
        self.downloader = None
        #self._position = [0.00,0.00,0.00]

    def gcodes(self, gcodes):
        if self.downloading_flag:
            self.logger.warning('Download command received while downloading processing. Aborting...')
            return
        self.downloader = http_client.File_Downloader(self)
        self.downloading_flag = True
        thread.start_new_thread(self.download_thread, (gcodes,))

    def download_thread(self, gcodes):
        if not self.stop_flag:
            self.logger.info('Starting download thread')
            gcode_file = self.downloader.async_download(gcodes)
            if gcode_file:
                with open(gcode_file, 'rb') as f:
                    gcodes = f.read()
                self.gcodes(gcodes)  # Derived class method call, for example makerbot_sender.gcodes(gcodes)
                self.downloading_flag = False  # TODO: For now it should be after gcodes() due to status error on site
                self.logger.info('Gcodes loaded to memory, deleting temp file')
            try:
                os.remove(gcode_file)
            except:
                pass
            self.downloader = None
            self.logger.info('Download thread has been closed')

    def is_downloading(self):
        return self.downloading_flag

    def cancel_download(self):
        self.downloading_flag = False
        self.logger.info("File downloading has been cancelled")

    def get_temps(self):
        return self.temps

    def get_target_temps(self):
        return self.target_temps

    def pause(self):
        self.pause_flag = True

    def unpause(self):
        self.pause_flag = False

    def close(self):
        self.stop_flag = True

    def get_error_code(self):
        return self.error_code

    def get_error_message(self):
        return self.error_message

    def is_error(self):
        return self.error_code != None

    def is_paused(self):
        return self.pause_flag

    # def close_hanged_port(self):
    #     self.logger.info("Trying to force close serial port %s" % self.usb_info['COM'])
    #     if self.printer_profile["force_port_close"] and self.usb_info['COM']:
    #         try:
    #             port = serial.Serial(self.usb_info['COM'], self.printer_profile['baudrate'][0], timeout=1)
    #             if port.isOpen():
    #                 port.setDTR(1)
    #                 time.sleep(1)
    #                 port.setDTR(0)
    #                 port.close()
    #                 self.logger.info("Malfunctioning port %s was closed." % self.usb_info['COM'])
    #         except serial.SerialException as e:
    #             self.logger.info("Force close serial port failed with error %s" % e.message)
    #     else:
    #         self.logger.info("Force close serial port forbidden: \
    #                             not serial printer or force_port_close disabled in config")

    def is_operational(self):
        return False

    def upload_logs(self):
        utils.make_full_log_snapshot()
        self.logger.info("Sending logs")
        utils.send_all_snapshots(self.app.user_login.user_token)
        self.logger.info("Done")

    def switch_camera(self, module):
        self.logger.info('Changing camera module to %s due to server request' % module)
        self.app.switch_camera(module)

    def update_sowtware(self):
        self.logger.info('Executing update command from server')
        self.app.updater.update()

    def quit_application(self):
        self.logger.info('Received quit command from server!')
        self.app.stop_flag = True
        self.app.quit_flag = True