; UTF-8
;
; CatSwitch Inno Setup script (per-user install)
; Build after PyInstaller: ISCC CatSwitch.iss
;
; Installs to %LOCALAPPDATA%\Programs\CatSwitch
; Appears in Settings → Apps (HKCU Uninstall key)
; Silent in-app update: temp helper (not under {app}) waits for CatSwitch.exe
; to exit, then runs Setup /VERYSILENT … and launches the new exe.
; Nothing in {app} may still be running — CloseApplications would deadlock.

#define MyAppName "CatSwitch"
; Version SSOT: catswitch/version.py (APP_VERSION). package.py writes dist\version_define.iss.
#include "dist\version_define.iss"
#define MyAppPublisher "github.com/0yz"
#define MyAppURL "https://switch.cat/"
#define MyAppExeName "CatSwitch.exe"
; Fixed AppId — keep forever so upgrades replace the same ARP entry
#define MyAppId "{{A7C4E2B1-9D8F-4E3A-B2C1-5F6A7D8E9B0C}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName}
; PE FileVersion / ProductVersion in Explorer (AppVersion alone does not set these)
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL=https://github.com/0yz/catswitch/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=CatSwitch-Setup-{#MyAppVersion}
SetupIconFile=catswitch\resources\assets\app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Restart Manager often destroys the WebView window without killing Python —
; force close, then PrepareToInstall taskkill as a fallback.
CloseApplications=force
; Do not use RestartApplications — WebView/Python often confuse Restart Manager.
RestartApplications=no
; User data lives in %LOCALAPPDATA%\CatSwitch — kept on uninstall unless the user
; checks “Also delete…” on the uninstall prompt (unchecked by default). Silent
; uninstalls (in-app updates) never wipe data.
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; Wipe prior PyInstaller payload so removed DLLs do not linger across upgrades
; (onefile→onedir migration also drops the old monolithic exe contents cleanly).
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\CatSwitchUpdater.exe"

[Files]
; onedir: CatSwitch.exe + _internal\ (+ notices copied by package.py)
Source: "dist\CatSwitch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion
; Wizard pages extract these at runtime (SourcePath only exists on the build PC)
Source: "LICENSE"; Flags: dontcopy
Source: "PRIVACY.md"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey

[Run]
; Interactive installs only — silent upgrades are launched by the temp helper bat
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  GDeleteUserData: Boolean;
  LicensePage: TWizardPage;
  PrivacyPage: TWizardPage;
  LicenseMemo: TNewMemo;
  PrivacyMemo: TNewMemo;
  LicenseAckCheck: TNewCheckBox;
  PrivacyAckCheck: TNewCheckBox;

function LoadLegalTextFile(const FileName: String): String;
var
  Path: String;
  Lines: TArrayOfString;
  i: Integer;
