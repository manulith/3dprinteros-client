# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/job.py
#
# conveyor - Printing dispatch engine for 3D objects and their friends.
# Copyright 2012 MakerBot Industries, LLC
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, print_function, unicode_literals)

import copy
import os
import threading

import conveyor.enum
import conveyor.event

JobState = conveyor.enum.enum('JobState',  # enum name
        'PENDING', 'RUNNING', 'STOPPED', 'PAUSED')
# Valid State Transitions are limited. see docs/job.png for state diagram

JobEvent = conveyor.enum.enum(
    'JobEvent', 'START', 'PAUSE', 'UNPAUSE', 'HEARTBEAT', 'END', 'FAIL',
    'CANCEL')
# Valid State Transitions are limited. see docs/job.png for state diagram

JobConclusion = conveyor.enum.enum(
    'JobConclusion', 'ENDED', 'FAILED', 'CANCELED')
# Valid State Transitions are limited. see docs/job.png for state diagram


class IllegalTransitionException(Exception):
    """ Exception for an illegal state change of Job state machine """
    def __init__(self, state, event):
        Exception.__init__(self, state, event)
        self.state = state
        self.event = event

class JobCounter(object):
    """
    A job counter to keep track of the ID of all conveyor jobs.
    """
    _instance = None

    @staticmethod
    def get_instance():
        if JobCounter._instance == None:
            JobCounter._instance = JobCounter()
        return JobCounter._instance

    @staticmethod
    def create_job_id():
        instance = JobCounter.get_instance()
        return instance.get_job_id()

    def __init__(self):
        self._id_condition = threading.Condition()
        self._counter = 0

    def get_job_id(self):
        with self._id_condition:
            _id = self._counter
            self._counter += 1
        return _id

