import threading
import time
import collections
import logging
import tempfile
import os
import ctypes

class Printer():

    STATE_NONE = 0
    STATE_READY = 1
    STATE_PRINTING = 2
    STATE_PRINTING_LOCALLY = 3
    STATE_PAUSED = 4
    STATE_CLOSED = 5
    STATE_RETRYABLE_ERROR = 6
    STATE_FATAL_ERROR = 7
    STATE_CANCELLED = 8

    def __init__(self, printer_dct):
        # Stub
        self._printer_name = printer_dct['printer_name']

        self._dll_lib = ctypes.windll.LoadLibrary('dll-name.dll')
        self._logger = logging.getLogger('main.c_printer')
        self._logger.propagate = True
        self._logger.setLevel(logging.DEBUG)
        self._buffer = collections.deque()
        self._state = self.STATE_READY
        self._actual_state = self.STATE_NONE
        self._state_before_error = self.STATE_READY
        self._percent = 0
        self._error_code = ''
        self._error_message = ''
        self._platform_temp = 0
        self._platform_ttemp = 0
        self._head_temp = [0, 0]
        self._head_ttemp = [0, 0]
        self._lock = threading.Lock()
        self._printing_thread = threading.Thread(target=self._printing, name='PR')
        self._printing_thread.start()
        self._logger.info(self._printer_name + ' printer created')


    def get_error_code(self):
        return self._error_code

    def get_error_message(self):
        return self._error_message

    def get_printing_job_state(self):
        state = {}
        state['parser_state'] = self._parser.state
        state['eof']          = self._eof
        state['buffer']       = self._buffer
        state['state']        = self._state_before_error
        self._logger.info('State before error ' + str(state['state']))
        return state

    def set_printing_job_state(self, state):
        self._parser.state = state['parser_state']
        self._eof          = state['eof']
        self._buffer       = state['buffer']
        self._state        = state['state']
        self._logger.info('Restoring state ' + str(state['state']))


    # def begin(self, length):
    #     with self._lock:
    #         self._state = self.STATE_PRINTING


    # def end(self):
    #     with self._lock:
    #         self._eof = True
    #         self._logger.info('End of GCodes')

    def enqueue(self, binary_file):
        # with self._lock:
        #     if self._state != self.STATE_PRINTING:
        #         self._state = self.STATE_FATAL_ERROR
        #         self._error_code = 'protocol'
        #         self._error_message = 'Begin was not sent'
        #         return
        #
        #     self._buffer += gcodes
        #     self._logger.info('Enqueued block: ' + str(len(gcodes)) + ', total: ' + str(len(self._buffer)))
        self.tmp_file_ready = False
        self.tmp_file = None
        self.tmp_file = tempfile.NamedTemporaryFile(delete=False, prefix='conveyor-secured3d-', suffix='.makerbot')
        self.tmp_file.write(binary_file)
        self.tmp_file.close()
        tmp_file_path = os.path.abspath(self.tmp_file.name)
        # TODO: Call print here with file path argument


    def pause(self):
        with self._lock:
            if self._state != self.STATE_PRINTING:
                return
            self._state = self.STATE_PAUSED
            self._wait_for_actual_status(self.STATE_PAUSED)

    def _pause(self):
        # TODO: pause call here
        pass

    def resume(self):
        with self._lock:
            if self._state == self.STATE_PAUSED:
                self._state = self.STATE_PRINTING

    def cancel(self):
        with self._lock:
            self._state = self.STATE_CANCELLED

    def _cancel(self):
        # TODO: should we send any cancel call?
        pass

    def emergency_stop(self):
        self.cancel()

    # def reset(self):
    #     with self._lock:
    #         self._state = self.STATE_READY


    def get_state(self):
        return self._state

    def get_platform_temp(self):
        return self._platform_temp

    def get_platform_ttemp(self):
        return self._platform_ttemp

    def get_head_temp(self, i):
        return self._head_temp[i]

    def get_head_ttemp(self, i):
        return self._head_ttemp[i]

    def get_percent(self):
        return self._percent

    def close(self):
        self._logger.info('Closing ' + self._printer_name + ' Printer')
        with self._lock:
            self._state = self.STATE_CLOSED

    def _close(self):
        # TODO: Close call here
        pass

    def _wait_for_actual_status(self, status):
        while self._actual_state != status:
            if not self._printing_thread.is_alive():
                return
            time.sleep(0.1)


    def _read_state(self):
        # TODO: State calls here
        pass
        #self._platform_temp =
        #self._platform_ttemp =
        #self._head_temp[0] =
        #self._head_ttemp[0] =
        #self._head_temp[1] =
        #self._head_ttemp[1] =


    def _read_temps(self):
        # TODO: Temps calls here
        pass
        #self._platform_temp =
        #self._head_temp[0] =
        #self._head_temp[1] =


    def is_printing(self):
        printing = [
            self.STATE_PRINTING,
            self.STATE_PRINTING_LOCALLY,
            self.STATE_PAUSED
        ]
        return self.get_state() in printing

    def is_error(self):
        return self.get_state() in [self.STATE_FATAL_ERROR, self.STATE_RETRYABLE_ERROR]

    def is_operational(self):
        return self.is_printing() or \
               self.get_state() in [self.STATE_READY, self.STATE_CANCELLED]

    def is_paused(self):
        return self.get_state() == self.STATE_PAUSED

    def _printing(self):
        is_heating        = False
        while True:
            if self._state == self.STATE_READY:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_READY')
                self._read_state()
                # keep warm enabled printer goes to PRINTING_LOCALLY
                # if self._is_physically_printing():
                #     if not self.get_percent() == 100:
                #         self._state = self.STATE_PRINTING_LOCALLY
                time.sleep(1)
            elif self._state == self.STATE_PRINTING_LOCALLY:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_PRINTING_LOCALLY')
                self._read_state()
                if not self.is_printing():
                    self._state = self.STATE_READY
                time.sleep(1)
            elif self._state == self.STATE_PAUSED:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._pause()
                    self._logger.info('State is STATE_PAUSED')
                self._read_state()
                time.sleep(1)
            elif self._state == self.STATE_PRINTING:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_PRINTING')
                if is_heating:
                    self._read_temps()
                    ready    = (self._platform_temp > self._platform_ttemp) or (self._platform_ttemp - self._platform_temp) < 5
                    h1_ready = (self._head_temp[0] > self._head_ttemp[0]) or (self._head_ttemp[0] - self._head_temp[0]) < 5
                    h2_ready = (self._head_temp[1] > self._head_ttemp[1]) or (self._head_ttemp[1] - self._head_temp[1]) < 5
                    if (self._platform_ttemp == 0 or ready) and (self._head_ttemp[0] == 0 or h1_ready) and (self._head_ttemp[1] == 0 or h2_ready):
                        is_heating = False
                        self._logger.info('Heating is done')
                    time.sleep(1)
                    continue
            elif self._state == self.STATE_CLOSED:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_CLOSED')
                self._close()
                return
            elif self._state == self.STATE_FATAL_ERROR:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_FATAL_ERROR')
                return
            elif self._state == self.STATE_RETRYABLE_ERROR:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_RETRYABLE_ERROR')
                return
            elif self._state == self.STATE_CANCELLED:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_CANCELLED')
                self._cancel()
                self._read_state()
                time.sleep(1)

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
                self.get_head_temp(0),
                self.get_head_temp(1)
            ]
            tool_target_temp = [
                self.get_head_ttemp(0),
                self.get_head_ttemp(1)
            ]
            platform_temp = self.get_platform_temp()
            platform_target_temp = self.get_platform_ttemp()
            percent = self.get_percent()
        else:
            tool_temp = [
                self.get_head_temp(0),
                self.get_head_temp(1)
            ]
            tool_target_temp = [
                self.get_head_ttemp(0),
                self.get_head_ttemp(1)
            ]
            tool_ready = [
                abs(tool_target_temp[0] - tool_temp[0]) < 10,
                abs(tool_target_temp[1] - tool_temp[1]) < 10
            ]
            platform_temp = self.get_platform_temp()
            platform_target_temp = self.get_platform_ttemp()
            platform_ready = platform_target_temp < 5 or abs(platform_target_temp - platform_temp) < 10
            if platform_ready and (tool_ready[0] or tool_ready[1]):
                status = 'printing'
            else:
                status = 'heating'
            percent = self.get_percent()
        if self.get_error_code():
            error = { "code" : self.get_error_code(), "message" : self.get_error_message() }
        else:
            error = {}
        result = {
            #'position' : [self._position[0][0], self._position[0][1], self._position[0][2]],
            'status': status,
            'platform_temperature': platform_temp,
            'platform_target_temperature': platform_target_temp,
            'toolhead1_temperature': tool_temp[0],
            'toolhead1_target_temperature': tool_target_temp[0],
            'toolhead2_temperature': tool_temp[1],
            'toolhead2_target_temperature': tool_target_temp[1],
            'percent': percent,
            'buffer_free_space': 10000,
            'last_error':  error
        }
        return result