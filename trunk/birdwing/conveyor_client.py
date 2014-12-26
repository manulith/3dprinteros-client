from __future__ import (absolute_import, print_function, unicode_literals)
import logging
import json
import select
import time

import logging
import conveyor_path

conveyor_path.conveyor_loader.prepare_conveyor_import()

import conveyor.client
import conveyor.main
import conveyor.platform
import conveyor.log
import conveyor.error
import conveyor.stoppable
import conveyor.machine

from conveyor.machine import MachineState

RESULT_TIMEOUT = 5 # in seconds

def set_attr_from_dict(obj, dct):
    for arg_name in dct.keys():
        arg_value = dct[arg_name]
        setattr(obj, arg_name, arg_value)
    return obj


class GetPrinters(conveyor.client.PrintersCommand):
    def __init__(self, parsed_args, config):
        self.logger = logging.getLogger('main')
        #self.logger.propagate = True
        self.result_flag = False
        conveyor.client.PrintersCommand.__init__(self, parsed_args, config)

    def _handle_result_default(self, result):
        self.logger.debug("Get printers:")
        for printer in result:
            self.logger.debug(printer)
        for machine in result:
            if machine['state'] != MachineState.DISCONNECTED:
                self.machine_name = self.parse_to_conveyor_readable_name(machine['name'])
                self.iserial = machine['name']['iserial']
                self.type = machine['printer_type']
                self.display_name = machine['display_name']
                self.result_flag = True
                break

    def parse_to_conveyor_readable_name(self, name_dct):
        serial = name_dct['iserial']
        #TODO get real VID:PID, not the first letters of serial number
        conveyor_readble_name = serial[0:4] + ':' + serial[4:8] + ':' + serial
        return conveyor_readble_name

class GetPrinterInfo(GetPrinters):
    def _handle_result_default(self, result):
        expected_machine_name = getattr(self._parsed_args, 'machine_name')
        if expected_machine_name:
            for machine in result:
                machine_name = self.parse_to_conveyor_readable_name(machine['name'])
                if expected_machine_name == machine_name:
                    break
        #self.machine_name = machine_name
        #self.logger.debug("Printer:")
        #self.logger.debug(machine)
        if 'platform_temperature' in machine:
            self.platform_temperature = machine['platform_temperature']
        else:
            self.platform_temperature = 0
        if 'machine_info' in machine:
            self.toolhead_temperature = machine['machine_info']['extruder_temp'] #machine['toolhead_temperature'] for some others
        else:
            self.toolhead_temperature = 0
        self.state = machine['state']
        self.result_flag = True


class Jobs(conveyor.client.JobsCommand):
    def __init__(self, parsed_args, config):
        self.logger = logging.getLogger('main')
        self.result_flag = False
        conveyor.client.JobsCommand.__init__(self, parsed_args, config)
        self.print_progress = 1

    def _handle_result_default(self, jobs):
        print_jobs = filter(lambda x:x['type'] == 'PrintJob', jobs)
        # research ability to use filter by conclusion == None
        print_jobs = filter(lambda x:x['conclusion'] not in ('ENDED', 'CANCELED'), print_jobs)
        self.logger.debug("Jobs:")
        self.logger.debug(print_jobs)
        if len(list(print_jobs)) == 1:
            print_job = print_jobs[0]
            self.print_job_id = print_job['id']
            self.print_job_state = print_job['state']
            self.logger.debug('job_id" ' + str(self.print_job_id))
            if 'progress' in print_job:
                self.logger.debug("Jobs has progress")
                self.progress_name = print_job['progress']['name']
                progress = print_job['progress']['progress']
                if self.progress_name == 'printing':
                    self.print_progress = min(progress, 95)
                elif self.progress_name == 'end_sequence':
                    self.print_progress = max(progress, 95)
                self.result_flag = True
                self.logger.debug(self.progress_name, self.print_progress)
        elif len(list(print_jobs)) > 1:
            print('len > 1')
            message = 'Error! Jobs command returned more than one print job. Can`t determine our job.'
            raise RuntimeError(message)
        else:
            raise Exception('Something went wrong: jobs are empty')


