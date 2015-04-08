set objWSHShell = CreateObject("WScript.Shell")
set objFso = CreateObject("Scripting.FileSystemObject")

sShortcut = objWSHShell.ExpandEnvironmentStrings(WScript.Arguments.Item(0))
sTargetPath = objWSHShell.ExpandEnvironmentStrings(WScript.Arguments.Item(1))
sWorkingDirectory = objFso.GetAbsolutePathName(sShortcut)

set objSC = objWSHShell.CreateShortcut(sShortcut)

objSC.TargetPath = sTargetPath
objSC.WorkingDirectory = sWorkingDirectory

objSC.Save