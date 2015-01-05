from printrun.printcore import printcore
from printrun.gcoder import LightGCode
import re
import threading
import time
import logging
from collections import deque

class Printer:

    def _debug_info(self):
        info = 'len(_gcodes): ' + str(len(self._gcodes)) + '\n'
        info += '_length: ' + str(self._length) + '\n'
        info += 'len(_append_buffer): ' + str(len(self._append_buffer)) + '\n'
        info += '_got_all_gcodes: ' + str(self._got_all_gcodes) + '\n'
        info += '_was_error: ' + str(self._was_error) + '\n'
        info += '_last_percent: ' + str(self._last_percent) + '\n'
        info += '_wait_heading: ' + str(self._wait_heading) + '\n'
        info += '_printing: ' + str(self._printing) + '\n'
        info += '_printer.online: ' + str(self._printer.online) + '\n'
        info += '_printer.printing: ' + str(self._printer.printing) + '\n'
        info += '_printer.paused: ' + str(self._printer.paused) + '\n'
        info += '_printer.queueindex: ' + str(self._printer.queueindex) + '\n'
        info += '_printer.read_thread.is_alive(): ' + \
                str(self._printer.read_thread and self._printer.read_thread.is_alive()) + '\n'
        info += '_printer.print_thread.is_alive(): ' + \
                str(self._printer.print_thread and self._printer.print_thread.is_alive()) + '\n'
        info += '_printer.send_thread.is_alive(): ' + \
                str(self._printer.send_thread and self._printer.send_thread.is_alive()) + '\n'
        return info

    def _debug_temp(self):
        temp = '_tool_temp: ' + str(self._tool_temp) + '\n'
        temp += '_tool_target_temp: ' + str(self._tool_target_temp) + '\n'
        temp += '_platform_temp: ' + str(self._platform_temp) + '\n'
        temp += '_platform_target_temp: ' + str(self._platform_target_temp)
        return temp

    #def _debug_position(self):
    #    text  = "X:" + str(self._position[0])
    #    text += " Y:" + str(self._position[1])
    #    text += " Z:" + str(self._position[2])
    #    return text

    def __init__(self, profile):
        self._profile = profile
        self._logger = logging.getLogger('app.' + __name__)
        self._extruder_count = profile['extruder_count']
        self._pause_lift_height = 5
        self._pause_extrude_length = 7
        self._force_operational = False
        self._was_error = False
        self._error_code = ''
        self._error_message = ''
        self._select_baudrate_and_connect()
        self._printer.tempcb = self._tempcb
        self._printer.recvcb = self._recvcb
        self._printer.sendcb = self._sendcb
        self._printer.errorcb = self._errorcb
        self._tool_temp = [0, 0]
        self._tool_target_temp = [0, 0]
        self._platform_temp = 0
        self._platform_target_temp = 0
        self._gcodes = LightGCode([])
        self.define_regexp()
        self._length = 0
        self._got_all_gcodes = True
        self._printing = False
        self._last_percent = 0
        self._wait_heading = False
        self._temp_request_extruder = 0
        self._temp_timeout = 0
        self._temp_request_thread = threading.Thread(target=self._temp_request)
        self._temp_request_active = True
        self._temp_request_thread.start()
        self._append_buffer = deque()
        # self._append_thread = threading.Thread(target=self._append)
        # self._append_active = True
        # self._append_thread.start()
        self._append_thread = None
        self._append_active = False
        #self._position = [0.00,0.00,0.00]
        time.sleep(0.1)
        for gcode in self._profile['end_gcodes']:
            self._printer.send_now(gcode)

    def _recvcb_for_connection_check(self, line):
        self._logger.debug("While selecting baudrate received: %s", str(line))
        if "ok " in line or 'echo' in line:
            self.connected_flag = True

    def _select_baudrate_and_connect(self):
        self.connected_flag = False
        baudrate_count = 0
        baudrates = self._profile['baudrate']
        while not self.connected_flag:
            if baudrate_count >= len(baudrates):
                raise RuntimeError("Printrun: no more baudrates to try for %s" % self._profile['name'])
            self._logger.info("Trying to connect with baudrate %i" % baudrates[baudrate_count])
            try:
                self._printer.reset()
                self._printer.disconnect()
            except:
                pass
            try:
                self._printer = printcore(self._profile['COM'], baudrates[baudrate_count])
            except Exception as e:
                self._logger.warning("Error connecting to printer with baudrate %i" % baudrates[baudrate_count])
                self._printer.reset()
                self._printer.disconnect()
            else:
                time.sleep(0.1)
                self._printer.recvcb = self._recvcb_for_connection_check
                #self._printer.errorcb = self._logger.warning
                self._printer.send("M105")
            time.sleep(2)
            baudrate_count += 1

        self._logger.info("Successful connection! Correct baudrate is %i" % baudrates[baudrate_count-1])

    def define_regexp(self):
        # ok T:29.0 /29.0 B:29.5 /29.0 @:0
        self._temp_re = re.compile('.*ok T:([\d\.]+) /([\d\.]+) B:(-?[\d\.]+) /(-?[\d\.]+)')
        #self._position_re = re.compile('.*X:([\d\.]+) Y:([\d\.]+) Z:([\d\.]+).*')
        # M190 - T:26.34 E:0 B:33.7
        # M109 - T:26.3 E:0 W:?
        self._wait_tool_temp_re = re.compile('T:([\d\.]+) E:(\d+)')
        self._wait_platform_temp_re = re.compile('.+B:(-?[\d\.]+)')

    def _append(self):
        while self._append_active:
            length = len(self._gcodes)
            try:
                while self._append_active:
                    gcode = self._append_buffer.popleft()
                    self._logger.info('append_gcode: '+gcode)
                    self._gcodes.append(gcode)
            except IndexError:
                pass
            if len(self._gcodes) > length:
                self._logger.info('GCodes appended: ' + str(len(self._gcodes) - length))

            if not self._printer.printing and not self._printer.paused and len(self._gcodes) > length:
                if not self._printer.startprint(self._gcodes, length):
                    self._logger.warning('Error starting print, startindex: ' + str(length))
                else:
                    self._logger.info('Printing started, startindex: ' + str(length))
            time.sleep(1)

    def _stop_append(self):
        self._append_active = False
        if self._append_thread:
            self._append_thread.join()
        self._append_buffer.clear()

    def _start_append(self):
        if self._append_thread:
            self._stop_append()
        self._append_buffer.clear()
        self._append_active = True
        self._append_thread = threading.Thread(target=self._append)
        self._append_thread.start()

    def _init_temps(self):
        self._tool_temp = [0, 0]
        self._tool_target_temp = [0, 0]
        self._platform_temp = 0
        self._platform_target_temp = 0

    def _temp_request(self):
        while self._temp_request_active:
            if self.is_operational():
                if self._wait_heading:
                    self._temp_timeout = time.time() + 5
                elif self._temp_timeout < time.time():
                    self._temp_request_extruder = (self._temp_request_extruder + 1) % self._extruder_count
                    self._printer.send_now('M105 T'+str(self._temp_request_extruder))
                    #self._printer.send_now('M114')
                    self._temp_timeout = time.time() + 5
            time.sleep(1)

    #also updates position now
    def _tempcb(self, line):
        match = self._temp_re.match(line)
        if match:
            self._tool_temp[self._temp_request_extruder] = float(match.group(1))
            self._tool_target_temp[self._temp_request_extruder] = float(match.group(2))
            self._platform_temp = float(match.group(3))
            self._platform_target_temp = float(match.group(4))
        #match = self._position_re.match(line)
        #if match:
        #    self._position = [ match.group(0), match.group(1), match.group(2) ]
        #self._logger.debug(self._debug_position())

    def _recvcb(self, line):
        self._logger.debug(line)
        if line[0] == 'T':
            self._wait_heading = True
            self._fetch_temps(line)
            self._logger.debug(self._debug_temp())
        elif line[0:2] == 'ok':
            self._wait_heading = False

    def _sendcb(self, command, gline):
        self._logger.info("command=" + command)
        if 'M104' in command or 'M109' in command:
            tool = 0
            tool_match = re.match('.+T(\d+)', command)
            if tool_match:
                tool = int(tool_match.group(1))
            temp_match = re.match('.+S([\d\.]+)', command)
            if temp_match:
                self._tool_target_temp[tool] = float(temp_match.group(1))
            self._logger.debug(self._debug_temp())

        elif 'M140' in command or 'M190' in command:
            temp_match = re.match('.+S([\d\.]+)', command)
            if temp_match:
                self._platform_target_temp = float(temp_match.group(1))
            self._logger.debug(self._debug_temp())
        self._logger.debug(command)

    def _errorcb(self, error):
        self._was_error = True
        self._error_code = 'general'
        self._error_message = error
        self._logger.debug(error)

    def _fetch_temps(self, wait_temp_line):
        self._logger.info("_fetch_temp" + str(wait_temp_line))
        match = self._wait_tool_temp_re.match(wait_temp_line)
        if match:
            self._tool_temp[int(match.group(2))] = float(match.group(1))
        match = self._wait_platform_temp_re.match(wait_temp_line)
        if match:
            self._platform_temp = float(match.group(1))

    def begin(self, length):
        self.set_total_gcodes(length)

    def set_total_gcodes(self, length):
        self._logger.debug('Begin debug info : ' + self._debug_info())
        self._length = length
        self._printing = True
        self._got_all_gcodes = False
        self._last_percent = 0
        self._wait_heading = False
        self._force_operational = False
        self._init_temps()
        self._gcodes = LightGCode([])
        self._start_append()

    def enqueue(self, gcodes):
        self.gcodes(gcodes)

    def gcodes(self, gcodes):
        # if not self._printing:
        #     self._was_error = True
        #     self._error_code = 'protocol'
        #     self._error_message = 'Begin was not sent'
        #     return
        self._logger.info('len(gcodes): ' + str(len(gcodes)) + ', ' + self._debug_info())
        if len(self._gcodes) > 0:
            self._append_buffer += gcodes
            return

        if len(gcodes) > 0:
            self._gcodes = LightGCode(gcodes[0:2000])
            try:
                '''
                Force operational state and wait for print_thread to start,
                because while starting print following condition (interpreted as error) arise:
                printcore.printing == True and print_thread.is_alive() == False
                '''
                self._force_operational = True
                if self._printer.startprint(self._gcodes):
                    time.sleep(2)
                    self._append_buffer += gcodes[2000:]
                else:
                    self._logger.critical('Error starting print')
            finally:
                self._force_operational = False

    def end(self):
        self._logger.debug('End debug info : ' + self._debug_info())
        self._got_all_gcodes = True

    def pause(self):
        self._logger.debug(self._debug_info())
        self._printer.pause()
        gcode = 'G1 Z' + str(self._printer.pauseZ + self._pause_lift_height) + \
                ' E' + str(self._printer.pauseE - self._pause_extrude_length)
        self._printer.send_now(gcode)

    def resume(self):
        self.unpause()

    def unpause(self):
        self._logger.debug(self._debug_info())
        if self._printer.paused:
            gcode = 'G1 Z' + str(self._printer.pauseZ) + ' E' + str(self._printer.pauseE)
            self._printer.send_now(gcode)
            self._printer.resume()

    def cancel(self):
        self.stop()
        self._printer.reset()
        self._printer.disconnect()

    def stop(self):
        self._logger.debug(self._debug_info())
        self._stop_append()
        self._printer.cancelprint()
        self._got_all_gcodes = True
        self._last_percent = 100

    def emergency_stop(self):
        self.cancel()

    def is_paused(self):
        self._logger.debug('Is_paused debug info : ' + self._debug_info())
        return self._printer.paused

    def is_printing(self):
        self._logger.debug('Is_printing debug info : ' + self._debug_info())
        if self._printing:
            if self._got_all_gcodes and not self._printer.printing and not self._printer.paused:
                self._printing = False
        return self._printing

    def is_operational(self):
        if self._force_operational:
            return True
        return self._printer.online and \
               not self._was_error and \
               self._is_threads_alive()

    def _is_threads_alive(self):
        if self._printer.printing:
            return self._printer.read_thread and \
                   self._printer.read_thread.is_alive() and \
                   self._printer.print_thread and \
                   self._printer.print_thread.is_alive()
        if self._printer.paused or self._printer.online:
            return self._printer.read_thread and \
                   self._printer.read_thread.is_alive() and \
                   self._printer.send_thread and \
                   self._printer.send_thread.is_alive()
        return True

    def is_error(self):
        return self._was_error or not self._is_threads_alive()

    def get_error(self):
        if self._was_error:
            self._logger.warning('Error occured while working.')
            return {'code': self._error_code, 'message': self._error_message}
        if not self._is_threads_alive():
            return {'code': 'serial', 'message': 'No connection to printer'}
        return {}

    def get_tool_temp(self, i):
        return self._tool_temp[i]

    def get_tool_target_temp(self, i):
        return self._tool_target_temp[i]

    def get_platform_temp(self):
        return self._platform_temp

    def get_platform_target_temp(self):
        return self._platform_target_temp

    def get_state(self):
        pass

    def set_state(self):
        pass

    def close(self):
        self._logger.debug('Close debug info : ' + self._debug_info())
        self._printer.disconnect()
        self._temp_request_active = False
        self._temp_request_thread.join()
        self._stop_append()

    def _get_percent(self):
        if len(self._gcodes) == 0 or self._length == 0:
            return 0
        if not self.is_printing():
            return 100
        if self._printer.queueindex == 0:  # when underflow print will be completed and queueindex = 0
            return self._last_percent
        return round((float(self._printer.queueindex) / self._length)*100, 2)

    def get_percent(self):
        self._logger.debug(self._debug_info())
        self._last_percent = self._get_percent()
        self._logger.debug('percent: ' + str(self._last_percent))
        return self._last_percent

    def get_remaining_gcode_count(self):
        pass

    def send(self, gcodes):
        if not self.is_printing():
            for gcode in gcodes:
                self._printer.send_now(gcode)

    def report(self):
        tool_temp = [0, 0]
        tool_target_temp = [0, 0]
        platform_temp = 0
        platform_target_temp = 0
        percent = 0
        if not self.is_operational():
            status = 'no_printer'
        elif not self.is_printing():
            status = 'ready'
            tool_temp = [
                self.get_tool_temp(0),
                self.get_tool_temp(1)
            ]
            tool_target_temp = [
                self.get_tool_target_temp(0),
                self.get_tool_target_temp(1)
            ]
            platform_temp = self.get_platform_temp()
            platform_target_temp = self.get_platform_target_temp()
            percent = self.get_percent()
        else:
            tool_temp = [
                self.get_tool_temp(0),
                self.get_tool_temp(1)
            ]
            tool_target_temp = [
                self.get_tool_target_temp(0),
                self.get_tool_target_temp(1)
            ]
            tool_ready = [
                abs(tool_target_temp[0] - tool_temp[0]) < 10,
                abs(tool_target_temp[1] - tool_temp[1]) < 10
            ]
            platform_temp = self.get_platform_temp()
            platform_target_temp = self.get_platform_target_temp()
            platform_ready = platform_target_temp < 5 or abs(platform_target_temp - platform_temp) < 10
            if platform_ready and (tool_ready[0] or tool_ready[1]):
                status = 'printing'
            else:
                status = 'heating'
            percent = self.get_percent()
        result = {
            #'position' : self._position,
            'status': status,
            'platform_temperature': platform_temp,
            'platform_target_temperature': platform_target_temp,
            'toolhead1_temperature': tool_temp[0],
            'toolhead1_target_temperature': tool_target_temp[0],
            'toolhead2_temperature': tool_temp[1],
            'toolhead2_target_temperature': tool_target_temp[1],
            'percent': percent,
            'buffer_free_space': 10000,
            'last_error':  self.get_error()
        }
        return result

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    p = Printer({"name" : "test", "COM" : "/dev/ttyACM0", "baudrate" : [115200, 250000], "end_gcodes" : [], "reconnect_on_cancel" : False, "extruder_count" :1})