class Print(conveyor.client.PrintFromFileCommand):
    # machine_name , input_file
    pass


class Pause(conveyor.client.JobPauseCommand):
    # job_id
    pass       


class Cancel(conveyor.client.CancelCommand):
    # job_id
    pass


class Resume(conveyor.client.JobResumeCommand):
    # job_id
    pass


class Disconnect(conveyor.client.DisconnectCommand):
    # machine_name
    pass


class TurnOnCamera(conveyor.client.ToggleCameraCommand):
    # machine_name
    def __init__(self, parsed_args, config):
        parsed_args = set_attr_from_dict(parsed_args, {'toggle' : '--toggle-on'})
        conveyor.client.ToggleCameraCommand.__init__(self, parsed_args, config)


class TurnOffCamera(conveyor.client.ToggleCameraCommand):
    # machine_name
    def __init__(self, parsed_args, config):
        parsed_args = set_attr_from_dict(parsed_args, {'toggle' : '--toggle-off'})
        conveyor.client.ToggleCameraCommand.__init__(self, parsed_args, config)


class ConveyorClient(conveyor.main.AbstractMain):
    _program_name = 'conveyor'
    _config_section = 'client'
    _logging_handlers = ['stdout', 'stderr',]

    def __init__(self, command_cls, add_args={}):        
        self.command_cls = command_cls        
        conveyor.main.AbstractMain.__init__(self)        
        self.toolhead_temperature = None
        self.printer_type_for_human = None
        self.command_cls = command_cls
        self._parsed_args = self.create_args_obj(add_args)                
        self.main()

    # Hack for conveyor.main.AbstractMain to work without command line arguments   
    def create_args_obj(self, args_dct):
        #TODO: change to logging.DEBUG to logging.INFO in release!
        default_args = {
            'config_file' : conveyor.platform.DEFAULT_CONFIG_FILE,
            'level_name' : logging.DEBUG,
            'json' : False,""
        }
        args_dct.update(default_args)
        class parsed_args_cls(object):
            pass
        parsed_args = parsed_args_cls()
        dummy_obj = set_attr_from_dict(parsed_args, args_dct) 
        return dummy_obj

    def main(self):        
        try:
            self._load_config()
            self._init_logging()
            self._run()
        except Exception as e:
            self.logger.debug(e)
        finally:
            conveyor.stoppable.StoppableManager.stopall()
            for thread in self._event_threads:
                thread.join(1)
                if thread.is_alive():
                    print('thread not terminated: %r', thread)

    # result are coming from another thread, so we need to wait for result_flag if command has one
    def wait_for_result(self, command_obj):
        count = 0
        if hasattr(command_obj, 'result_flag'):
            while not command_obj.result_flag:
                time.sleep(0.1)
                count += 1
                if count > RESULT_TIMEOUT * 10:
                    class_name = str(command_obj.__class__)
                    message = "Error! Conveyor failed to produce result of command" + class_name
                    self.logger.info(message)
                    raise RuntimeError(message)
            return command_obj

    def _run(self):
        self.logger = logging.getLogger('main')
        self.logger.debug('Starting: ' + str(self.command_cls.__name__))
        self._log_startup(logging.INFO)
        self.logger.debug('Done log_startup of : ' + str(self.command_cls.__name__))
        self._init_event_threads()
        self.logger.debug('Done init event threads: ' + str(self.command_cls.__name__))
        #self.logger.propagate = True
        command_obj = self.command_cls(self._parsed_args, self._config)
        self.logger.debug('Done constructor for command obj ' + str(self.command_cls.__name__))
        # Guard against conveyor`s own bugs(plenty of them)
        try:
            command_obj.run()
        except (IOError, KeyError, select.error) as e:
            self.logger.debug(e)
        # this is the only way to get data from object that had errors in it
        finally:
            self.command_obj = self.wait_for_result(command_obj)
            self.logger.debug('Done execution of: ' +  str(self.command_cls.__name__))