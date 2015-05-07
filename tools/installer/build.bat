echo
python get_version.py
set /p version= < version.txt
makensis /DVERSION="%version%" /DBUILD="%1" 3dprinteros-client.nsi