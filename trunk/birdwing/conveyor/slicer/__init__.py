# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/slicer/__init__.py
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

import cStringIO as StringIO
import logging
import os.path
import subprocess
import codecs
import sys

import conveyor.log
import conveyor.job
import conveyor.util


class Slicer(object):
    MIRACLEGRUE = 'miraclegrue'

    _name = None

    _display_name = None

    @staticmethod
    def get_gcode_scaffold(path):
        raise NotImplementedError

    def __init__(
            self, profile, input_file, output_file, slicer_settings, dualstrusion, 
            job):
        self._log = conveyor.log.getlogger(self)
        self._profile = profile
        self._input_file = input_file
        self._output_file = output_file
        self._slicer_settings = slicer_settings
        self._dualstrusion = dualstrusion
        self._job = job

    def _setprogress(self, new_progress):
        """
        posts progres update to our job, lazily
        @param new_progress progress dict of {'name':$NANME 'progress'$INT_PERCENT }
        """
        self._job.lazy_heartbeat(new_progress)

    def _setprogress_percent(self, percent, pMin=1, pMax=99):
        """ Sets a progress update as percent, clipped to pMin, pMax
        @param percent integer percent for progress update
        @param pMin percent min, default is 1 (0 is a special 'start' case)
        @param pMax percent max, default is 99 (100 is a special 'start' case)
        """
        clamped_percent= min(pMax, max(percent, pMin))
        progress = {'name': 'slice','progress': clamped_percent }
        self._setprogress(progress)

    def _setprogress_ratio(self, current, total):
        """ sets progress based on current(int) and total(int)
        @param current: current integer index
        @param total:   expected total count
        TRICKY: This will not report 0% or 100%, those are special edge cases
        """
        # At the least we want to return 1
        ratio = max(1, int(99 * current / total))
        progress = {'name': 'slice','progress': ratio }
        self._setprogress(progress)

    def slice(self):
        raise NotImplementedError


class SubprocessSlicerException(Exception):
    pass


class SubprocessSlicer(Slicer):
    def __init__(
            self, profile, input_file, output_file, slicer_settings,
            dualstrusion, job, slicer_file):
        super(SubprocessSlicer, self).__init__(profile, input_file, output_file, 
            slicer_settings, dualstrusion, job)
        self._popen = None
        self._slicerlog = None
        self._code = None
        self._slicer_file = slicer_file

    def slice(self):
        try:
            progress = {'name': 'slice', 'progress': 0}
            self._setprogress(progress)
            self._prologue()
            executable = self._get_executable()
            quoted_executable = self._quote(executable)
            arguments = list(self._get_arguments())
            quoted_arguments = ' '.join(self._quote(a) for a in arguments)
            self._log.info('executable: %s', quoted_executable)
            self._log.info('command: %s', quoted_arguments)
            cwd = self._get_cwd()

            if None is cwd:
                path = executable
            else:
                path = os.path.join(cwd, executable)
                cwd = cwd.encode(sys.getfilesystemencoding())
            if not os.path.exists(path):
                raise conveyor.error.MissingExecutableException(path)
				
            # Encode arguments according to file system encoding
			for arg in arguments:
                idx = arguments.index(arg)
                arguments[idx] = arguments[idx].encode(sys.getfilesystemencoding())
            executable = executable.encode(sys.getfilesystemencoding())

            self._popen = subprocess.Popen(
                arguments, executable=executable, stdout=codecs.getwriter(sys.getfilesystemencoding())(subprocess.PIPE),
                stderr=codecs.getwriter(sys.getfilesystemencoding())(subprocess.STDOUT), cwd=cwd)
            def cancel_callback(task):
                self._popen.terminate()
            self._job.cancelevent.attach(cancel_callback)
            self._slicerlog = StringIO.StringIO()
            self._read_popen()
            slicerlog = self._slicerlog.getvalue()
            self._code = self._popen.wait()
            try:
                self._popen.stdout.close()
            except:
                self._log.debug('handled exception', exc_info=True)
            try:
                if None is not self._popen.stderr:
                    self._popen.stderr.close()
            except:
                self._log.debug('handled exception', exc_info=True)
            if (0 != self._code
                    and conveyor.job.JobConclusion.CANCELED != self._job.conclusion):
                self._log.error(
                    '%s terminated with code %s:\n%s', self._display_name,
                    self._code, slicerlog)
                failure = self._get_failure(None)
                self._job.fail(failure)
            else:
                self._log.debug(
                    '%s terminated with code %s', self._display_name,
                    self._code)
                self._epilogue()
                if conveyor.job.JobConclusion.CANCELED != self._job.conclusion:
                    progress = {'name': 'slice', 'progress': 100}
                    self._setprogress(progress)
        except SubprocessSlicerException as e:
            self._log.debug('handled exception', exc_info=True)
            if conveyor.job.JobConclusion.CANCELED != self._job.conclusion:
                failure = self._get_failure(e)
                self._job.fail(failure)
        except OSError as e:
            self._log.error('operating system error', exc_info=True)
            if conveyor.job.JobConclusion.CANCELED != self._job.conclusion:
                failure = self._get_failure(e)
                self._job.fail(failure)
        except Exception as e:
            self._log.error('unhandled exception', exc_info=True)
            if conveyor.job.JobConclusion.CANCELED != self._job.conclusion:
                failure = self._get_failure(e)
                self._job.fail(failure)
        else:
            self._job.cancelevent.detach(cancel_callback)

    def _prologue(self):
        raise NotImplementedError

    def _get_executable(self):
        raise NotImplementedError

    def _get_arguments(self):
        raise NotImplementedError

    @staticmethod
    def get_temperatures(self):
        raise NotImplementedError

    def _get_cwd(self):
        return None

    def _quote(self, s):
        quoted = ''.join(('"', unicode(s), '"'))
        return quoted

    def _read_popen(self):
        raise NotImplementedError

    def _epilogue(self):
        raise NotImplementedError

    def _get_failure(self, exception):
        slicerlog = None
        if None is not self._slicerlog:
            slicerlog = self._slicerlog.getvalue()
        failure = conveyor.util.exception_to_failure(
            exception, slicerlog=slicerlog, code=self._code)
        return failure
