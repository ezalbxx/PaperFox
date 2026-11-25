$ErrorActionPreference = 'Stop'
$powerpoint = $null
$window = $null
$alreadyRunning = [bool](Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)

function Read-ShapeText($shape) {
    if ($shape.Type -eq 6) {
        foreach ($member in $shape.GroupItems) { Read-ShapeText $member }
    } elseif ($shape.HasTable -eq -1) {
        $table = $shape.Table
        for ($row = 1; $row -le $table.Rows.Count; $row++) {
            $cells = for ($column = 1; $column -le $table.Columns.Count; $column++) {
                $table.Cell($row, $column).Shape.TextFrame.TextRange.Text
            }
            $cells -join "`t"
        }
    } elseif ($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1) {
        $shape.TextFrame.TextRange.Text.Replace("`r", "`n").Replace([char]11, [char]10)
    }
}

try {
    $powerpoint = New-Object -ComObject PowerPoint.Application
    $window = $powerpoint.ProtectedViewWindows.Open($env:PAPERFOX_PPT_INPUT)
    $slides = @(foreach ($slide in $window.Presentation.Slides) {
        $parts = @(foreach ($shape in $slide.Shapes) { Read-ShapeText $shape })
        $parts -join "`n"
    })
    [IO.File]::WriteAllText($env:PAPERFOX_PPT_OUTPUT, (ConvertTo-Json -InputObject $slides -Compress))
} finally {
    if ($window) { $window.Close() }
    if ($powerpoint -and -not $alreadyRunning -and $powerpoint.Presentations.Count -eq 0) { $powerpoint.Quit() }
}
