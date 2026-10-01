Write-Output "Building Screen Annotator executable..."
pyinstaller --noconsole --onedir --icon=icon.ico --exclude-module PyQt5 --exclude-module PyQt6 --name ScreenAnnotator main.py
Write-Output "Build complete! Creating zip file..."
Compress-Archive -Path dist\ScreenAnnotator -DestinationPath dist\ScreenAnnotator_Setup.zip -Force
Write-Output "Zip complete! Check the 'dist' folder for ScreenAnnotator_Setup.zip"
