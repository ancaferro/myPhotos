"""Settings dialog: view, folder watching and advanced clustering options."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

LOG_LEVELS = ["WARNING", "INFO", "DEBUG"]


class SettingsDialog(QDialog):
    """Edits a plain values dict; the window applies and persists it."""

    def __init__(self, values, parent=None):
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
