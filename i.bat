@echo off
if "%1"=="s1" python instl sync --in C:\p4client\ProAudio\dev_install\sample_data\betainstl\V9\s3.yaml
if "%1"=="s2" C:\p4client\ProAudio\dev_install\sample_data\betainstl\V9\s3.yaml-sync.bat
if "%2"=="s2" C:\p4client\ProAudio\dev_install\sample_data\betainstl\V9\s3.yaml-sync.bat

if "%1"=="c1" python instl copy --in C:\p4client\ProAudio\dev_install\sample_data\betainstl\V9\s3.yaml
if "%1"=="c2" c:\p4client\ProAudio\dev_install\sample_data\betainstl\V9\s3.yaml-copy.bat
if "%2"=="c2" c:\p4client\ProAudio\dev_install\sample_data\betainstl\V9\s3.yaml-copy.bat
