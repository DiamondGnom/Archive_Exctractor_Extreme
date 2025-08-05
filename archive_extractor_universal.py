"""
Cross-platform archive extractor without external dependencies
-----------------------------------------------------------

This script provides a graphical interface using Tkinter (and optionally
TkinterDnD2) and relies solely on Python's standard library (`zipfile`,
`tarfile`, `shutil`, `os`) to automatically unpack archives on selection or drop,
list formats, special files, and supports reporting.
"""

import os
import shutil
import zipfile
import tarfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

# Try to import TkinterDnD2 or tkinterdnd2 for drag-and-drop support
DND_BACKEND = None
try:
    from TkinterDnD2 import TkinterDnD, DND_FILES
    DND_BACKEND = 'tkdnd2'
except ImportError:
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        DND_BACKEND = 'tkdnd2'
    except ImportError:
        pass

SUPPORTED_FORMATS = {
    '.zip': 'zip',
    '.tar': 'tar',
    '.tar.gz': 'gztar',
    '.tgz': 'gztar',
    '.tar.bz2': 'bztar',
    '.tbz2': 'bztar',
    '.tar.xz': 'xztar',
    '.txz': 'xztar',
}
SPECIAL_EXTENSIONS = {'.jar', '.war', '.exe', '.dll', '.apk', '.ipa'}
CLASS_EXTENSION = '.class'
REPORT_EXTENSIONS = SPECIAL_EXTENSIONS.union({CLASS_EXTENSION})

class ArchiveExtractorApp:
    def __init__(self):
        # Use specialized root for DnD if available
        if DND_BACKEND == 'tkdnd2':
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()
        self.root.title("Universal Archive Extractor")
        self.archive_path = None
        self.extract_dir = None
        self.listbox = None
        self._build_ui()
        self.root.mainloop()

    def _build_ui(self):
        frame = tk.Frame(self.root, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Drag-and-drop label
        drop_text = "Перетащите файл архива сюда"
        drop_label = tk.Label(frame, text=drop_text, relief=tk.RIDGE, height=3)
        drop_label.pack(fill=tk.X, pady=(0,5))
        if DND_BACKEND == 'tkdnd2':
            drop_label.drop_target_register(DND_FILES)
            drop_label.dnd_bind('<<Drop>>', self._handle_drop)
        else:
            drop_label.config(
                text=drop_text + "\n(Установите TkinterDnD2 для Drag&Drop)"
            )

        # Buttons (optional manual actions)
        tk.Button(frame, text="Выбрать архив", command=self.select_archive).pack(fill=tk.X)
        tk.Button(frame, text="Сохранить отчет", command=self.save_report).pack(fill=tk.X, pady=(5,10))

        # Listbox for formats and notifications
        tk.Label(frame, text="Форматы файлов и уведомления:").pack(anchor=tk.W)
        self.listbox = tk.Listbox(frame, width=60, height=15)
        self.listbox.pack(fill=tk.BOTH, expand=True)

    def _compute_extract_dir(self, path):
        """Compute extraction directory by stripping longest supported extension."""
        lp = path.lower()
        for ext in sorted(SUPPORTED_FORMATS, key=len, reverse=True):
            if lp.endswith(ext):
                return path[:-len(ext)] + "_extracted"
        return os.path.splitext(path)[0] + "_extracted"

    def _handle_drop(self, event):
        """Handle files dropped onto the DnD area"""
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        self._process_archive(paths[0])

    def select_archive(self):
        path = filedialog.askopenfilename(title="Выберите файл архива")
        if path:
            self._process_archive(path)

    def _process_archive(self, path):
        """Set archive path, extract it, and list formats automatically."""
        self.archive_path = path
        self.extract_dir = self._compute_extract_dir(path)
        # Perform extraction and listing in background
        threading.Thread(target=self._extract_and_list, daemon=True).start()

    def _extract_and_list(self):
        """Unpack archive and list contents."""
        try:
            # Clean previous
            if os.path.isdir(self.extract_dir):
                shutil.rmtree(self.extract_dir)
            os.makedirs(self.extract_dir)
            ext = os.path.splitext(self.archive_path)[1].lower()
            # Extract
            if ext in SPECIAL_EXTENSIONS:
                zipfile.ZipFile(self.archive_path).extractall(self.extract_dir)
            else:
                shutil.unpack_archive(self.archive_path, self.extract_dir)
            os.remove(self.archive_path)
            # Recursive unpack
            unpacked = set()
            for root, _, files in os.walk(self.extract_dir):
                if '__MACOSX' in root:
                    continue
                for f in files:
                    if f.startswith('._'): continue
                    full = os.path.join(root, f)
                    iext = os.path.splitext(f)[1].lower()
                    if iext in SPECIAL_EXTENSIONS or iext in SUPPORTED_FORMATS:
                        try:
                            if iext in SPECIAL_EXTENSIONS:
                                zipfile.ZipFile(full).extractall(full[:-len(iext)])
                            else:
                                shutil.unpack_archive(full, full[:-len(iext)])
                            unpacked.add(iext)
                            os.remove(full)
                        except Exception:
                            pass
            # Scan disk and display
            formats, classes = self._scan_disk(self.extract_dir)
            self.root.after(0, self._update_listbox, formats, classes, unpacked)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))

    def _update_listbox(self, formats, classes, unpacked):
        """Update listbox with new scan results."""
        self.listbox.delete(0, tk.END)
        for ext in sorted(formats):
            tags = []
            if ext in SPECIAL_EXTENSIONS:
                tags.append("спец.")
            if ext in unpacked:
                tags.append("распакован")
            label = ext + ("  (" + "; ".join(tags) + ")" if tags else "")
            self.listbox.insert(tk.END, label)
        for cls in classes:
            self.listbox.insert(tk.END, f"{cls}  ({CLASS_EXTENSION})")

    def _scan_disk(self, dirpath):
        exts, classes = set(), []
        for root, _, files in os.walk(dirpath):
            if '__MACOSX' in root: continue
            for f in files:
                if f.startswith('._'): continue
                rel = os.path.relpath(os.path.join(root, f), dirpath)
                if f.lower().endswith(CLASS_EXTENSION): classes.append(rel)
                if f.lower().endswith('.tar.gz'):
                    e = '.tar.gz'
                else:
                    e = os.path.splitext(f)[1].lower()
                if e: exts.add(e)
        return exts, classes

    def save_report(self):
        if not os.path.isdir(self.extract_dir):
            messagebox.showwarning("Внимание", "Сначала распакуйте архив для создания отчета")
            return
        rpt = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text files','*.txt')], title='Сохранить отчет')
        if not rpt: return
        lines = []
        for root, _, files in os.walk(self.extract_dir):
            if '__MACOSX' in root: continue
            for f in files:
                _, e = os.path.splitext(f)
                if e.lower() in REPORT_EXTENSIONS:
                    rel = os.path.relpath(os.path.join(root, f), self.extract_dir)
                    lines.append(f"{rel} -> {e.lower()}")
        with open(rpt, 'w', encoding='utf-8') as rf:
            rf.write("Отчет по файлам форматов: " + ", ".join(sorted(REPORT_EXTENSIONS)) + "\n")
            rf.write("\n".join(lines))
        messagebox.showinfo("Готово", f"Отчет сохранен: {rpt}")

if __name__ == "__main__":
    ArchiveExtractorApp()
