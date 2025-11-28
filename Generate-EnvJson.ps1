# PowerShell script: Generate-EnvJson.ps1
# Purpose: Convert an existing .env file (KEY=VALUE format) into a JSON file (env.json)
#          that can be used with AWS SAM CLI (--env-vars).
# Notes:
# - This script reads the .env file line by line using UTF-8 encoding.
# - Each line is parsed into a key/value pair.
# - The key/value pairs are stored in a hashtable.
# - The hashtable is then converted into JSON in the format SAM expects.
# - The resulting env.json file is written explicitly in UTF-8 (without BOM).

# Read the .env file with explicit UTF-8 encoding
$envVars = @{}
Get-Content -Path .env -Encoding UTF8 | ForEach-Object {
    if ($_ -match "^(.*?)=(.*)$") {
        $envVars[$matches[1]] = $matches[2]
    }
}

# Create a JSON object in the SAM (--env-vars) format
$json = @{
    PresignFunction    = @{ INPUT_BUCKET_NAME = $envVars["INPUT_BUCKET_NAME"] }
    VoiceAgentFunction = $envVars
} | ConvertTo-Json -Depth 3 -Compress

# Write the JSON object to env.json explicitly in UTF-8
[System.IO.File]::WriteAllText("env.json", $json, (New-Object System.Text.UTF8Encoding($false)))
