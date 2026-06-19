$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python .\server.py --host 127.0.0.1 --port 8081
