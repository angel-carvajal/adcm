# Voice install

The recorder speaks with one voice, `edge:es-MX-DaliaNeural` (Microsoft Edge read-aloud,
free, needs the network). Two offline fallbacks exist and are chosen by the owner, never
applied silently: `piper` with the `es_MX-claude-high` model, and the macOS `say` voice
`Paulina`, which needs no install and sounds the most synthetic.

## Layout

The recorder looks for the engines and the model in one voice home:

```
~/.local/share/adcm-voz/
  venv/bin/edge-tts
  venv/bin/piper
  voces/es_MX-claude-high.onnx
  voces/es_MX-claude-high.onnx.json
```

`REC_TTS_HOME` points at another voice home with the same layout (engines in `venv/bin` or
`bin`, the model in `voces/`). With it unset the default above is used. Engines are also found
on `PATH`.

## 1. The venv

```bash
python3 -m venv ~/.local/share/adcm-voz/venv && ~/.local/share/adcm-voz/venv/bin/pip install -U edge-tts "piper-tts==1.8.0"
```

`edge-tts` is not pinned on purpose. Microsoft changes the read-aloud handshake from time to
time and an older release then starts failing with an HTTP 403. `piper-tts` stays pinned
to the version the recorder was tested with.

When a take fails with `could not synthesize` and a 403, re-run the same command (it upgrades):

```bash
~/.local/share/adcm-voz/venv/bin/pip install -U edge-tts
```

## 2. The piper model (offline fallback)

The model comes from the `rhasspy/piper-voices` repository on Hugging Face, folder
`es/es_MX/claude/high`. Read the model card for the voice's license before publishing videos.

```bash
mkdir -p ~/.local/share/adcm-voz/voces && cd ~/.local/share/adcm-voz/voces
base=https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_MX/claude/high
curl -fL -o es_MX-claude-high.onnx "$base/es_MX-claude-high.onnx"
curl -fL -o es_MX-claude-high.onnx.json "$base/es_MX-claude-high.onnx.json"
```

Check the download against the hash the repository publishes. Open the `.onnx` file page
on Hugging Face, copy the SHA256 shown for the file, record it in your own notes, and verify:

```bash
echo "<SHA256_FROM_THE_DOWNLOAD_PAGE>  es_MX-claude-high.onnx" | shasum -a 256 -c -
```

(`sha256sum -c -` on Linux.) Do not trust a hash from anywhere else, and do not continue on a
mismatch: download again.

## 3. Test

```bash
explainer-record --doctor
```

Expected: `ok voice engine (edge:es-MX-DaliaNeural)` and `ok voice home (...)`, ending in
`DOCTOR: ready`. For the fallbacks:

```bash
REC_TTS=piper explainer-record --doctor
REC_TTS=say explainer-record --doctor
```

The doctor synthesizes one word with the selected engine (20 s at most) after checking that
the engine runs, the voice id looks valid and, for edge, the Microsoft endpoint resolves. An
engine that is installed but cannot synthesize reads:

```
missing voice engine — edge is installed but synthesis failed (<reason>): pip install -U edge-tts in the voice venv, or set REC_TTS=piper|say
```

A `403` in the reason means the upgrade above is due. To reproduce it by hand, speak one
sentence with the venv's engine:

```bash
~/.local/share/adcm-voz/venv/bin/edge-tts -v es-MX-DaliaNeural -t "Hola, esto es una prueba." --write-media "${TMPDIR:-.}/probe.mp3"
```

A written, non-empty `probe.mp3` means edge works. An offline machine falls back to
`REC_TTS=piper` or `REC_TTS=say`, chosen by the owner.

## Changing the voice

A different voice for good is the owner's decision after listening to samples at the same
loudness (the recorder normalizes every clip to -17 LUFS). `REC_VOICE` (one run) and
`voice.id` (the config) select another voice of the same engine.
