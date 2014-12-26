# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/util.py
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

"""
This module is a collection of utility functions that don't fit somewhere more
specific.

"""

from __future__ import (absolute_import, print_function, unicode_literals)

import ctypes
import datetime
import json
import os
import subprocess
import sys
import time

import conveyor.error
import conveyor.log
import makerbot_driver


def exception_to_failure(exception, **kwargs):
    """
    Convert an exception to a failure dict suitable for passing to Job.fail.

    @param exception the exception
    @param kwargs additional data that will be included in the failure dict.

    """

    if isinstance(exception, conveyor.error.JobFailedException):
        failure = exception.failure
        if isinstance(failure, dict):
            failure.update(kwargs)
        return failure
    exception_data = None
    if None is not exception:
        exception_data = {
            'name': unicode(exception.__class__.__name__),
            'args': unicode(exception.args),
            'errno': unicode(getattr(exception, 'errno', None)),
            'strerror': unicode(getattr(exception, 'strerror', None)),
            'filename': unicode(getattr(exception, 'filename', None)),
            'winerror': unicode(getattr(exception, 'winerror', None)),
            'message': unicode(exception),
        }
    failure = {'exception': exception_data,}
    failure.update(kwargs)
    return failure

def get_used_extruders(slicer_settings, makerbot_thing_tool_path, input_file):
    """
    Get a list of the explicitely used extruders based on the job and slicer settings.
    Since we need extruders as a str (TODO: WHY ADONAI, WHY?), we force
    these extruders into a string.

    do_auto_raft/do_auto_support: The slicer should do a "mixed" raft, 
    where rafts/supports are made out of the material they support.

    Its important to note: MakerwareUI will always output the correct extruders
    for each mesh. And, its up to the user using the command
    line client to give the correct extruders for an stl/gcode file.

    @param slicer_settings
    @param makerbot_thing_tool_path: path to the makerbot thing tool.  Used to
        determine how many extruders a "thing" file requires
    @param input_file: Path to the input file
    @return <list>: List of extruders used, in the from of ['0', '1']
    """
    extruders = set([e.strip() for e in slicer_settings['extruder'].split(',')])
    if None is slicer_settings['path']:
        if len(extruders) == 1:
            if not slicer_settings['do_auto_raft'] and slicer_settings['raft']:
                extruders.add(str(slicer_settings['default_raft_extruder']))
            if not slicer_settings['do_auto_support'] and slicer_settings['support']:
                extruders.add(str(slicer_settings['default_support_extruder']))
    else:
        with open(slicer_settings['path']) as f:
            custom_conf = json.load(f)
        if not custom_conf['doMixedRaft'] and custom_conf['doRaft']:
            extruders.add(str(custom_conf['defaultRaftMaterial']))
        if not custom_conf['doMixedSupport'] and custom_conf['doSupport']:
            extruders.add(str(custom_conf['defaultSupportMaterial']))
    return list(extruders)

def execute_job(job, timeout=20.0, heartbeat_timeout=None):
    run_job(job, timeout, heartbeat_timeout)
    if job.isfailed():
        raise conveyor.error.JobFailedException(job.failure)
    else:
        return job.result

def run_job(job, timeout=20.0, heartbeat_timeout=None):
    start_time = datetime.datetime.now()
    if heartbeat_timeout:
        heart_time = [datetime.datetime.now()]
        def heartbeat(job):
            heart_time[0] = datetime.datetime.now()
        job.heartbeatevent.attach(heartbeat)
    job.start()
    while not job.isstopped():
        if timeout:
            if (datetime.datetime.now() - start_time).total_seconds() > timeout:
                log = conveyor.log.getlogger(object())
                log.debug("Execution of job %s failed: %r", job.name, 
                          job.failure)
                raise conveyor.error.KaitenNotResponsiveException
        if heartbeat_timeout:
            heart_copy = heart_time[0] # Avoid negative time intervals
            if (datetime.datetime.now() - heart_copy).total_seconds() > heartbeat_timeout:
                log = conveyor.log.getlogger(object())
                log.debug("Execution of job %s failed: %r", job.name, 
                          job.failure)
                raise conveyor.error.KaitenNotResponsiveException
        # Lets rest here a second
        time.sleep(.1)
