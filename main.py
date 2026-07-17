"""Desktop entry point: start the server and open the browser."""

import threading
import webbrowser

from app import app

HOST = "127.0.0.1"
PORT = 5001


def open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    print(f"myPhotos is running on http://{HOST}:{PORT} (Ctrl+C to quit)")
    app.run(host=HOST, port=PORT, debug=False)
