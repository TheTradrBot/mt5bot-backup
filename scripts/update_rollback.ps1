<#
.SYNOPSIS
    Update or rollback Tradr Bot

.DESCRIPTION
    This script updates the bot from git or rolls back to a previous version.

.EXAMPLE
    .\update_rollback.ps1 -Action update
    .\update_rollback.ps1 -Action rollback
    .\update_rollback.ps1 -Action restart

#>

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("update", "rollback", "restart", "status")]
    [string]$Action,
    
    [string]$InstallPath = "C:\tradr",
    [int]$RollbackCommits = 1
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

function Stop-BotTasks {
    Write-Step "Stopping bot tasks..."
    
    $liveTask = Get-ScheduledTask -TaskName "TradrLive" -ErrorAction SilentlyContinue
    if ($liveTask -and $liveTask.State -eq "Running") {
        Stop-ScheduledTask -TaskName "TradrLive"
        Write-Success "TradrLive stopped"
    }
    
    $discordTask = Get-ScheduledTask -TaskName "TradrDiscord" -ErrorAction SilentlyContinue
    if ($discordTask -and $discordTask.State -eq "Running") {
        Stop-ScheduledTask -TaskName "TradrDiscord"
        Write-Success "TradrDiscord stopped"
    }
    
    Start-Sleep -Seconds 2
}

function Start-BotTasks {
    Write-Step "Starting bot tasks..."
    
    $liveTask = Get-ScheduledTask -TaskName "TradrLive" -ErrorAction SilentlyContinue
    if ($liveTask) {
        Start-ScheduledTask -TaskName "TradrLive"
        Write-Success "TradrLive started"
    }
    
    $discordTask = Get-ScheduledTask -TaskName "TradrDiscord" -ErrorAction SilentlyContinue
    if ($discordTask) {
        Start-ScheduledTask -TaskName "TradrDiscord"
        Write-Success "TradrDiscord started"
    }
}

function Get-BotStatus {
    Write-Header "BOT STATUS"
    
    $liveTask = Get-ScheduledTask -TaskName "TradrLive" -ErrorAction SilentlyContinue
    if ($liveTask) {
        $liveInfo = Get-ScheduledTaskInfo -TaskName "TradrLive"
        Write-Host "TradrLive:" -ForegroundColor Cyan
        Write-Host "  State: $($liveTask.State)"
        Write-Host "  Last Run: $($liveInfo.LastRunTime)"
        Write-Host "  Last Result: $($liveInfo.LastTaskResult)"
    }
    else {
        Write-Host "TradrLive: Not configured" -ForegroundColor Red
    }
    
    Write-Host ""
    
    $discordTask = Get-ScheduledTask -TaskName "TradrDiscord" -ErrorAction SilentlyContinue
    if ($discordTask) {
        $discordInfo = Get-ScheduledTaskInfo -TaskName "TradrDiscord"
        Write-Host "TradrDiscord:" -ForegroundColor Cyan
        Write-Host "  State: $($discordTask.State)"
        Write-Host "  Last Run: $($discordInfo.LastRunTime)"
        Write-Host "  Last Result: $($discordInfo.LastTaskResult)"
    }
    else {
        Write-Host "TradrDiscord: Not configured" -ForegroundColor Yellow
    }
    
    Write-Host ""
    
    Set-Location $InstallPath
    if (Test-Path ".git") {
        Write-Host "Git Status:" -ForegroundColor Cyan
        $branch = & git rev-parse --abbrev-ref HEAD
        $commit = & git rev-parse --short HEAD
        $commitDate = & git log -1 --format=%ci
        Write-Host "  Branch: $branch"
        Write-Host "  Commit: $commit"
        Write-Host "  Date: $commitDate"
    }
}

function Update-Bot {
    Write-Header "UPDATING BOT"
    
    Set-Location $InstallPath
    
    if (-not (Test-Path ".git")) {
        Write-Error "Not a git repository. Cannot update."
        return $false
    }
    
    Stop-BotTasks
    
    Write-Step "Saving current commit for rollback..."
    $currentCommit = & git rev-parse HEAD
    Set-Content -Path ".rollback_commit" -Value $currentCommit
    
    Write-Step "Pulling latest changes..."
    try {
        & git pull origin main
        Write-Success "Code updated"
    }
    catch {
        Write-Error "Git pull failed: $_"
        Write-Step "Rolling back..."
        & git reset --hard $currentCommit
        Start-BotTasks
        return $false
    }
    
    Write-Step "Updating dependencies..."
    & "$InstallPath\venv\Scripts\Activate.ps1"
    if (Test-Path "requirements.txt") {
        & pip install -r requirements.txt --quiet
    }
    
    Start-BotTasks
    
    Write-Success "Update complete!"
    Write-Host ""
    Write-Host "New commit: $(& git rev-parse --short HEAD)"
    Write-Host "To rollback: .\update_rollback.ps1 -Action rollback"
    
    return $true
}

function Rollback-Bot {
    Write-Header "ROLLING BACK BOT"
    
    Set-Location $InstallPath
    
    if (-not (Test-Path ".git")) {
        Write-Error "Not a git repository. Cannot rollback."
        return $false
    }
    
    $rollbackFile = ".rollback_commit"
    
    if (Test-Path $rollbackFile) {
        $rollbackCommit = Get-Content $rollbackFile
        Write-Step "Rolling back to saved commit: $rollbackCommit"
    }
    else {
        $rollbackCommit = "HEAD~$RollbackCommits"
        Write-Step "Rolling back $RollbackCommits commit(s)"
    }
    
    Stop-BotTasks
    
    Write-Step "Resetting to previous version..."
    try {
        & git reset --hard $rollbackCommit
        Write-Success "Rolled back to: $(& git rev-parse --short HEAD)"
    }
    catch {
        Write-Error "Rollback failed: $_"
        Start-BotTasks
        return $false
    }
    
    Write-Step "Reinstalling dependencies..."
    & "$InstallPath\venv\Scripts\Activate.ps1"
    if (Test-Path "requirements.txt") {
        & pip install -r requirements.txt --quiet
    }
    
    if (Test-Path $rollbackFile) {
        Remove-Item $rollbackFile
    }
    
    Start-BotTasks
    
    Write-Success "Rollback complete!"
    
    return $true
}

function Restart-Bot {
    Write-Header "RESTARTING BOT"
    
    Stop-BotTasks
    Start-Sleep -Seconds 2
    Start-BotTasks
    
    Write-Success "Bot restarted"
    Write-Host ""
    
    Get-BotStatus
}

switch ($Action) {
    "update" {
        Update-Bot
    }
    "rollback" {
        Rollback-Bot
    }
    "restart" {
        Restart-Bot
    }
    "status" {
        Get-BotStatus
    }
}
