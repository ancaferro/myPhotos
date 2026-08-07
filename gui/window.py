"""Main window: top bar, analysis progress, gallery, people sidebar."""

import html
import logging
import os

from PySide6.QtCore import QFileSystemWatcher, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import analyzer as analyzer_mod
from analyzer import Analyzer
from gui import data
from gui.gallery import GalleryView
from gui.lightbox import Lightbox
from gui.people import PeoplePanel
from gui.settings import SettingsDialog
from gui.tags import TagsPanel
from gui.theme import (
    app_icon,
    aspect_icon,
    eye_icon,
    gear_icon,
    pin_icon,
    sort_icon,
)
from gui.thumbs import ImageLoader
from paths import default_photos_dir

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 400
SIDEBAR_W = 280
RESCAN_DEBOUNCE_MS = 2000
MAX_WATCH_DIRS = 512


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
        self.setAcceptDrops(True)

        self.analyzer = Analyzer()
        self.loader = ImageLoader(self)
        self.settings = QSettings()
        self.aspect_key = "43" if self.settings.value("aspect") == "43" else "34"
        self.show_boxes = self.settings.value("showBoxes", "1") != "0"
        self.sort_order = "date" if self.settings.value("sort") == "date" else "name"
        self.watch_enabled = self.settings.value("watch", "1") != "0"
        self.active_person_ids: set[int] = set()
        self.active_tag_ids: set[int] = set()
        self.location_only = False
        self.watched_folder: str | None = None
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._poll_progress)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._on_dir_changed)
        self.rescan_timer = QTimer(self)
        self.rescan_timer.setSingleShot(True)
        self.rescan_timer.setInterval(RESCAN_DEBOUNCE_MS)
        self.rescan_timer.timeout.connect(self._auto_rescan)

        analyzer_mod.GREEDY_THRESHOLD = float(
            self.settings.value("greedyThreshold", analyzer_mod.GREEDY_THRESHOLD)
        )
        analyzer_mod.CLUSTER_THRESHOLD = float(
            self.settings.value("clusterThreshold", analyzer_mod.CLUSTER_THRESHOLD)
        )
        logging.getLogger().setLevel(str(self.settings.value("logLevel", "INFO")))

        self._build_ui()
        self.gallery.set_columns(int(self.settings.value("columns", 4)))
        self._apply_view_settings()
        self.refresh_all()
        self.gallery.setFocus()

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
        self.folder_input.setText(str(self.settings.value("lastFolder") or default_photos_dir()))
        # Let a dropped folder reach MainWindow.dropEvent instead of Qt
        # inserting the URL's raw text into the field.
        self.folder_input.setAcceptDrops(False)
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
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("linkBtn")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._cancel_analysis)
        progress.addWidget(self.cancel_btn)
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
        self.gallery.customContextMenuRequested.connect(self._photo_context_menu)
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
        self.sort_btn = QToolButton()
        self.location_btn = QToolButton()
        self.settings_btn = QToolButton()
        for btn in (
            self.aspect_btn,
            self.boxes_btn,
            self.sort_btn,
            self.location_btn,
            self.settings_btn,
        ):
            btn.setObjectName("actionBtn")
            btn.setFixedSize(36, 36)
            btn.setCursor(Qt.PointingHandCursor)
        self.aspect_btn.clicked.connect(self._toggle_aspect)
        self.boxes_btn.clicked.connect(self._toggle_boxes)
        self.sort_btn.clicked.connect(self._toggle_sort)
        self.location_btn.clicked.connect(self._toggle_location_filter)
        self.settings_btn.setIcon(gear_icon())
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.clicked.connect(self._open_settings)
        actions.addWidget(self.aspect_btn)
        actions.addWidget(self.boxes_btn)
        actions.addWidget(self.sort_btn)
        actions.addWidget(self.location_btn)
        actions.addStretch()
        actions.addWidget(self.settings_btn)
        side.addLayout(actions)

        people_title = QLabel("PEOPLE")
        people_title.setObjectName("sidebarTitle")
        side.addWidget(people_title)
        self.people = PeoplePanel(self.loader)
        self.people.person_clicked.connect(self._on_person_clicked)
        self.people.rename_requested.connect(self._rename_person)
        self.people.merge_requested.connect(self._merge_person)
        self.people.delete_requested.connect(self._delete_person)
        side.addWidget(self.people, 2)

        tags_header = QHBoxLayout()
        tags_title = QLabel("TAGS")
        tags_title.setObjectName("sidebarTitle")
        tags_header.addWidget(tags_title)
        tags_header.addStretch()
        new_tag_btn = QToolButton()
        new_tag_btn.setObjectName("personBtn")
        new_tag_btn.setText("+")
        new_tag_btn.setToolTip("New tag")
        new_tag_btn.setFixedSize(22, 22)
        new_tag_btn.setCursor(Qt.PointingHandCursor)
        new_tag_btn.clicked.connect(self._new_tag)
        tags_header.addWidget(new_tag_btn)
        side.addLayout(tags_header)
        self.tags = TagsPanel()
        self.tags.tag_clicked.connect(self._on_tag_clicked)
        self.tags.rename_requested.connect(self._rename_tag)
        self.tags.delete_requested.connect(self._delete_tag)
        side.addWidget(self.tags, 1)
        body.addWidget(sidebar)

        root.addLayout(body, 1)
        self.setCentralWidget(central)
        self.lightbox = Lightbox(self)
        self.lightbox.face_context_requested.connect(self._face_context_menu)

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
        self.active_person_ids &= {p["id"] for p in persons}
        self.people.rebuild(persons, self.active_person_ids)
        self._update_filter_banner()

    def refresh_tags(self):
        try:
            tags = data.list_tags()
        except Exception as exc:  # noqa: BLE001 - e.g. a corrupted database
            self._report_error("Loading tags", exc)
            return
        self.active_tag_ids &= {t["id"] for t in tags}
        self.tags.rebuild(tags, self.active_tag_ids)
        self._update_filter_banner()

    def refresh_photos(self):
        try:
            photos = data.list_photos(
                sorted(self.active_person_ids) or None,
                self.aspect_key,
                self.sort_order,
                sorted(self.active_tag_ids) or None,
                self.location_only,
            )
        except Exception as exc:  # noqa: BLE001 - e.g. a corrupted database
            self._report_error("Loading photos", exc)
            return
        self.gallery.set_photos(photos)
        self.stack.setCurrentIndex(0 if photos else 1)

    def refresh_all(self):
        self.refresh_persons()
        self.refresh_tags()
        self.refresh_photos()

    def _update_filter_banner(self):
        parts = []
        people = [p for p in self.people.persons() if p["id"] in self.active_person_ids]
        if people:
            names = ", ".join(f"<b>{html.escape(p['name'])}</b>" for p in people)
            parts.append(f"with {names}")
        tags = [t for t in self.tags.tags() if t["id"] in self.active_tag_ids]
        if tags:
            names = ", ".join(f"<b>{html.escape(t['name'])}</b>" for t in tags)
            parts.append(f"tagged {names}")
        if self.location_only:
            parts.append("with location")
        self.filter_banner.setVisible(bool(parts))
        if parts:
            self.filter_label.setText("Showing photos " + " · ".join(parts))

    # ---------------------------------------------------------------- filter

    def _on_person_clicked(self, person_id):
        # Toggle membership; several selected people filter with AND.
        if person_id in self.active_person_ids:
            self.active_person_ids.discard(person_id)
        else:
            self.active_person_ids.add(person_id)
        self.refresh_all()

    def _on_tag_clicked(self, tag_id):
        if tag_id in self.active_tag_ids:
            self.active_tag_ids.discard(tag_id)
        else:
            self.active_tag_ids.add(tag_id)
        self.refresh_all()

    def _toggle_location_filter(self):
        self.location_only = not self.location_only
        self._apply_view_settings()
        self.refresh_all()

    def _clear_filter(self):
        self.active_person_ids.clear()
        self.active_tag_ids.clear()
        self.location_only = False
        self._apply_view_settings()
        self.refresh_all()

    def _has_filter(self):
        return bool(self.active_person_ids or self.active_tag_ids or self.location_only)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._has_filter():
            self._clear_filter()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ drag & drop

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            folder = local_path if os.path.isdir(local_path) else os.path.dirname(local_path)
            if os.path.isdir(folder):
                self.folder_input.setText(folder)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    # ------------------------------------------------------------------ tags

    def _new_tag(self, photos=None):
        """Create a tag and, when photos are given, attach it to them."""
        name, ok = QInputDialog.getText(self, "New tag", "Tag name:")
        name = name.strip()
        if not ok or not name:
            return
        try:
            tag_id = data.create_tag(name)
            if photos:
                data.set_photo_tag([p["id"] for p in photos], tag_id, True)
        except Exception as exc:  # noqa: BLE001
            self._report_error("New tag", exc)
            return
        self.refresh_all()

    def _rename_tag(self, tag):
        name, ok = QInputDialog.getText(
            self, "Rename tag", "Tag name:", QLineEdit.Normal, tag["name"]
        )
        name = name.strip()
        if not ok or not name or name == tag["name"]:
            return
        try:
            data.rename_tag(tag["id"], name)
        except Exception as exc:  # noqa: BLE001
            self._report_error("Rename tag", exc)
            return
        self.refresh_all()

    def _delete_tag(self, tag):
        answer = QMessageBox.question(
            self,
            "Delete tag",
            f"Delete the tag “{tag['name']}”?\n"
            f"It will be removed from {tag['photo_count']} photo(s);"
            " the photos themselves are kept.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            data.delete_tag(tag["id"])
        except Exception as exc:  # noqa: BLE001
            self._report_error("Delete tag", exc)
            return
        self.active_tag_ids.discard(tag["id"])
        self.refresh_all()

    def toggle_tag_on(self, photos, tag_id, attached):
        try:
            data.set_photo_tag([p["id"] for p in photos], tag_id, attached)
        except Exception as exc:  # noqa: BLE001
            self._report_error("Tagging", exc)
            return
        self.refresh_all()

    # ------------------------------------------------------------ face edits

    def _face_context_menu(self, face, global_pos):
        self.build_face_menu(face).exec(global_pos.toPoint())

    def build_face_menu(self, face):
        """Move a face to another person, split it off, or delete the box."""
        menu = QMenu(self)
        current = face["person_name"] or "Unknown"
        menu.addAction(f"Face: {current}").setEnabled(False)
        menu.addSeparator()

        for person in self.people.persons():
            if person["id"] == face["person_id"]:
                continue
            action = menu.addAction(f"Move to {person['name']}")
            action.triggered.connect(
                lambda _=False, p=person: self._assign_face(face, p)
            )
        menu.addAction("Move to a new person…").triggered.connect(
            lambda: self._split_face(face)
        )
        menu.addSeparator()
        menu.addAction("Delete this face box").triggered.connect(
            lambda: self._delete_face(face)
        )
        return menu

    def _after_face_edit(self):
        self.refresh_all()
        if self.lightbox.isVisible():
            self.lightbox.refresh(self.gallery._model.photos())

    def _assign_face(self, face, person):
        try:
            data.assign_face(face["id"], person["id"])
        except Exception as exc:  # noqa: BLE001
            self._report_error("Move face", exc)
            return
        log.info("face %s moved to person %s", face["id"], person["id"])
        self._after_face_edit()

    def _split_face(self, face):
        name, ok = QInputDialog.getText(
            self, "Move to a new person", "Name:", QLineEdit.Normal, ""
        )
        name = name.strip()
        if not ok or not name:
            return
        try:
            data.split_face_to_new_person(face["id"], name)
        except Exception as exc:  # noqa: BLE001
            self._report_error("Move face", exc)
            return
        self._after_face_edit()

    def _delete_face(self, face):
        answer = QMessageBox.question(
            self,
            "Delete face box",
            f"Delete this face box ({face['person_name'] or 'Unknown'})?\n"
            "The photo itself is kept.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            data.delete_face(face["id"])
        except Exception as exc:  # noqa: BLE001
            self._report_error("Delete face", exc)
            return
        self._after_face_edit()

    # ---------------------------------------------------------- context menu

    def _photo_context_menu(self, pos):
        photo = self.gallery.photo_at(pos)
        if photo is None:
            return
        selected = self.gallery.selected_photos()
        if not any(p["id"] == photo["id"] for p in selected):
            selected = [photo]
        menu = self.build_photo_menu(photo, selected)
        menu.exec(self.gallery.viewport().mapToGlobal(pos))

    def build_photo_menu(self, photo, selected):
        """Tag toggles for the selection plus per-photo location actions."""
        menu = QMenu(self)
        header = f"{len(selected)} photos" if len(selected) > 1 else photo["filename"]
        menu.addAction(header).setEnabled(False)
        menu.addSeparator()

        tagged_everywhere = set.intersection(
            *({t["id"] for t in p.get("tags", [])} for p in selected)
        )
        for tag in self.tags.tags():
            action = menu.addAction(tag["name"])
            action.setCheckable(True)
            action.setChecked(tag["id"] in tagged_everywhere)
            action.triggered.connect(
                lambda checked, tag_id=tag["id"]: self.toggle_tag_on(
                    selected, tag_id, checked
                )
            )
        menu.addAction("New tag…").triggered.connect(lambda: self._new_tag(selected))

        if photo.get("lat") is not None and len(selected) == 1:
            menu.addSeparator()
            coords = f"{photo['lat']:.6f}, {photo['lon']:.6f}"
            menu.addAction(f"Copy coordinates ({coords})").triggered.connect(
                lambda: QApplication.clipboard().setText(coords)
            )
            menu.addAction("Open location in OpenStreetMap").triggered.connect(
                lambda: QDesktopServices.openUrl(
                    QUrl(
                        f"https://www.openstreetmap.org/?mlat={photo['lat']}"
                        f"&mlon={photo['lon']}#map=15/{photo['lat']}/{photo['lon']}"
                    )
                )
            )
        if len(selected) == 1:
            menu.addAction("Copy file path").triggered.connect(
                lambda: QApplication.clipboard().setText(photo["path"])
            )
        return menu

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
        if person["id"] in self.active_person_ids:
            self.active_person_ids.discard(person["id"])
            self.active_person_ids.add(target["id"])
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
        self.active_person_ids.discard(person["id"])
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
        self.sort_btn.setIcon(sort_icon(self.sort_order))
        self.sort_btn.setToolTip(
            "Sorted by filename — click to sort by capture date"
            if self.sort_order == "name"
            else "Sorted by capture date — click to sort by filename"
        )
        self.location_btn.setIcon(pin_icon(active=self.location_only))
        self.location_btn.setToolTip(
            "Showing only photos with GPS coordinates — click to show all"
            if self.location_only
            else "Show only photos with GPS coordinates"
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

    def _toggle_sort(self):
        self.sort_order = "date" if self.sort_order == "name" else "name"
        self.settings.setValue("sort", self.sort_order)
        self._apply_view_settings()
        self.refresh_photos()

    # -------------------------------------------------------------- settings

    def _open_settings(self):
        dialog = SettingsDialog(
            {
                "columns": self.gallery.columns,
                "aspect": self.aspect_key,
                "sort": self.sort_order,
                "watch": self.watch_enabled,
                "greedy_threshold": analyzer_mod.GREEDY_THRESHOLD,
                "cluster_threshold": analyzer_mod.CLUSTER_THRESHOLD,
                "log_level": logging.getLevelName(logging.getLogger().level),
            },
            self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.apply_settings(dialog.values())

    def apply_settings(self, values):
        self.gallery.set_columns(values["columns"])
        self.settings.setValue("columns", values["columns"])
        self.aspect_key = values["aspect"]
        self.settings.setValue("aspect", values["aspect"])
        self.sort_order = values["sort"]
        self.settings.setValue("sort", values["sort"])
        self.watch_enabled = values["watch"]
        self.settings.setValue("watch", "1" if values["watch"] else "0")
        analyzer_mod.GREEDY_THRESHOLD = values["greedy_threshold"]
        self.settings.setValue("greedyThreshold", values["greedy_threshold"])
        analyzer_mod.CLUSTER_THRESHOLD = values["cluster_threshold"]
        self.settings.setValue("clusterThreshold", values["cluster_threshold"])
        logging.getLogger().setLevel(values["log_level"])
        self.settings.setValue("logLevel", values["log_level"])
        self._setup_watch(self.watched_folder)
        self._apply_view_settings()
        self.refresh_photos()

    # -------------------------------------------------------- folder watching

    def _setup_watch(self, folder):
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.watched_folder = folder
        if not (folder and self.watch_enabled and os.path.isdir(folder)):
            return
        dirs = [folder]
        for root, subdirs, _files in os.walk(folder):
            for sub in subdirs:
                dirs.append(os.path.join(root, sub))
                if len(dirs) >= MAX_WATCH_DIRS:
                    log.warning("watching only the first %d folders", MAX_WATCH_DIRS)
                    break
            if len(dirs) >= MAX_WATCH_DIRS:
                break
        self.watcher.addPaths(dirs)
        log.info("watching %d folder(s) under %s", len(dirs), folder)

    def _on_dir_changed(self, _path):
        if self.watch_enabled and not self.analyzer.is_running():
            self.rescan_timer.start()

    def _auto_rescan(self):
        if not self.watched_folder or self.analyzer.is_running():
            return
        if self.analyzer.start(self.watched_folder):
            log.info("folder changed — re-indexing %s", self.watched_folder)
            self._set_analyzing(True)
            self.poll_timer.start()

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
        self.settings.setValue("lastFolder", folder)
        self._analyzing_folder = folder
        self._set_analyzing(True)
        self.poll_timer.start()

    def _cancel_analysis(self):
        self.analyzer.cancel()
        self.cancel_btn.setDisabled(True)

    def _set_analyzing(self, on):
        self.analyze_btn.setDisabled(on)
        self.analyze_btn.setText("Analyzing…" if on else "Analyze")
        self.progress_row.setVisible(on)
        self.cancel_btn.setDisabled(False)

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
            elif progress["status"] == "canceled":
                QMessageBox.information(
                    self,
                    "Analyze",
                    f"Analysis canceled — kept {done} of {total} photo(s)"
                    " already processed.",
                )
            elif progress["status"] == "done":
                self._setup_watch(getattr(self, "_analyzing_folder", None)
                                  or self.watched_folder)
            self.refresh_all()

    # -------------------------------------------------------------- lightbox

    def _open_lightbox(self, photo):
        photos = self.gallery._model.photos()
        index = next((i for i, p in enumerate(photos) if p["id"] == photo["id"]), 0)
        self.lightbox.show_photos(photos, index, show_boxes=self.show_boxes)
