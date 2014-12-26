# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/client/__main__.py
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

import logging
import sys

import conveyor.client
import conveyor.log
import conveyor.main

from conveyor.decorator import command

@command(conveyor.client.AuthenticateConnectionCommand)
@command(conveyor.client.BirdWingCancelCommand)
@command(conveyor.client.BirdWingGetCommand)
@command(conveyor.client.BirdWingHandshakeCommand)
@command(conveyor.client.BirdWingListCommand)
@command(conveyor.client.BirdWingLockCommand)
@command(conveyor.client.BirdWingPutCommand)
@command(conveyor.client.BirdWingUnlockCommand)
@command(conveyor.client.BirdWingUpdateFirmwareCommand)
@command(conveyor.client.BirdWingZipLogsCommand)
@command(conveyor.client.CalibrateCameraOldCommand)
@command(conveyor.client.CalibrateLaserCommand)
@command(conveyor.client.CalibrateTurntableOldCommand)
@command(conveyor.client.CancelCommand)
@command(conveyor.client.CaptureBackgroundCommand)
@command(conveyor.client.CaptureImageCommand)
@command(conveyor.client.ChangeDisplayNameCommand)
@command(conveyor.client.ConnectCommand)
@command(conveyor.client.CreateMeshCommand)
@command(conveyor.client.CutPlaneCommand)
@command(conveyor.client.DebugCommand)
@command(conveyor.client.DefaultConfigCommand)
@command(conveyor.client.DestroyMeshCommand)
@command(conveyor.client.DirCommand)
@command(conveyor.client.DisconnectCommand)
@command(conveyor.client.DirectConnectCommand)
@command(conveyor.client.DownloadFirmware)
@command(conveyor.client.DriverCommand)
@command(conveyor.client.DriversCommand)
@command(conveyor.client.FirstContactCommand)
@command(conveyor.client.GetDigitizerVersionCommand)
@command(conveyor.client.GetMachineVersions)
@command(conveyor.client.GetReprojectionErrorCommand)
@command(conveyor.client.GetUploadableMachines)
@command(conveyor.client.GetAuthenticationCodeCommand)
@command(conveyor.client.JobCommand)
@command(conveyor.client.JobsCommand)
@command(conveyor.client.JobPauseCommand)
@command(conveyor.client.JobResumeCommand)
@command(conveyor.client.LoadCalibrationCommand)
@command(conveyor.client.LoadMeshCommand)
@command(conveyor.client.LoadFactoryCalibrationCommand)
@command(conveyor.client.LoadFilamentCommand)
@command(conveyor.client.LoadUserCalibrationCommand)
@command(conveyor.client.MeshCommand)
@command(conveyor.client.NetworkStateCommand)
@command(conveyor.client.PauseCommand)
@command(conveyor.client.PortsCommand)
@command(conveyor.client.PrintAgainCommand)
@command(conveyor.client.PrintCommand)
@command(conveyor.client.StreamingPrintCommand)
@command(conveyor.client.PrintFromFileCommand)
@command(conveyor.client.PrintToFileCommand)
@command(conveyor.client.PrintersCommand)
@command(conveyor.client.ProfileCommand)
@command(conveyor.client.ProfilesCommand)
@command(conveyor.client.PlaceOnPlatformCommand)
@command(conveyor.client.PointCloudCreateCommand)
@command(conveyor.client.PointCloudDestroyCommand)
@command(conveyor.client.PointCloudFineAlignmentCommand)
@command(conveyor.client.PointCloudCoarseAlignmentCommand)
@command(conveyor.client.PointCloudGlobalAlignmentCommand)
@command(conveyor.client.PointCloudCropCommand)
@command(conveyor.client.PointCloudLoadCommand)
@command(conveyor.client.PointCloudLoadFromIDCommand)
@command(conveyor.client.PointCloudProcessCommand)
@command(conveyor.client.PointCloudSaveCommand)
@command(conveyor.client.QueryDigitizerCommand)
@command(conveyor.client.ReadEepromCommand)
@command(conveyor.client.ResetToFactoryCommand)
@command(conveyor.client.SaveCalibrationCommand)
@command(conveyor.client.SaveMeshCommand)
@command(conveyor.client.SaveFactoryCalibrationCommand)
@command(conveyor.client.SaveUserCalibrationCommand)
@command(conveyor.client.ScanCommand)
@command(conveyor.client.ScannerJogCommand)
@command(conveyor.client.SendThingiverseCredentialsCommand)
@command(conveyor.client.SliceCommand)
@command(conveyor.client.StartUploadFirmwareJobCommand)
@command(conveyor.client.ToggleCameraCommand)
@command(conveyor.client.ToggleLaserCommand)
@command(conveyor.client.UnloadFilamentCommand)
@command(conveyor.client.UnpauseCommand)
@command(conveyor.client.UpgradeMiracleGrueConfigCommand)
@command(conveyor.client.UploadFirmwareCommand)
@command(conveyor.client.UsbDeviceInsertedCommand)
@command(conveyor.client.UsbDeviceRemovedCommand)
@command(conveyor.client.WaitForServiceCommand)
@command(conveyor.client.WifiScanCommand)
@command(conveyor.client.WifiConnectCommand)
@command(conveyor.client.WifiDisconnectCommand)
@command(conveyor.client.WifiForgetCommand)
@command(conveyor.client.WifiDisableCommand)
@command(conveyor.client.WifiEnableCommand)
@command(conveyor.client.WriteEepromCommand)
@command(conveyor.client.JogCommand)
@command(conveyor.client.TOMCalibrationCommand)
@command(conveyor.client.HomeCommand)
@command(conveyor.client.ResetEepromCompletelyCommand)
@command(conveyor.client.CalibrateCameraCommand)
@command(conveyor.client.CalibrateTurntableCommand)
@command(conveyor.client.GlobalAlignAndMeshCommand)

class ClientMain(conveyor.main.AbstractMain):
    _program_name = 'conveyor'

    _config_section = 'client'

    _logging_handlers = ['stdout', 'stderr',]

    def _run(self):
        self._log_startup(logging.DEBUG)
        self._init_event_threads()
        command = self._parsed_args.command_class(
            self._parsed_args, self._config)
        code = command.run()
        return code


def _main(argv): # pragma: no cover
    conveyor.log.earlylogging('conveyor', True)
    main = ClientMain()
    code = main.main(argv)
    return code


if '__main__' == __name__: # pragma: no cover
    sys.exit(_main(sys.argv))
