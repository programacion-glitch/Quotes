$src = 'C:\Users\Usuario\.claude\projects\c--Users-Usuario-Documents-Bots-H2O-Quotes\73a08dea-7656-48a8-bb61-5a606a0cf4be\tool-results\mcp-playwright-browser_evaluate-1779987138273.txt'
$raw = Get-Content -Path $src -Raw -Encoding UTF8

# Extract the JSON between '### Result' header and the next section.
$marker = '### Result'
$startIdx = $raw.IndexOf($marker) + $marker.Length
$rest = $raw.Substring($startIdx)
$endMarker = '### Ran'
$endIdx = $rest.IndexOf($endMarker)
$jsonStr = $rest.Substring(0, $endIdx).Trim()

# It is a JSON-encoded string of a JSON object - parse twice.
$inner = $jsonStr | ConvertFrom-Json
$data = $inner | ConvertFrom-Json

Write-Output ("contentType: " + $data.contentType)
Write-Output ("size: " + $data.size)

$pdfBytes = [System.Convert]::FromBase64String($data.base64)
$out = 'data\output\geico_quote_HUMBERTO_VILLARREAL.pdf'
New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
[System.IO.File]::WriteAllBytes($out, $pdfBytes)
Write-Output ("Wrote " + $pdfBytes.Length + " bytes to " + $out)
