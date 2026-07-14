Set-Location d:\ClothesNetData\chat-platform
Write-Host "[Watcher] Started. Watching signals/ ..."
while ($true) {
    $found = $false
    $files = Get-ChildItem "signals\*.json" -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        if ($f.Name.StartsWith(".")) { continue }
        $found = $true
        $agent = [io.path]::GetFileNameWithoutExtension($f.Name)
        Write-Host "[Watcher] $(Get-Date -Format 'HH:mm:ss') $agent - $($f.Name)"
        # Let console settle so pyautogui targets VS Code, not this terminal
        Start-Sleep 1
        python scripts\wake_vscode.py $agent 2>&1
        # Delete signal so we don't re-trigger
        Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
        Start-Sleep 3
    }
    Start-Sleep 2
}
