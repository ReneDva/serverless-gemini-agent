<#
.SYNOPSIS
  Build Python layer, ensure SAM artifacts S3 bucket exists, run sam build and sam deploy.

.DESCRIPTION
  - Installs dependencies from backend/requirements.txt into layer/python/lib/python3.14/site-packages
  - Creates layer.zip (optional) and keeps layer/ folder for SAM ContentUri
  - Ensures the SAM artifacts bucket exists; if missing, creates it and configures:
      * server-side encryption (SSE-S3)
      * block public access
      * versioning enabled
      * lifecycle rule to expire artifacts after 90 days
  - Loads deployment parameters (GeminiApiKey, InputBucketName) from .env file
  - Validates that InputBucketName does not already exist (to avoid CloudFormation ResourceExistenceCheck failures)
  - Runs sam build and sam deploy with parameter overrides
  - Defaults:
      Profile = "gemini-project-runner"
      Region = "us-east-1"
      StackName = "gemini-voice-agent-dev"
      S3BucketForSam = "rene-gemini-sam-artifacts-dev" (used when not provided)
  - How to run
    From project root (where template.yaml lives):
    .\deploy-layer-and-sam.ps1
    # or specify parameters
    .\deploy-layer-and-sam.ps1 -Profile gemini-project-runner -Region us-east-1 -StackName gemini-voice-agent-dev -S3BucketForSam rene-gemini-sam-artifacts-dev
#>

param(
  [string]$Profile = "gemini-project-runner",
  [string]$Region = "us-east-1",
  [string]$StackName = "gemini-voice-agent-dev",
  [string]$S3BucketForSam = ""
)

Set-StrictMode -Version Latest

# -------------------------
# Helper: write error and exit
function Fail([string]$msg, [int]$code = 1) {
  Write-Error $msg
  exit $code
}

# -------------------------
# Load .env file (if exists)
$envFile = Join-Path $PWD ".env"
if (Test-Path $envFile) {
  Write-Host "Loading environment variables from $envFile"
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -match "^\s*#") { return }    # skip comments
    if ($line -match "^\s*$") { return }    # skip empty
    $parts = $line -split "=", 2
    if ($parts.Length -eq 2) {
      $key = $parts[0].Trim()
      $val = $parts[1].Trim()
      # Remove surrounding quotes if present
      if ($val.StartsWith('"') -and $val.EndsWith('"')) { $val = $val.Trim('"') }
      if ($val.StartsWith("'") -and $val.EndsWith("'")) { $val = $val.Trim("'") }
      Set-Item -Path "Env:$key" -Value $val
      Write-Host "Loaded $key from .env"
    }
  }
} else {
  Write-Warning ".env file not found at $envFile. Make sure to set required env vars manually."
}

# -------------------------
# Extract required parameters from environment
$InputBucketName = $env:INPUT_BUCKET_NAME
$GeminiApiKey    = $env:GEMINI_API_KEY

if ([string]::IsNullOrWhiteSpace($InputBucketName) -or [string]::IsNullOrWhiteSpace($GeminiApiKey)) {
  Fail "Missing required parameters. Ensure INPUT_BUCKET_NAME and GEMINI_API_KEY are set in .env or environment."
}

# Default artifacts bucket if not provided
if ([string]::IsNullOrEmpty($S3BucketForSam)) {
  $S3BucketForSam = "rene-gemini-sam-artifacts-dev"
  Write-Host "S3BucketForSam not provided. Using default: $S3BucketForSam"
} else {
  Write-Host "Using S3 artifacts bucket: $S3BucketForSam"
}

# -------------------------
# Validate required CLIs
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
  Fail "AWS CLI not found in PATH. Install and configure AWS CLI before running this script."
}
if (-not (Get-Command sam -ErrorAction SilentlyContinue)) {
  Fail "SAM CLI not found in PATH. Install AWS SAM CLI before running this script."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Warning "Python not found in PATH. Ensure python is available for pip installs if you need to build the layer."
}

