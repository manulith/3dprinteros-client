#Copyright (c) 2015 3D Control Systems LTD

#3DPrinterOS client is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

#3DPrinterOS client is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.

#You should have received a copy of the GNU Affero General Public License
#along with 3DPrinterOS client.  If not, see <http://www.gnu.org/licenses/>.

# Author: Vladimir Avdeev <another.vic@yandex.ru>

from printrun.printcore import printcore
from printrun.gcoder import FastLightGCode
import re
import time
import logging
import threading

import log
import config
from base_sender import BaseSender


class Sender(BaseSender):

    pause_lift_height = 5
    pause_extrude_length = 7
    RETRIES_FOR_EACH_BAUDRATE = 2
    TEMP_REQUEST_WAIT = 5
    DEFAULT_TIMEOUT_FOR_PRINTER_ONLINE = 3

    def __init__(self, profile, usb_info):
        BaseSender.__init__(self, profile, usb_info)
        self.logger = logging.getLogger('app.' + __name__)
        self.printcore = None
        self.last_line = None
        self.define_regexps()
        if self.select_baudrate_and_connect():
            self.extruder_count = self.profile['extruder_count']
            self.total_gcodes = 0
            self.temp_request_thread = threading.Thread(target=self.temp_request)
            if not self.stop_flag:
                self.temp_request_thread.start()

    def select_baudrate_and_connect(self):
        baudrates = self.profile['baudrate']
        self.logger.info('Baudrates list for %s : %s' % (self.profile['name'], str(baudrates)))
        for baudrate in baudrates:
            self.error_code = 0
            self.error_message = ""
            self.online_flag = False
            self.logger.info("Connecting at baudrate %i" % baudrate)
            self.printcore = printcore()
            self.printcore.onlinecb = self.onlinecb
            self.printcore.errorcb = self.errorcb
            self.printcore.tempcb = self.tempcb
            self.printcore.recvcb = self.recvcb
            self.printcore.sendcb = self.sendcb
            self.printcore.endcb = self.endcb
            self.printcore.connect(self.profile['COM'], baudrate)
            time.sleep(0.1)
            if not self.printcore.printer:
                self.logger.warning("Error connecting to printer at %i" % baudrate)
                self.disconnect_printcore()
            else:
                wait_start_time = time.time()
                self.logger.info("Waiting for printer online")
                while time.time() < (wait_start_time + self.DEFAULT_TIMEOUT_FOR_PRINTER_ONLINE):
                    if config.get_app().stop_flag:
                        self.disconnect_printcore()
                        raise RuntimeError("Connection to printer interrupted by closing")
                    if self.online_flag:
                        self.logger.info("Successful connection to printer %s:%i" % (self.profile['COM'], baudrate))
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
        self.logger.info("Printer %s is ready" % str(self.usb_info))
        self.online_flag = True

    def endcb(self):
        self.logger.info("Printrun has called end callback.")

    def reset(self):
        if self.printcore:
            self.logger.debug("Resetting...")
            try:
                self.printcore.reset()
            except Exception as e:
                self.logger.warning("Error occured on printrun printer reset: " + str(e))
            time.sleep(0.2)
            self.logger.debug("Disconnecting...")
            self.disconnect_printcore()
            self.logger.info("Successful reset and disconnect")
        else:
            self.logger.warning("No printrun printcore to execute reset")

    def define_regexps(self):
        # ok T:29.0 /29.0 B:29.5 /29.0 @:0
        self.temp_re = re.compile('.*T:([\d\.]+) /([\d\.]+) B:(-?[\d\.]+) /(-?[\d\.]+)')
        self.position_re = re.compile('.*X:(-?[\d\.]+).?Y:(-?[\d\.]+).?Z:(-?[\d\.]+).?E:(-?[\d\.]+).*')
        # M190 - T:26.34 E:0 B:33.7
        # M109 - T:26.3 E:0 W:?
        #self.wait_tool_temp_re = re.compile('T:([\d\.]+) E:(\d+)')
        self.wait_tool_temp_re = re.compile('T:([\d\.]+)')
        self.wait_platform_temp_re = re.compile('.+B:(-?[\d\.]+)')

    @log.log_exception
    def temp_request(self):
        wait_step = 0.1
        steps_in_cycle = int(self.TEMP_REQUEST_WAIT / wait_step)
        counter = steps_in_cycle
        while not self.stop_flag:
            if counter >= steps_in_cycle:
                self.printcore.send_now('M105')
                time.sleep(0.01)
                #self.printcore.send_now('M114')
                #time.sleep(0.01)
                counter = 0
            time.sleep(wait_step)
            counter += 1

    def tempcb(self, line):
        self.logger.debug(line)
        self.logger.debug("Last executed line: " + str(self.last_line))
        match = self.temp_re.match(line)
        if match:
            tool_temp = float(match.group(1))
            tool_target_temp = float(match.group(2))
            platform_temp = float(match.group(3))
            platform_target_temp = float(match.group(4))
            self.temps = [platform_temp, tool_temp]
            self.target_temps = [platform_target_temp, tool_target_temp]

    def recvcb(self, line):
        #self.logger.debug(line)
        if line.startswith('T:'):
            self.fetch_temps(line)
            self.online_flag = True
        elif line.startswith('ok'):
            self.online_flag = True
        match = self.position_re.match(line)
        if match:
            self.position = [float(match.group(1)), float(match.group(2)), float(match.group(3)), float(match.group(4))]

    def sendcb(self, command, gline):
        #self.logger.debug("Executing command: " + command)
        self.last_line = command
        if 'M104' in command or 'M109' in command:
            tool_match = re.match('.+T(\d+)', command)
            if tool_match:
                tool = int(tool_match.group(1)) + 1
            else:
                tool = 1
            temp_match = re.match('.+S([\d\.]+)', command)
            if temp_match:
                if not tool >= len(self.target_temps):
                    self.target_temps[tool] = float(temp_match.group(1))
        elif 'M140' in command or 'M190' in command:
            temp_match = re.match('.+S([\d\.]+)', command)
            if temp_match:
                self.target_temps[0] = float(temp_match.group(1))

    def errorcb(self, error):
        self.logger.warning("Error occurred in printrun: " + str(error))
        self.error_code = 1
        self.error_message = error
        #if "M999" in error:
        #    self.reset()

    def fetch_temps(self, wait_temp_line):
        match = self.wait_tool_temp_re.match(wait_temp_line)
        if match:
            #self.temps[int(match.group(2)) + 1] = float(match.group(1))
            self.temps[1] = float(match.group(1))
        match = self.wait_platform_temp_re.match(wait_temp_line)
        if match:
            self.temps[0] = float(match.group(1))

    def set_total_gcodes(self, length):
        self.logger.info("Total gcodes number set to: %d" % length)
        self.total_gcodes = length
        self.current_line_number = 0

    def startcb(self, resuming_flag):
        if resuming_flag:
            self.logger.info("Printrun is resuming print")
        else:
            self.logger.info("Printrun is starting print")

    def load_gcodes(self, gcodes):
        gcodes = self.preprocess_gcodes(gcodes)
        length = len(gcodes)
        self.set_total_gcodes(length)
        self.logger.info('Loading %d gcodes...' % length)
        if length:
            self.buffer = FastLightGCode(gcodes)
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
        if self.downloading_flag:
            self.cancel_download()
            return
        self.printcore.cancelprint()
        self.reset()
        self.logger.info("Cancelled successfully")

    def emergency_stop(self):
        self.printcore.reset()

    def unbuffered_gcodes(self, gcodes):
        self.logger.info("Gcodes for unbuffered execution: " + str(gcodes))
        if self.printcore.printing:
            self.logger.warning("Can't execute gcodes - wrong mode")
            return False
        else:
            for gcode in self.preprocess_gcodes(gcodes):
                self.printcore.send_now(gcode)
            self.printcore.send_now('M114')
            self.logger.info("Gcodes were sent to printer")
            return True

    def is_paused(self):
        return self.printcore.paused

    def is_printing(self):
        return self.printcore.printing

    def is_error(self):
        return self.error_code

    def is_operational(self):
        if self.printcore:
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

    def update_current_line_number(self):
        if self.printcore:
            if self.current_line_number < self.printcore.queueindex:
                self.current_line_number = self.printcore.queueindex

    def get_percent(self):
        if self.downloading_flag:
            self.logger.info('Downloading flag is true. Getting percent from downloader')
            return self.downloader.get_percent()
        percent = 0
        if self.total_gcodes:
            self.update_current_line_number()
            percent = int( self.current_line_number / float(self.total_gcodes) * 100 )
        return percent

    def get_current_line_number(self):
        self.update_current_line_number()
        return self.current_line_number

    def disconnect_printcore(self):
        self.logger.info("Disconnecting printcore...")
        if self.printcore.printer:
            self.printcore.printer.close()
        self.printcore.disconnect()
        self.logger.info("...done")

    def close(self):
        self.recvcb = None
        self.sendcb = None
        self.onlinecb = None
        self.endcb = None
        self.tempcb = None
        self.stop_flag = True
        self.logger.info('Printrun sender is closing')
        if hasattr(self, 'temp_request_thread'):
            self.logger.debug('(Joining printrun threads...')
            self.temp_request_thread.join(10)
            if self.temp_request_thread.isAlive():
                self.logger.error("Error stopping temperature request thread!")
            else:
                self.logger.debug('...done)')
        self.logger.info('Printrun sender disconnectiong from printer...')
        if self.printcore:
            port = None
            self.disconnect_printcore()
            if port:
                port.close()
        self.logger.info('...done')

