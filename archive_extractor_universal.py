"""
Cross-platform archive extractor without external dependencies
-----------------------------------------------------------

This script provides a graphical interface using Tkinter and optionally
TkinterDnD2, and uses only Python's standard library to unpack archives or analyze
folders. It automatically processes on selection or drag-and-drop, lists formats,
special files, supports reporting, handles nested archives up to a depth, and
supports Cyrillic names on Windows via encoding fallbacks.

Drag & Drop alternatives:
- Tkdnd extension (Tcl/Tk built-in) via tkdnd load command.
- PyQt5/PySide2 with QDragEnterEvent/QDropEvent.
- wxPython DragAndDrop framework.
- PySimpleGUI abstraction with DnD on supported backends.
"""

import os
import shutil
import zipfile
import tarfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
try:
    from tkinter import scrolledtext
except ImportError:
    scrolledtext = None

# Try to import drag-and-drop support
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
    '.zip': 'zip', '.tar': 'tar', '.tar.gz': 'gztar', '.tgz': 'gztar',
    '.tar.bz2': 'bztar', '.tbz2': 'bztar', '.tar.xz': 'xztar', '.txz': 'xztar',
}
SPECIAL_EXTENSIONS = {'.jar', '.war', '.exe', '.dll', '.apk', '.ipa'}
CLASS_EXTENSION = '.class'
REPORT_EXTENSIONS = SPECIAL_EXTENSIONS.union({CLASS_EXTENSION, '.tar.gz', '.tar.bz2', '.tar.xz'})
MAX_DEPTH = 5