# -------------------------
# Helper: run aws command and capture output
function Run-Aws([string]$cmd) {
  $full = "aws $cmd --profile $Profile --region $Region"
  Write-Host "Running: $full"
  $output = & aws $cmd --profile $Profile --region $Region 2>&1
  $exit = $LASTEXITCODE
  return @{ ExitCode = $exit; Output = $output }
}

# -------------------------
# Validate that the deployment InputBucketName does NOT already exist
Write-Host "Validating that stack-managed input bucket does not already exist: $InputBucketName"
$headResult = & aws s3api head-bucket --bucket $InputBucketName --profile $Profile --region $Region 2>&1
$headExit = $LASTEXITCODE
if ($headExit -eq 0) {
  Fail "Input bucket '$InputBucketName' already exists. Choose a unique name for stack-managed bucket (update INPUT_BUCKET_NAME in .env)."
} else {
  # Inspect output to differentiate Not Found vs permission/redirect
  if ($headResult -match "Not Found|404") {
    Write-Host "Input bucket does not exist (OK)."
  } elseif ($headResult -match "301|PermanentRedirect") {
    Fail "Bucket name '$InputBucketName' exists in another region (PermanentRedirect). Choose a different name or use an existing-bucket deployment flow."
  } elseif ($headResult -match "403|Forbidden") {
    Fail "Access denied when checking bucket '$InputBucketName'. The bucket may exist but be owned by another account. Choose a different name or ensure caller has permissions."
  } else {
    Write-Host "head-bucket returned non-zero exit code; assuming bucket does not exist but please verify if unsure. Output:"
    Write-Host $headResult
  }
}

# -------------------------
# 1. Prepare layer directory structure
Write-Host "Preparing layer directory..."
try {
  Remove-Item -Recurse -Force .\layer -ErrorAction SilentlyContinue
} catch { }
New-Item -ItemType Directory -Path .\layer\python\lib\python3.14\site-packages -Force | Out-Null

# -------------------------
# 2. Install dependencies into layer site-packages
if (Test-Path .\backend\requirements.txt) {
  Write-Host "Installing Python dependencies into layer from backend/requirements.txt..."
  & python -m pip install --upgrade -r .\backend\requirements.txt -t .\layer\python\lib\python3.14\site-packages
  if ($LASTEXITCODE -ne 0) {
    Fail "pip install failed. Fix errors and re-run."
  }
} else {
  Write-Warning "backend/requirements.txt not found. Proceeding without adding dependencies to the layer."
}

# -------------------------
# 3. Create layer.zip (optional)
Write-Host "Creating layer.zip..."
if (Test-Path .\layer.zip) { Remove-Item .\layer.zip -Force }
try {
  Compress-Archive -Path .\layer\* -DestinationPath .\layer.zip -Force
  Write-Host "layer.zip created."
} catch {
  Write-Warning "Compress-Archive failed or returned non-zero. Verify layer contents manually."
}

# -------------------------
# 4. Ensure SAM artifacts S3 bucket exists and is configured
Write-Host "Ensuring SAM artifacts bucket exists: $S3BucketForSam"
$bucketHead = & aws s3api head-bucket --bucket $S3BucketForSam --profile $Profile --region $Region 2>&1
$bucketHeadExit = $LASTEXITCODE
$bucketExists = $false
if ($bucketHeadExit -eq 0) {
  $bucketExists = $true
  Write-Host "Bucket $S3BucketForSam already exists."
} else {
  if ($bucketHead -match "Not Found|404") {
    $bucketExists = $false
  } elseif ($bucketHead -match "301|PermanentRedirect") {
    Fail "Artifacts bucket '$S3BucketForSam' exists in another region (PermanentRedirect). Choose a different artifacts bucket name or set the correct region."
  } elseif ($bucketHead -match "403|Forbidden") {
    Fail "Access denied when checking artifacts bucket '$S3BucketForSam'. Ensure the deployer has permissions or choose a different bucket name."
  } else {
    Write-Host "head-bucket returned non-zero; proceeding to create bucket (output below):"
    Write-Host $bucketHead
  }
}

