param([string]$Spec, [switch]$ListVoices, [switch]$VoiceDetails)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
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
            $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
            $speaker.SetOutputToWaveFile([string]$inputSpec.target, $format)
            $speaker.Speak([string]$inputSpec.text)
            $speaker.SetOutputToNull()
        }
    } finally { $speaker.Dispose() }
} catch { [Console]::Error.WriteLine('Windows TTS failed.'); exit 1 }
