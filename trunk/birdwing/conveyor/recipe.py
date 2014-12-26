# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4
# conveyor/src/main/python/conveyor/recipe.py
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

import contextlib
import ctypes
import json
import inspect
import logging
import makerbot_driver
import mock
import os
import os.path
import re
import shutil
import subprocess
import time
import tempfile
import uuid
import zipfile

import conveyor.address
import conveyor.enum
import conveyor.log
import conveyor.machine.digitizer
import conveyor.machine.s3g
import conveyor.job
import conveyor.util

def running_event(func):
    """
    Decorator that will wrap "func" into a callback and attach that callback
    to the Recipe's running callback.  These running callbacks will then 
    be executed in serial.
    """
    def decorator(self, *args, **kwargs):
        # The running callback is attached to the job
        def running_callback(job):
            try:
                # We only want to execute this callback if the job is still
                # running.
                if job.state == conveyor.job.JobState.RUNNING:
                    func(self, *args, **kwargs)
            except Exception as e:
                self._log.info("Unhandled exception", exc_info=True)
                # If the error raised from func was not cause, we need to
                # fail the job here
                if conveyor.job.JobState.RUNNING == self._job.state:
                    failure = conveyor.util.exception_to_failure(e)
                    job.fail(failure)
        self._job.runningevent.attach(running_callback)
    return decorator

