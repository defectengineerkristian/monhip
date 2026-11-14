# Monhip

A desktop app for local AI on Windows and Linux, in English or German: chat with GGUF
models, work with files and documents, create images and 3D models, and collaborate in
Teamwork rooms. Everything runs on your own computer.

## Features

- **Chat** with streamed answers, saved conversations and image understanding.
- **Documents and research:** PDFs, Office files and code; web search with sources.
- **Browser:** a browser in a side panel that you share with the AI – it opens and reads
  pages, fills in forms, and asks you to handle logins and captchas yourself.
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

## Notes

- Data (settings, chats, models) is stored next to the app; set `MONHIP_DATA` to use another
  folder. The Linux package uses `~/.local/share/monhip`.
- AMD graphics: if Qwen-Image shows color noise, choose **Compatible (slower)** under
  **Settings → Images → Qwen Image: compute mode**.
- Browser: needs the add-on library pywebview. On Windows, click **Set up browser** in the
  browser panel; on Linux, run `sudo apt install python3-webview gir1.2-webkit2-4.1`
  (the browser then opens in its own window).
- Linux: install `whisper-cli` yourself for speech recognition; controlling other
  applications is only available on Windows.
- Changes: [development notes (German)](progress/FORTSCHRITT.md).
