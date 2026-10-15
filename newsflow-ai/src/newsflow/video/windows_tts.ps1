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