class ArchiveExtractorApp:
    def __init__(self):
        # Choose root widget based on DnD support
        if DND_BACKEND == 'tkdnd2':
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()
        self.root.title("Universal Archive Extractor")
        self.path = None
        self.extract_dir = None
        self.text_display = None
        self._build_ui()
        self.root.mainloop()

    def _build_ui(self):
        frame = tk.Frame(self.root, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Drag-and-drop label
        drop_text = "Перетащите файл или папку сюда"
        drop_label = tk.Label(frame, text=drop_text, relief=tk.RIDGE, height=3)
        drop_label.pack(fill=tk.X, pady=(0,5))
        if DND_BACKEND == 'tkdnd2':
            drop_label.drop_target_register(DND_FILES)
            drop_label.dnd_bind('<<Drop>>', self._handle_drop)
        else:
            drop_label.config(text=drop_text + "\n(Установите TkinterDnD2 или альтернативу для Drag&Drop)")

        # Buttons for file and folder selection
        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(5,5))
        tk.Button(btn_frame, text="Выбрать файл", command=self.select_archive).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,5))
        tk.Button(btn_frame, text="Выбрать папку", command=self.select_folder).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5,0))

        # Display label
        tk.Label(frame, text="Форматы файлов и уведомления:").pack(anchor=tk.W, pady=(10,0))

        # Scrollable text display
        if scrolledtext:
            self.text_display = scrolledtext.ScrolledText(frame, wrap='word', height=20)
            self.text_display.pack(fill=tk.BOTH, expand=True)
        else:
            txt_frame = tk.Frame(frame)
            txt_frame.pack(fill=tk.BOTH, expand=True)
            v_scroll = tk.Scrollbar(txt_frame, orient=tk.VERTICAL)
            h_scroll = tk.Scrollbar(txt_frame, orient=tk.HORIZONTAL)
            self.text_display = tk.Text(txt_frame, wrap='word', yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
            v_scroll.config(command=self.text_display.yview)
            h_scroll.config(command=self.text_display.xview)
            v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
            self.text_display.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Save report button
        tk.Button(frame, text="Сохранить отчет", command=self.save_report).pack(fill=tk.X, pady=(5,0))

    def _handle_drop(self, event):
        """Handle drag-and-drop event"""
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self._process_path(paths[0])

    def select_archive(self):
        """Open file dialog for archive selection"""
        file = filedialog.askopenfilename(title="Выберите файл архива")
        if file:
            self._process_path(file)

    def select_folder(self):
        """Open directory dialog for folder selection"""
        folder = filedialog.askdirectory(title="Выберите папку для анализа")
        if folder:
            self._process_path(folder)

    def _process_path(self, path):
        """Process given path: archive or folder"""
        self.path = path
        if os.path.isdir(path):
            # Analyze folder
            self.extract_dir = path
            formats, classes, specials = self._scan_disk(path)
            self._update_display(formats, classes, specials, unpacked=set())
        else:
            # Extract archive
            self.extract_dir = self._compute_extract_dir(path)
            threading.Thread(target=self._extract_and_list, daemon=True).start()

    def _compute_extract_dir(self, path):
        """Compute directory for extraction by stripping known extensions"""
        lp = path.lower()
        for ext in sorted(SUPPORTED_FORMATS.keys(), key=len, reverse=True):
            if lp.endswith(ext):
                return path[:-len(ext)] + "_extracted"
        return os.path.splitext(path)[0] + "_extracted"

    def _extract_and_list(self):
        """Extract archive and recursively unpack inner archives"""
        try:
            if os.path.isdir(self.extract_dir):
                shutil.rmtree(self.extract_dir)
            os.makedirs(self.extract_dir)

            ext = os.path.splitext(self.path)[1].lower()
            # Top-level extraction
            if ext in SPECIAL_EXTENSIONS:
                zf = self._open_zip(self.path)
                zf.extractall(self.extract_dir)
                zf.close()
            elif ext in SUPPORTED_FORMATS:
                if ext.startswith('.tar'):
                    self._extract_tar(self.path, self.extract_dir)
                else:
                    shutil.unpack_archive(self.path, self.extract_dir)
            os.remove(self.path)

            unpacked = set()
            self._recursive_unpack(self.extract_dir, 0, unpacked)

            formats, classes, specials = self._scan_disk(self.extract_dir)
            self.root.after(0, self._update_display, formats, classes, specials, unpacked)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))

    def _open_zip(self, path):
        """Open zip with cp866 fallback for Cyrillic filenames"""
        try:
            return zipfile.ZipFile(path, 'r', encoding='cp866')
        except TypeError:
            return zipfile.ZipFile(path, 'r')

    def _extract_tar(self, path, dest):
        """Extract tar archives with any compression"""
        try:
            with tarfile.open(path, 'r:*') as tf:
                tf.extractall(dest)
        except Exception:
            with tarfile.open(path, 'r') as tf:
                tf.extractall(dest)

    def _recursive_unpack(self, directory, depth, unpacked):
        """Recursively unpack inner archives up to MAX_DEPTH"""
        if depth >= MAX_DEPTH:
            return
        for root, _, files in os.walk(directory):
            if '__MACOSX' in root:
                continue
            for f in files:
                if f.startswith('._'):
                    continue
                full = os.path.join(root, f)
                iext = os.path.splitext(f)[1].lower()
                if iext in SPECIAL_EXTENSIONS or iext in SUPPORTED_FORMATS:
                    target = full[:-len(iext)]
                    try:
                        if iext in SPECIAL_EXTENSIONS:
                            zf = self._open_zip(full)
                            zf.extractall(target)
                            zf.close()
                        elif iext.startswith('.tar'):
                            self._extract_tar(full, target)
                        else:
                            shutil.unpack_archive(full, target)
                        unpacked.add(iext)
                        os.remove(full)
                        self._recursive_unpack(target, depth+1, unpacked)
                    except Exception:
                        continue

    def _scan_disk(self, directory):
        """Scan directory for extensions and special files"""
        exts, classes, specials = set(), [], []
        for root, _, files in os.walk(directory):
            if '__MACOSX' in root:
                continue
            for f in files:
                if f.startswith('._'):
                    continue
                rel = os.path.relpath(os.path.join(root, f), directory)
                le = f.lower()
                if le.endswith(CLASS_EXTENSION):
                    classes.append(rel)
                ext = '.tar.gz' if le.endswith('.tar.gz') else os.path.splitext(f)[1].lower()
                if ext in SPECIAL_EXTENSIONS:
                    specials.append(rel)
                if ext:
                    exts.add(ext)
        return exts, classes, specials

    def _update_display(self, formats, classes, specials, unpacked):
        """Update text display with categorized entries"""
        self.text_display.delete('1.0', tk.END)
        # Class files
        if classes:
            self.text_display.insert(tk.END, "Обнаружены .class-файлы:\n")
            for c in classes:
                self.text_display.insert(tk.END, f"  {c}\n")
            self.text_display.insert(tk.END, "\n")
        # Code/app packages
        if specials:
            self.text_display.insert(tk.END, "Сборка кода/приложения:\n")
            for s in specials:
                tag = " (распакован)" if os.path.splitext(s)[1].lower() in unpacked else ""
                self.text_display.insert(tk.END, f"  {s}{tag}\n")
            self.text_display.insert(tk.END, "\n")
        # Other formats
        others = sorted(formats - {os.path.splitext(x)[1].lower() for x in classes+specials})
        if others:
            self.text_display.insert(tk.END, "Обнаруженные форматы:\n")
            for ext in others:
                tags = []
                if ext in SPECIAL_EXTENSIONS:
                    tags.append("спец.")
                if ext in unpacked:
                    tags.append("распакован")
                tag_str = f" ({'; '.join(tags)})" if tags else ""
                self.text_display.insert(tk.END, f"  {ext}{tag_str}\n")

    def save_report(self):
        """Save report to text file"""
        if not self.extract_dir or not os.path.isdir(self.extract_dir):
            messagebox.showwarning("Внимание", "Сначала распакируйте или анализируйте путь")
            return
        rpt = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text files','*.txt')], title='Сохранить отчет')
        if not rpt:
            return
        exts, classes, specials = self._scan_disk(self.extract_dir)
        with open(rpt, 'w', encoding='utf-8') as rf:
            rf.write("Отчет по файлам форматов: " + ", ".join(sorted(REPORT_EXTENSIONS)) + "\n\n")
            for c in classes:
                rf.write(f"{c} -> {CLASS_EXTENSION}\n")
            for s in specials:
                rf.write(f"{s} -> {os.path.splitext(s)[1].lower()}\n")
            for ext in sorted(exts):
                if ext not in REPORT_EXTENSIONS:
                    rf.write(f"* -> {ext}\n")
        messagebox.showinfo("Готово", f"Отчет сохранен: {rpt}")

if __name__ == "__main__":
    ArchiveExtractorApp()
