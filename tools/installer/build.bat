echo
echo python get_version.py | (set /p VERSION= & set VERSION)
makensis /DVERSION="%VERSION%" /DBUILD="%1" 3dprinteros-client.nsi