class Job(object):
    def __init__(self, id_=-1, name="job", state=JobState.PENDING):
        """
        Creates a stateful job object, which encapsulates all the data and
        functionality needed to properly execute a job.  We can optionally
        start in a specific state, to support discovering jobs that have
        been started by remote clients.
        """
        self._log = conveyor.log.getlogger(self)
        self.type = self.__class__.__name__
        self.id = id_
        self.name = name
        self.pausable = False
        self.changed_callbacks = []
        self._extra_info = {}
        self.state = state
        self.conclusion = None
        self.progress = None # data from 'heartbeat'
        self.result = None   # data from 'end'
        self.failure = None  # data from 'fail'
        self.can_cancel = True

        eventqueue = conveyor.event.geteventqueue()

        # Event events (edge-ish events)
        self.startevent = conveyor.event.Event('Job.startevent', eventqueue,
            sequence=True)
        self.pauseevent = conveyor.event.Event('Job.pauseevent', eventqueue,
            sequence=True)
        self.unpauseevent = conveyor.event.Event('Job.unpauseevent',
            eventqueue,
            sequence=True)
        self.heartbeatevent = conveyor.event.Event(
            'Job.heartbeatevent', eventqueue,
            sequence=True)
        self.endevent = conveyor.event.Event('Job.endevent', eventqueue,
            sequence=True)
        self.failevent = conveyor.event.Event('Job.failevent', eventqueue,
            sequence=True)
        self.cancelevent = conveyor.event.Event('Job.cancelevent', eventqueue,
            sequence=True)

        # State events (level-ish events)
        self.runningevent = conveyor.event.Event(
            'Job.runningevent', eventqueue, sequence=True)
        self.stoppedevent = conveyor.event.Event(
            'Job.stoppedevent', eventqueue, sequence=True)

    def add_extra_info(self, key, value, callback=True):
        """
        Adds an aditional key,val pair to the job's info dict
        """
        if(self._extra_info.get(key) == value):
            return
        self._extra_info[key] = value
        if callback:
            self._invoke_changed_callbacks()

    def pop_extra_info(self, key, callback=True):
        """
        Removes a specific key from the job's info dict
        """
        self._extra_info.pop(key)
        if callback:
            self._invoke_changed_callbacks()

    def attach_changed_callback(self, callback):
        """
        Job objects have a list of changed_callbacks that are executed when
        some aspect of the job changes we want connected clients to be
        notified about.
        """
        self.changed_callbacks.append(callback)

    def _invoke_changed_callbacks(self):
        for callback in self.changed_callbacks[::-1]:
            try:
                callback(self)
            except Exception as e:
                self._log.info("ERROR: error executing job changed callback, removing callback from callback list", exc_info=True)
                self.changed_callbacks.remove(callback)

    def set_pausable(self, callback=True):
        self.pausable = True
        if callback:
            self._invoke_changed_callbacks()

    def set_not_pausable(self, callback=True):
        self.pausable = False
        if callback:
            self._invoke_changed_callbacks()

    def set_cancellable(self, callback=True):
        self.can_cancel = True
        if callback:
            self._invoke_changed_callbacks()

    def set_not_cancellable(self, callback=True):
        self.can_cancel = False
        if callback:
            self._invoke_changed_callbacks()

    def _get_machine_name(self):
        return None

    def _get_driver_name(self):
        return None

    def _get_profile_name(self):
        return None

    def _get_state(self):
        return self.state

    def _get_progress(self):
        return self.progress

    def _get_failure(self):
        return self.failure

    def _get_conclusion(self):
        return self.conclusion

    def get_info(self):
        info = {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "state": self._get_state(),
            "progress": self._get_progress(),
            "conclusion": self._get_conclusion(),
            "failure": self._get_failure(),
            "machine_name": self._get_machine_name(),
            "driver_name": self._get_driver_name(),
            "profile_name": self._get_profile_name(),
            "pausable": self.pausable,
            "can_cancel": self.can_cancel,
        }
        info.update(self._extra_info)
        return info

    def log_job_started(self, log):
        self._log.info("Job %r started", self.name)

    def log_job_heartbeat(self, log):
        progress = self._get_progress()
        if progress:
            log.debug(
                'job %d: progress: %s, %d%%', self.id, progress['name'],
                progress['progress'])

    def log_job_stopped(self, log):
        conclusion = self._get_conclusion()
        if conclusion == JobConclusion.ENDED:
            log.info('job %d: ended', self.id)
        elif conclusion == JobConclusion.FAILED:
            failure = self._get_failure()
            log.error('job %d: failed: %r', self.id, failure)
        elif conclusion == JobConclusion.CANCELED:
            log.warning('job %d: canceled', self.id)
        else:
            raise ValueError(conclusion)

    def _transition(self, event, data):
        if self.state == JobState.PENDING:
            if event == JobEvent.START:
                self.state = JobState.RUNNING
                self.startevent(self)
                self.runningevent(self)
            elif event == JobEvent.CANCEL:
                self.state = JobState.STOPPED
                self.conclusion = JobConclusion.CANCELED
                self.cancelevent(self)
                self.stoppedevent(self)
            else:
                raise IllegalTransitionException(self.state, event)
        elif self.state == JobState.RUNNING:
            if event == JobEvent.HEARTBEAT:
                self.progress = data
                self.heartbeatevent(self)
            elif event == JobEvent.PAUSE:
                self.state = JobState.PAUSED
                self.pauseevent(self)
            elif event == JobEvent.END:
                self.state = JobState.STOPPED
                self.conclusion = JobConclusion.ENDED
                self.result = data
                self.endevent(self)
                self.stoppedevent(self)
            elif event == JobEvent.FAIL:
                self.state = JobState.STOPPED
                self.conclusion = JobConclusion.FAILED
                self.failure = data
                self.failevent(self)
                self.stoppedevent(self)
            elif event == JobEvent.CANCEL:
                self.state = JobState.STOPPED
                self.conclusion = JobConclusion.CANCELED
                self.cancelevent(self)
                self.stoppedevent(self)
            else:
                raise IllegalTransitionException(self.state, event)
        elif self.state == JobState.PAUSED:
            if event == JobEvent.UNPAUSE:
                self.state = JobState.RUNNING
                self.unpauseevent(self)
            elif event == JobEvent.CANCEL:
                self.state = JobState.STOPPED
                self.conclusion = JobConclusion.CANCELED
                self.cancelevent(self)
                self.stoppedevent(self)
            elif event == JobEvent.FAIL:
                self.state = JobState.STOPPED
                self.conclusion = JobConclusion.FAILED
                self.failure = data
                self.failevent(self)
                self.stoppedevent(self)
            else:
                raise IllegalTransitionException(self.state, event)
        elif self.state == JobState.STOPPED:
            raise IllegalTransitionException(self.state, event)
        else:
            raise ValueError(self.state)

    def start(self):
        """ Sets the Job in to active mode, where it can accept heartbeats,
        events, etc
        """
        self._transition(JobEvent.START, None)


    def heartbeat(self, progress):
        """Post a heartbeat update.
        @param progress dict of { 'name':$PROGRESS, 'progress':$INT_PERCENT_PROGRESS }
        """
        self._log.debug(progress)
        self._transition(JobEvent.HEARTBEAT, progress)

    def lazy_heartbeat(self, progress):
        """
        This doesnt work well.  We need to keep generating new
        dicts to pass into this, since the job has a reference
        to the actual progress dict being passed in.  It makes for
        unnecessary creation of objects and poor handling of them
        in the actual job objects.
        """
        try:
            copy_progress= copy.deepcopy(self.progress)
            if copy_progress != progress:
                self.heartbeat(progress)
        except:
             self._log.info("ERROR: error sending hearbeat", exc_info=True)


    def pause(self):
        self._transition(JobEvent.PAUSE, None)

    def unpause(self):
        self._transition(JobEvent.UNPAUSE, None)

    def end(self, result):
        self._transition(JobEvent.END, result)

    def fail(self, failure):
        self._transition(JobEvent.FAIL, failure)

    def cancel(self):
        self._transition(JobEvent.CANCEL, None)

    def ispending(self):
        return self.state == JobState.PENDING

    def isrunning(self):
        return self.state == JobState.RUNNING

    def ispaused(self):
        return self.state == JobState.PAUSED

    def isstopped(self):
        return self.state == JobState.STOPPED

    def isended(self):
        return self.conclusion == JobConclusion.ENDED

    def isfailed(self):
        return self.conclusion == JobConclusion.FAILED

    def iscanceled(self):
        return self.conclusion == JobConclusion.CANCELED


