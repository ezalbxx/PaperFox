$ErrorActionPreference='Stop'
$word=$null
$window=$null
try {
    $word=New-Object -ComObject Word.Application
    $word.AutomationSecurity=3
    $word.Visible=$false
    $word.DisplayAlerts=0
    $window=$word.ProtectedViewWindows.Open($env:PAPERFOX_WORD_INPUT)
    $doc=$window.Document
    $count=$doc.ComputeStatistics(2)
    $start=$doc.Content.Start
    $pages=@(for($i=1;$i -le $count;$i++){
        $end=if($i -eq $count){$doc.Content.End}else{$doc.GoTo(1,1,$i+1).Start}
        $doc.Range($start,$end).Text.Replace([string][char]7," ").Replace("`r","`n").Replace([string][char]11,"`n")
        $start=$end
    })
    [IO.File]::WriteAllText($env:PAPERFOX_WORD_OUTPUT,(ConvertTo-Json -InputObject $pages -Compress))
} finally {
    if($window){$window.Close()}
    if($word){$word.Quit()}
}
