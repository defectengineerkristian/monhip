# Monhip

Monhip is a desktop application for local AI models. It combines a chat interface with
document analysis, tools for working on your own computer, and a Teamwork mode
where people and their local AI assistants can collaborate.

Language models run on your own computer in GGUF format using
[llama.cpp](https://github.com/ggml-org/llama.cpp). The interface is written in Python with Tkinter
and is primarily in German. Monhip runs on Windows and Linux; see [Linux](#linux) for the differences.

## Features

### Chat with local models

- Load GGUF models from the `modelle/` folder or additional folders you select.
- Download and update a suitable llama.cpp version directly from the application;
  CPU and GPU variants are available depending on your hardware.
- Read responses as they are generated, and save and reopen previous chats locally.
- Configure the system prompt, temperature, response length, context size, and GPU layers.
- Monitor context usage and automatically summarize older parts of the conversation
  when needed to keep longer conversations going.

### Include documents and images

Monhip can read documents attached to a chat so the model can answer questions about them
or summarize their contents. Supported formats include:

- PDF files with extractable text;
- Word, Excel, and PowerPoint files in modern Office formats (`.docx`, `.xlsx`, `.pptx`);
- OpenDocument files (`.odt`, `.ods`, `.odp`), RTF, and HTML;
- text, Markdown, CSV, JSON, XML, and source code files.

With a vision-capable model and a matching `mmproj` file, you can also discuss
PNG, JPG, BMP, and GIF images in the chat. The AI can optionally request screenshots
after confirmation. Image features require a model with the appropriate capabilities.

### Analyze document collections in expert mode

Expert mode makes an entire document folder available as a knowledge source for the AI:

- summarize documents individually, or in sections for longer content;
- create a searchable full-text index and an overall summary;
- search for specific information and read individual pages or sections;
- pause and resume an analysis, and reanalyze changed files.

Scanned PDFs can be read page by page using a suitable model's vision capabilities.
The PDF rendering required for this uses Windows features (on Linux: `pdftoppm` from poppler-utils).
Results are stored separately
under `chats/experten/`; the source documents remain unchanged.

### Use the AI as an agent

Optional tools let the model perform tasks that go beyond providing
a text response:

- read, search, and edit files and folders in shared directories;
- create Word documents, Excel spreadsheets, and PowerPoint presentations;
- create coding projects from templates and work with existing development tools;
- run PowerShell (Windows) or Bash (Linux) and Python commands, provided this feature is enabled;
- search the web and retrieve webpages as text;
- save notes as memory across chats and create reminders.

The settings define the working folder, additional shared folders, and available tools.
The “Confirm every action” option lets you confirm tool calls before they run.
Which tasks can be completed reliably also depends on the selected model
and its support for tool calls.

Web search uses DuckDuckGo or, optionally, the Brave Search API. Brave requires
your own API key.

### Convert speech to text locally

[whisper.cpp](https://github.com/ggml-org/whisper.cpp) lets you transcribe microphone recordings
and audio files locally. The application can download the required program and a
speech recognition model. Microphone recording uses Windows interfaces (on Linux: PipeWire, PulseAudio
or ALSA). On Linux, whisper.cpp is not available as a ready-made download – see [Linux](#linux).

### Collaborate as a team

In Teamwork mode, one participant creates a room on their computer. Others join
using an invitation code; their computers must be able to reach the host over the network.

- People and their AI assistants write in a shared group chat.
- Address AI assistants with `@Name` or `@alle`.
- A shared main task and a task list support collaboration.
- Files and a project folder shared by the host can be used together.
- Each participant decides which tools their own AI may use in the room.
- Ongoing AI responses can be stopped individually or for the entire room.

Each AI uses the model loaded on its own computer. The room is run by the host
and requires a working network connection to that computer.

## Requirements

- **Windows 10/11 or Linux** (x64 or arm64). On Linux, a few features need common system packages;
  see [Linux](#linux).
- **Python 3.12 or newer with Tkinter** to run from source. On Windows the Python code uses only
  the standard library; on Linux, Pillow is used for images.
- **A GGUF language model and llama.cpp** for AI responses. Model files are not included
  in the repository. RAM usage, GPU memory usage, and speed depend on the model
  and settings.
- **Optional additional models** for vision and speech recognition, and possibly
  additional development tools for coding tasks.

## Run from source

1. Clone or download the repository and make sure Python with Tkinter is available.
2. Start the application from the repository folder:

   ```sh
   python Monhip.pyw
   ```

3. Under **Settings → Loading**, use **“Download / update llama.cpp”**
   to set up the model server.
4. Place a suitable `.gguf` model in the `modelle/` folder or add another model folder
   under **Settings → Models**.
5. Select the model in the interface and click **“▶ Load”**. Once it has loaded,
   you can start your first chat.
6. If needed, enable additional features and working folders under **Settings → Tools**.
   Speech recognition is set up separately under **Settings → Language**.

Model inference runs locally. Downloads, web search, and page retrieval require internet
access; Teamwork mode transfers shared content to the participating computers.

## Linux

Monhip uses the same code on both systems; everything that differs is collected in `app/plattform.py`
and in Linux branches of the affected modules.

On Debian and Ubuntu (24.04 or newer), the easiest way is the package built by
`installer/linux/build-deb.sh` (see [installer/linux](installer/linux/README.md)): it installs Monhip to
`/opt/monhip`, adds a menu entry and pulls in everything listed below. Its data lives in
`~/.local/share/monhip`.

To run from source instead, Monhip relies on common system programs. On Debian and Ubuntu, this
installs all of them:

```sh
sudo apt install python3 python3-tk python3-pil xdg-utils pciutils libvulkan1 mesa-vulkan-drivers \
    poppler-utils libnotify-bin xclip wl-clipboard tkdnd pipewire-bin alsa-utils
```

| Package | Used for |
| --- | --- |
| `python3-tk` | the interface (Tkinter) |
| `python3-pil` (Pillow) | image previews, images from the clipboard, `bilder_bearbeiten`, screenshots on X11 |
| `xdg-utils` | opening files and folders (`xdg-open`) |
| `pciutils` | recognizing the graphics card (`lspci`) to download the right llama.cpp build |
| `libvulkan1`, `mesa-vulkan-drivers` | the Vulkan build of llama.cpp on AMD and Intel graphics (NVIDIA: CUDA build, needs the proprietary NVIDIA driver) |
| `poppler-utils` | scanned PDFs in expert mode (`pdftoppm`, `pdfinfo`) |
| `libnotify-bin` | reminders as desktop notifications (`notify-send`) |
| `xclip` / `wl-clipboard` | clipboard for the AI tools and for pasting files and images (X11 / Wayland) |
| `tkdnd` | drag & drop of files onto the window (optional) |
| `pipewire-bin` or `alsa-utils` | microphone recording (`pw-record`, `parecord` or `arecord`) |

Other distributions have packages with similar names. Additional notes:

- **llama.cpp** is downloaded as on Windows (the `ubuntu` builds: CPU, Vulkan or CUDA, depending on the
  graphics card). A `llama-server` installed elsewhere on the system is found automatically.
- **whisper.cpp** is not offered as a ready-made Linux program. Install `whisper-cli` with your package
  manager or build it from [source](https://github.com/ggml-org/whisper.cpp); Monhip finds it in `PATH`
  and downloads the speech recognition model itself.
- **Screenshots** use `grim`, `gnome-screenshot` or `spectacle` on Wayland, and Pillow, ImageMagick
  (`import`), `scrot` or `maim` on X11.
- **Commands** run in Bash instead of PowerShell. `sudo` is not possible because nobody could enter the
  password.
- **Operating program windows** (keyboard and mouse control) is only available on Windows; the option
  is hidden on Linux.
- **Icons** come from [Fluent UI System Icons](https://github.com/microsoft/fluentui-system-icons)
  (Microsoft, MIT License): `app/fonts/MonhipIcons.ttf` contains just the 45 icons Monhip uses and is built
  with `tools/icon_font.py`. On Windows, Monhip uses the system's Segoe Fluent Icons as before.
- Deleted files go to the desktop trash (`gio trash`, or `~/.local/share/Trash` directly).

## Interface language

Since version 1.3, you can choose between **Deutsch** and **English** under
**Settings → Appearance → Interface language**. Your choice is saved and applied
the next time you start Monhip.

On first launch without a saved language choice, Monhip automatically detects the system language:
German systems use the German interface; English and all other system languages use English.
On Windows, the Windows display language is used for this; on Linux, the locale (`LANG`). A language selected manually
later takes precedence over the system language.

The interface language is independent of speech recognition and the AI model's system prompt.
Your own messages, model responses, document contents, and saved names are not translated
or changed when you switch languages.

## Local data and project structure

Monhip stores settings and usage data alongside the startup program – or in the folder named by the
environment variable `MONHIP_DATA` (the Linux package uses `~/.local/share/monhip`):

| Path | Contents |
| --- | --- |
| `Monhip.pyw` | Entry point for starting the application |
| `app/` | Interface, model integration, agent tools, and other Python modules |
| `installer/` | Linux package and Windows installer (`Monhip-Setup.exe`) – see [installer](installer/README.md) |
| `tests/` | Automated tests (`python -m unittest discover -s tests`), run on Windows and Linux for every push |
| `tools/` | Developer tools, e.g. `icon_font.py` to rebuild the icon font |
| `config.json` | Application settings |
| `modelle/` | Local GGUF models and speech recognition models |
| `server/` | Downloaded llama.cpp and whisper.cpp programs |
| `chats/` | Saved conversations, attached images, and expert analyses |
| `checkpoints/`, `raeume/` | Undo points for file changes, Teamwork rooms |
| `gedaechtnis.json` | The AI's notes across chats |
| `erinnerungen.json` | Saved reminders |

The data folders and settings files are created as you use the application. Your own chats,
models, settings, and access keys are local usage data and should not be uploaded
when publishing source code.
