$PSScriptRoot = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
$pythonPath = "python"
& $pythonPath "$PSScriptRoot\divCLI.py"
