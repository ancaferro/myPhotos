"""Main window: top bar, analysis progress, gallery, people sidebar."""

import logging
import os

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from analyzer import Analyzer
from gui import data
from gui.gallery import GalleryView
from gui.lightbox import Lightbox
from gui.people import PeoplePanel
from gui.theme import app_icon, aspect_icon, eye_icon
from gui.thumbs import ImageLoader
from paths import default_photos_dir

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 400
SIDEBAR_W = 280


class MergeDialog(QDialog):
    """Pick the person that source will be merged into."""

    def __init__(self, source, others, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge person")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Merge “{source['name']}” into:"))
        self.combo = QComboBox()
        for person in others:
            self.combo.addItem(
                f"{person['name']} ({person['photo_count']} photos)", person
            )
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def target(self):
        return self.combo.currentData()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("myPhotos")
        self.setMinimumSize(960, 640)

        self.analyzer = Analyzer()
        self.loader = ImageLoader(self)
        self.settings = QSettings()
        self.aspect_key = "43" if self.settings.value("aspect") == "43" else "34"
        self.show_boxes = self.settings.value("showBoxes", "1") != "0"
        self.active_person_id = None
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._poll_progress)

        self._build_ui()
        self._apply_view_settings()
        self.refresh_all()

    # ------------------------------------------------------------------- UI

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar: brand, folder input, browse, analyze.
        topbar = QWidget()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(16, 12, 16, 12)
        top.setSpacing(12)
        brand_icon = QLabel()
        brand_icon.setPixmap(app_icon().pixmap(24, 24))
        top.addWidget(brand_icon)
        brand = QLabel("myPhotos")
        brand.setObjectName("brand")
        top.addWidget(brand)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Path to a folder with photos…")
        self.folder_input.setText(default_photos_dir())
        top.addWidget(self.folder_input, 1)
        browse = QToolButton()
        browse.setObjectName("browseBtn")
        browse.setText("Browse…")
        browse.clicked.connect(self._browse_folder)
        top.addWidget(browse)
        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.setObjectName("analyzeBtn")
        self.analyze_btn.setCursor(Qt.PointingHandCursor)
        self.analyze_btn.clicked.connect(self._start_analysis)
        top.addWidget(self.analyze_btn)
        root.addWidget(topbar)

        # Analysis progress row (hidden while idle).
        self.progress_row = QWidget()
        self.progress_row.setObjectName("progressRow")
        progress = QHBoxLayout(self.progress_row)
        progress.setContentsMargins(16, 8, 16, 8)
        progress.setSpacing(12)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        progress.addWidget(self.progress_bar, 1)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("progressLabel")
        progress.addWidget(self.progress_label)
        self.progress_row.hide()
        root.addWidget(self.progress_row)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Gallery pane with the person-filter banner and empty state.
        pane = QVBoxLayout()
        pane.setContentsMargins(16, 16, 16, 16)
        pane.setSpacing(12)

        self.filter_banner = QFrame()
        self.filter_banner.setObjectName("banner")
        banner = QHBoxLayout(self.filter_banner)
        banner.setContentsMargins(12, 8, 12, 8)
        banner.setSpacing(6)
        self.filter_label = QLabel()
        banner.addWidget(self.filter_label)
        clear_btn = QPushButton("show all")
        clear_btn.setObjectName("linkBtn")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_filter)
        banner.addWidget(clear_btn)
        banner.addStretch()
        self.filter_banner.hide()
        pane.addWidget(self.filter_banner)

        self.gallery = GalleryView(self.loader)
        self.gallery.photo_clicked.connect(self._open_lightbox)
        empty = QLabel("No analyzed photos yet. Pick a folder and press Analyze.")
        empty.setObjectName("emptyState")
        empty.setAlignment(Qt.AlignCenter)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.gallery)
        self.stack.addWidget(empty)
        pane.addWidget(self.stack, 1)
        body.addLayout(pane, 1)

        # Sidebar: view actions and people.
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_W)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 16, 10, 16)
        side.setSpacing(10)

        actions_title = QLabel("ACTIONS")
        actions_title.setObjectName("sidebarTitle")
        side.addWidget(actions_title)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.aspect_btn = QToolButton()
        self.boxes_btn = QToolButton()
        for btn in (self.aspect_btn, self.boxes_btn):
            btn.setObjectName("actionBtn")
            btn.setFixedSize(36, 36)
            btn.setCursor(Qt.PointingHandCursor)
        self.aspect_btn.clicked.connect(self._toggle_aspect)
        self.boxes_btn.clicked.connect(self._toggle_boxes)
        actions.addWidget(self.aspect_btn)
        actions.addWidget(self.boxes_btn)
        actions.addStretch()
        side.addLayout(actions)

        people_title = QLabel("PEOPLE")
        people_title.setObjectName("sidebarTitle")
        side.addWidget(people_title)
        self.people = PeoplePanel(self.loader)
        self.people.person_clicked.connect(self._on_person_clicked)
        self.people.rename_requested.connect(self._rename_person)
        self.people.merge_requested.connect(self._merge_person)
        self.people.delete_requested.connect(self._delete_person)
        side.addWidget(self.people, 1)
        body.addWidget(sidebar)

        root.addLayout(body, 1)
        self.setCentralWidget(central)
        self.lightbox = Lightbox(self)

    # ------------------------------------------------------------- refreshing

    def _report_error(self, title, exc):
        """Log a failed operation and tell the user instead of crashing."""
        log.exception("%s failed", title)
        QMessageBox.critical(self, title, f"{title} failed:\n{exc}")

    def refresh_persons(self):
        try:
            persons = data.list_persons()
        except Exception as exc:  # noqa: BLE001 - e.g. a corrupted database
            self._report_error("Loading people", exc)
            return
        if self.active_person_id is not None and not any(
            p["id"] == self.active_person_id for p in persons
        ):
            self.active_person_id = None
        self.people.rebuild(persons, self.active_person_id)
        self._update_filter_banner()

    def refresh_photos(self):
        try:
            photos = data.list_photos(self.active_person_id, self.aspect_key)
        except Exception as exc:  # noqa: BLE001 - e.g. a corrupted database
            self._report_error("Loading photos", exc)
            return
        self.gallery.set_photos(photos)
        self.stack.setCurrentIndex(0 if photos else 1)

    def refresh_all(self):
        self.refresh_persons()
        self.refresh_photos()

    def _update_filter_banner(self):
        person = next(
            (p for p in self.people.persons() if p["id"] == self.active_person_id), None
        )
        self.filter_banner.setVisible(person is not None)
        if person is not None:
            self.filter_label.setText(f"Showing photos with <b>{person['name']}</b>")

    # ---------------------------------------------------------------- filter

    def _on_person_clicked(self, person_id):
        self.active_person_id = None if self.active_person_id == person_id else person_id
        self.refresh_all()

    def _clear_filter(self):
        self.active_person_id = None
        self.refresh_all()

    # ---------------------------------------------------------- person edits

    def _rename_person(self, person):
        name, ok = QInputDialog.getText(
            self, "Rename person", "Name:", QLineEdit.Normal, person["name"]
        )
        name = name.strip()
        if ok and name and name != person["name"]:
            try:
                data.rename_person(person["id"], name)
            except Exception as exc:  # noqa: BLE001
                self._report_error("Rename person", exc)
                return
            self.refresh_all()  # labels on photos use the person name

    def _merge_person(self, person):
        others = [p for p in self.people.persons() if p["id"] != person["id"]]
        if not others:
            QMessageBox.information(self, "Merge person", "There is no other person to merge into.")
            return
        dialog = MergeDialog(person, others, self)
        if dialog.exec() != QDialog.Accepted:
            return
        target = dialog.target()
        answer = QMessageBox.question(
            self,
            "Merge person",
            f"Merge “{person['name']}” into “{target['name']}”?\n"
            f"All faces of “{person['name']}” will become “{target['name']}”.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            data.merge_person(person["id"], target["id"])
        except Exception as exc:  # noqa: BLE001
            self._report_error("Merge person", exc)
            return
        if self.active_person_id == person["id"]:
            self.active_person_id = target["id"]
        self.refresh_all()

    def _delete_person(self, person):
        answer = QMessageBox.question(
            self,
            "Delete person",
            f"Delete “{person['name']}”?\n"
            f"Its {person['face_count']} face box(es) will be removed from the photos."
            " The photos themselves are kept.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            data.delete_person(person["id"])
        except Exception as exc:  # noqa: BLE001
            self._report_error("Delete person", exc)
            return
        if self.active_person_id == person["id"]:
            self.active_person_id = None
        self.refresh_all()

    # ----------------------------------------------------------- view actions

    def _apply_view_settings(self):
        self.aspect_btn.setIcon(aspect_icon(self.aspect_key))
        self.aspect_btn.setToolTip(
            "Preview aspect 3:4 — click for 4:3"
            if self.aspect_key == "34"
            else "Preview aspect 4:3 — click for 3:4"
        )
        self.boxes_btn.setIcon(eye_icon(off=not self.show_boxes))
        self.boxes_btn.setToolTip(
            "Hide face boxes and names" if self.show_boxes else "Show face boxes and names"
        )
        self.gallery.set_aspect(self.aspect_key)
        self.gallery.set_show_boxes(self.show_boxes)

    def _toggle_aspect(self):
        self.aspect_key = "43" if self.aspect_key == "34" else "34"
        self.settings.setValue("aspect", self.aspect_key)
        self._apply_view_settings()
        self.refresh_photos()

    def _toggle_boxes(self):
        self.show_boxes = not self.show_boxes
        self.settings.setValue("showBoxes", "1" if self.show_boxes else "0")
        self._apply_view_settings()

    # -------------------------------------------------------------- analysis

    def _browse_folder(self):
        start = self.folder_input.text().strip() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder with photos", start)
        if folder:
            self.folder_input.setText(folder)

    def _start_analysis(self):
        folder = os.path.abspath(os.path.expanduser(self.folder_input.text().strip()))
        if not self.folder_input.text().strip():
            QMessageBox.warning(self, "Analyze", "Folder is required")
            return
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Analyze", f"Folder not found: {folder}")
            return
        if not self.analyzer.start(folder):
            QMessageBox.warning(self, "Analyze", "Analysis is already running")
            return
        self._set_analyzing(True)
        self.poll_timer.start()

    def _set_analyzing(self, on):
        self.analyze_btn.setDisabled(on)
        self.analyze_btn.setText("Analyzing…" if on else "Analyze")
        self.progress_row.setVisible(on)

    def _poll_progress(self):
        progress = self.analyzer.get_progress()
        total, done = progress["total"], progress["done"]
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        if progress["status"] == "running":
            current = f" — {progress['current']}" if progress["current"] else ""
            self.progress_label.setText(f"{done} / {total}{current}")
            # Refresh people as they appear during the run.
            self.refresh_persons()
        else:
            self.poll_timer.stop()
            self._set_analyzing(False)
            if progress["status"] == "error":
                QMessageBox.critical(
                    self, "Analyze", f"Analysis failed: {progress['error']}"
                )
            self.refresh_all()

    # -------------------------------------------------------------- lightbox

    def _open_lightbox(self, photo):
        photos = self.gallery._model.photos()
        index = next((i for i, p in enumerate(photos) if p["id"] == photo["id"]), 0)
        self.lightbox.show_photos(photos, index, show_boxes=self.show_boxes)
