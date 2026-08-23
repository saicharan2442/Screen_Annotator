@echo off
echo Building Screen Annotator EXE...
pip install pyinstaller

if exist "icon.ico" (
    echo Building with custom logo...
    pyinstaller --noconsole --onefile --icon=icon.ico --name "ScreenAnnotator" main.py
) else (
    echo NOTE: No icon.ico found! Please place an 'icon.ico' file in this folder if you want a custom logo.
    echo Building without a custom logo...
    pyinstaller --noconsole --onefile --name "ScreenAnnotator" main.py
)

echo.
echo Done! You can find your final application inside the 'dist' folder:
echo dist\ScreenAnnotator.exe
pause
