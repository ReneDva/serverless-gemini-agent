# build-layer.ps1
# סקריפט לבניית שכבת Lambda נכונה עבור Amazon Linux

# 1. נקה תיקיות ישנות
Write-Host "Cleaning old build..."
Remove-Item -Recurse -Force .\layer\python -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path .\layer\python\lib\python3.12\site-packages

# 2. ודא ש-Docker Desktop רץ
Write-Host "Checking Docker Desktop..."
$dockerStatus = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $dockerStatus) {
    Write-Host "Starting Docker Desktop..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Write-Host "Waiting for Docker to start..."
    $maxWait = 60
    $waited = 0
    while ($waited -lt $maxWait) {
        try {
            docker info | Out-Null
            Write-Host "Docker is running."
            break
        } catch {
            Start-Sleep -Seconds 5
            $waited += 5
        }
    }
    if ($waited -ge $maxWait) {
        Write-Error "Docker did not start within $maxWait seconds."
        exit 1
    }
} else {
    Write-Host "Docker Desktop is already running."
}

# 3. התקנת תלויות בתוך container של Amazon Linux
Write-Host "Installing dependencies inside Amazon Linux container..."
docker run --rm -v ${PWD}:/var/task public.ecr.aws/sam/build-python3.12 sh -c "pip install -r requirements.txt -t /var/task/layer/python/lib/python3.12/site-packages"


# 3a. דיבאג – הצגת מה הותקן בפועל
Write-Host "Debug: listing installed packages in site-packages..."
Get-ChildItem .\layer\python\lib\python3.12\site-packages | ForEach-Object {
    Write-Host " - $($_.Name)"
}

if ((Get-ChildItem .\layer\python\lib\python3.12\site-packages).Count -eq 0) {
    Write-Error "No packages were installed! The layer will be empty."
    exit 1
}

# 4. אריזת השכבה ל-zip
Write-Host "Compressing layer..."
Compress-Archive -Path .\layer\* -DestinationPath .\layer.zip -Force

Write-Host "Layer build complete: layer.zip"

# 5. סגירת Docker Desktop
Write-Host "Stopping Docker Desktop..."
Stop-Process -Name "Docker Desktop" -Force -ErrorAction SilentlyContinue
Write-Host "Waiting for Docker to stop..."
$maxWaitStop = 30
$waitedStop = 0
while ($waitedStop -lt $maxWaitStop) {
    $dockerStatus = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    if (-not $dockerStatus) {
        Write-Host "Docker Desktop stopped."
        break
    }
    Start-Sleep -Seconds 5
    $waitedStop += 5
}
