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

# --- Load .env file (same folder as template.yaml) ---
$envFile = Join-Path $PWD ".env"
if (Test-Path $envFile) {
  Write-Host "Loading environment variables from $envFile"
  Get-Content $envFile | ForEach-Object {
    if ($_ -match "^\s*#") { return } # comments
    if ($_ -match "^\s*$") { return } # empty lines
    $parts = $_ -split "=", 2
    if ($parts.Length -eq 2) {
      $key = $parts[0].Trim()
      $val = $parts[1].Trim()
      Set-Item -Path "Env:$key" -Value $val
      Write-Host "Loaded $key from .env"
    }
  }
} else {
  Write-Warning ".env file not found at $envFile. Make sure to set required env vars manually."
}

# Extract required parameters from environment
$InputBucketName = $env:INPUT_BUCKET_NAME
$GeminiApiKey    = $env:GEMINI_API_KEY

if ([string]::IsNullOrWhiteSpace($InputBucketName) -or [string]::IsNullOrWhiteSpace($GeminiApiKey)) {
  Write-Error "Missing required parameters. Ensure INPUT_BUCKET_NAME and GEMINI_API_KEY are set in .env"
  exit 1
}

# Default artifacts bucket if not provided
if ([string]::IsNullOrEmpty($S3BucketForSam)) {
  $S3BucketForSam = "rene-gemini-sam-artifacts-dev"
  Write-Host "S3BucketForSam not provided. Using default: $S3BucketForSam"
} else {
  Write-Host "Using S3 artifacts bucket: $S3BucketForSam"
}

# Validate AWS CLI available
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
  Write-Error "AWS CLI not found in PATH. Install and configure AWS CLI before running this script."
  exit 1
}

# Validate SAM available
if (-not (Get-Command sam -ErrorAction SilentlyContinue)) {
  Write-Error "SAM CLI not found in PATH. Install AWS SAM CLI before running this script."
  exit 1
}

# Validate that the deployment InputBucketName does NOT already exist (CloudFormation will create it)
Write-Host "Validating that stack-managed input bucket does not already exist: $InputBucketName"
$inputBucketExists = $false
try {
  aws s3api head-bucket --bucket $InputBucketName --profile $Profile --region $Region 2>$null
  if ($LASTEXITCODE -eq 0) { $inputBucketExists = $true }
} catch {
  $inputBucketExists = $false
}
if ($inputBucketExists) {
  Write-Error "Input bucket '$InputBucketName' already exists. Choose a unique name for stack-managed bucket (update INPUT_BUCKET_NAME in .env)."
  exit 1
}

# 1. Prepare layer directory structure
Write-Host "Preparing layer directory..."
try {
  Remove-Item -Recurse -Force .\layer -ErrorAction SilentlyContinue
} catch { }
New-Item -ItemType Directory -Path .\layer\python\lib\python3.14\site-packages -Force | Out-Null

# 2. Install dependencies into layer site-packages
if (Test-Path .\backend\requirements.txt) {
  Write-Host "Installing Python dependencies into layer from backend/requirements.txt..."
  python -m pip install --upgrade -r .\backend\requirements.txt -t .\layer\python\lib\python3.14\site-packages
  if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed. Fix errors and re-run."
    exit 1
  }
} else {
  Write-Warning "backend/requirements.txt not found. Proceeding without adding dependencies to the layer."
}

# 3. Create layer.zip (optional)
Write-Host "Creating layer.zip..."
if (Test-Path .\layer.zip) { Remove-Item .\layer.zip -Force }
Compress-Archive -Path .\layer\* -DestinationPath .\layer.zip -Force
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Compress-Archive returned non-zero exit code. Verify layer contents."
}

# 4. Ensure SAM artifacts S3 bucket exists and is configured
Write-Host "Ensuring SAM artifacts bucket exists: $S3BucketForSam"
$bucketExists = $false
try {
  aws s3api head-bucket --bucket $S3BucketForSam --profile $Profile --region $Region 2>$null
  if ($LASTEXITCODE -eq 0) { $bucketExists = $true }
} catch {
  $bucketExists = $false
}

if ($bucketExists) {
  Write-Host "Bucket $S3BucketForSam already exists."
} else {
  Write-Host "Bucket $S3BucketForSam not found. Creating bucket..."
  if ($Region -eq "us-east-1") {
    aws s3api create-bucket --bucket $S3BucketForSam --profile $Profile --region $Region
  } else {
    aws s3api create-bucket --bucket $S3BucketForSam --profile $Profile --region $Region --create-bucket-configuration LocationConstraint=$Region
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create bucket $S3BucketForSam. Check permissions and try again."
    exit 1
  }

  Write-Host "Configuring bucket encryption (SSE-S3)..."
  aws s3api put-bucket-encryption --bucket $S3BucketForSam --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' --profile $Profile --region $Region
  Write-Host "Blocking public access..."
  aws s3api put-public-access-block --bucket $S3BucketForSam --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true --profile $Profile --region $Region
  Write-Host "Enabling versioning..."
  aws s3api put-bucket-versioning --bucket $S3BucketForSam --versioning-configuration Status=Enabled --profile $Profile --region $Region
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
  aws s3api put-bucket-lifecycle-configuration --bucket $S3BucketForSam --lifecycle-configuration file://$tmpLifecycle --profile $Profile --region $Region
  Remove-Item $tmpLifecycle -ErrorAction SilentlyContinue
  Write-Host "Bucket $S3BucketForSam created and configured."
}

# 5. Build with SAM
Write-Host "Running sam build..."
sam build
if ($LASTEXITCODE -ne 0) {
  Write-Error "sam build failed. Fix build errors and re-run."
  exit 1
}

# 6. Deploy with SAM (with parameter overrides from .env)
Write-Host "Running sam deploy..."
sam deploy `
  --stack-name $StackName `
  --profile $Profile `
  --region $Region `
  --s3-bucket $S3BucketForSam `
  --capabilities CAPABILITY_IAM `
  --parameter-overrides InputBucketName=$InputBucketName GeminiApiKey=$GeminiApiKey
if ($LASTEXITCODE -ne 0) {
  Write-Error "sam deploy failed. Check output and fix issues."
  exit 1
}

Write-Host "Deployment finished. Layer and functions should be updated in stack: $StackName"
