# Monhip

A desktop app for local AI on Windows and Linux, with an English or German interface.
Chat with GGUF models, work with documents and files, generate images and 3D models,
or collaborate with people and their local AI assistants in Teamwork rooms.

Language models run through [llama.cpp](https://github.com/ggml-org/llama.cpp).
The interface is built with Python and Tkinter.

## Features

- **Chat:** streamed answers, saved conversations, vision support with a matching
  `mmproj` file, and automatic summaries to keep longer conversations going.
- **Documents and research:** read PDFs, Office and OpenDocument files, text and source
  code. Expert mode indexes document folders; the **Sources & research** panel shows
  what the AI searches and reads, with clickable references.
- **Agent tools:** work in shared folders, create Office documents, run Python and
  shell commands, search the web, and read, edit or execute Jupyter notebooks.
  Choose the available tools and whether each action needs confirmation in settings.
- **Images:** create pictures from a prompt or edit an existing image using
  [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp).
- **3D models:** turn an image or a description into a textured model using
  [trellis.cpp](https://github.com/pwilkin/trellis.cpp) and TRELLIS.2, preview it in
  your browser, and export GLB or STL.
- **Teamwork:** host or join a room with an invitation code, share files and tasks,
  and address participants' AI assistants with `@Name` or `@alle`. Each participant
  controls their own model and tools; participants must be able to reach the host.
- **Speech and notifications:** transcribe audio locally with
  [whisper.cpp](https://github.com/ggml-org/whisper.cpp), keep notes and reminders,
  and receive desktop notifications when longer tasks finish.

## Get started

Download **Monhip-Setup.exe** for Windows or the **.deb** package for Debian/Ubuntu
from [Releases](https://github.com/defectengineerkristian/monhip/releases).
They are also available in [`installer/`](installer/). On Linux, install the downloaded
package with `sudo apt install ./monhip_<version>_all.deb`.

The `main` branch may include features not yet available in those installers.
Recent changes are listed in the [development notes (German)](progress/FORTSCHRITT.md).

### Run from source

Use **Python 3.12 or newer with Tkinter**. On Linux, install Pillow as well
(see [Linux](#linux)). Clone the repository and start from its folder:

```sh
git clone https://github.com/defectengineerkristian/monhip.git
cd monhip
python Monhip.pyw
```

1. Under **Settings → Models**, choose **Download / update llama.cpp**.
2. Under **Settings → Models → Download…**, download a recommended model, or put
   your own `.gguf` files in `modelle/`. Additional model folders can be added there.
3. Select a model and load it to start chatting. Split GGUF models appear as one entry;
   keep all parts together.

The recommended downloads are Qwen3.8-27B (about 16 GB; roughly 20 GB combined RAM
and graphics memory) and Qwen3.8-Flash-Next (about 63 GB; roughly 72 GB combined).
Actual memory use depends on context size and settings. Models are not included in
the repository, and CPU/GPU support depends on the selected engine build and hardware.

Change the interface language under **Settings → Appearance → Interface language**.
Tool access and shared folders are configured under **Settings → Tools**.

## Images and 3D

The **Images** area has three entries: **Create image**, **Edit image** and **3D model**.
Choose, drag in or paste an input image for editing or 3D generation. Missing engines
and model files are offered for download when first needed.

| Image model | Approx. download | License |
| --- | --- | --- |
| Qwen-Image 2.1 Turbo (default) | 14 GB | Qwen Research License; non-commercial use only |
| FLUX.2 [klein] 4B | 9 GB, or 5 GB for Q4 | Apache 2.0 |

Without CUDA (AMD and Intel graphics, Linux), Monhip and the Windows installer load
Qwen Image as GGUF (Q8_0) instead of the int8 file, which is reliable only with CUDA.
If Qwen Image produces colored noise, choose **Compatible (slower)** under
**Settings → Images → Qwen Image: compute mode**. **Automatic** applies this workaround
to the confirmed b1068/Vulkan issue on the Radeon RX 9070 XT under Windows.
On this card under Windows, **Settings → Images → Download / update image engine and
model** installs the native ROCm engine and its matching AMD runtime, including hipBLAS,
rocBLAS and GPU kernels (about 1.2 GB extra for ROCm 10.1.0). Existing models are reused.
Runtime downloads use SHA-256 checks; no separate Python environment is required.
A matching complete SDK under `HIP_PATH`, `ROCM_PATH` or the standard AMD installation
folder can also be used. Windows needs a current AMD driver and the
[Microsoft Visual C++ x64 runtime](https://aka.ms/vs/17/release/vc_redist.x64.exe).
The existing Vulkan
compatibility mode remains available; select **Automatic** to use ROCm. NVIDIA cards
continue to use CUDA.

For **3D model**, use a picture of one complete object against a simple background.
The background is removed automatically; unseen parts are inferred. With
**From a description**, Monhip first creates a suitable object image with the image
model, unloads it to free GPU memory and then builds the 3D model; the image stays in
the gallery. TRELLIS.2 defaults to Q8 (about 9.5 GB), with full precision (16.5 GB)
and Q4 (6 GB) alternatives.
A GPU is required; 16 GB of VRAM is recommended for **Fine (1024)**, while **Fast (512)**
needs less. Prebuilt trellis.cpp downloads are for x64 Windows/Linux, using CUDA on
compatible NVIDIA hardware or Vulkan otherwise.

Results appear in the gallery. **View** opens an offline browser viewer; GLB preserves
textures, while STL export lets you choose the height in millimeters for 3D printing
and omits colors. TRELLIS.2 and BiRefNet use the MIT license; DINOv3 uses Meta's
DINOv3 license. Language and image models may be unloaded to free GPU memory.

## Linux

For a source checkout on Ubuntu 24.04+ or a recent Debian release:

```sh
sudo apt install python3 python3-tk python3-pil xdg-utils pciutils libvulkan1 mesa-vulkan-drivers \
    poppler-utils libnotify-bin xclip wl-clipboard tkdnd pipewire-bin alsa-utils
python3 Monhip.pyw
```

These packages cover image handling, opening files, GPU detection, Vulkan, PDF
rendering, notifications, clipboard, drag and drop, and microphone recording.
NVIDIA GPU acceleration requires a suitable driver. On other distributions, use
equivalent packages and Python 3.12+.

- Monhip can download llama.cpp, stable-diffusion.cpp and trellis.cpp builds, or use
  `llama-server`, `sd-server` and `trellis-cli` from `PATH`. Available builds vary by platform.
- For speech recognition, install or build `whisper-cli` separately on Linux.
- Shell tools use Bash. Keyboard/mouse control of other applications is Windows-only.

## Data and optional tools

Inference runs locally. Downloads and web tools need internet access; Teamwork shares
content with the room's participants. Web search uses DuckDuckGo or an optional Brave
Search API key. Model capabilities determine which tools and inputs work.

Settings, chats, models and generated files are stored beside the source launcher by
default. Set `MONHIP_DATA` to use another folder; the Linux package uses
`~/.local/share/monhip`. Keep personal data and API keys out of commits.

Notebook execution additionally needs `nbclient`, `ipykernel` and any packages used
by the notebook, installed in its Python environment. Reading and editing notebooks
does not require Jupyter.