class Recipe(object):
    """
    A recipe encapsulates various tidbits of information pertaining to a
    specific "job".  Its main function is to stage a job, which will 
    determine what functions need to get executed to successfully complete
    a job.

    NB: In our infinite wisdom we have decided that the birdwing file extension
    is .makerbot.  Since this makes for a lot of confusion, we are going to 
    refer to those files internally as tinything files.
    """
    def __init__(self, config, server, job):
        self._config = config
        self._server = server
        self._job = job
        self._log = conveyor.log.getlogger(self)
        self._job_dir = None
        self._tempfile_prefix = "%s.job[%i]." % ("conveyor", self._job.id)

    def cook(self):
        """
        The main function that sets up a job to be exectued.  Recipe does not
        do any actual work, instead it sets up various callbacks and places
        them in a single job's runningevent's list of callbacks.  After the
        recipe finishes setting up the environment/callbacks, we call
        "start" on the job and watch all the callbacks be executed in serial.

        There is no magic.

        There are (mainly) two types of functions below that look like: 
            * _goto_*: These functions can be considered the "transition"
                functions.  They do not place any callbacks on a job's queue,
                they only set the environment up and determine what to call next
            * _*_job: These functions are all decorated with the @running_event
                decorator, which wraps them up into a callback and places them
                on the job's queue.
        """
        self._goto_input_file()

    def streaming_cook(self):
        """
        Simply calls the streaming print job.
        """
        self._streaming_print_job(self._job.layout_id, self._job.thingiverse_token)

    def _goto_input_file(self):
        input_file = self._job.input_file
        root, ext = os.path.splitext(input_file)
        self._input_ext = ext.lower()
        if self._input_ext == '.gcode':
            # MonkeyPatch: We mark that we are printing from a gcode file
            self._job.print_from_gcode_file = True
            if not self._job.get_has_start_end():
                extruders = self._job.used_extruders
                dualstrusion = '0' in extruders and '1' in extruders
                self._goto_unprocessed_toolpath(input_file, dualstrusion)
            else:
                self._goto_processed_gcode(input_file)
        elif self._input_ext in ['.stl', '.obj']:
            self._goto_stl(input_file)
        elif self._input_ext == '.thing':
            self._goto_thing(input_file)
        elif self._input_ext == '.makerbot':
            self._goto_tinything(input_file)
        else:
            raise conveyor.error.UnsupportedModelTypeException(input_file)

    def _goto_preheat(self):
        """
        Preheats the machine.
        """
        self._log.info("Preheating machine")
        self._preheat_job()

    def _goto_stl(self, stl_file):
        unprocessed_toolpath_file = self._get_tempfile(".toolpath")
        dualstrusion = False
        self._slice_job(
            stl_file, unprocessed_toolpath_file, self._job.slicer_settings,
            dualstrusion)
        self._goto_unprocessed_toolpath(unprocessed_toolpath_file, dualstrusion)

    def _deduce_dualstrustion(self):
        """
        Determines if this job/slicer_settings combination uses dualstrusion.

        @return <bool>: True if we require dualstrusion, false otherwise.
        """
        # We use the monkey patched "used_extruders" list to determine if
        # we have a dualstrusion print
        return len(self._job.used_extruders) == 2

    def _goto_thing(self, thing_file):
        self._goto_miracle_grue_print(thing_file)

    def _goto_miracle_grue_print(self, thing_file):
        # Conveyor will always set default extruder to the 0th one.  In
        # the case of a single extruder print, we'll always be correct.
        # In the case of a dualstrusion print, we'll default to our
        # best guess.
        slicer_settings = self._override_extruder(self._job.used_extruders[0])
        dualstrusion = self._deduce_dualstrustion()
        unprocessed_toolpath = self._get_tempfile(".toolpath")
        self._slice_job(thing_file, unprocessed_toolpath,
            slicer_settings, dualstrusion)
        self._goto_unprocessed_toolpath(unprocessed_toolpath, dualstrusion)

    def _override_extruder(self, extruder):
        """
        Sets the slicer config's extruder value to extruder. This MUST
        be called on slicer configs that have a list of extruders, otherwise
        conveyor will fail when it tries to do various jobs (i.e. create
        the MG config)
        """
        new_settings = self._job.slicer_settings.copy()
        new_settings['extruder'] = extruder
        return new_settings

    def _goto_unprocessed_toolpath(self, unprocessed_toolpath_file, dualstrusion):
        if self._job.device_family == self._job.DeviceFamily.BIRDWING:
            tinything_file = self._get_tempfile(".makerbot")
            self._bundle_tinything_job(unprocessed_toolpath_file, 
                tinything_file)
            self._goto_tinything(tinything_file)
        elif not self._job.get_add_start_end():
            self._goto_output_file(unprocessed_toolpath_file)
            self._end_job()
        else:
            processed_gcode_file = self._get_tempfile(".gcode")
            self._gcode_processor_job(unprocessed_toolpath_file, 
                processed_gcode_file, dualstrusion)
            gcode_with_start_end_file = self._get_tempfile(".gcode")
            self._add_start_end_job(processed_gcode_file, 
                gcode_with_start_end_file)
            self._goto_processed_gcode(gcode_with_start_end_file)

    def _goto_tinything(self, tinything_file):
        if isinstance(self._job, (conveyor.job.PrintToFileJob, 
                conveyor.job.SliceJob)):
            self._goto_output_file(tinything_file)
            # We now need to end the job
            self._end_job()
        elif isinstance(self._job, conveyor.job.PrintJob):
            self._print_job(tinything_file)
        elif isinstance(self._job, conveyor.job.PrintFromFileJob):
            self._print_from_file_job(tinything_file)
        else:
            raise ValueError(self._job)

    def _goto_processed_gcode(self, gcode_file):
        # If we have a custom profile or are printing from a gcode file
        if self._job.slicer_settings['path'] or getattr(self._job, "print_from_gcode_file", False):
            self._verify_gcode_job(gcode_file)
        if isinstance(self._job, conveyor.job.PrintJob):
            self._print_job(gcode_file)
            # TODO: It would be WONDERFUL if we could end the job here, but 
            # because the architecture for s3g.py is super intuitive and not 
            # bad (*sarcasm*), we'll do this for now.
            #self._end_job()
        elif isinstance(self._job, conveyor.job.PrintToFileJob):
            # We want the desired output ext, so we can support [sx]3g
            output_ext = os.path.splitext(self._job.output_file)[1]
            if output_ext == ".gcode":
                substituted_gcode_file = self._get_tempfile(".gcode")
                self._substitute_variables_job(gcode_file, substituted_gcode_file)
                self._goto_output_file(substituted_gcode_file)
                self._end_job()
            elif output_ext in ['.x3g', '.s3g']:
                s3g_file = self._get_tempfile(output_ext)
                self._print_to_file_job(gcode_file, s3g_file)
                self._goto_output_file(s3g_file)
                self._end_job()
            else:
                raise ValueError(self._job)
        elif isinstance(self._job, conveyor.job.SliceJob):
            substituted_gcode_file = self._get_tempfile(".gcode")
            self._substitute_variables_job(gcode_file, substituted_gcode_file)
            self._goto_output_file(substituted_gcode_file)
            self._end_job()
        else:
            raise ValueError(self._job)

    def _goto_output_file(self, output_file):
        self._copy_output_file_job(output_file)

    # Below are the various callback functions.  These functions do the actual
    # work required to execute the job at hand.  They ALL should be decorated
    # with the running_event decorator

    @running_event
    def _preheat_job(self):
        self._log.info("Preheating machine with extruders: %r",
            self._job.used_extruders)
        self._job.machine.preheat(self._job, self._job.used_extruders,
            self._job.slicer_settings['extruder_temperatures'],
            self._job.slicer_settings['heat_platform'],
            self._job.slicer_settings['platform_temperature'])

    def _get_lib_tinything(self):
        """
        Gets libtinything and specifies all the return/param types, since
        unix seems like the only platform that is good at interrpreting 
        those types of things.
        """
        lib = self._config.get("server", "lib_tinything")
        lib.NewTinyThingWriter.argtypes = [ctypes.c_char_p]
        lib.NewTinyThingWriter.restype = ctypes.c_void_p
        lib.SetToolpathFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.SetMetadataFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.SetThumbnailDirectory.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.Zip.argtypes = [ctypes.c_void_p]
        lib.Zip.restype = ctypes.c_bool
        lib.DestroyTinyThingWriter.argtypes = [ctypes.c_void_p]
        return lib

    @running_event
    def _bundle_tinything_job(self, toolpath_file, tinything_file):
        jt_dir = os.path.dirname(toolpath_file)
        self._log.info("Bundling jsontoolpath file to %s", 
            tinything_file) 
        metafile = os.path.join(jt_dir, "meta.json")
        with open(metafile) as f:
            metadata = json.load(f)
        #If slicer_settings has a non-null path then we are using a custom
        #profile and the custom values need to be used in meta.json. So,
        #we override slicer_settings with the custom values.
        if self._job.slicer_settings.get('path', None):
            self._override_slicer_settings()
        metadata.update(getattr(self._job, "metadata", {}))
        metadata.update({
            "printer_settings": self._job.slicer_settings})
        temp_string = "toolhead_%i_temperature"
        for i in range(len(self._job.slicer_settings['extruder_temperatures'])):
            metadata[temp_string % i] = self._job.slicer_settings['extruder_temperatures'][i]
        # Generate the UUID and add it to the metadata
        uuidAsString = str(uuid.uuid4())
        metadata.update({"uuid": uuidAsString})
        with open(metafile, 'w') as f:
            json.dump(metadata, f, indent=4)
        # Start libtinything bundling
        lib_tinything = self._get_lib_tinything()
        writer = lib_tinything.NewTinyThingWriter(
            ctypes.c_char_p(tinything_file))
        try:
            lib_tinything.SetToolpathFile(writer, 
                ctypes.c_char_p(toolpath_file))
            if (hasattr(self._job, "thumbnail_dir") and 
                    os.path.exists(self._job.thumbnail_dir)):
                lib_tinything.SetThumbnailDirectory(writer, 
                    ctypes.c_char_p(self._job.thumbnail_dir))
            lib_tinything.SetMetadataFile(writer, ctypes.c_char_p(metafile))
            if not lib_tinything.Zip(writer):
                self._job.fail("Could not zip %s" % (tinything_file))
        except Exception as e:
            self._log.info("Error bundling %s", toolpath_file, exc_info=True)
            raise
        # Always destroy this, since it was created with New
        finally:
            lib_tinything.DestroyTinyThingWriter(writer)

    def _override_slicer_settings(self):
        '''
        This is used to override slicer settings when a custom profile is being
        used.
        '''
        slicer_settings_to_profile = {
            'default_raft_extruder': 'defaultRaftMaterial',
            'slicer': None,
            'platform_temperature': 'platformTemp',
            'shells': 'numberOfShells',
            'default_support_extruder': 'defaultSupportMaterial',
            'support': 'doSupport',
            'layer_height': 'layerHeight',
            'travel_speed': 'rapidMoveFeedRateXY',
            'extruder_temperatures': ['extruderTemp0', 'extruderTemp1'],
            'materials': None,
            'infill': 'infillDensity',
            'heat_platform': None,
            'raft': 'doRaft',
            'do_auto_support': None,
            'path': None,
            'print_speed': None,
            'do_auto_raft': None,
            'extruder': 'defaultExtruder'
        }
        with open(self._job.slicer_settings['path']) as f:
            custom_values = json.load(f)
        for key in slicer_settings_to_profile:
            key_value = slicer_settings_to_profile[key]
            if key_value is not None:
                #The simplest way to handle extruder_temperatures (not the most elegant)
                if key is 'extruder_temperatures':
                    self._job.slicer_settings['extruder_temperatures'] = [custom_values['extruderTemp0'],
                        custom_values['extruderTemp1']]
                else:
                    self._job.slicer_settings[key] = custom_values[slicer_settings_to_profile[key]]

    @running_event
    def _slice_job(
            self, stl_file, unprocessed_toolpath_file, 
                slicer_settings, dualstrusion):
        profile = self._job.get_profile()
        self._log.info(
            'job %d: slicing: %s -> %s', self._job.id, stl_file,
            unprocessed_toolpath_file)
        method = self._get_slicer_miraclegrue
        slicer = method(
            profile, stl_file, unprocessed_toolpath_file, slicer_settings, 
            dualstrusion, self._job)
        slicer.slice()
        self._set_estimations(unprocessed_toolpath_file)

    def _set_estimations(self, toolpath_file):
        extra_info = {
            "duration_s": 0.0,
            "extrusion_distance_a_mm": 0.0,
            "extrusion_distance_b_mm": 0.0,
            "extrusion_mass_a_grams": 0.0,
            "extrusion_mass_b_grams": 0.0,
        }
        if self._job.get_profile().driver.name == "birdwing":
            jt_dir = os.path.dirname(toolpath_file)
            with open(os.path.join(jt_dir, "meta.json")) as f:
                meta_info = json.load(f)
            for key in extra_info:
                extra_info[key] = meta_info.get(key, None)
        # TODO: Have MG output the meta.json file regardless, we we get it in
        # the same way
        elif self._job.get_profile().driver.name == "s3g":
            with open(toolpath_file) as f:
                comment_regex = "^\s*[;(]" # Saddest regex in the world
                time_estimation_regex = "%s Duration: ([\d\.]+) seconds" % (
                    comment_regex)
                toolhead_regex = "(Right|Left)"
                number_regex = "([\d\.]+)"
                weight_estimation_regex = "%s %s Toolhead Weight \(grams\): %s" % (
                    comment_regex,
                    toolhead_regex,
                    number_regex)
                distance_regex = "%s %s Toolhead Distance \(mm\): %s" % (
                    comment_regex,
                    toolhead_regex,
                    number_regex)
                toolhead_map = {
                    "Right": "a",
                    "Left": "b"}
                for line in f:
                    # We expect MG to have a block of comments with print 
                    # metadata
                    # This chunk may have blank noncomment lines in the middle.
                    if re.match(comment_regex, line):
                        dur_match = re.match(time_estimation_regex, line)
                        if dur_match:
                            extra_info["duration_s"] = float(dur_match.group(1))
                        weight_match = re.match(weight_estimation_regex, line)
                        if weight_match:
                            toolhead = toolhead_map[weight_match.group(1)]
                            key = "extrusion_mass_%s_grams" % (toolhead)
                            extra_info[key] = float(weight_match.group(2))
                        distance_match = re.match(distance_regex, line)
                        if distance_match:
                            toolhead = toolhead_map[distance_match.group(1)]
                            key = "extrusion_distance_%s_mm" % (toolhead)
                            extra_info[key] = float(distance_match.group(2))
                    elif len(line.strip()) > 0:
                        break
        for key, val in extra_info.iteritems():
            if val:
                self._job.add_extra_info(key, val, callback=False)
        self._job._invoke_changed_callbacks()

    def _get_slicer_miraclegrue(
            self, profile, input_file, output_file, slicer_settings,
            dualstrusion, job):
        exe = self._config.get('miracle_grue', 'exe')
        profile_dir = self._config.get('miracle_grue', 'profile_dir')
        slicer = conveyor.slicer.miraclegrue.MiracleGrueSlicer(
            profile, input_file, output_file, slicer_settings, dualstrusion, 
            job, exe, profile_dir)
        return slicer

    @running_event
    def _gcode_processor_job(self, unprocessed_gcode_file, 
            processed_gcode_file, dualstrusion):
        profile = self._job.get_profile()
        factory = makerbot_driver.GcodeProcessors.ProcessorFactory()
        gcode_processor_names = list(self._get_gcode_processor_names(
            dualstrusion))
        if 0 == len(gcode_processor_names):
            self._log.info(
                'job %d: processing g-code: no processors selected: %s',
                self._job.id, unprocessed_gcode_file)
            self._copy_file(unprocessed_gcode_file, processed_gcode_file)
        else:
            self._log.info(
                'job %d: processing g-code: %s to %s [%s]', self._job.id,
                unprocessed_gcode_file, processed_gcode_file, 
                ', '.join(gcode_processor_names))
            gcode_info = {
                'size_in_bytes': os.path.getsize(unprocessed_gcode_file)
            }
            with open(unprocessed_gcode_file, "rb") as unprocessed:
                cascade_generator = factory.create_cascading_generator(
                    gcode_processor_names, unprocessed, 
                    gcode_info, profile.json_profile)
                with open(processed_gcode_file, 'wb') as processed:
                    for line in cascade_generator:
                        processed.write(line)

    def _get_gcode_processor_names(self, dualstrusion):
        gcode_processor_names = self._get_default_gcode_processor_names(
            dualstrusion)
        return gcode_processor_names

    def _get_default_gcode_processor_names(self, dualstrusion):
        profile = self._job.get_profile()
        # These processors need to come first
        # We should only be yielding these for Rep2X machines
        if 'Replicator' in profile.name:
            if not dualstrusion:
                yield 'RepSinglePrimeProcessor'
            else:
                yield 'RepDualstrusionPrimeProcessor'
        if 'Replicator2' == profile.name:
            yield 'FanProcessor'

    @running_event
    def _add_start_end_job(self, incomplete_gcode_file, gcode_with_start_end_file):
        """
        In an ideal world, we would patch the scaffold variables onto the job
        so the s3g machine wouldn't need to get the scaffold again.  Also, in 
        an ideal world gcode scaffolding would be called start_end_gcode, since
        scaffolding has no instrinsic value and is an attempt to sound like  
        erudite.
        """
        self._log.info(
            'job %d: adding start/end g-code: %s -> %s', self._job.id,
            incomplete_gcode_file, gcode_with_start_end_file)
        gcode_scaffold = self._get_gcode_scaffold()
        # NOTE: we use `write` here because the start/end G-code lines
        # are expected to always have line separators.
        with open(gcode_with_start_end_file, 'wb') as f:
            for line in gcode_scaffold.start:
                f.write(line)
            with open(incomplete_gcode_file, "rb") as gcode_fh:
                for line in gcode_fh:
                    f.write(line)
            for line in gcode_scaffold.end:
                f.write(line)

    def _get_gcode_scaffold(self):
        extruders = self._job.used_extruders
        if not self._job.slicer_settings['path']:
            profile = self._job.get_profile()
            # Since the only two mats that can be printed together have
            # the same print temperature, we just take the 0th index
            gcode_scaffold = profile.get_gcode_scaffold(
                extruders,
                self._job.slicer_settings['extruder_temperatures'],
                self._job.slicer_settings['platform_temperature'],
                self._job.slicer_settings['heat_platform'],
                self._job.slicer_settings["materials"][0]
                )
        else:
            slicer = conveyor.slicer.miraclegrue.MiracleGrueSlicer
            gcode_scaffold = slicer.get_gcode_scaffold(self._job.slicer_settings['path'])
            #If the custom profile does not have start and end gcode generate it
            if not gcode_scaffold.start and not gcode_scaffold.end:
                temperatures = slicer.get_temperatures(self._job.slicer_settings['path'])
                if temperatures:
                    extruder_temperatures = [temperatures['extruders'][0],
                        temperatures['extruders'][1]]
                    platform_temperature = temperatures['platform']
                    #If you are using a custom profile with dynamic start-end gcode
                    #override the default temps
                    self._job.slicer_settings['extruder_temperatures'] = extruder_temperatures
                    self._job.slicer_settings['platform_temperature'] = platform_temperature
                #if there is a valid setting for the platform temp in the custom profile heat it
                if(self._job.slicer_settings['platform_temperature'] > 0 and
                    self._job.slicer_settings['platform_temperature'] not in ['', None]):
                    self._job.slicer_settings['heat_platform'] = True
                profile = self._job.get_profile()
                # Since the only two mats that can be printed together have
                # the same print temperature, we just take the 0th index
                gcode_scaffold = profile.get_gcode_scaffold(
                    extruders,
                    self._job.slicer_settings['extruder_temperatures'],
                    self._job.slicer_settings['platform_temperature'],
                    self._job.slicer_settings['heat_platform'],
                    self._job.slicer_settings["materials"][0]
                )
        return gcode_scaffold

    @running_event
    def _print_to_file_job(self, gcode_file, s3g_file):
        profile = self._job.get_profile()
        self._log.info(
            'job %d: printing to file: %s -> %s', self._job.id, gcode_file,
            s3g_file)
        has_start_end = True
        self._job.driver.print_to_file(
            profile, gcode_file, s3g_file, 
            self._job.slicer_settings['extruder'],
            self._job.slicer_settings['extruder_temperatures'],
            self._job.slicer_settings['platform_temperature'],
            self._job.slicer_settings['heat_platform'],
            self._job.slicer_settings["materials"], self._job.name, self._job)

    @running_event
    def _verify_gcode_job(self, gcode_file):
        profile = self._job.get_profile()
        parser = makerbot_driver.Gcode.GcodeParser()
        if (profile.json_profile.values.get('use_legacy_parser', False)):
            parser.state = makerbot_driver.Gcode.LegacyGcodeStates()
        parser.state.values['build_name'] = self._job.name
        parser.state.profile = profile.json_profile

        #Create s3g stub for verification purposes
        parser.s3g = makerbot_driver.s3g()
        for key in makerbot_driver.s3g.__dict__:
            func = makerbot_driver.s3g.__dict__[key]
            if(hasattr(func, '__call__')):
                parser.s3g.__setattr__(func.func_name, lambda *args: None)

        gcode_scaffold = self._get_gcode_scaffold()
        parser.environment.update(gcode_scaffold.variables)
        self._log.info(
            'job %d: verifying g-code: %s', self._job.id, gcode_file)
        with open(gcode_file) as gcode_fp:
            for line in gcode_fp:
                try:
                    parser.execute_line(line)
                    percent = min(100, int(parser.state.percentage))
                    progress = {
                        'name': 'verify',
                        'progress': percent,
                    }
                    # There is a race condition all over the job object;
                    # we can call lazy_heartbest whenever, but some other thread
                    # could have cancelled it.  Each job needs its own mutex,
                    # otherwise these race conditions will linger
                    if self._job.state != conveyor.job.JobState.RUNNING:
                        # We return here, since the job has been failed/cancelled
                        # and we dont want to end it again.
                        # This will MITIGATE the race condition, but won't solve
                        # it.
                        return
                    else:
                        self._job.heartbeat(progress)
                except Exception as e:
                    self._job.fail(str(e))

    @running_event
    def _print_job(self, gcode_file):
        self._job.set_pausable()
        self._log.info(
            'job %d: printing: %s -> %s', self._job.id, gcode_file,
            self._job.machine.name)
        has_start_end = True
        self._job.machine.print(
            gcode_file, self._job.slicer_settings['extruder'],
            self._job.slicer_settings['extruder_temperatures'],
            self._job.slicer_settings['platform_temperature'],
            self._job.slicer_settings['heat_platform'],
            self._job.slicer_settings["materials"],
            self._job.name, self._job, self._job.username)

    @running_event
    def _print_from_file_job(self, gcode_file):
        self._job.set_pausable()
        self._log.info(
            'job %d: printing: %s -> %s', self._job.id, gcode_file,
            self._job.machine.name)
        has_start_end = True
        self._job.machine.print_from_file(
            gcode_file,
            self._job.name,
            self._job,
            self._job.username)

    @running_event
    def _streaming_print_job(self, layout_id, thingiverse_token):
        self._job.set_pausable()
        self._job.machine.streaming_print(
            layout_id, thingiverse_token, self._job.name,
            self._job.metadata_tmp_path, self._job)

    @running_event
    def _substitute_variables_job(self, gcode_file, substituted_file):
        gcode_scaffold = self._get_gcode_scaffold()
        variables = gcode_scaffold.variables
        with open(gcode_file) as gcode_file_handle:
            with open(substituted_file, "wb") as substituted_file_handle:
                for line in gcode_file_handle:
                    line_out = makerbot_driver.Gcode.variable_substitute(line,
                        variables)
                    substituted_file_handle.write(line_out)


    @running_event
    def _copy_output_file_job(self, output_file):
        self._log.info(
            'job %d: copying output: %s -> %s', self._job.id, 
            output_file, self._job.output_file)
        self._copy_file(output_file, self._job.output_file)

    @running_event
    def _end_job(self):
        self._job.end(True)

    def _get_tempfile(self, suffix=None):
        with tempfile.NamedTemporaryFile(prefix=self.
                _tempfile_prefix, suffix=suffix, dir=self._job_dir) as f:
            return f.name

    def _get_switched_filehandle(self, handle):
        handle.close()
        if handle.mode.startswith("r"):
            new_handle = open(handle.name, "wb")
        elif handle.mode.startswith("w"):
            new_handle = open(handle.name, "rb")
        return new_handle
        
    @staticmethod
    def _copy_file(input_file, output_filepath):
        """Copy a file's contents to another file.

        If the output_filepath already exists, shutil.copyfile is used
        to directly copy contents. Otherwise shutil.copy2 is used.

        This special handling is done because MakerWare provides a
        restricted file for conveyor to write to. Conveyor does not
        have necessary permissions on Mac to use shutil.copy2 or even
        shutil.copy.
        """
        if os.path.exists(output_filepath):
            shutil.copyfile(input_file, output_filepath)
        else:
            shutil.copy2(input_file, output_filepath)


class InvalidThingException(Exception):
    def __init__(self, path):
        Exception.__init__(self, path)
        self.path = path
