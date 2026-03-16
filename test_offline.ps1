<#
.SYNOPSIS
    Offline test script for the Louisiana Weather Geofence API.

.DESCRIPTION
    Runs the full offline test flow without requiring a real database,
    NWS/WPC API access, or an ML pipeline.

    What this script does:
      1. Installs Python dependencies from requirements.txt
      2. Starts the FastAPI server (python -m uvicorn) in the background
      3. Waits for the server to be ready
      4. Loads the built-in sample hazard zones  (POST /geofences/load-demo)
      5. Registers a test device                 (POST /users/register)
      6. Moves the device into a hazard zone     (PUT  /users/1/location)
      7. Triggers the notification scan          (POST /notifications/send-hazard-alerts)
      8. Verifies zone count and lists all zones (GET  /geofences/count, GET /geofences)
      9. Prints a summary and stops the server

.NOTES
    Run from the repository root directory:
        .\test_offline.ps1
#>

$BASE_URL = "http://localhost:8000"
$SERVER_PROCESS = $null

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "    OK  $Message" -ForegroundColor Green
}

function Write-Failure {
    param([string]$Message)
    Write-Host "    FAIL $Message" -ForegroundColor Red
}

function Invoke-API {
    <#
    .SYNOPSIS
        Thin wrapper around Invoke-RestMethod that pretty-prints the response.
    #>
    param(
        [string]$Method = "GET",
        [string]$Path,
        [string]$Body = $null
    )

    $uri = "$BASE_URL$Path"
    $params = @{
        Method      = $Method
        Uri         = $uri
        ErrorAction = "Stop"
    }
    if ($Body) {
        $params["ContentType"] = "application/json"
        $params["Body"]        = $Body
    }

    try {
        $response = Invoke-RestMethod @params
        return $response
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        Write-Failure "$Method $Path  ->  HTTP $statusCode : $_"
        return $null
    }
}

function Wait-ForServer {
    param([int]$TimeoutSeconds = 20)
    Write-Step "Waiting for server to be ready..."
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $null = Invoke-RestMethod -Uri "$BASE_URL/health" -ErrorAction Stop
            Write-Success "Server is up."
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    Write-Failure "Server did not respond within $TimeoutSeconds seconds."
    return $false
}

# ---------------------------------------------------------------------------
# Step 1: Create virtual environment (if needed) and install dependencies
# ---------------------------------------------------------------------------

Write-Step "Setting up virtual environment (.venv)..."
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Failed to create virtual environment. Make sure Python 3 is on your PATH."
        exit 1
    }
}
Write-Success "Virtual environment ready."

Write-Step "Installing Python dependencies into .venv..."
& ".venv\Scripts\pip" install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Failure "pip install failed inside the virtual environment."
    exit 1
}
Write-Success "Dependencies installed."

# ---------------------------------------------------------------------------
# Step 2: Start the FastAPI server in the background
# ---------------------------------------------------------------------------

Write-Step "Starting FastAPI server (.venv/Scripts/python -m uvicorn main:app)..."
$SERVER_PROCESS = Start-Process `
    -FilePath ".venv\Scripts\python" `
    -ArgumentList "-m", "uvicorn", "main:app", "--port", "8000" `
    -PassThru `
    -NoNewWindow

if (-not $SERVER_PROCESS) {
    Write-Failure "Failed to start the server process."
    exit 1
}
Write-Success "Server process started (PID $($SERVER_PROCESS.Id))."

# ---------------------------------------------------------------------------
# Step 3: Wait for the server to be ready
# ---------------------------------------------------------------------------

