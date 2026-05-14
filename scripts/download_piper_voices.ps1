param(
    [string]$OutputDir = "data\piper"
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$voices = @(
    @{
        Name = "uk_UA-ukrainian_tts-medium"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/uk/uk_UA/ukrainian_tts/medium"
    },
    @{
        Name = "en_US-amy-medium"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium"
    },
    @{
        Name = "en_US-ryan-medium"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ryan/medium"
    },
    @{
        Name = "de_DE-thorsten-medium"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/de/de_DE/thorsten/medium"
    },
    @{
        Name = "de_DE-eva_k-x_low"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/de/de_DE/eva_k/x_low"
    },
    @{
        Name = "pl_PL-gosia-medium"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pl/pl_PL/gosia/medium"
    },
    @{
        Name = "pl_PL-darkman-medium"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pl/pl_PL/darkman/medium"
    },
    @{
        Name = "sk_SK-lili-medium"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/sk/sk_SK/lili/medium"
    },
    @{
        Name = "cs_CZ-jirka-medium"
        BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/cs/cs_CZ/jirka/medium"
    }
)

foreach ($voice in $voices) {
    $modelPath = Join-Path $OutputDir "$($voice.Name).onnx"
    $configPath = Join-Path $OutputDir "$($voice.Name).onnx.json"

    if (-not (Test-Path $modelPath)) {
        Invoke-WebRequest `
            -Uri "$($voice.BaseUrl)/$($voice.Name).onnx?download=true" `
            -OutFile $modelPath
    }

    if (-not (Test-Path $configPath)) {
        Invoke-WebRequest `
            -Uri "$($voice.BaseUrl)/$($voice.Name).onnx.json?download=true" `
            -OutFile $configPath
    }
}

Get-ChildItem -Path $OutputDir -Filter "*.onnx*"
