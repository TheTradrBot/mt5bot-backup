<#
.SYNOPSIS
    Tradr Bot Deployment Script for Windows VM

.DESCRIPTION
    This script automates the deployment of the Tradr Bot on a Windows VM.
    It installs all dependencies, clones the repository, configures the
    environment, and sets up Windows Task Scheduler for 24/7 operation.

.NOTES
    Run as Administrator: Right-click PowerShell -> Run as Administrator
    
.EXAMPLE
    .\deploy.ps1

#>

param(
    [string]$InstallPath = "C:\tradr",
    [string]$GitRepo = "",
    [switch]$SkipPython,
    [switch]$SkipGit,
    [switch]$SkipTasks
)

$ErrorActionPreference = "Stop"

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Text)
    Write-Host "[*] $Text" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Text)
    Write-Host "[+] $Text" -ForegroundColor Green
}

function Write-Error {
    param([string]$Text)
    Write-Host "[-] $Text" -ForegroundColor Red
}

function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-Python {
    Write-Header "INSTALLING PYTHON 3.11"
    
    $pythonPath = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonPath) {
        $version = & python --version 2>&1
        Write-Step "Python already installed: $version"
        return
    }
    
    Write-Step "Downloading Python 3.11..."
    $pythonUrl = "https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe"
    $installer = "$env:TEMP\python-installer.exe"
    
    Invoke-WebRequest -Uri $pythonUrl -OutFile $installer
    
    Write-Step "Installing Python 3.11..."
    Start-Process -FilePath $installer -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1" -Wait
    
    Remove-Item $installer -Force
    
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    
    Write-Success "Python 3.11 installed"
}

function Install-Git {
    Write-Header "INSTALLING GIT"
    
    $gitPath = Get-Command git -ErrorAction SilentlyContinue
    if ($gitPath) {
        $version = & git --version
        Write-Step "Git already installed: $version"
        return
    }
    
    Write-Step "Downloading Git..."
    $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.43.0.windows.1/Git-2.43.0-64-bit.exe"
    $installer = "$env:TEMP\git-installer.exe"
    
    Invoke-WebRequest -Uri $gitUrl -OutFile $installer
    
    Write-Step "Installing Git..."
    Start-Process -FilePath $installer -ArgumentList "/VERYSILENT", "/NORESTART" -Wait
    
    Remove-Item $installer -Force
    
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    
    Write-Success "Git installed"
}

function Setup-Repository {
    Write-Header "SETTING UP REPOSITORY"
    
    if (Test-Path $InstallPath) {
        Write-Step "Installation directory exists, updating..."
        Set-Location $InstallPath
        
        if (Test-Path ".git") {
            & git pull
            Write-Success "Repository updated"
        }
    }
    else {
        Write-Step "Creating installation directory..."
        New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
        Set-Location $InstallPath
        
        if ($GitRepo) {
            Write-Step "Cloning repository..."
            & git clone $GitRepo .
            Write-Success "Repository cloned"
        }
        else {
            Write-Step "No git repo specified, creating empty structure..."
            New-Item -ItemType Directory -Path "logs" -Force | Out-Null
            Write-Success "Directory structure created"
        }
    }
}

function Setup-VirtualEnv {
    Write-Header "SETTING UP PYTHON ENVIRONMENT"
    
    Set-Location $InstallPath
    
    if (-not (Test-Path "venv")) {
        Write-Step "Creating virtual environment..."
        & python -m venv venv
        Write-Success "Virtual environment created"
    }
    
    Write-Step "Activating virtual environment..."
    & "$InstallPath\venv\Scripts\Activate.ps1"
    
    Write-Step "Upgrading pip..."
    & python -m pip install --upgrade pip
    
    Write-Step "Installing dependencies..."
    if (Test-Path "requirements.txt") {
        & pip install -r requirements.txt
    }
    else {
        & pip install MetaTrader5 discord.py pandas numpy python-dotenv requests pytz python-dateutil
    }
    
    Write-Success "Dependencies installed"
}

function Setup-Environment {
    Write-Header "CONFIGURING ENVIRONMENT"
    
    $envFile = Join-Path $InstallPath ".env"
    
    if (Test-Path $envFile) {
        Write-Step ".env file already exists"
        $overwrite = Read-Host "Overwrite? (y/N)"
        if ($overwrite -ne "y") {
            return
        }
    }
    
    Write-Step "Please enter your configuration:"
    
    $mt5Server = Read-Host "MT5 Server (e.g., FTMO-Demo)"
    $mt5Login = Read-Host "MT5 Login"
    $mt5Password = Read-Host "MT5 Password" -AsSecureString
    $mt5PasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($mt5Password))
    
    $discordToken = Read-Host "Discord Bot Token (optional, press Enter to skip)"
    
    $envContent = @"
# MT5 Configuration
MT5_SERVER=$mt5Server
MT5_LOGIN=$mt5Login
MT5_PASSWORD=$mt5PasswordPlain

