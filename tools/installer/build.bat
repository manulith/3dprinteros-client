echo
python get_version.py
set /p VERSION=<version.txt
makensis /DVERSION="%VERSION%" /DBUILD="%1" 3dprinteros-client.nsi