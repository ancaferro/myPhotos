"""Settings dialog: view, folder watching and advanced clustering options."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

LOG_LEVELS = ["WARNING", "INFO", "DEBUG"]


def format_size(num_bytes):
    """Byte count as a short human-readable string."""
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.0f} MB"
    return f"{num_bytes / 1024 / 1024 / 1024:.1f} GB"


class SettingsDialog(QDialog):
    """Edits a plain values dict; the window applies and persists it.

    `cache` is an optional (size_fn, clear_fn) pair; when given, the dialog
    shows the thumbnail cache size and a button that empties it.
    """

    def __init__(self, values, parent=None, cache=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.columns = QSpinBox()
        self.columns.setRange(2, 8)
        self.columns.setValue(values["columns"])
        form.addRow("Gallery columns", self.columns)

        self.aspect = QComboBox()
        self.aspect.addItem("Vertical 3:4", "34")
        self.aspect.addItem("Horizontal 4:3", "43")
        self.aspect.setCurrentIndex(0 if values["aspect"] == "34" else 1)
        form.addRow("Preview aspect", self.aspect)

        self.sort = QComboBox()
        self.sort.addItem("Filename", "name")
        self.sort.addItem("Capture date", "date")
        self.sort.setCurrentIndex(0 if values["sort"] == "name" else 1)
        form.addRow("Sort photos by", self.sort)

        self.watch = QCheckBox("Re-index automatically when the folder changes")
        self.watch.setChecked(values["watch"])
        form.addRow("Folder watching", self.watch)

        self._cache = cache
        if cache is not None:
            self.cache_size = QLabel()
            self.clear_cache_btn = QPushButton("Clear")
            self.clear_cache_btn.clicked.connect(self._clear_cache)
            row = QHBoxLayout()
            row.addWidget(self.cache_size)
            row.addStretch(1)
            row.addWidget(self.clear_cache_btn)
            form.addRow("Thumbnail cache", row)
            self._refresh_cache_size()

        advanced = QLabel("Advanced — clustering (applies to the next analysis)")
        advanced.setObjectName("mutedLabel")

        self.greedy = QDoubleSpinBox()
        self.greedy.setRange(0.05, 0.90)
        self.greedy.setSingleStep(0.01)
        self.greedy.setValue(values["greedy_threshold"])

        self.cluster = QDoubleSpinBox()
        self.cluster.setRange(0.05, 0.90)
        self.cluster.setSingleStep(0.01)
        self.cluster.setValue(values["cluster_threshold"])

        self.log_level = QComboBox()
        self.log_level.addItems(LOG_LEVELS)
        self.log_level.setCurrentText(values["log_level"])

        layout.addLayout(form)
        layout.addSpacing(6)
        layout.addWidget(advanced)
        advanced_form = QFormLayout()
        advanced_form.setSpacing(10)
        advanced_form.addRow("Greedy match threshold", self.greedy)
        advanced_form.addRow("Re-cluster threshold", self.cluster)
        advanced_form.addRow("Log level", self.log_level)
        layout.addLayout(advanced_form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_cache_size(self):
        size_fn, _clear_fn = self._cache
        size = size_fn()
        self.cache_size.setText(format_size(size))
        self.clear_cache_btn.setEnabled(size > 0)

    def _clear_cache(self):
        _size_fn, clear_fn = self._cache
        clear_fn()
        self._refresh_cache_size()

    def values(self):
        return {
            "columns": self.columns.value(),
            "aspect": self.aspect.currentData(),
            "sort": self.sort.currentData(),
            "watch": self.watch.isChecked(),
            "greedy_threshold": round(self.greedy.value(), 2),
            "cluster_threshold": round(self.cluster.value(), 2),
            "log_level": self.log_level.currentText(),
        }
