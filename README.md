# MyPhoto — Face Catalog

A local web app that scans a folder (recursively) for photos, detects faces with
OpenCV, groups identical faces into persons and lets you browse and filter the
photo library by person.

## Download

Prebuilt standalone executables are attached to every
[release](../../releases/latest):

| OS      | File                 |
|---------|----------------------|
| Windows | `MyPhoto-Windows.exe`|
| Linux   | `MyPhoto-Linux`      |
| macOS   | `MyPhoto-macOS`      |

Run the file — a local server starts and your browser opens the app
(http://127.0.0.1:5001). On Linux/macOS make it executable first:
`chmod +x MyPhoto-Linux && ./MyPhoto-Linux`. On macOS you may need to allow it
in *System Settings → Privacy & Security* (the binary is not notarized).

## Features

- Pick any folder; images are discovered recursively (jpg, jpeg, png, webp, bmp, tiff).
- Face detection with OpenCV **YuNet**, face embeddings with **SFace**.
- Faces are clustered into persons (`Persona 1`, `Persona 2`, …): a fast greedy
  pass runs while analysis is in progress, then a final average-linkage
  re-clustering of all faces.
- Persons can be renamed, merged into one another, or deleted (useful for
  false detections); every edit survives re-analysis.
- Each person has a stable distinct color used for its face boxes on photos
  and for its name in the sidebar.
- Every photo preview shows semi-transparent rectangles over detected faces
  with the person's name below each box; click a photo to see it full-size.
- Click a person portrait in the right sidebar to filter the gallery to photos
  containing that person (photos with several people match any of their filters).
- Progress bar while analysis is running.
- Results (photos, faces, persons) are persisted in SQLite; unchanged photos
  are not re-analyzed on subsequent runs.

## Run from source

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python scripts/download_models.py   # fetches ONNX models from the OpenCV Zoo
python3 app.py
```

Open http://127.0.0.1:5001, check the folder path and press **Analyze**.

## Build executables

Executables are built with PyInstaller — locally:

```bash
pip install pyinstaller
python scripts/download_models.py
pyinstaller myphoto.spec
```

or by CI: pushing a `v*` tag triggers the
[build workflow](.github/workflows/build.yml), which compiles binaries on
Windows, Linux and macOS runners and attaches them to a GitHub release.

## Project layout

| Path                         | Purpose                                        |
|------------------------------|------------------------------------------------|
| `app.py`                     | Flask server and HTTP API                      |
| `analyzer.py`                | Folder scanning, face detection and clustering |
| `database.py`                | SQLite schema and connection helpers           |
| `paths.py`                   | Path resolution (source vs frozen bundle)      |
| `main.py`                    | Desktop entry point (server + browser)         |
| `static/`                    | Frontend (HTML/CSS/JS)                         |
| `scripts/download_models.py` | Downloads YuNet and SFace ONNX models          |
| `myphoto.spec`               | PyInstaller build spec                         |

## Storage

- Running from source: `myphoto.db` next to the code.
- Running a packaged executable: `~/.myphoto/myphoto.db`.
