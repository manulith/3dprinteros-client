'Copyright (c) 2015 3D Control Systems LTD

'3DPrinterOS client is free software: you can redistribute it and/or modify
'it under the terms of the GNU Affero General Public License as published by
'the Free Software Foundation, either version 3 of the License, or
'(at your option) any later version.

'3DPrinterOS client is distributed in the hope that it will be useful,
'but WITHOUT ANY WARRANTY; without even the implied warranty of
'MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
'GNU Affero General Public License for more details.

'You should have received a copy of the GNU Affero General Public License
'along with 3DPrinterOS client.  If not, see <http://www.gnu.org/licenses/>.


set WSHShell = CreateObject("WScript.Shell")
set objFso = CreateObject("Scripting.FileSystemObject")

sShortcut = WSHShell.ExpandEnvironmentStrings(WScript.Arguments.Item(0))
sTargetPath = WSHShell.ExpandEnvironmentStrings(WScript.Arguments.Item(1))
sIconLocation = WSHShell.ExpandEnvironmentStrings(WScript.Arguments.Item(2))
sWorkingDirectory = objFso.GetAbsolutePathName(sShortcut)

set objSC = WSHShell.CreateShortcut(sShortcut)

objSC.TargetPath = sTargetPath
objSC.WorkingDirectory = sWorkingDirectory
objSC.IconLocation = sIconLocation

objSC.Save