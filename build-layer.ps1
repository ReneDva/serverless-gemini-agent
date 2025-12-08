# build-layer.ps1
# סקריפט לבניית שכבת Lambda נכונה עבור Amazon Linux עם ffmpeg/ffprobe

# 1. נקה תיקיות ישנות
Write-Host "Cleaning old build..."
Remove-Item -Recurse -Force .\layer\python -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\layer\bin -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path .\layer\python\lib\python3.12\site-packages
New-Item -ItemType Directory -Force -Path .\layer\bin

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

    # --- השהיה נוספת ובדיקה רק אם הופעל כאן ---
    Write-Host "Pausing for 30 seconds to ensure Docker is fully up..."
    Start-Sleep -Seconds 30
    try {
        docker info | Out-Null
        Write-Host "Docker confirmed running after pause."
    } catch {
        Write-Error "Docker is not responding after 30s pause."
        exit 1
    }
} else {
    Write-Host "Docker Desktop is already running."
}
# 3. התקנת תלויות Python
Write-Host "Installing Python dependencies inside Amazon Linux container..."
docker run --rm -v ${PWD}:/var/task public.ecr.aws/sam/build-python3.12 `
    sh -c "pip install -r requirements.txt -t /var/task/layer/python/lib/python3.12/site-packages" | Out-Null

if ((Get-ChildItem .\layer\python\lib\python3.12\site-packages).Count -gt 0) {
    Write-Host "==================== PYTHON DEPENDENCIES INSTALLED SUCCESSFULLY ====================" -ForegroundColor Green
} else {
    Write-Host "==================== PYTHON DEPENDENCIES INSTALLATION FAILED ====================" -ForegroundColor Red
    exit 1
}

# 3b. הורדת ffmpeg/ffprobe
Write-Host "Downloading static ffmpeg/ffprobe build..."
docker run --rm -v ${PWD}:/var/task amazonlinux:2023 sh -c @'
  yum install -y tar xz wget &&
  wget -O /tmp/ffmpeg.tar.xz https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz &&
  tar -xJf /tmp/ffmpeg.tar.xz -C /tmp &&
  cp /tmp/ffmpeg-*-amd64-static/ffmpeg /var/task/layer/bin/ &&
  cp /tmp/ffmpeg-*-amd64-static/ffprobe /var/task/layer/bin/
'@ | Out-Null

if ( (Test-Path .\layer\bin\ffmpeg) -and (Test-Path .\layer\bin\ffprobe) ) {
    Write-Host "==================== FFMPEG/FFPROBE INSTALLED SUCCESSFULLY ====================" -ForegroundColor Green
} else {
    Write-Host "==================== FFMPEG/FFPROBE INSTALLATION FAILED ====================" -ForegroundColor Red
    exit 1
}

# 4. אריזת השכבה
Write-Host "Compressing layer..."
Compress-Archive -Path .\layer\* -DestinationPath .\layer.zip -Force
if (Test-Path .\layer.zip) {
    Write-Host "==================== LAYER ZIP CREATED SUCCESSFULLY ====================" -ForegroundColor Green
} else {
    Write-Host "==================== LAYER ZIP CREATION FAILED ====================" -ForegroundColor Red
    exit 1
}

# 5. סגירת Docker Engine ואז Desktop
Write-Host "Stopping all running Docker containers..."
docker stop $(docker ps -q) | Out-Null
Write-Host "==================== DOCKER ENGINE STOPPED ====================" -ForegroundColor Green

Write-Host "Stopping Docker Desktop..."
Stop-Process -Name "Docker Desktop" -Force -ErrorAction SilentlyContinue
Write-Host "==================== DOCKER DESKTOP CLOSED ====================" -ForegroundColor Green