class JogJob(Job):
    def __init__(self, id, name):
        super(JogJob, self).__init__(id, name)

    def log_job_started(self, log):
        log.info('job %d: started jogging', self.id)


class RecipeJob(Job):
    DeviceFamily = conveyor.enum.enum("DeviceFamily", "LEGACY", "BIRDWING",
        "AGNOSTIC")

    def get_has_start_end(self):
        raise NotImplementedError

    def get_add_start_end(self):
        raise NotImplementedError

    def get_profile(self):
        raise NotImplementedError

    def _derive_device_family(self):
        raise NotImplementedError

class StrictlyPrintJob(Job):
    def __init__(self, id, name, machine, state=JobState.PENDING):
        super(StrictlyPrintJob, self).__init__(id, name, state)
        self.machine = machine

    def _get_machine_name(self):
        return self.machine.name

    def _get_driver_name(self):
        return self.machine.get_driver().name

    def _get_profile_name(self):
        return self.machine.get_profile().name

    def log_job_started(self, log):
        log.info('job %d: started printing: %s', self.id, self.machine.name)


class PrintJob(RecipeJob):
    def __init__(
            self, id, name, machine, input_file,
            has_start_end, slicer_settings, thumbnail_dir,
            metadata, username):
        super(PrintJob, self).__init__(id, name)
        self.thumbnail_dir = thumbnail_dir
        self.metadata = metadata or {}
        self.machine = machine
        self.input_file = input_file
        self.has_start_end = has_start_end
        self.slicer_settings = slicer_settings
        self.device_family = self._derive_device_family()
        self.username = username

    def _derive_device_family(self):
        if isinstance(self.machine, conveyor.machine.birdwing.BirdWingMachine):
            family = self.DeviceFamily.BIRDWING
        else:
            family = self.DeviceFamily.LEGACY
        return family

    def _get_machine_name(self):
        return self.machine.name

    def _get_driver_name(self):
        driver = self.machine.get_driver()
        return driver.name

    def _get_profile_name(self):
        profile = self.machine.get_profile()
        return profile.name

    def log_job_started(self, log):
        log.info(
            'job %d: started printing: %s -> %s', self.id, self.input_file,
            self.machine.name)

    def get_has_start_end(self):
        return self.has_start_end

    def get_add_start_end(self):
        return True

    def get_profile(self):
        profile = self.machine.get_profile()
        return profile

