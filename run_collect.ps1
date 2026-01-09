param(
  [string]$Output = "data/snapshots/ai_device.json",
  [string]$AiEndpoint = "",
  [string]$AiModel = "",
  [switch]$AiInteractive
)

Write-Host "[IotMd] 采集设备快照..."

$argsList = @(
  "src/collect_device_snapshot.py",
  "--output", $Output
)

if ($AiInteractive) {
  $argsList += "--ai-interactive"
}

if ($AiEndpoint) {
  $argsList += @("--ai-endpoint", $AiEndpoint)
}

if ($AiModel) {
  $argsList += @("--ai-model", $AiModel)
}

python @argsList
