<div align="center">
# ▣ Source Montage

Source Montage is a premium standalone desktop video editing companion and timeline automation suite designed to automate video editing workflows. Featuring a native desktop wrapper, real-time media importing, timeline automation, and integration with advanced AI models, Source Montage provides a powerful companion panel that can control the timeline programmatically or via natural language chat.

<img width="1024" height="1024" alt="ChatGPT Image Jul 4, 2026, 12_53_49 AM" src="https://github.com/user-attachments/assets/f72ae309-0de1-4cbb-a399-810e2a3d1ef6" />

<div align="left">
---

## 🚀 Key Features

*   **Dual-Model AI Agent Routing**:
    *   **🤖 Source Editor**: Directs complex timeline modification tasks to `gemma4:31b-cloud` via local Ollama wrappers, interpreting natural language commands (e.g., *"cinematic styling"*, *"auto-montage"*, *"split clip"*) and executing them on the active timeline.
    *   **✦ Source Gen 1.0**: Bypasses the LLM entirely, sending text prompts directly to high-fidelity image and video generation backends. It parses aspect ratios (16:9, 9:16, 1:1) from prompts, generates the media, imports it, and appends it to the active timeline automatically.
*   **AI Generation Backend & Fallback Chain**:
    *   **Video Generation**: MiniMax API (`video-01`) ➔ Replicate Fallback (`minimax/video-01` predictions).
    *   **Image Generation**: MiniMax API (`image-01`) ➔ Pollinations.ai Fallback.
*   **Intuitive UI/UX & Layout**:
    *   **Full-Height AI Sidebar**: A dedicated left sidebar spanning the full vertical height of the application below the titlebar.
    *   **Curated Warm Coral & Ink Theme**: A distinct, premium brand aesthetic applied exclusively to the Agent sidebar, using warm cream backgrounds, soft card surfaces, and bold coral action buttons.
    *   **Stop Button (■)**: Implements client-side fetch abortion via an `AbortController` structure, instantly stopping active stream predictions when clicked.
*   **Native App Wrapper**: Native Windows application execution using `pywebview` (Edge WebView2 chromium engine).
*   **Aggressive Cache Prevention**: Custom `Cache-Control: no-cache, no-store, must-revalidate` HTTP headers served on all static assets to ensure code updates are loaded instantly in WebView2.

---

## 📂 Project Structure

```
Source Montage/
├── backend/                  # Python FastAPI server & application entrypoints
│   ├── launcher.py           # GUI application launcher (pywebview and system tray icon)
│   ├── server.py             # FastAPI REST endpoints, AI routing, and tool executor
│   └── requirements.txt      # Python dependencies
├── static/                   # Application frontend source files
│   ├── index.html            # Main desktop application interface layout
│   ├── app.js                # Core frontend interaction, playback controls, and agent stream parser
│   └── styles.css            # Obsidian dark layout & curated agent sidebar styles
├── studio/                   # Landing page code deployed to Vercel
│   ├── index.html            # Premium marketing landing page
│   ├── index.css             # Landing page CSS
│   ├── favicon.png           # Transparent 256x256 circular logo
│   └── favicon.ico           # Multi-resolution favicon fallback (16px to 64px)
├── build.ps1                 # PyInstaller standalone compilation script
├── serve-public.ps1          # Script to run public file servers
├── SourceMontage.spec        # PyInstaller packaging config file
└── README.md                 # Project documentation
```

---

## 🛠️ Getting Started

### Prerequisites
1.  **Python 3.10+** (Ensure Python is added to your system `PATH`).
2.  **FFmpeg** installed and added to your system environment variables (required for local media exports).
3.  **Ollama** installed locally (running on port `11434` with the target LLM pulled).

### Running in Development Mode
1.  Navigate to the project root directory:
    ```powershell
    cd "Source Montage"
    ```
2.  Create and activate a Python virtual environment:
    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    ```
3.  Install the required dependencies:
    ```powershell
    pip install -r backend/requirements.txt
    ```
4.  Run the application launcher:
    ```powershell
    python backend/launcher.py
    ```

---

## 📦 Building the Standalone Executable

The application can be compiled into a single directory containing a native `.exe` with fast startup and bundled python dependencies.

1.  Run the build script:
    ```powershell
    powershell -ExecutionPolicy Bypass -File build.ps1
    ```
2.  Once completed, the compiled files will be located in the `dist/` folder.
3.  Launch the standalone desktop application at:
    `dist\SourceMontage\SourceMontage.exe`

---

## 🚀 Deploying the Landing Page to Vercel

The marketing landing page (located in the `/studio` directory) is designed to be hosted on Vercel.

1.  Navigate to the `/studio` directory:
    ```powershell
    cd studio
    ```
2.  Deploy to production using the Vercel CLI:
    ```powershell
    npx vercel --prod --yes
    ```

---

## 🔒 Configuration & API Keys

Environment keys and tokens are configured in the server's backend. To modify configurations, locate the constant variables at the top of `backend/server.py`:

*   `MINIMAX_API_KEY`: API key for MiniMax image and video models.
*   `REPLICATE_API_TOKEN`: API token for Replicate predictions.