class StreamingPrintJob(StrictlyPrintJob):
    def __init__(self, id, name, machine,
                 layout_id, thingiverse_token, metadata_tmp_path):
        super(StreamingPrintJob, self).__init__(id, name, machine)
        self.machine = machine
        self.layout_id = layout_id
        self.thingiverse_token = thingiverse_token
        self.metadata_tmp_path = metadata_tmp_path

class PrintFromFileJob(RecipeJob):
    def __init__(self, id, name, machine, input_file, username):
        super(PrintFromFileJob, self).__init__(id, name)
        self.machine = machine
        self.input_file = input_file
        self.username = username
        self.device_family = self._derive_device_family()

    def _derive_device_family(self):
        if isinstance(self.machine, conveyor.machine.birdwing.BirdWingMachine):
            family = self.DeviceFamily.BIRDWING
        else:
            raise NotImplementedError
        return family

    def _get_machine_name(self):
        return self.machine.name

    def _get_driver_name(self):
        driver = self.machine.get_driver()
        return driver.name

    def _get_profile_name(self):
        profile = self.machine.get_profile()
        return profile.name

    def log_job_started(self, log):
        log.info(
            'job %d: started printing: %s -> %s', self.id, self.input_file,
            self.machine.name)

    def get_profile(self):
        profile = self.machine.get_profile()
        return profile


class PrintToFileJob(RecipeJob):
    def __init__(
            self, id, name,driver, profile, input_file, output_file,
            has_start_end, slicer_settings,
            thumbnail_dir, metadata):
        super(PrintToFileJob, self).__init__(id, name)
        self.thumbnail_dir = thumbnail_dir
        self.metadata = metadata or {}
        self.driver = driver
        self.profile = profile
        self.input_file = input_file
        self.output_file = output_file
        self.file_type = os.path.splitext(self.output_file)[-1]
        self.has_start_end = has_start_end
        self.slicer_settings = slicer_settings
        self.device_family = self._derive_device_family()

    def _derive_device_family(self):
        if self.file_type in ['.makerbot']:
            family = self.DeviceFamily.BIRDWING
        else:
            family = self.DeviceFamily.LEGACY
        return family

    def _get_driver_name(self):
        return self.driver.name

    def _get_profile_name(self):
        return self.profile.name

    def log_job_started(self, log):
        log.info(
            'job %d: started print-to-file: %s -> %s', self.id,
            self.input_file, self.output_file)

    def get_has_start_end(self):
        return self.has_start_end

    def get_add_start_end(self):
        return True

    def get_profile(self):
        return self.profile


class SliceJob(RecipeJob):
    def __init__(
            self, id, name,driver, profile, input_file, output_file,
            add_start_end,
            slicer_settings):
        super(SliceJob, self).__init__(id, name)
        self.driver = driver
        self.profile = profile
        self.input_file = input_file
        self.output_file = output_file
        self.add_start_end = add_start_end
        self.slicer_settings = slicer_settings
        self.device_family = self._derive_device_family()

    def _derive_device_family(self):
        if self.driver.name == "birdwing":
            family = self.DeviceFamily.BIRDWING
        else:
            family = self.DeviceFamily.LEGACY
        return family

    def _get_driver_name(self):
        return self.driver.name

    def _get_profile_name(self):
        return self.profile.name

    def log_job_started(self, log):
        log.info(
            'job %d: started slicing: %s -> %s', self.id, self.input_file,
            self.output_file)

    def get_has_start_end(self):
        return False

    def get_add_start_end(self):
        return self.add_start_end

    def get_profile(self):
        return self.profile

class ScanJob(RecipeJob):

    def __init__(self, id, name, scanner, point_data, rotation_resolution,
            exposure, intensity_threshold, laserline_peak, laser, archive,
            output_left_right, bounding_cylinder_top, bounding_cylinder_bottom,
            bounding_cylinder_radius, debug_output_path):
        super(ScanJob, self).__init__(id, name)
        self.input_file = None
        self.scanner = scanner
        self.point_data = point_data
        self.rotation_resolution = rotation_resolution
        self.exposure = exposure
        self.intensity_threshold = intensity_threshold
        self.laserline_peak = laserline_peak
        self.laser = laser
        self.archive = archive
        self.output_left_right = output_left_right
        self.bounding_cylinder_top = bounding_cylinder_top
        self.bounding_cylinder_bottom = bounding_cylinder_bottom
        self.bounding_cylinder_radius = bounding_cylinder_radius
        self.debug_output_path = debug_output_path

    def log_job_started(self, log):
        log.info('job %d: started scanning', self.id)

    def get_has_start_end(self):
        return False

    def get_add_start_end(self):
        return None

    def get_profile(self):
        return self.scanner.get_profile()