if (-not $bucketExists) {
  Write-Host "Creating bucket $S3BucketForSam..."
  if ($Region -eq "us-east-1") {
    $create = Run-Aws "s3api create-bucket --bucket $S3BucketForSam"
  } else {
    $create = Run-Aws "s3api create-bucket --bucket $S3BucketForSam --create-bucket-configuration LocationConstraint=$Region"
  }
  if ($create.ExitCode -ne 0) {
    Fail "Failed to create bucket $S3BucketForSam. Output:`n$($create.Output)"
  }

  # Wait briefly for bucket propagation
  Write-Host "Waiting for bucket propagation..."
  Start-Sleep -Seconds 5

  Write-Host "Configuring bucket encryption (SSE-S3)..."
  $enc = Run-Aws "s3api put-bucket-encryption --bucket $S3BucketForSam --server-side-encryption-configuration '{\"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"AES256\"}}]}'"
  if ($enc.ExitCode -ne 0) { Write-Warning "put-bucket-encryption returned: $($enc.Output)" }

  Write-Host "Blocking public access..."
  $pub = Run-Aws "s3api put-public-access-block --bucket $S3BucketForSam --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
  if ($pub.ExitCode -ne 0) { Write-Warning "put-public-access-block returned: $($pub.Output)" }

  Write-Host "Enabling versioning..."
  $ver = Run-Aws "s3api put-bucket-versioning --bucket $S3BucketForSam --versioning-configuration Status=Enabled"
  if ($ver.ExitCode -ne 0) { Write-Warning "put-bucket-versioning returned: $($ver.Output)" }

  Write-Host "Adding lifecycle rule to expire artifacts after 90 days..."
  $lifecycleJson = @"
{
  "Rules": [
    {
      "ID": "ExpireSamArtifacts",
      "Status": "Enabled",
      "Prefix": "",
      "Expiration": { "Days": 90 },
      "NoncurrentVersionExpiration": { "NoncurrentDays": 90 }
    }
  ]
}
"@
  $tmpLifecycle = Join-Path $PWD "sam-lifecycle.json"
  $lifecycleJson | Out-File -FilePath $tmpLifecycle -Encoding utf8
  $lc = Run-Aws "s3api put-bucket-lifecycle-configuration --bucket $S3BucketForSam --lifecycle-configuration file://$tmpLifecycle"
  if ($lc.ExitCode -ne 0) { Write-Warning "put-bucket-lifecycle-configuration returned: $($lc.Output)" }
  Remove-Item $tmpLifecycle -ErrorAction SilentlyContinue

  Write-Host "Bucket $S3BucketForSam created and configured."
}

# -------------------------
# 5. Build with SAM
# Ensure SAM uses the intended profile
$env:AWS_PROFILE = $Profile
Write-Host "Running sam build with AWS profile '$Profile'..."
sam build
if ($LASTEXITCODE -ne 0) {
  Fail "sam build failed. Fix build errors and re-run."
}

# -------------------------
# 6. Deploy with SAM (with parameter overrides from .env)
Write-Host "Running sam deploy..."
# Quote parameter overrides to avoid issues with special characters
$paramInput = "InputBucketName=$InputBucketName"
$paramGemini = "GeminiApiKey=$GeminiApiKey"

sam deploy `
  --stack-name $StackName `
  --profile $Profile `
  --region $Region `
  --s3-bucket $S3BucketForSam `
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM `
  --parameter-overrides "$paramInput" "$paramGemini"

if ($LASTEXITCODE -ne 0) {
  Fail "sam deploy failed. Check output and fix issues."
}

Write-Host "Deployment finished. Layer and functions should be updated in stack: $StackName"