begin
  Result := '';
  // Extract from Setup into {tmp}; do not use SourcePath (build machine only).
  ExtractTemporaryFile(FileName);
  Path := ExpandConstant('{tmp}\' + FileName);
  if not FileExists(Path) then
  begin
    Result := '(Could not load ' + FileName + ' from the installer package.)';
    Exit;
  end;
  if not LoadStringsFromFile(Path, Lines) then
  begin
    Result := '(Could not read ' + FileName + '.)';
    Exit;
  end;
  for i := 0 to GetArrayLength(Lines) - 1 do
    Result := Result + Lines[i] + #13#10;
end;

procedure CreateAckPage(
  PreviousPageID: Integer;
  const Title, SubCaption, AckCaption, BodyText: String;
  var OutPage: TWizardPage;
  var OutMemo: TNewMemo;
  var OutCheck: TNewCheckBox
);
begin
  OutPage := CreateCustomPage(PreviousPageID, Title, SubCaption);

  OutMemo := TNewMemo.Create(OutPage);
  OutMemo.Parent := OutPage.Surface;
  OutMemo.Left := 0;
  OutMemo.Top := 0;
  OutMemo.Width := OutPage.SurfaceWidth;
  OutMemo.Height := OutPage.SurfaceHeight - ScaleY(36);
  OutMemo.ScrollBars := ssVertical;
  OutMemo.ReadOnly := True;
  OutMemo.WordWrap := True;
  OutMemo.Lines.Text := BodyText;

  OutCheck := TNewCheckBox.Create(OutPage);
  OutCheck.Parent := OutPage.Surface;
  OutCheck.Left := 0;
  OutCheck.Top := OutPage.SurfaceHeight - ScaleY(28);
  OutCheck.Width := OutPage.SurfaceWidth;
  OutCheck.Caption := AckCaption;
  OutCheck.Checked := False;
end;

procedure LicenseAckCheckClick(Sender: TObject);
begin
  WizardForm.NextButton.Enabled := LicenseAckCheck.Checked;
end;

procedure PrivacyAckCheckClick(Sender: TObject);
begin
  WizardForm.NextButton.Enabled := PrivacyAckCheck.Checked;
end;

procedure InitializeWizard;
begin
  CreateAckPage(
    wpWelcome,
    'License',
    'Please review the License before installing.',
    'I have read and acknowledge the License',
    LoadLegalTextFile('LICENSE'),
    LicensePage,
    LicenseMemo,
    LicenseAckCheck
  );
  LicenseAckCheck.OnClick := @LicenseAckCheckClick;

  CreateAckPage(
    LicensePage.ID,
    'Privacy Policy',
    'Please review the Privacy Policy before installing.',
    'I have read and acknowledge the Privacy Policy',
    LoadLegalTextFile('PRIVACY.md'),
    PrivacyPage,
    PrivacyMemo,
    PrivacyAckCheck
  );
  PrivacyAckCheck.OnClick := @PrivacyAckCheckClick;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (LicensePage <> nil) and (CurPageID = LicensePage.ID) then
    WizardForm.NextButton.Enabled := LicenseAckCheck.Checked
  else if (PrivacyPage <> nil) and (CurPageID = PrivacyPage.ID) then
    WizardForm.NextButton.Enabled := PrivacyAckCheck.Checked;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (LicensePage <> nil) and (CurPageID = LicensePage.ID) then
  begin
    Result := LicenseAckCheck.Checked;
    if not Result then
      MsgBox(
        'Please confirm that you have read and acknowledge the License.',
        mbInformation,
        MB_OK
      );
  end
  else if (PrivacyPage <> nil) and (CurPageID = PrivacyPage.ID) then
  begin
    Result := PrivacyAckCheck.Checked;
    if not Result then
      MsgBox(
        'Please confirm that you have read and acknowledge the Privacy Policy.',
        mbInformation,
        MB_OK
      );
  end;
end;

procedure KillRunningCatSwitch;
var
  ResultCode: Integer;
begin
  { /T also ends WebView2 child trees that can keep files locked }
  Exec(
    ExpandConstant('{sys}\taskkill.exe'),
    '/F /IM "{#MyAppExeName}" /T',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  NeedsRestart := False;
  Result := '';
  KillRunningCatSwitch;
end;

function InitializeUninstall(): Boolean;
var
  Form: TSetupForm;
  Info: TNewStaticText;
  CheckBox: TNewCheckBox;
  OKButton: TNewButton;
  CancelButton: TNewButton;
begin
  GDeleteUserData := False;
  Result := True;

  { In-app silent updates must never prompt or wipe AppData }
  if UninstallSilent then
    Exit;

  Form := CreateCustomForm(ScaleX(440), ScaleY(190), False, False);
  try
    Form.Caption := 'Uninstall {#MyAppName}';
    Form.Position := poScreenCenter;

    Info := TNewStaticText.Create(Form);
    Info.Parent := Form;
    Info.Left := ScaleX(16);
    Info.Top := ScaleY(16);
    Info.Width := Form.ClientWidth - ScaleX(32);
    Info.Height := ScaleY(64);
    Info.AutoSize := False;
    Info.WordWrap := True;
    Info.Caption :=
      '{#MyAppName} will be uninstalled. Settings, lists, tokens, and cache under %LOCALAPPDATA%\{#MyAppName} are kept unless you opt in below.';

    CheckBox := TNewCheckBox.Create(Form);
    CheckBox.Parent := Form;
    CheckBox.Left := ScaleX(16);
    CheckBox.Top := ScaleY(90);
    CheckBox.Width := Form.ClientWidth - ScaleX(32);
    CheckBox.Caption := 'Also delete all settings, lists, tokens, and cache';
    CheckBox.Checked := False;

    OKButton := TNewButton.Create(Form);
    OKButton.Parent := Form;
    OKButton.Caption := 'Uninstall';
    OKButton.Default := True;
    OKButton.ModalResult := mrOk;
    OKButton.Width := ScaleX(100);
    OKButton.Left := Form.ClientWidth - ScaleX(220);
    OKButton.Top := Form.ClientHeight - ScaleY(44);

    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Caption := 'Cancel';
    CancelButton.Cancel := True;
    CancelButton.ModalResult := mrCancel;
    CancelButton.Width := ScaleX(100);
    CancelButton.Left := Form.ClientWidth - ScaleX(110);
    CancelButton.Top := OKButton.Top;

    if Form.ShowModal <> mrOk then
    begin
      Result := False;
      Exit;
    end;
    GDeleteUserData := CheckBox.Checked;
  finally
    Form.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;

  { Always clear the Start with Windows Run entry (points at removed exe) }
  RegDeleteValue(HKEY_CURRENT_USER,
    'Software\Microsoft\Windows\CurrentVersion\Run', '{#MyAppName}');

  if GDeleteUserData then
    DelTree(ExpandConstant('{localappdata}\{#MyAppName}'), True, True, True);
end;