class CameraCalibrationJob(RecipeJob):

    def __init__(self, id, name, scanner, archive, debug_output_path):
        super(CameraCalibrationJob, self).__init__(id, name)
        self.input_file = None
        self.scanner = scanner
        self.archive = archive
        self.debug_output_path = debug_output_path

    def log_job_started(self, log):
        log.info('job %d: started camera calibration', self.id)

    def get_has_start_end(self):
        return False

    def get_add_start_end(self):
        return None

    def get_profile(self):
        return self.scanner.get_profile()

class TurntableCalibrationJob(RecipeJob):

    def __init__(self, id, name, scanner, archive, debug_output_path):
        super(TurntableCalibrationJob, self).__init__(id, name)
        self.input_file = None
        self.scanner = scanner
        self.archive = archive
        self.debug_output_path = debug_output_path

    def log_job_started(self, log):
        log.info('job %d: started turntable calibration', self.id)

    def get_has_start_end(self):
        return False

    def get_add_start_end(self):
        return None

    def get_profile(self):
        return self.scanner.get_profile()

class LoadFilamentJob(Job):
    def __init__(self, id_, name, machine):
        super(LoadFilamentJob, self).__init__(id_, name)
        self._machine = machine

    def _get_machine_name(self):
        return self._machine.name

    def _get_driver_name(self):
        return self._machine.get_driver().name

    def _get_profile_name(self):
        return self._machine.get_profile().name

    def log_job_started(self, log):
        log.info("job %d: started loading filament for %s", self.id, self._machine.name)

class ResetToFactoryJob(Job):
    def __init__(self, id_, name, machine):
        super(ResetToFactoryJob, self).__init__(id_, name)
        self._machine = machine

    def _get_machine_name(self):
        return self._machine.name

    def _get_driver_name(self):
        return self._machine.get_driver().name

    def _get_profile_name(self):
        return self._machine.get_profile().name

    def log_job_started(self, log):
        log.info("job %d: started reset to factory for %s", self.id, self._machine.name)

class ChangeChamberLightsJob(Job):
    def __init__(self, id_, name, machine):
        super(ChangeChamberLightsJob, self).__init__(id_, name)
        self._machine = machine

    def _get_machine_name(self):
        return self._machine.name

    def _get_driver_name(self):
        return self._machine.get_driver().name

    def _get_profile_name(self):
        return self._machine.get_profile().name

    def log_job_started(self, log):
        log.info("job %d: started change chamber lights for %s", self.id, self._machine.name)

class LoadPrintToolJob(Job):
    def __init__(self, id_, name, machine):
        super(LoadPrintToolJob, self).__init__(id_, name)
        self._machine = machine

    def _get_machine_name(self):
        return self._machine.name

    def _get_driver_name(self):
        return self._machine.get_driver().name

    def _get_profile_name(self):
        return self._machine.get_profile().name

    def log_job_started(self, log):
        log.info("job %d: started change print tool for %s", self.id, self._machine.name)

class UnloadFilamentJob(LoadFilamentJob):
    def __init__(self, id_, name, machine):
        super(UnloadFilamentJob, self).__init__(id_, name, machine)

    def log_job_started(self, log):
        log.info("job %d: started unloading filament for %s", self.id, self._machine.name)

class FirmwareJob(Job):
    def __init__(self, id_, name, machine):
        super(FirmwareJob, self).__init__(id_, name)
        self.machine = machine

class ZipLogsJob(Job):
    def __init__(self, id_, name, machine):
        super(ZipLogsJob, self).__init__(id_, name)
        self.machine = machine

class AnonymousJob(Job):
    def __init__(self, _type, id_, name, machine, state=JobState.PENDING):
        super(AnonymousJob, self).__init__(id_, name, state)
        self._machine = machine
        self.type = _type

    def _get_machine_name(self):
        return self._machine.name

    def _get_driver_name(self):
        return self._machine.get_driver().name

    def _get_profile_name(self):
        return self._machine.get_profile().name

    def log_job_started(self, log):
        log.info("Anonymous %s Job started", self.type)
