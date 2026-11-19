# ifseen installer for Windows (PowerShell 5.1+ or 7+).
#
#   irm https://krishj.com/ifseen/install.ps1 | iex
#
# Downloads ifseen.exe from the latest GitHub release, checks it against SHA256SUMS, installs
# it to %LOCALAPPDATA%\Programs\ifseen and adds that folder to your user PATH. No admin rights.
# Safe to re-run (upgrades in place).
#
#   $env:IFSEEN_VERSION = '0.1.0'          install a specific version (default: latest)
#   $env:IFSEEN_INSTALL_DIR = 'C:\tools'   install somewhere else

# Everything runs in a script block so `iex` leaves no variables behind, and errors use
# `throw` rather than `exit` so a failure never closes the user's terminal.
& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is very slow with the progress bar in 5.1
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $repo = 'KrishJoshi/ifseen'
    $installDir = if ($env:IFSEEN_INSTALL_DIR) { $env:IFSEEN_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'Programs\ifseen' }

    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'ifseen only has a 64-bit Windows build. Install with Python instead: pipx install "ifseen[all]"'
    }
    # Windows on ARM runs the x64 build under emulation (Windows 11).

    $version = $env:IFSEEN_VERSION
    if (-not $version) {
        try {
            $latest = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'ifseen-installer' }
            $version = $latest.tag_name
        } catch {
            throw "Couldn't find a published ifseen release (none yet, or the GitHub API rate limit was hit). See https://github.com/$repo/releases, set `$env:IFSEEN_VERSION, or install with: pipx install `"ifseen[all]`""
        }
    }
    $version = $version -replace '^v', ''

    $asset = "ifseen-$version-windows-x86_64.zip"
    $base = "https://github.com/$repo/releases/download/v$version"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("ifseen-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null

    try {
        Write-Host "Downloading ifseen $version for Windows x64..."
        $sums = Join-Path $tmp 'SHA256SUMS'
        $zip = Join-Path $tmp $asset
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS" -OutFile $sums
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$asset" -OutFile $zip
        } catch {
            throw "Release v$version (or its $asset) wasn't found. See https://github.com/$repo/releases"
        }

        $pattern = '^\s*([0-9a-fA-F]{64})\s+\*?' + [regex]::Escape($asset) + '\s*$'
        $line = Get-Content -Path $sums | Where-Object { $_ -match $pattern } | Select-Object -First 1
        if (-not $line) { throw "$asset is not listed in SHA256SUMS" }
        $expected = ([regex]::Match($line, $pattern)).Groups[1].Value
        $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash
        if ($actual -ne $expected) {
            throw "Checksum mismatch for $asset (expected $expected, got $actual). Not installing."
        }

        $extract = Join-Path $tmp 'x'
        Expand-Archive -Path $zip -DestinationPath $extract -Force
        $exe = Join-Path $extract 'ifseen.exe'
        if (-not (Test-Path $exe)) { throw "$asset doesn't contain ifseen.exe" }

        New-Item -ItemType Directory -Path $installDir -Force | Out-Null
        $target = Join-Path $installDir 'ifseen.exe'
        try {
            Copy-Item -Path $exe -Destination $target -Force
        } catch {
            throw "Couldn't write $target. Is ifseen still running? Stop it and re-run the installer."
        }
        Unblock-File -Path $target -ErrorAction SilentlyContinue
    } finally {
        Remove-Item -Recurse -Force -Path $tmp -ErrorAction SilentlyContinue
    }

    # Add to the user PATH once (compare entries, not substrings).
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @($userPath -split ';' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') })
    if ($entries -notcontains $installDir.TrimEnd('\')) {
        $newPath = (@($entries) + $installDir) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Write-Host "Added $installDir to your user PATH (open a new terminal to pick it up)."
    }
    if (($env:Path -split ';' | ForEach-Object { $_.TrimEnd('\') }) -notcontains $installDir.TrimEnd('\')) {
        $env:Path = "$env:Path;$installDir"
    }

    $installed = & $target --version
    Write-Host "Installed $installed to $target"
    Write-Host ''
    Write-Host 'Next: $env:GEMINI_API_KEY = "..."   (free at https://aistudio.google.com/apikey)'
    Write-Host '      ifseen doctor'
    Write-Host 'If SmartScreen warns about the unsigned exe, choose More info > Run anyway.'
}