if (-not (Wait-ForServer)) {
    Stop-Process -Id $SERVER_PROCESS.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

# ---------------------------------------------------------------------------
# Step 4: Load demo hazard zones
# ---------------------------------------------------------------------------

Write-Step "Loading demo hazard zones (POST /geofences/load-demo)..."
$demoResult = Invoke-API -Method Post -Path "/geofences/load-demo"
if ($demoResult) {
    Write-Success "Loaded $($demoResult.loaded) zone(s). Cache total: $($demoResult.total_cached)."
    Write-Host "    $($demoResult.message)" -ForegroundColor Gray
} else {
    Write-Failure "Could not load demo zones."
}

# ---------------------------------------------------------------------------
# Step 5: Register a test device
# ---------------------------------------------------------------------------

Write-Step "Registering test device (POST /users/register)..."
$regBody = '{"device_token":"test-fcm-token","lat":30.45,"lon":-91.10}'
$regResult = Invoke-API -Method Post -Path "/users/register" -Body $regBody
if ($regResult) {
    Write-Success "Registered device. user_id=$($regResult.user_id), message='$($regResult.message)'"
    $userId = $regResult.user_id
} else {
    Write-Failure "Device registration failed."
    $userId = 1
}

# ---------------------------------------------------------------------------
# Step 6: Move device into a hazard zone
# ---------------------------------------------------------------------------

Write-Step "Updating device location to inside a hazard zone (PUT /users/$userId/location)..."
$locBody = '{"lat":30.45,"lon":-91.10}'
$locResult = Invoke-API -Method Put -Path "/users/$userId/location" -Body $locBody
if ($locResult) {
    if ($locResult.inside_hazard) {
        Write-Success "inside_hazard=true  event='$($locResult.event)'  severity='$($locResult.severity)'"
    } else {
        Write-Failure "Expected inside_hazard=true but got false. Check that demo zones were loaded."
    }
} else {
    Write-Failure "Location update failed."
}

# ---------------------------------------------------------------------------
# Step 7: Move device outside all hazard zones
# ---------------------------------------------------------------------------

Write-Step "Updating device location to outside all hazard zones (PUT /users/$userId/location)..."
$outsideBody = '{"lat":10.0,"lon":10.0}'
$outsideResult = Invoke-API -Method Put -Path "/users/$userId/location" -Body $outsideBody
if ($outsideResult) {
    if (-not $outsideResult.inside_hazard) {
        Write-Success "inside_hazard=false (correctly outside all zones)"
    } else {
        Write-Failure "Expected inside_hazard=false but got true."
    }
}

# ---------------------------------------------------------------------------
# Step 8: Trigger hazard alert notification scan
# ---------------------------------------------------------------------------

Write-Step "Triggering hazard notification scan (POST /notifications/send-hazard-alerts)..."
# First move the device back inside a zone so there is something to notify about
$null = Invoke-API -Method Put -Path "/users/$userId/location" -Body $locBody
$notifResult = Invoke-API -Method Post -Path "/notifications/send-hazard-alerts"
if ($notifResult) {
    Write-Success "notified_users=$($notifResult.notified_users)  firebase_configured=$($notifResult.firebase_configured)  success=$($notifResult.success_count)  failure=$($notifResult.failure_count)"
    if (-not $notifResult.firebase_configured) {
        Write-Host "    (Firebase credentials not set - notifications fail gracefully, which is expected)" -ForegroundColor Gray
    }
}

# ---------------------------------------------------------------------------
# Step 9: Verify zone count and list zones
# ---------------------------------------------------------------------------

Write-Step "Checking geofence count (GET /geofences/count)..."
$countResult = Invoke-API -Path "/geofences/count"
if ($countResult) {
    Write-Success "count=$($countResult.count)"
}

Write-Step "Listing all loaded zones (GET /geofences)..."
$zones = Invoke-API -Path "/geofences"
if ($zones) {
    Write-Success "Found $($zones.Count) zone(s):"
    foreach ($z in $zones) {
        Write-Host "      - $($z.event) [$($z.severity)]" -ForegroundColor Gray
    }
}

# ---------------------------------------------------------------------------
# Step 10: Run the automated test suite
# ---------------------------------------------------------------------------

Write-Step "Running automated test suite (python -m pytest)..."
& ".venv\Scripts\python" -m pytest test_hazard_notifications.py -v
if ($LASTEXITCODE -eq 0) {
    Write-Success "All tests passed."
} else {
    Write-Failure "Some tests failed. See output above."
}

# ---------------------------------------------------------------------------
# Cleanup: stop the server
# ---------------------------------------------------------------------------

Write-Host "`nAll steps complete. Open http://localhost:8000/docs in your browser for interactive API exploration (server is still running)." -ForegroundColor Cyan
Write-Host "Press any key to stop the server and exit..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Write-Step "Stopping server (PID $($SERVER_PROCESS.Id))..."
Stop-Process -Id $SERVER_PROCESS.Id -Force -ErrorAction SilentlyContinue
Write-Success "Server stopped."
