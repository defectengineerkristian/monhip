# Monhip

Monhip is a desktop application for local AI models. It combines a chat interface with
document analysis, tools for working on your own computer, and a Teamwork mode
where people and their local AI assistants can collaborate.

Language models run on your own computer in GGUF format using
[llama.cpp](https://github.com/ggml-org/llama.cpp). The interface is written in Python with Tkinter
and is primarily in German. The current feature set is geared toward Windows.

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
The PDF rendering required for this uses Windows features. Results are stored separately
under `chats/experten/`; the source documents remain unchanged.

### Use the AI as an agent

Optional tools let the model perform tasks that go beyond providing
a text response:

- read, search, and edit files and folders in shared directories;
- create Word documents, Excel spreadsheets, and PowerPoint presentations;
- create coding projects from templates and work with existing development tools;
- run PowerShell and Python commands, provided this feature is enabled;
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
speech recognition model. Microphone recording uses Windows interfaces.

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

- **Windows** for the intended full desktop feature set. Parts of the interface and document
  processing can run on other operating systems; however, downloaders, microphone recording,
  image processing, and other integrations use Windows technology.
- **Python with Tkinter**, for example Python 3.12, to run from source.
  The Python code uses the standard library; separate pip packages are not currently declared.
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

## Interface language

Since version 1.3, you can choose between **Deutsch** and **English** under
**Settings → Appearance → Interface language**. Your choice is saved and applied
the next time you start Monhip.

On first launch without a saved language choice, Monhip automatically detects the system language:
German systems use the German interface; English and all other system languages use English.
On Windows, the Windows display language is used for this. A language selected manually
later takes precedence over the system language.

The interface language is independent of speech recognition and the AI model's system prompt.
Your own messages, model responses, document contents, and saved names are not translated
or changed when you switch languages.

## Local data and project structure

Monhip stores settings and usage data alongside the startup program:

| Path | Contents |
| --- | --- |
| `Monhip.pyw` | Entry point for starting the application |
| `app/` | Interface, model integration, agent tools, and other Python modules |
| `config.json` | Application settings |
| `modelle/` | Local GGUF models and speech recognition models |
| `server/` | Downloaded llama.cpp and whisper.cpp programs |
| `chats/` | Saved conversations, attached images, and expert analyses |
| `gedaechtnis.json` | The AI's notes across chats |
| `erinnerungen.json` | Saved reminders |

The data folders and settings files are created as you use the application. Your own chats,
models, settings, and access keys are local usage data and should not be uploaded
when publishing source code.
