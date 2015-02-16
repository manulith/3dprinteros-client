from printrun.printcore import printcore
from printrun.gcoder import LightGCode
import re
import threading
import time
import logging

import base_sender


class Sender(base_sender.BaseSender):

    pause_lift_height = 5
    pause_extrude_length = 7
    TEMP_REQUEST_WAIT = 5
    DEFAULT_TIMEOUT_FOR_PRINTER_ONLINE = 15

    def __init__(self, profile, usb_info):
        self.temp_request_thread = None
        self.printcore = None
        self.logger = logging.getLogger('app.' + __name__)
        base_sender.BaseSender.__init__(self, profile, usb_info)
        self.define_regexps()
        if self.select_baudrate_and_connect():
            self.extruder_count = self.profile['extruder_count']
            self.total_gcodes = 0
            self.temp_request_thread = threading.Thread(target=self.temp_request)
            self.temp_request_thread.start()
            self.stop_flag = False
            for gcode in self.profile['end_gcodes']:
                self.printcore.send_now(gcode)

    def select_baudrate_and_connect(self):
        baudrates = self.profile['baudrate']
        self.logger.info('Baudrates list for %s : %s' % (self.profile['name'], str(baudrates)))
        for baudrate in baudrates:
            self.error_code = 0
            self.error_message = ""
            self.logger.info("Connecting at baudrate %i" % baudrate)
            self.printcore = printcore()
            self.printcore.onlinecb = self.onlinecb
            self.printcore.errorcb = self.errorcb
            self.printcore.connect(self.profile['COM'], baudrate)
            time.sleep(0.1)
            if not self.printcore.printer:
                self.logger.warning("Error connecting to printer at %i" % baudrate)
                self.printcore.disconnect()
            else:
                self.online_flag = False
                wait_start_time = time.time()
                self.logger.info("Waiting for printer online")
                while time.time() < (wait_start_time + self.DEFAULT_TIMEOUT_FOR_PRINTER_ONLINE):
                    if self.stop_flag:
                        return False
                    if self.online_flag:
                        self.logger.info("Successful connection to printer %s:%i" % (self.profile['COM'], baudrate))
                        self.printcore.tempcb = self.tempcb
                        self.printcore.recvcb = self.recvcb
                        self.printcore.sendcb = self.sendcb
                        time.sleep(0.1)
                        self.logger.info("Sending homing gcodes...")
                        for gcode in self.profile["end_gcodes"]:
                            self.printcore.send_now(gcode)
                        self.logger.info("...done homing")
                        return True

                self.logger.warning("Timeout while waiting for printer online. Reseting and reconnecting...")
                self.reset()
                time.sleep(2)
                self.logger.warning("...done reseting.")
        raise RuntimeError("No more baudrates to try")

    def onlinecb(self):
        self.online_flag = True

    def reset(self):
        if self.printcore:
            self.logger.debug("Sending M999...")
            self.printcore.send_now("M999")
            time.sleep(1)
            self.logger.debug("Resetting...")
            self.printcore.reset()
            time.sleep(1)
            self.logger.debug("Disconnecting...")
            self.printcore.disconnect()
            self.logger.debug("Successful reset and disconnect")
        else:
            self.logger.warning("No printrun printcore to execute reset")

    def define_regexps(self):
        # ok T:29.0 /29.0 B:29.5 /29.0 @:0
        self.temp_re = re.compile('.*ok T:([\d\.]+) /([\d\.]+) B:(-?[\d\.]+) /(-?[\d\.]+)')
        #self.position_re = re.compile('.*X:([\d\.]+) Y:([\d\.]+) Z:([\d\.]+).*')
        # M190 - T:26.34 E:0 B:33.7
        # M109 - T:26.3 E:0 W:?
        self.wait_tool_temp_re = re.compile('T:([\d\.]+) E:(\d+)')
        self.wait_platform_temp_re = re.compile('.+B:(-?[\d\.]+)')

    def temp_request(self):
        wait_step = 0.1
        steps_in_cycle = int(self.TEMP_REQUEST_WAIT / wait_step)
        counter = steps_in_cycle
        while not self.stop_flag:
            if counter >= steps_in_cycle:
                self.printcore.send_now('M105 T0')
                time.sleep(0.01)
                counter = 0
            time.sleep(wait_step)
            counter += 1

    def tempcb(self, line):
        self.logger.debug(line)
        match = self.temp_re.match(line)
        if match:
            tool_temp = float(match.group(1))
            tool_target_temp = float(match.group(2))
            platform_temp = float(match.group(3))
            platform_target_temp = float(match.group(4))
            self.temps = [platform_temp, tool_temp]
            self.target_temps = [platform_target_temp, tool_target_temp]
        #match = self.position_re.match(line)
        #if match:
        #    self.position = [ match.group(0), match.group(1), match.group(2) ]
        #self.logger.debug(self.debug_position())

    def recvcb(self, line):
        self.logger.debug(line)
        if line[0] == 'T':
            self.online_flag = True
            self.fetch_temps(line)
        # elif line[0:2] == 'ok':
        #     self.ready_flag = True

    def sendcb(self, command, gline):
        self.logger.info("Executing command: " + command)
        # if 'M104' in command or 'M109' in command:
        #     tool = 0
        #     tool_match = re.match('.+T(\d+)', command)
        #     if tool_match:
        #         tool = int(tool_match.group(1))
        #     temp_match = re.match('.+S([\d\.]+)', command)
        #     if temp_match:
        #         self.tool_target_temp[tool] = float(temp_match.group(1))
        #
        # elif 'M140' in command or 'M190' in command:
        #     temp_match = re.match('.+S([\d\.]+)', command)
        #     if temp_match:
        #         self.platform_target_temp = float(temp_match.group(1))

    def errorcb(self, error):
        self.logger.warning("Error occurred in printrun: " + str(error))
        self.error_code = 1
        self.error_message = error
        if "M999" in error:
            self.reset()

    def fetch_temps(self, wait_temp_line):
        match = self.wait_tool_temp_re.match(wait_temp_line)
        if match:
            self.temps[int(match.group(2)) + 1] = float(match.group(1))
        match = self.wait_platform_temp_re.match(wait_temp_line)
        if match:
            self.temps[0] = float(match.group(1))

    def set_total_gcodes(self, length):
        self.total_gcodes = length

    def startcb(self, resuming_flag):
        if resuming_flag:
            self.logger.info("Printrun is resuming print")
        else:
            self.logger.info("Printrun is starting print")

    def gcodes(self, gcodes_text):
        gcodes = gcodes_text.split("\n")
        while gcodes[-1] in ("\n", "\r\n", "\t", " ", "", None):
            gcodes.pop()
        length = len(gcodes)
        self.set_total_gcodes(length)
        self.logger.info('Loading %i gcodes in printcore...' % length)
        if length:
            self.buffer = LightGCode(gcodes)
            if self.printcore.startprint(self.buffer):
                self.logger.info('...done loading gcodes.')
                return True
        self.logger.warning('...failed to load gcodes.')
        return False

    def pause(self):
        self.logger.info("Printrun pause")
        if not self.printcore.paused:
            self.printcore.pause()
            gcode = 'G1 Z' + str(self.printcore.pauseZ + self.pause_lift_height) + \
                    ' E' + str(self.printcore.pauseE - self.pause_extrude_length)
            self.printcore.send_now(gcode)
            self.logger.info("Paused successfully")
            return True
        else:
            return False

    def unpause(self):
        self.logger.info("Printrun unpause")
        if self.printcore.paused:
            gcode = 'G1 Z' + str(self.printcore.pauseZ) + ' E' + str(self.printcore.pauseE)
            self.printcore.send_now(gcode)
            self.printcore.resume()
            self.logger.info("Unpaused successfully")
            return True
        else:
            return False

    def cancel(self):
        self.printcore.cancelprint()
        self.printcore.reset()
        self.printcore.disconnect()
        self.logger.info("Cancelled successfully")

    def emergency_stop(self):
        self.printcore.reset()

    def is_paused(self):
        return self.printcore.paused

    def is_printing(self):
        return self.printcore.printing

    def is_error(self):
        return self.error_code

    def is_operational(self):
        if self.printcore.printing:
            return self.printcore.read_thread and \
               self.printcore.read_thread.is_alive() and \
               self.printcore.print_thread and \
               self.printcore.print_thread.is_alive()
        elif self.printcore.paused or self.printcore.online:
            return self.printcore.read_thread and \
               self.printcore.read_thread.is_alive() and \
               self.printcore.send_thread and \
               self.printcore.send_thread.is_alive()
        return False

    def get_percent(self):
        percent = 0
        if self.total_gcodes:
            percent = int( self.printcore.queueindex / float(self.total_gcodes) * 100 )
        return percent

    def close(self):
        self.stop_flag = True
        self.logger.debug('Printrun sender is closing')
        if self.printcore:
            self.printcore.disconnect()
        self.logger.debug('(Joining printrun threads...')
        if self.temp_request_thread:
            self.temp_request_thread.join(10)
            if self.temp_request_thread.isAlive():
                self.logger.error("Error stopping temperature request thread.")
            else:
                self.logger.debug('...done)')