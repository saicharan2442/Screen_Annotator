Write-Output "Building Screen Annotator executable..."
pyinstaller --noconsole --onefile --icon=icon.ico --name ScreenAnnotator main.py
Write-Output "Build complete! Check the 'dist' folder for ScreenAnnotator.exe"
