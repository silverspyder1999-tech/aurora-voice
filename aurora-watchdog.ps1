# Aurora Voice watchdog: keep the F9 dictation daemon alive and un-wedged.
# Restarts Aurora if (a) its process is gone, or (b) its heartbeat goes stale
# while the process is alive -> the worker thread died/hung (the wedge that
# silently dropped every dictation). Companion to gpu-watchdog; scoped to Aurora.
$ErrorActionPreference = 'SilentlyContinue'

$dir      = 'C:\Users\silve\Projects\aurora-voice'
$pyw      = Join-Path $dir 'venv\Scripts\pythonw.exe'
$hb       = Join-Path $dir 'aurora.heartbeat'
$wlog     = Join-Path $dir 'aurora-watchdog.log'
$interval = 30    # seconds between checks
$staleSec = 60    # heartbeat older than this (process alive) = worker wedged/hung
$graceSec = 120   # after a (re)launch, don't judge health until the ASR model loads

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Add-Content -Path $wlog }

function Get-Aurora {
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.ExecutablePath -like '*aurora-voice*' }
}

function Start-Aurora {
  Start-Process -FilePath $pyw -ArgumentList '-m','app.main' -WorkingDirectory $dir -WindowStyle Hidden
  Log 'launched Aurora'
}

# Only one watchdog at a time (autostart + a manual run would double-restart).
$created = $false
$mtx = New-Object System.Threading.Mutex($true, 'Global\aurora-watchdog-singleton', [ref]$created)
if (-not $created) { Log 'another watchdog already running - exiting'; return }

Log 'watchdog started'
# Backdate so the first loop immediately checks an already-running instance.
$launchedAt = (Get-Date).AddSeconds(-$graceSec - 1)

while ($true) {
  Start-Sleep -Seconds $interval
  try {
    $proc = Get-Aurora

    if (-not $proc) {
      Log 'Aurora process not running - restarting'
      Start-Aurora
      $launchedAt = Get-Date
      continue
    }

    # Still booting (model load ~10-25s) - don't mistake it for a wedge.
    if (((Get-Date) - $launchedAt).TotalSeconds -lt $graceSec) { continue }

    # Process alive & past grace: is the worker still beating?
    if (Test-Path $hb) {
      $age = ((Get-Date) - (Get-Item $hb).LastWriteTime).TotalSeconds
      if ($age -gt $staleSec) {
        Log ("heartbeat stale ({0:N0}s) - Aurora wedged, restarting" -f $age)
        $proc | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Start-Sleep -Milliseconds 800
        Start-Aurora
        $launchedAt = Get-Date
      }
    }
    # No heartbeat file yet -> process alive but hasn't written one; leave it.
  } catch {
    Log ("watchdog loop error: {0}" -f $_.Exception.Message)
  }
}
