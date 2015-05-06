!ifndef VERSION
  !define VERSION 'DEV'
!endif

!ifndef BUILD
  !define BUILD '3dprinteros_client_setup'
!endif

; Define your application name
!define APPNAME "3DPrinterOS Client"
!define APPNAMEANDVERSION "3DPrinterOS Client ${VERSION}"

; Main Install settings
Name "${APPNAMEANDVERSION}"
InstallDir "$PROGRAMFILES\3DPrinterOS Client"
InstallDirRegKey HKLM "Software\${APPNAME}" ""
OutFile "${BUILD}.exe"
Icon "pictures\icon.ico"

!include x64.nsh

; Modern interface settings
!include "MUI.nsh"

; MUI Settings / Icons
!define MUI_ICON "pictures\icon.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\orange-uninstall-nsis.ico"
 
; MUI Settings / Header
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "pictures\header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "pictures\header.bmp"
 
; MUI Settings / Wizard
!define MUI_WELCOMEFINISHPAGE_BITMAP "pictures\side_banner.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "pictures\side_banner.bmp"


!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\3dprinteros_client.exe"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "C:\installer\license.txt"
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

	; Set Section Files and Shortcuts
	SetOutPath "$INSTDIR\"
	File /r "3dprinteros-client\"
	CreateShortCut "$DESKTOP\3DPrinterOS Client.lnk" "$INSTDIR\3dprinteros_client.exe"
	CreateDirectory "$SMPROGRAMS\3DPrinterOS Client"
	CreateShortCut "$SMPROGRAMS\3DPrinterOS Client\3DPrinteros Client.lnk" "$INSTDIR\3dprinteros_client.exe"
	CreateShortCut "$SMPROGRAMS\3DPrinterOS Client\Uninstall.lnk" "$INSTDIR\uninstall.exe"

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
	
  SetShellVarContext all
	
	; Delete self
	Delete "$INSTDIR\uninstall.exe"
	
	; Clean up 3DPrinteros Client
	RMDir /r "$INSTDIR\"

	;Remove from registry...
	DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
	DeleteRegKey HKLM "SOFTWARE\${APPNAME}"

	; Delete Shortcuts
	Delete "$DESKTOP\3DPrinterOS Client.lnk"
	RMDir /r "$SMPROGRAMS\3DPrinterOS Client\"

SectionEnd

; On initialization
Function .onInit

	!insertmacro MUI_LANGDLL_DISPLAY

FunctionEnd

; eof