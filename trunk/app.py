import sys
import time
import signal
import platform

import log
import paths
import usb_detect
import http_client
import camera_controller
import user_login
import updater
import version
import printer_interface
import config


class App(object):

    MAIN_LOOP_SLEEP = 2
    LOG_FLUSH_TIME = 30

    @log.log_exception
    def __init__(self):
        self.logger = log.create_logger("app", log.LOG_FILE)
        self.logger.info("Starting 3DPrinterOS client. Version %s_%s" % (version.version, version.build))
        self.logger.info('Operating system: ' + platform.system() + ' ' + platform.release())
        self.time_stamp()
        paths.init_path_to_libs()
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.detected_printers = []
        self.printer_interfaces = []
        self.stop_flag = False
        self.updater = updater.Updater()
        self.user_login = user_login.UserLogin(self)
        self.init_interface()
        if self.user_login.wait_for_login():
            config.Config.instance().set_profiles(self.user_login.profiles)
            if config.get_settings()["camera"]["enabled"]:
                self.camera_controller = camera_controller.CameraController()

    def init_interface(self):
        if config.get_settings()['web_interface']:
            import webbrowser
            from web_interface import WebInterface
            self.web_interface = WebInterface(self)
            self.web_interface.start()
            self.logger.debug("Waiting for webserver to start...")
            while not self.web_interface.server:
                time.sleep(0.01)
            self.logger.debug("...server is up and running. Connecting browser...")
            webbrowser.open("http://127.0.0.1:8008", 2, True)
            self.logger.debug("...done")

    @log.log_exception
    def start_main_loop(self):
        self.last_flush_time = 0
        self.detector = usb_detect.USBDetector()
        self.http_client = http_client.HTTPClient()
        while not self.stop_flag:
            self.updater.timer_check_for_updates()
            self.time_stamp()
            self.detected_printers = self.detector.get_printers_list()
            self.check_and_connect()
            for pi in self.printer_interfaces:
                if pi.usb_info not in self.detected_printers:
                    self.disconnect_printer(pi, 'not_detected')
                elif not pi.is_alive():
                    self.disconnect_printer(pi, 'error')
            if not self.stop_flag:
                time.sleep(self.MAIN_LOOP_SLEEP)
            now = time.time()
            if now - self.last_flush_time > self.LOG_FLUSH_TIME:
                self.last_flush_time = now
                self.flush_log()
        self.quit()

    def flush_log(self):
        self.logger.info('Flushing logger handlers')
        for handler in self.logger.handlers:
            handler.flush()

    def time_stamp(self):
        self.logger.debug("Time stamp: " + time.strftime("%d %b %Y %H:%M:%S", time.localtime()))

    def check_and_connect(self):
        currently_connected_usb_info = [pi.usb_info for pi in self.printer_interfaces]
        for usb_info in self.detected_printers:
            if usb_info not in currently_connected_usb_info:
                pi = printer_interface.PrinterInterface(usb_info, self.user_login.user_token)
                pi.start()
                self.printer_interfaces.append(pi)


    def disconnect_printer(self, pi, reason):
        self.logger.info('Disconnecting because of %s %s' % (reason , str(pi.usb_info)))
        pi.report_error()
        pi.close()
        self.printer_interfaces.remove(pi)
        self.logger.info("Successful disconnection of " + str(pi.usb_info))

    def intercept_signal(self, signal_code, frame):
        self.logger.warning("SIGINT or SIGTERM received. Closing 3DPrinterOS Client version %s_%s" % \
                (version.version, version.build))
        self.stop_flag = True

    def quit(self):
        self.logger.info("Starting exit sequence...")
        if hasattr(self, 'cloud_sync'):
            self.cloud_sync.terminate()
        if hasattr(self, 'camera_controller'):
            self.camera_controller.stop_camera_process()
        for pi in self.printer_interfaces:
            pi.close()
        time.sleep(0.2) #to reduce logging spam in next
        self.time_stamp()
        self.logger.info("Waiting for gcode sending modules to close...")
        while True:
            ready_flag = True
            for pi in self.printer_interfaces:
                if pi.isAlive():
                    pi.close()
                    ready_flag = False
                    self.logger.debug("Waiting for %s" % str(pi.usb_info))
                else:
                    self.printer_interfaces.remove(pi)
                    self.logger.info("Printer on %s was closed." % str(pi.usb_info))
            if ready_flag:
                break
            time.sleep(0.1)
        self.logger.info("...all gcode sending modules are closed.")
        self.logger.debug("Waiting web interface server to shutdown...")
        try:
            self.web_interface.server.shutdown()
            self.web_interface.join()
        except:
            pass
        self.logger.info("...done.")
        self.time_stamp()
        self.logger.info("Goodbye ;-)")
        time.sleep(0.1)
        self.flush_log()
        sys.exit(0)

if __name__ == '__main__':
    app = App()
    config.Config.instance().set_app_pointer(app)
    app.start_main_loop()