!ifndef VERSION
  !define VERSION 'DEV'
!endif

!ifndef BUILD
  !define BUILD '3dprinteros_client_setup'
!endif

; Define your application name
!define APPNAME "3DPrinterOS Client"
!define APPNAMEANDVERSION "${APPNAME} ${VERSION}"

; Main Install settings
Name "${APPNAMEANDVERSION}"
InstallDir "$PROGRAMFILES\${APPNAME}"
InstallDirRegKey HKLM "Software\${APPNAME}" ""
OutFile "${BUILD}.exe"
Icon "pictures\icon.ico"

!include x64.nsh

; Modern interface settings
!include "MUI.nsh"

; MUI Settings / Icons
!define MUI_ICON "pictures\icon.ico"
!define MUI_UNICON "pictures\uninstall.ico"
 
; MUI Settings / Header
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "pictures\header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "pictures\header.bmp"
 
; MUI Settings / Wizard
!define MUI_WELCOMEFINISHPAGE_BITMAP "pictures\side_banner.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "pictures\side_banner.bmp"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchLink"

Function LaunchLink
	ExecShell "" "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
FunctionEnd

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "license.txt"
;!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; Set languages (first is default language)
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Russian"
!insertmacro MUI_RESERVEFILE_LANGDLL

Section "3DPrinterOS Client" Section1

	; Set Section properties
	SetOverwrite on

	SetOutPath "$INSTDIR\"

	; Set Section Files and Shortcuts
	File /r "3dprinteros-client\"
		
	SetOutPath "$INSTDIR\client"
	
	CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\python27\pythonw.exe" '"$INSTDIR\client\launcher.py"' "$INSTDIR\icon.ico"
	ShellLink::SetRunAsAdministrator "$DESKTOP\${APPNAME}.lnk"
	CreateDirectory "$SMPROGRAMS\${APPNAME}"
	CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\python27\pythonw.exe" '"$INSTDIR\client\launcher.py"' "$INSTDIR\icon.ico"
	ShellLink::SetRunAsAdministrator "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
	CreateShortCut "$SMPROGRAMS\${APPNAME}\Uninstall.lnk" "$INSTDIR\uninstall.exe"
	
	SetShellVarContext all

SectionEnd

Section "Drivers" Section2
	SetOutPath $INSTDIR\drivers
	File /r "drivers\"
	${If} ${RunningX64}
    ExecWait "$INSTDIR\drivers\dpinst64.exe"
	${Else}
		ExecWait "$INSTDIR\drivers\dpinst32.exe"
	${EndIf}	
  ExecWait "$INSTDIR\drivers\CDM v2.08.30 WHQL Certified.exe"
	ExecWait "$INSTDIR\drivers\RUMBA_DRIVER.exe"
  
SectionEnd

Section -FinishSection

	WriteRegStr HKLM "Software\${APPNAME}" "" "$INSTDIR"
	WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayName" "${APPNAME}"
	WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "UninstallString" "$INSTDIR\uninstall.exe"
	WriteUninstaller "$INSTDIR\uninstall.exe"

SectionEnd

; Modern install component descriptions
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
	!insertmacro MUI_DESCRIPTION_TEXT ${Section1} ""
!insertmacro MUI_FUNCTION_DESCRIPTION_END

;Uninstall section
Section Uninstall	
	
	FindProcDLL::FindProc "python.exe"
	IntCmp $R0 1 0 notRunning
			MessageBox MB_OK|MB_ICONEXCLAMATION "${APPNAME} or another Python application is running. Please close it first" /SD IDOK
			Abort
	notRunning:
		
	; Delete self
	Delete "$INSTDIR\uninstall.exe"
	
	; Clean up 3DPrinteros Client
	RMDir /r "$INSTDIR\"

	;Remove from registry...
	DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
	DeleteRegKey HKLM "SOFTWARE\${APPNAME}"
	
	
	; Delete Shortcuts

	SetShellVarContext all
	Delete "$DESKTOP\${APPNAME}.lnk"

	RMDir /r "$SMPROGRAMS\${APPNAME}"

SectionEnd

; On initialization
Function .onInit

	!insertmacro MUI_LANGDLL_DISPLAY

FunctionEnd


; eof