# PowerShell script: Generate-EnvJson.ps1
# Purpose: Convert an existing .env file (KEY=VALUE format) into a JSON file (env.json)
#          that can be used with AWS SAM CLI (--env-vars).
# Notes:
# - Reads the .env file line by line using UTF-8 encoding.
# - Builds a hashtable of key/value pairs.
# - Converts the entire JSON string so that non-ASCII characters are stored as \uXXXX escapes.
# - Writes the resulting env.json explicitly in UTF-8 (without BOM).

function Convert-JsonToUnicodeEscape {
    param([string]$jsonText)
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $jsonText.ToCharArray()) {
        if ([int][char]$ch -gt 127) {
            # Convert non-ASCII characters to \uXXXX
            $null = $sb.AppendFormat("\u{0:x4}", [int][char]$ch)
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
        $key = $matches[1]
        $value = $matches[2]
        $envVars[$key] = $value
    }
}

# Create a JSON object in the SAM (--env-vars) format
$jsonObj = @{
    PresignFunction    = @{ INPUT_BUCKET_NAME = $envVars["INPUT_BUCKET_NAME"] }
    VoiceAgentFunction = $envVars
}

# Convert to JSON string
$jsonText = $jsonObj | ConvertTo-Json -Depth 3 -Compress

# Escape non-ASCII characters in the entire JSON string
$jsonEscaped = Convert-JsonToUnicodeEscape $jsonText

# Write the JSON object to env.json explicitly in UTF-8
[System.IO.File]::WriteAllText("env.json", $jsonEscaped, (New-Object System.Text.UTF8Encoding($false)))
