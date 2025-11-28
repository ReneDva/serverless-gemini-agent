# PowerShell script: Generate-EnvJson.ps1
# Purpose: Convert an existing .env file (KEY=VALUE format) into a JSON file (env.json)
#          that can be used with AWS SAM CLI (--env-vars).
# Notes:
# - Reads the .env file line by line using UTF-8 encoding.
# - Builds a JSON object in the SAM format with Hebrew characters converted to \uXXXX.
# - Writes the resulting env.json explicitly in UTF-8 (without BOM).

function Convert-HebrewToUnicode {
    param([string]$jsonText)
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $jsonText.ToCharArray()) {
        $code = [int][char]$ch
        if ($code -ge 0x0590 -and $code -le 0x05FF) {
            # Convert only Hebrew characters to \uXXXX
            $null = $sb.AppendFormat("\u{0:x4}", $code)
        } else {
            $null = $sb.Append($ch)
        }
    }
    return $sb.ToString()
}

# Read the .env file with explicit UTF-8 encoding
$envVars = @{}
Get-Content -Path .env -Encoding UTF8 | ForEach-Object {
    if ($_ -match "^(.*?)=(.*)$") {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim()
        $envVars[$key] = $value
    }
}

# Build JSON object
$jsonObj = @{
    PresignFunction    = @{ INPUT_BUCKET_NAME = $envVars["INPUT_BUCKET_NAME"] }
    VoiceAgentFunction = $envVars
}

# Convert to JSON string (with Hebrew characters still literal)
$jsonText = $jsonObj | ConvertTo-Json -Depth 3

# Replace Hebrew characters with \uXXXX escapes
$jsonEscaped = Convert-HebrewToUnicode $jsonText

# Write the JSON object to env.json explicitly in UTF-8 (without BOM)
[System.IO.File]::WriteAllText("env.json", $jsonEscaped, (New-Object System.Text.UTF8Encoding($false)))
