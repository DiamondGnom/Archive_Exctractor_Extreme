"""
Cross-platform archive extractor without external dependencies
-----------------------------------------------------------

This script provides a graphical interface using Tkinter (and optionally
TkinterDnD2) and relies solely on Python's standard library (`zipfile`,
`tarfile`, `shutil`, `os`) to list and unpack archives.
It supports ZIP and TAR formats (including gz, bz2, xz variants), handles
recursive unpacking, cleans up unpacked archives, marks special extensions
`.jar`, `.war`, `.exe`, `.dll`, `.apk`, `.ipa`, indicates when an inner archive
was unpacked, skips macOS metadata files, identifies `.class` files inside
archives and on disk (with full paths), supports drag-and-drop via TkinterDnD2
when available, and allows generation of a report file listing occurrences
of specified formats.
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

        # Buttons
        tk.Button(frame, text="Выбрать архив", command=self.select_archive).pack(fill=tk.X)
        tk.Button(frame, text="Распаковать", command=self.extract_archive).pack(fill=tk.X, pady=(5,5))
        tk.Button(frame, text="Сохранить отчет", command=self.save_report).pack(fill=tk.X, pady=(0,10))

        # Listbox for formats and notifications
        tk.Label(frame, text="Форматы файлов и уведомления:").pack(anchor=tk.W)
        self.listbox = tk.Listbox(frame, width=60, height=15)
        self.listbox.pack(fill=tk.BOTH, expand=True)

    def _handle_drop(self, event):
        """Handle files dropped onto the DnD area"""
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        self.archive_path = paths[0]
        self.extract_dir = self._compute_extract_dir(self.archive_path)
        self._list_formats_initial()

    def select_archive(self):
        path = filedialog.askopenfilename(title="Выберите файл архива")
        if not path:
            return
        self.archive_path = path
        self.extract_dir = self._compute_extract_dir(path)
        self._list_formats_initial()

    def _compute_extract_dir(self, path):
        """Compute extraction directory by stripping longest supported extension"""
        lp = path.lower()
        for ext in sorted(SUPPORTED_FORMATS.keys(), key=len, reverse=True):
            if lp.endswith(ext):
                return path[:-len(ext)] + "_extracted"
        base, _ = os.path.splitext(path)
        return base + "_extracted"

    def _list_formats_initial(self):
        self.listbox.delete(0, tk.END)
        formats, class_files = self._scan_archive(self.archive_path)
        for ext in sorted(formats):
            tags = []
            if ext in SPECIAL_EXTENSIONS:
                tags.append("спец.")
            label = ext + ("  (" + "; ".join(tags) + ")" if tags else "")
            self.listbox.insert(tk.END, label)
        for cls in class_files:
            self.listbox.insert(tk.END, f"{cls}  ({CLASS_EXTENSION})")

    def _scan_archive(self, path):
        ext = os.path.splitext(path)[1].lower()
        # Detect special formats directly
        if ext in SPECIAL_EXTENSIONS or ext in ('.jar', '.war', '.apk', '.ipa'):
            return {ext}, []
        fmt = next((f for pat, f in SUPPORTED_FORMATS.items() if path.lower().endswith(pat)), None)
        try:
            if fmt == 'zip':
                members = zipfile.ZipFile(path).namelist()
            elif fmt in ('tar', 'gztar', 'bztar', 'xztar'):
                members = tarfile.open(path).getnames()
            else:
                raise ValueError
        except Exception:
            messagebox.showerror("Ошибка", f"Невозможно прочитать архив: {path}")
            return set(), []
        exts, classes = set(), []
        for m in members:
            if m.startswith('._') or '__MACOSX/' in m:
                continue
            if m.lower().endswith(CLASS_EXTENSION):
                classes.append(m)
            if m.lower().endswith('.tar.gz'):
                e = '.tar.gz'
            else:
                e = os.path.splitext(m)[1].lower()
            if e:
                exts.add(e)
        return exts, classes

    def _scan_disk(self, dirpath):
        exts, classes = set(), []
        for root, _, files in os.walk(dirpath):
            if '__MACOSX' in root:
                continue
            for f in files:
                if f.startswith('._'):
                    continue
                rel = os.path.relpath(os.path.join(root, f), dirpath)
                if f.lower().endswith(CLASS_EXTENSION):
                    classes.append(rel)
                if f.lower().endswith('.tar.gz'):
                    e = '.tar.gz'
                else:
                    e = os.path.splitext(f)[1].lower()
                if e:
                    exts.add(e)
        return exts, classes

    def extract_archive(self):
        if not self.archive_path:
            messagebox.showwarning("Внимание", "Сначала выберите или перетащите архив")
            return
        def worker():
            try:
                if os.path.isdir(self.extract_dir):
                    shutil.rmtree(self.extract_dir)
                os.makedirs(self.extract_dir)
                ext = os.path.splitext(self.archive_path)[1].lower()
                # Top-level extraction
                if ext in SPECIAL_EXTENSIONS:
                    zipfile.ZipFile(self.archive_path).extractall(self.extract_dir)
                else:
                    shutil.unpack_archive(self.archive_path, self.extract_dir)
                os.remove(self.archive_path)
                unpacked = set()
                # Recursive unpacking
                for root, _, files in os.walk(self.extract_dir):
                    if '__MACOSX' in root:
                        continue
                    for f in files:
                        if f.startswith('._'):
                            continue
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
                # Refresh display based on disk
                self.listbox.delete(0, tk.END)
                formats, classes = self._scan_disk(self.extract_dir)
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
                messagebox.showinfo("Готово", "Распаковка завершена")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        threading.Thread(target=worker, daemon=True).start()

    def save_report(self):
        if not os.path.isdir(self.extract_dir):
            messagebox.showwarning("Внимание", "Сначала распакуйте архив для создания отчета")
            return
        rpt = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text files','*.txt')], title='Сохранить отчет')
        if not rpt:
            return
        lines = []
        for root, _, files in os.walk(self.extract_dir):
            if '__MACOSX' in root:
                continue
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
