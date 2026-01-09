param(
  [string]$Input = "data/generated_topology.json",
  [string]$Output = "output/network_topology.md",
  [switch]$AiSummary
)

Write-Host "[IotMd] 生成网络拓扑文档..."

$argsList = @(
  "src/generate_topology_doc.py",
  "--input", $Input,
  "--output", $Output
)

if ($AiSummary) {
  $argsList += "--ai-summary"
}

python @argsList