# Discord Configuration (optional)
DISCORD_BOT_TOKEN=$discordToken

# Trading Configuration
SCAN_INTERVAL_HOURS=4
MIN_CONFLUENCE=4
"@
    
    Set-Content -Path $envFile -Value $envContent
    Write-Success "Environment configured"
}

function Create-ScheduledTasks {
    Write-Header "CREATING SCHEDULED TASKS"
    
    $pythonExe = Join-Path $InstallPath "venv\Scripts\python.exe"
    $liveBot = Join-Path $InstallPath "main_live_bot.py"
    $discordBot = Join-Path $InstallPath "discord_minimal.py"
    
    Write-Step "Creating TradrLive task..."
    
    $liveAction = New-ScheduledTaskAction -Execute $pythonExe -Argument $liveBot -WorkingDirectory $InstallPath
    $liveTrigger = New-ScheduledTaskTrigger -AtStartup
    $liveSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 5) -RestartCount 999 -ExecutionTimeLimit (New-TimeSpan -Days 365)
    $livePrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    
    $existingTask = Get-ScheduledTask -TaskName "TradrLive" -ErrorAction SilentlyContinue
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName "TradrLive" -Confirm:$false
    }
    
    Register-ScheduledTask -TaskName "TradrLive" -Action $liveAction -Trigger $liveTrigger -Settings $liveSettings -Principal $livePrincipal -Description "Tradr Bot - MT5 Live Trading (24/7)"
    Write-Success "TradrLive task created"
    
    if (Test-Path $discordBot) {
        Write-Step "Creating TradrDiscord task..."
        
        $discordAction = New-ScheduledTaskAction -Execute $pythonExe -Argument $discordBot -WorkingDirectory $InstallPath
        $discordTrigger = New-ScheduledTaskTrigger -AtStartup
        $discordSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 5) -RestartCount 999 -ExecutionTimeLimit (New-TimeSpan -Days 365)
        $discordPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        
        $existingDiscord = Get-ScheduledTask -TaskName "TradrDiscord" -ErrorAction SilentlyContinue
        if ($existingDiscord) {
            Unregister-ScheduledTask -TaskName "TradrDiscord" -Confirm:$false
        }
        
        Register-ScheduledTask -TaskName "TradrDiscord" -Action $discordAction -Trigger $discordTrigger -Settings $discordSettings -Principal $discordPrincipal -Description "Tradr Bot - Discord Monitoring (24/7)"
        Write-Success "TradrDiscord task created"
    }
}

function Start-Tasks {
    Write-Header "STARTING TASKS"
    
    Write-Step "Starting TradrLive..."
    Start-ScheduledTask -TaskName "TradrLive"
    Write-Success "TradrLive started"
    
    $discordTask = Get-ScheduledTask -TaskName "TradrDiscord" -ErrorAction SilentlyContinue
    if ($discordTask) {
        Write-Step "Starting TradrDiscord..."
        Start-ScheduledTask -TaskName "TradrDiscord"
        Write-Success "TradrDiscord started"
    }
}

function Show-Summary {
    Write-Header "DEPLOYMENT COMPLETE"
    
    Write-Host ""
    Write-Host "Installation Path: $InstallPath" -ForegroundColor Green
    Write-Host ""
    Write-Host "Scheduled Tasks:" -ForegroundColor Cyan
    Write-Host "  - TradrLive: 24/7 MT5 trading bot"
    Write-Host "  - TradrDiscord: Discord monitoring bot"
    Write-Host ""
    Write-Host "Useful Commands:" -ForegroundColor Cyan
    Write-Host "  View logs:          Get-Content $InstallPath\logs\tradr_live.log -Tail 50"
    Write-Host "  Stop live bot:      Stop-ScheduledTask -TaskName TradrLive"
    Write-Host "  Start live bot:     Start-ScheduledTask -TaskName TradrLive"
    Write-Host "  Restart live bot:   Stop-ScheduledTask -TaskName TradrLive; Start-ScheduledTask -TaskName TradrLive"
    Write-Host "  Update bot:         .\scripts\update_rollback.ps1 -Action update"
    Write-Host ""
    Write-Host "The bot will:" -ForegroundColor Yellow
    Write-Host "  - Start automatically on Windows boot"
    Write-Host "  - Restart automatically if it crashes (every 5 minutes)"
    Write-Host "  - Keep running even after you close RDP"
    Write-Host ""
}

Write-Header "TRADR BOT DEPLOYMENT"
Write-Host "This script will set up the Tradr Bot for 24/7 trading."
Write-Host ""

if (-not (Test-Administrator)) {
    Write-Error "This script must be run as Administrator!"
    Write-Host "Right-click PowerShell and select 'Run as Administrator'"
    exit 1
}

if (-not $SkipPython) {
    Install-Python
}

if (-not $SkipGit) {
    Install-Git
}

Setup-Repository
Setup-VirtualEnv
Setup-Environment

if (-not $SkipTasks) {
    Create-ScheduledTasks
    Start-Tasks
}

Show-Summary
