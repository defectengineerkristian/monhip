# Monhip

A desktop app for local AI on Windows and Linux, in English or German: chat with GGUF
models, work with files and documents, create images and 3D models, and collaborate in
Teamwork rooms. Everything runs on your own computer.

## Features

- **Chat** with streamed answers, saved conversations and image understanding.
- **Documents and research:** PDFs, Office files and code; web search with sources.
- **Agent tools:** files and folders, Office documents, Python and shell commands,
  Jupyter notebooks – each action can require confirmation.
- **Images and 3D:** create or edit images; turn an image or a description into a 3D
  model (GLB, or STL for 3D printing).
- **Teamwork:** rooms with other people and their AI assistants, shared files and tasks.
- **Speech:** local dictation; notifications when longer tasks finish.

## Install

- **Windows:** `Monhip-Setup.exe`
- **Debian/Ubuntu:** `sudo apt install ./monhip_<version>_all.deb`

Both are available under [Releases](https://github.com/defectengineerkristian/monhip/releases)
and in [`installer/`](installer/).

## Run from source

Requires Python 3.12+ with Tkinter.

```sh
git clone https://github.com/defectengineerkristian/monhip.git
cd monhip
python Monhip.pyw
```

On Linux, install these packages first:

```sh
sudo apt install python3 python3-tk python3-pil xdg-utils pciutils libvulkan1 mesa-vulkan-drivers \
    poppler-utils libnotify-bin xclip wl-clipboard tkdnd pipewire-bin alsa-utils
```

## First steps

1. **Settings → Models:** click **Download / update llama.cpp**, then **Download…** for a
   recommended model – or add your own `.gguf` files.
2. Select the model and click **Load model**.
3. Images and 3D models: missing engines and model files are offered for download the
   first time you use them.

## Models

| Model | Download | License |
| --- | --- | --- |
| Qwen3.8-27B / Qwen3.8-Flash-Next (chat) | 16 GB / 63 GB | see model page |
| Qwen-Image 2.1 Turbo (images, default) | 14 GB | Qwen Research License – non-commercial only |
| FLUX.2 [klein] 4B (images) | 5–9 GB | Apache 2.0 |
| TRELLIS.2 (3D) | 6–16.5 GB | MIT; DINOv3 license (Meta) |

Images and 3D need a graphics card; 16 GB of graphics memory is recommended.

## Notes

- Data (settings, chats, models) is stored next to the app; set `MONHIP_DATA` to use another
  folder. The Linux package uses `~/.local/share/monhip`.
- AMD graphics: if Qwen-Image shows color noise, choose **Compatible (slower)** under
  **Settings → Images → Qwen Image: compute mode**.
- Linux: install `whisper-cli` yourself for speech recognition; controlling other
  applications is only available on Windows.
- Changes: [development notes (German)](progress/FORTSCHRITT.md).
