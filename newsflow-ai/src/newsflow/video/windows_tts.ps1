param([string]$Spec, [switch]$ListVoices, [switch]$VoiceDetails, [switch]$RegistryVoices)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
if ($RegistryVoices) {
    # Read-only listing of SAPI5 and OneCore voice tokens. No synthesizer, no admin rights,
    # no registry writes: Get-ItemProperty only. Used to explain why a voice is not listed.
    try {
        $hives = @(
            @{hive='sapi'; path='HKLM:\SOFTWARE\Microsoft\Speech\Voices\Tokens'},
            @{hive='sapi_wow'; path='HKLM:\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens'},
            @{hive='sapi_user'; path='HKCU:\SOFTWARE\Microsoft\Speech\Voices\Tokens'},
            @{hive='onecore'; path='HKLM:\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens'}
        )
        $items = [System.Collections.ArrayList]::new()
        foreach ($entry in $hives) {
            if ($items.Count -ge 200) { break }
            if (-not (Test-Path -LiteralPath $entry.path)) { continue }
            $tokens = @(Get-ChildItem -LiteralPath $entry.path -ErrorAction SilentlyContinue)
            foreach ($token in $tokens) {
                if ($items.Count -ge 200) { break }
                $name = ''
                $language = ''
                $gender = ''
                $values = Get-ItemProperty -LiteralPath $token.PSPath -ErrorAction SilentlyContinue
                if ($null -ne $values -and $null -ne $values.'(default)') { $name = [string]$values.'(default)' }
                $attributesPath = $token.PSPath + '\Attributes'
                if (Test-Path -LiteralPath $attributesPath) {
                    $attributes = Get-ItemProperty -LiteralPath $attributesPath -ErrorAction SilentlyContinue
                    if ($null -ne $attributes) {
                        if ($null -ne $attributes.Language) { $language = [string]$attributes.Language }
                        if ($null -ne $attributes.Gender) { $gender = [string]$attributes.Gender }
                    }
                }
                [void]$items.Add(@{hive=$entry.hive; token=[string]$token.PSChildName; name=$name; language=$language; gender=$gender})
            }
        }
        ConvertTo-Json -InputObject @($items.ToArray()) -Compress
        exit 0
    } catch { [Console]::Error.WriteLine('Windows TTS registry read failed.'); exit 1 }
}
try {
    Add-Type -AssemblyName System.Speech
    $speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    try {
        if ($VoiceDetails) {
            $details = @($speaker.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { @{name=$_.VoiceInfo.Name; culture=$_.VoiceInfo.Culture.Name} })
            ConvertTo-Json -InputObject $details -Compress
        } elseif ($ListVoices) {
            $names = @($speaker.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
            ConvertTo-Json -InputObject $names -Compress
        } else {
            $inputSpec = Get-Content -LiteralPath $Spec -Raw -Encoding UTF8 | ConvertFrom-Json
            $speaker.SelectVoice([string]$inputSpec.voice)
            $rate = 0
            if ($null -ne $inputSpec.rate) { $rate = [int]$inputSpec.rate }
            if ($rate -lt -10) { $rate = -10 }
            if ($rate -gt 10) { $rate = 10 }
            $speaker.Rate = $rate
            $pause = 0
            if ($null -ne $inputSpec.pause_ms) { $pause = [int]$inputSpec.pause_ms }
            if ($pause -lt 0) { $pause = 0 }
            if ($pause -gt 2000) { $pause = 2000 }
            $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
            $speaker.SetOutputToWaveFile([string]$inputSpec.target, $format)
            $sentences = @($inputSpec.sentences)
            if ($sentences.Count -eq 0) { $sentences = @([string]$inputSpec.text) }
            # Sentences are appended as plain text data; SSML or markup inside them is not interpreted.
            $prompt = [System.Speech.Synthesis.PromptBuilder]::new()
            for ($i = 0; $i -lt $sentences.Count; $i++) {
                $prompt.AppendText([string]$sentences[$i])
                if ($pause -gt 0 -and $i -lt ($sentences.Count - 1)) {
                    $prompt.AppendBreak([TimeSpan]::FromMilliseconds($pause))
                }
            }
            $speaker.Speak($prompt)
            $speaker.SetOutputToNull()
        }
    } finally { $speaker.Dispose() }
} catch { [Console]::Error.WriteLine('Windows TTS failed.'); exit 1 }
