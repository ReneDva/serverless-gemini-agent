# Generate-EnvJson.ps1
# Purpose: Convert a .env file (KEY=VALUE) into env.json for SAM (--env-vars)
# Notes: Writes UTF-8 without BOM, ignores comments and empty lines.

param(
    [string]$EnvFile = ".env",
    [string]$OutFile = "env.json"
)

# Read .env into dictionary
$envVars = @{}
Get-Content -Path $EnvFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if ([string]::IsNullOrWhiteSpace($line)) { return }
    if ($line.StartsWith("#")) { return }
    if ($line -match "^\s*([^=]+?)\s*=\s*(.*)$") {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim()

        # Remove surrounding quotes if present
        if ($value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        } elseif ($value.StartsWith("'") -and $value.EndsWith("'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        # Escape backslashes for JSON (e.g., Windows paths)
        $value = $value -replace '\\', '\\\\'

        $envVars[$key] = $value
    }
}

# Build SAM-style JSON object. Adjust function names here if needed.
$jsonObj = @{
    PresignFunction = @{
        INPUT_BUCKET_NAME = $envVars["INPUT_BUCKET_NAME"]
    }
    VoiceAgentFunction = $envVars
}

# Convert to JSON and write as UTF-8 without BOM
$jsonText = $jsonObj | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($OutFile, $jsonText, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Wrote $OutFile (UTF-8 without BOM)."
