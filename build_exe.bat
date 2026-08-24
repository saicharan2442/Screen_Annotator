@echo off
echo Building Screen Annotator EXE...
pip install pyinstaller

if exist "icon.ico" (
    echo Building with custom logo via ScreenAnnotator.spec...
) else (
    echo NOTE: No icon.ico found! 
    echo Building without a custom logo via ScreenAnnotator.spec...
)

echo Running PyInstaller...
pyinstaller --clean -y ScreenAnnotator.spec

echo.
echo Adding application to Windows Startup...
powershell "$s=(New-Object -COM WScript.Shell).CreateShortcut('%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ScreenAnnotator.lnk');$s.TargetPath='%~dp0dist\ScreenAnnotator.exe';$s.WorkingDirectory='%~dp0dist';$s.Save()"
echo.
echo Done! You can find your final application inside the 'dist' folder:
echo dist\ScreenAnnotator.exe
echo The application has been added to Startup and will launch automatically when you restart.
pause
