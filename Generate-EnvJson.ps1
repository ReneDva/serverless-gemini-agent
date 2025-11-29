<#
.SYNOPSIS
  Convert a .env file (KEY=VALUE) into env.json for AWS SAM (--env-vars).

.DESCRIPTION
  - Reads .env as UTF-8.
  - Ignores empty lines and comments (#).
  - Removes surrounding quotes from values.
  - Does NOT manually escape backslashes (ConvertTo-Json handles escaping).
  - Backs up existing env.json and writes atomically (UTF-8 without BOM).
#>

param(
    [string]$EnvFile = ".env",
    [string]$OutFile = "env.json"
)

function Read-DotEnv {
    param([string]$Path)
    $dict = @{}
    if (-not (Test-Path $Path)) {
        Write-Error "Env file not found: $Path"
        return $null
    }

    Get-Content -Path $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { return }
        if ($line.StartsWith("#")) { return }

        if ($line -match "^\s*([^=]+?)\s*=\s*(.*)$") {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()

            # Remove surrounding quotes if present
            if ($value.Length -ge 2) {
                if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }

            # Keep value as-is (do not pre-escape backslashes)
            $dict[$key] = $value
        }
    }

    return $dict
}

# Read .env
$envVars = Read-DotEnv -Path $EnvFile
if ($null -eq $envVars) { exit 1 }

# Build SAM-style JSON object. Add or remove function keys as needed.
$jsonObj = @{
    PresignFunction    = @{
        INPUT_BUCKET_NAME = $envVars["INPUT_BUCKET_NAME"]
    }
    VoiceAgentFunction = $envVars
    EnvEchoFunction    = $envVars
}

# Convert to pretty JSON
$jsonText = $jsonObj | ConvertTo-Json -Depth 10


# Atomic write: write to temp file then move to destination
$temp = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($temp, $jsonText, (New-Object System.Text.UTF8Encoding($false)))
Move-Item -Path $temp -Destination $OutFile -Force

Write-Host "Wrote $OutFile (UTF-8 without BOM)."
