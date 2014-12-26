# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/slicer/miraclegrue.py
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

from distutils.version import LooseVersion, StrictVersion

import collections
import json
import os
import tempfile

import conveyor.event
import conveyor.json_reader
import conveyor.machine
import conveyor.slicer
import conveyor.util

class MiracleGrueSlicer(conveyor.slicer.SubprocessSlicer):
    _name = conveyor.slicer.Slicer.MIRACLEGRUE

    _display_name = 'Miracle Grue'

    @staticmethod
    def get_config_version(config):
        '''Get the version from the configuration file

        Returns 0.0.0 if the config has no version'''
        return LooseVersion(str(config.get('version', '0.0.0')))

    @staticmethod
    def config_compare_version(config):
        '''Compares the configuration's version with the current MG config version

        Returns <0 if the config is out of date, 0 if the config is up
        to date, and >0 if the config is from a newer-than-supported
        version'''

        #This current_version does not correspond to the latest version of MG
        #but rather the version of the MG config that the lastest MG uses
        #If this values changes you must also add values to upgrade_config()
        #so older (pre-current_version) configs can be updated.
        current_version = LooseVersion('2.4.0')

        config_version = MiracleGrueSlicer.get_config_version(config)
        if config_version == current_version:
            return 0
        elif config_version < current_version:
            return -1
        else:
            return 1

    @staticmethod
    def upgrade_config(config):
        '''Upgrade configuration data to latest version'''

        config_version = MiracleGrueSlicer.get_config_version(config)

        if MiracleGrueSlicer.config_compare_version(config) < 0:
            if config_version < LooseVersion('2.2.0'):
                config["version"] = '2.2.0'
                config.setdefault("computeVolumeLike2_1_0", True)
                config.setdefault("doBacklashCompensation", False)
                config.setdefault("anchorWidth", 2.0)
                config.setdefault("anchorExtrusionAmount", 5.0)
                config.setdefault("anchorExtrusionSpeed", 2.0)
                config.setdefault("backlashX", 0.0)
                config.setdefault("backlashY", 0.09)
                config.setdefault("backlashEpsilon", 0.05)
                config.setdefault("backlashFeedback", 0.9)            
                config.setdefault("doDynamicSpeed", True)
                config.setdefault("doDynamicSpeedGradually", True)
                config.setdefault("dynamicSpeedTransitionWindow", 6.0)
                config.setdefault("dynamicSpeedTransitionShape", 0.4)
                config.setdefault("doDynamicSpeedOutermostShell", True)
                config.setdefault("doDynamicSpeedInteriorShells", False)
                config.setdefault("dynamicSpeedSlowdownRatio", 0.5)
                config.setdefault("dynamicSpeedCurvatureThreshold", 15)
                config.setdefault("dynamicSpeedDetectionWindow", 3.0)
                config.setdefault("doSplitLongMoves", True)
                config.setdefault("splitMinimumDistance", 0.4)
                config.setdefault("doBridging", True)
                config.setdefault("bridgeAnchorWidth", 0.8)
                config.setdefault("bridgeMaximumLength", 80.0)
                config.setdefault("bridgeSpacingMultiplier", 0.8)
                config.setdefault("bridgeAnchorMinimumLength", 0.8)
                config.setdefault("directionWeight", 0.5)
                config.setdefault("commentOpen", ";")
                config.setdefault("commentClose", "")
                config.setdefault("weightedFanCommand", -1)
                config.setdefault("supportModelSpacing", 0.4)
                config.setdefault("doSupportUnderBridges", False)
                config.setdefault("supportAligned", True)
                config.setdefault("supportLeakyConnections", True)
                config.setdefault("supportExtraDistance", 0.5)
                config.setdefault("sparseInfillPattern", "linear")
                config.setdefault("roofAnchorMargin", 0.4)
                config.setdefault("raftBaseLayers", 1)
                config.setdefault("raftBaseWidth", 2.0)
                config.setdefault("raftBaseDensity", 0.7)
                config.setdefault("raftBaseRunLength", 15.0)
                config.setdefault("raftBaseRunGapRatio", 0.8)
                config.setdefault("raftBaseAngle", 0.0)
                config.setdefault("raftInterfaceLayers", 1)
                config.setdefault("raftInterfaceWidth", 0.4)
                config.setdefault("raftInterfaceDensity", 0.3)
                config.setdefault("raftInterfaceAngle", 45.0)
                config.setdefault("raftSurfaceAngle", 0.0)
                config.setdefault("raftSurfaceLayers", 2)
                config.setdefault("raftSurfaceThickness", 0.27)
                config.setdefault("supportAngle", 68.0)
                config["coarseness"] = 0.0001
                config["extruderProfiles"][0]["bridgesExtrusionProfile"] = "bridges"
                config["extruderProfiles"][1]["bridgesExtrusionProfile"] = "bridges"
                config["extruderProfiles"][0]["firstLayerRaftExtrusionProfile"] = "firstlayer"
                config["extruderProfiles"][1]["firstLayerRaftExtrusionProfile"] = "firstlayer"
                config["extrusionProfiles"] = {
                      "bridges" : {
                         "feedrate" : 40,
                         "temperature" : 230.0
                      },
                      "firstlayer" : {
                         "feedrate" : config["extrusionProfiles"]["firstlayer"]["feedrate"],
                         "temperature" : 230.0
                      },
                      "infill" : {
                         "feedrate" : config["extrusionProfiles"]["infill"]["feedrate"],
                         "temperature" : 230.0
                      },
                      "insets" : {
                         "feedrate" : config["extrusionProfiles"]["insets"]["feedrate"],
                         "temperature" : 230.0
                      },
                      "outlines" : {
                         "feedrate" : config["extrusionProfiles"]["outlines"]["feedrate"],
                         "temperature" : 230.0
                      },
                      "raftbase" : {
                         "feedrate" : config["extrusionProfiles"]["raftbase"]["feedrate"],
                         "temperature" : 230.0
                      }
                    }

            if config_version < LooseVersion('2.3.0'):
                config["version"] = '2.3.0'
                for extruder in (0, 1):
                    exConfig = config["extruderProfiles"][extruder]
                    exConfig["toolchangeRestartDistance"] = 18.0
                    exConfig["toolchangeRetractDistance"] = 19.0
                    exConfig["toolchangeRestartRate"] = 5.0 # mm/s
                    exConfig["toolchangeRetractRate"] = 5.0 # mm/s
                config["defaultRaftMaterial"] = 0
                config["defaultSupportMaterial"] = 0
                config["doMixedRaft"] = False
                config["doMixedSupport"] = False
                config["doPurgeWall"] = False
                config["purgeWallModelOffset"] = 2.0
                config["purgeWallSpacing"] = 1.0
                config["purgeWallWidth"] = 0.5
                config["purgeWallBasePatternWidth"] = 8.0
                config["purgeWallBaseFilamentWidth"] = 2.0
                config["purgeWallBasePatternLength"] = 10.0
            if config_version < LooseVersion('2.4.0'):
                config["version"] = '2.4.0'
                config["doFanModulation"] = False
                config["fanModulationWindow"] = 0.1
                config["fanModulationThreshold"] = 0.5
                config["purgeWallPatternWidth"] = 2.0
                config["purgeBucketSide"] = 4.0
            if config_version < LooseVersion('3.0.0'):
                config["version"] = '3.0.0'
                config["raftSurfaceShells"] = 2
                config["raftSurfaceShellSpacingMultiplier"] = 0.7
            #if config_version < LooseVersion('x.x.x'):

        return config

    @staticmethod
    def get_gcode_scaffold(path):
        gcode_scaffold = conveyor.machine.GcodeScaffold()
        dirname = os.path.dirname(path)
        with open(path) as config_fp:
            config = conveyor.json_reader.load(config_fp)
        start_value = config.get('startGcode', None)
        if start_value in ['', None]:
            gcode_scaffold.start = []
        else:
            start_file = os.path.join(dirname, start_value)
            with open(start_file) as start_fp:
                gcode_scaffold.start = start_fp.readlines()
        end_value = config.get('endGcode', None)
        if end_value in ['', None]:
            gcode_scaffold.end = []
        else:
            end_file = os.path.join(dirname, end_value)
            with open(end_file) as end_fp:
                gcode_scaffold.end = end_fp.readlines()
        gcode_scaffold.variables = {}
        return gcode_scaffold

    def __init__(
            self, profile, input_file, output_file, slicer_settings,
            dualstrusion, job, slicer_file, config_file_dir):
        super(MiracleGrueSlicer, self).__init__(profile, input_file, output_file, 
            slicer_settings, dualstrusion, job, slicer_file)
        self._profile = profile
        # TODO: Dave change, this var to something sane, like config_file_dir
        self._config_file = config_file_dir
        self._tmp_config_file = None

    def _prologue(self):
        """
        The "prologue" of the slicer story; gets the config file based on the 
        slicer config passed in.
        """
        config = self._get_config()
        s = json.dumps(config)
        self._log.debug('using miracle grue configuration: %s', s)
        with tempfile.NamedTemporaryFile(suffix='.config', delete=False) as tmp_config_fp:
            self._tmp_config_file = tmp_config_fp.name
            json.dump(config, tmp_config_fp, indent=8)

    def _get_config(self):
        """
        Gets the correct config for this slice. If the user specified a custom
        profile, the path to the custom profile will be in slicer_config.path,
        otherwise, we grab construct the correct profile and pass that to MG.
        """
        if self._slicer_settings['path']:
            config = self._get_config_custom()
        else:
            config = self._get_config_printomatic()
        return config

    def _get_material_specific_options(self, material):
        """
        Given a material name, returns a dict that contains overrides for
        the miracle grue config.  Currently this function does nothing,
        after talking with joe (clang) sadusk, we decided to create it anyway, 
        to support material specific options later.
        """
        material_specific_values = {}
        try:
            mat_dict = material_specific_values[material]
        except KeyError:
            self._log.debug("Material %s not found, returning {}", material)
            mat_dict = {}
        finally:
            return mat_dict

    def _get_config_custom(self):
        """
        Fills in several config values for a custom profile (conveyor knows if
        a slicer config has a custom profile is there is a slicer_config.path
        attribute present.  

        NB: We should not be filling in values willy-nilly; leave most of the
        config values to the custom config to define.
        """
        self._log.info('using miracle-grue config: %s' % self._slicer_settings['path'])
        with open(self._slicer_settings['path']) as config_fp:
            config = conveyor.json_reader.load(config_fp)
        if self._profile.driver.name == 'birdwing':
            config['jsonToolpathOutput'] = True
            config['metadataOutput'] = True
            config['outputFilepath'] =  os.path.dirname(self._output_file)
        config['startX'] = self._profile.json_profile.values['print_start_sequence']['start_position']['start_x']
        config['startY'] = self._profile.json_profile.values['print_start_sequence']['start_position']['start_y']
        #TODO startZ being 0 was a fix for the cupcake print in 2.2.2, we should fix this the
        #right way, same goes for _get_config_printomatic
        config['startZ'] = 0
        if self._dualstrusion:
            config['doPutModelOnPlatform'] = False
        config['startGcode'] = None
        config['endGcode'] = None
        #This is done since M127 can be potentially dangerous on a TOM
        if 'TOM' in self._profile.json_profile.values['machinenames']:
            config['doFanCommand'] = False
        return config

    def _get_config_printomatic(self):
        """
        Filles in several config values for user defined printomatic settings.
        """
        config_file = self._get_config_printomatic_file()
        self._log.info('using miracle-grue config: %s'%config_file)
        with open(config_file) as fp:
            config = conveyor.json_reader.load(fp)
        if self._profile.driver.name == 'birdwing':
            config['jsonToolpathOutput'] = True
            config['metadataOutput'] = True
            config['outputFilepath'] =  os.path.dirname(self._output_file)
        config['startX'] = self._profile.json_profile.values['print_start_sequence']['start_position']['start_x']
        config['startY'] = self._profile.json_profile.values['print_start_sequence']['start_position']['start_y']
        config['startZ'] = 0
        # Conveyor keeps extruder as strings internally, so we need to
        # force them into ints when we generate the MG config
        config['defaultRaftMaterial'] = int(self._slicer_settings['default_raft_extruder'])
        config['defaultSupportMaterial'] = int(self._slicer_settings['default_support_extruder'])
        config['doMixedRaft'] = self._slicer_settings['do_auto_raft']
        config['doMixedSupport'] = self._slicer_settings['do_auto_support']
        config['infillDensity'] = self._slicer_settings['infill']
        config['numberOfShells'] = self._slicer_settings['shells']
        config['rapidMoveFeedRateXY'] = self._slicer_settings['travel_speed']
        config['doRaft'] = self._slicer_settings['raft']
        config['doSupport'] = self._slicer_settings['support']
        config['layerHeight'] = self._slicer_settings['layer_height']
        config['extrusionProfiles']['insets']['feedrate'] = self._slicer_settings['print_speed']
        config['extrusionProfiles']['infill']['feedrate'] = self._slicer_settings['print_speed']
        config['extruderTemp0'],config['extruderTemp1'] = self._slicer_settings['extruder_temperatures']
        config['platformTemp'] = self._slicer_settings['platform_temperature']
        if self._dualstrusion:
            config['doPutModelOnPlatform'] = False
            config['doPurgeWall'] = True
            # MG ignores these values if there is no dualstrustion, so we
            # are only settings them if we have a dualstrusion print
            if self._profile.name != 'Replicator2X':
                for extruder in (0, 1):
                    exConfig = config["extruderProfiles"][extruder]
                    exConfig["toolchangeRestartDistance"] = 1.0
                    exConfig["toolchangeRetractDistance"] = 1.0
        else:
            config['doPurgeWall'] = False
        config['startGcode'] = None
        config['endGcode'] = None
        if (self._profile.driver.name != 'birdwing' and
            'TOM' in self._profile.json_profile.values['machinenames']):
            config['doFanCommand'] = False
        for mat in self._slicer_settings["materials"]:
            config.update(self._get_material_specific_options(mat))
        # Per JoeClang, these values are for the following specific cases:
        # Single Extrusion
        if len(self._slicer_settings['extruder']) == 1:
            # Not auto support and regular support and HIPS
            if (not self._slicer_settings['do_auto_support'] and 
            self._slicer_settings['support'] and
            self._slicer_settings["materials"][self._slicer_settings['default_support_extruder']] == "HIPS"):
                # Support opposite of print
                if (self._slicer_settings['extruder'][0] != 
                self._slicer_settings['default_support_extruder']):
                    config['supportAligned'] = False
                    config['supportAngle'] = 35.0
                    config['supportDensity'] = 0.35
                    config['supportExtraDistance'] = 1.5
                    config['supportLeakyConnections'] = False
            # Not auto raft and regular raft and HIPS
            if (not self._slicer_settings['do_auto_raft'] and
            self._slicer_settings['raft'] and
            self._slicer_settings["materials"][self._slicer_settings['default_raft_extruder']] == "HIPS"):
                # Raft opposite of print
                if (self._slicer_settings['extruder'][0] != 
                self._slicer_settings['default_raft_extruder']):
                    config['raftAligned'] = False
                    config['raftModelSpacing'] = 0.0
        return config

    def _get_config_printomatic_file(self):
        """
        Returns the proper material config file based on the slicer config 
        assigned to this miracle grue object.  Things that impact this decision:

            * material type
            * Layer height
            * type of bot

        If no profiles are found that fit our criterion, we default to the
        generic miracle.config file.

        Theres a rather large deficiency in this function: it doesn't really
        support differentiating between the two materials. After talking with 
        JoeClang, we've decided to just pretend this doesn't exist, and only
        worry about it when it becomes an issue (this is partially because
        MakerWare only allows HIPS and ABS to be printed in tandem, and they
        have the same profile.

        FG: This is now a big problem, as birdwing class machines require
        significantly different profiles from Replicator 2(X) and earlier.
        """
        # The list of materials are strings like "STL", "HIPS"
        material_config_files = filter(lambda config: any(mat in config.upper() for mat in self._slicer_settings["materials"]),
                                       os.listdir(self._config_file))
        # Birdwing class machines each have a separate profile
        if self._profile.driver.name == 'birdwing':
            material_config_files = [config for config in material_config_files if self._profile.name.lower() in config.lower()]
        else:
            #TODO have the list of excluded machine specific slicer profiles be queried from teh birdwing driver
            material_config_files = filter(lambda config: not any(excluded_machine in config.lower() for excluded_machine in ('tinkerbell','platypus','moose')),
                material_config_files)
        for config_file in material_config_files:
            config_path = os.path.join(self._config_file, config_file)
            with open(config_path) as fp:
                try:
                    config = conveyor.json_reader.load(fp)
                except:
                    continue
            try:
                #Try to find a valid config to use based on the print's layer_height
                if config['layerHeightMinimum'] <= self._slicer_settings['layer_height'] < config['layerHeightMaximum']:
                    if os.path.exists(config_path):
                        return config_path
            except KeyError:
                continue
        if os.path.join(self._config_file, 'miracle.config'):
            return os.path.join(self._config_file, 'miracle.config')
        else:
            raise IOError("No suitable miracle grue config found")

    def _get_executable(self):
        executable = os.path.abspath(self._slicer_file)
        return executable

    def _get_arguments(self):
        for iterable in self._get_arguments_miraclegrue():
            for value in iterable:
                yield value

    def _get_arguments_miraclegrue(self):
        yield (self._get_executable(),)
        yield ('-c', self._tmp_config_file,)
        if self._profile.driver.name == 'birdwing':
            yield ('-j',)
            yield ('--json-toolpath-output',)
            yield ('-o', self._output_file,)
            yield ('--metadata-output',)
            yield ('--metadata-file',os.path.join(os.path.dirname(self._output_file),'meta.json'))
        else:
            yield ('-o', self._output_file,)
            yield ('-j',)
            
        yield (self._input_file,)

    @staticmethod
    def get_temperatures(path):
        with open(path) as config_fp:
            config = conveyor.json_reader.load(config_fp)
        temperatures = {
            'extruders': [config['extruderTemp0'], config['extruderTemp1']],
            'platform': config['platformTemp']
        }
        return temperatures

    def _get_cwd(self):
        if None is self._slicer_settings['path']:
            cwd = None
        else:
            cwd = os.path.dirname(self._slicer_settings['path'])
        return cwd

    def _read_popen(self):
        # Slightly confusing loop needed because of a bug in Python
        # 2.x, see stackoverflow.com/questions/1183643
        for line in iter(self._popen.stdout.readline, b''):
            self._slicerlog.write(line)
            try:
                dct = json.loads(line)
            except ValueError:
                pass
            else:
                if isinstance(dct, dict):
                    percent = dct.get('totalPercentComplete')
                    if percent:
                        self._setprogress_ratio(int(percent), 100)

    def _epilogue(self):
        pass
