"""
PaxoInsight 0.3.0: Cross-platform archive extractor without external dependencies
-------------------------------------------------------------------------------

PaxoInsight provides a graphical interface using Tkinter and optionally TkinterDnD2,
relying solely on Python's standard library and the pure-Python `py7zr` module to unpack archives
or analyze folders. It processes on selection or drag-and-drop, lists formats,
highlights special files, supports reporting, handles nested archives up to a depth,
and supports Cyrillic names on Windows via encoding fallbacks.

Drag & Drop alternatives:
- Tkdnd extension (Tcl/Tk built-in) via tkdnd load command.
- PyQt5/PySide2 with QDragEnterEvent/QDropEvent.
- wxPython DragAndDrop framework.
- PySimpleGUI abstraction with DnD on supported backends.

All required libraries imported below:
- os, shutil, gzip, zipfile, tarfile, py7zr, threading
- tkinter for UI, including scrolledtext, filedialog, messagebox
- Optional TkinterDnD2 for Drag&Drop
"""

import os
import shutil
import gzip
import zipfile
import tarfile
import py7zr
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
try:
    from tkinter import scrolledtext
except ImportError:
    scrolledtext = None

import tkinter as tk
from tkinter import filedialog, messagebox
try:
    from tkinter import scrolledtext
except ImportError:
    scrolledtext = None

# Drag-and-drop support
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

# Supported and special formats
SUPPORTED_FORMATS = {
    '.zip': 'zip', '.7z': '7z', '.tar': 'tar', '.tar.gz': 'gztar', '.tgz': 'gztar',
    '.tar.bz2': 'bztar', '.tbz2': 'bztar', '.tar.xz': 'xztar', '.txz': 'xztar'
}
SPECIAL_EXTENSIONS = {'.jar', '.war', '.exe', '.dll', '.apk', '.ipa', '.so'}
CLASS_EXTENSION = '.class'
REPORT_EXTENSIONS = SPECIAL_EXTENSIONS.union({CLASS_EXTENSION, '.tar.gz', '.tar.bz2', '.tar.xz', '.gz'})
MAX_DEPTH = 5
AUTHOR = 'DiamondGnom'
VERSION = '0.3.0'

class PaxoInsightApp:
    def __init__(self):
        # Initialize root window
        if DND_BACKEND == 'tkdnd2':
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()
        self.root.title(f"PaxoInsight {VERSION}")

        # State
        self.path = None
        self.extract_dir = None
        self.text_display = None
        self.class_count_label = None
        self.special_count_label = None
        self.status_label = None

        # Build UI
        self._build_ui()
        self.root.mainloop()

    def _build_ui(self):
        # Menu bar
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Выбрать файл", command=self.select_archive)
        file_menu.add_command(label="Выбрать папку", command=self.select_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.root.quit)
        menubar.add_cascade(label="Файл", menu=file_menu)

        about_menu = tk.Menu(menubar, tearoff=0)
        about_menu.add_command(label="О программе", command=self._show_about)
        menubar.add_cascade(label="О программе", menu=about_menu)
        self.root.config(menu=menubar)

        # Main frame
        frame = tk.Frame(self.root, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Drag-and-drop zone
        drop_label = tk.Label(frame, text="Перетащите файл или папку сюда",
                              relief=tk.RIDGE, height=3)
        drop_label.pack(fill=tk.X, pady=(0,5))
        if DND_BACKEND == 'tkdnd2':
            drop_label.drop_target_register(DND_FILES)
            drop_label.dnd_bind('<<Drop>>', self._handle_drop)
        else:
            drop_label.config(text="Перетащите файл или папку сюда\n(Установите TkinterDnD2 для DnD)")

        # Duplicate buttons
        tk.Button(frame, text="Выбрать файл", command=self.select_archive).pack(fill=tk.X, pady=(5,0))
        tk.Button(frame, text="Выбрать папку", command=self.select_folder).pack(fill=tk.X, pady=(0,5))

        # Counters
        counter_frame = tk.Frame(frame)
        counter_frame.pack(fill=tk.X, pady=(5,5))
        self.class_count_label = tk.Label(counter_frame, text="Классов: 0")
        self.class_count_label.pack(side=tk.LEFT, padx=(0,10))
        self.special_count_label = tk.Label(counter_frame, text="Спец. файлов: 0")
        self.special_count_label.pack(side=tk.LEFT)

        # Display label
        tk.Label(frame, text="Форматы файлов и уведомления:").pack(anchor=tk.W, pady=(10,0))

        # Scrollable text area
        if scrolledtext:
            self.text_display = scrolledtext.ScrolledText(frame, wrap='word', height=20)
            self.text_display.pack(fill=tk.BOTH, expand=True)
        else:
            txt_frame = tk.Frame(frame)
            txt_frame.pack(fill=tk.BOTH, expand=True)
            v_scroll = tk.Scrollbar(txt_frame, orient=tk.VERTICAL)
            h_scroll = tk.Scrollbar(txt_frame, orient=tk.HORIZONTAL)
            self.text_display = tk.Text(txt_frame, wrap='word',
                                       yscrollcommand=v_scroll.set,
                                       xscrollcommand=h_scroll.set)
            v_scroll.config(command=self.text_display.yview)
            h_scroll.config(command=self.text_display.xview)
            v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
            self.text_display.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Status label
        self.status_label = tk.Label(frame, text="Готов к работе", anchor=tk.W)
        self.status_label.pack(fill=tk.X, pady=(5,0))

        # Save report button
        tk.Button(frame, text="Сохранить отчет", command=self.save_report).pack(fill=tk.X, pady=(5,0))

    def _show_about(self):
        messagebox.showinfo("О программе", f"PaxoInsight {VERSION}\nАвтор: {AUTHOR}")

    def _handle_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self._process_path(paths[0])

    def select_archive(self):
        file = filedialog.askopenfilename(title="Выберите файл архива")
        if file:
            self._process_path(file)

    def select_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку для анализа")
        if folder:
            self._process_path(folder)

    def _get_extension(self, path):
        """Return the longest matching extension, checking all except '.gz' first, then '.gz' last."""
        lp = path.lower()
        # Combine supported and special extensions
        exts = list(SUPPORTED_FORMATS.keys()) + list(SPECIAL_EXTENSIONS)
        # Sort by length descending, excluding '.gz'
        exts = [e for e in exts if e != '.gz']
        exts.sort(key=len, reverse=True)
        # Check all except pure '.gz'
        for ext in exts:
            if lp.endswith(ext):
                return ext
        # Finally, check '.gz' if nothing else matched
        if lp.endswith('.gz'):
            return '.gz'
        # Fallback to simple splitext
        return os.path.splitext(path)[1].lower()

    def _process_path(self, path):
        self.status_label.config(text="Обработка...")
        self.path = path
        if os.path.isdir(path):
            self.extract_dir = path
            formats, classes, specials = self._scan_disk(path)
            self._update_display(formats, classes, specials, unpacked=set())
            self.status_label.config(text="Анализ завершён успешно")
        else:
            self.extract_dir = self._compute_extract_dir(path)
            thread = threading.Thread(target=self._extract_and_list, daemon=True)
            thread.start()

    def _compute_extract_dir(self, path):
        lp = path.lower()
        for ext in sorted(SUPPORTED_FORMATS.keys(), key=len, reverse=True):
            if lp.endswith(ext):
                return path[:-len(ext)] + "_extracted"
        return os.path.splitext(path)[0] + "_extracted"

    def _extract_and_list(self):
        """Extract archive and recursively unpack inner archives"""
        try:
            if os.path.isdir(self.extract_dir): shutil.rmtree(self.extract_dir)
            os.makedirs(self.extract_dir)

            ext = self._get_extension(self.path)
            # 7z extraction
            if ext == '.7z':
                self._extract_7z(self.path, self.extract_dir)
            # raw gzip
            elif ext == '.gz':
                gz_name = os.path.splitext(os.path.basename(self.path))[0]
                target = os.path.join(self.extract_dir, gz_name)
                with gzip.open(self.path, 'rb') as f_in, open(target, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            # zip-like
            elif ext in SPECIAL_EXTENSIONS:
                zf = self._open_zip(self.path); zf.extractall(self.extract_dir); zf.close()
            elif ext in SUPPORTED_FORMATS and ext != '.7z':
                if ext.startswith('.tar'):
                    self._extract_tar(self.path, self.extract_dir)
                else:
                    shutil.unpack_archive(self.path, self.extract_dir)
            else:
                raise ValueError(f"Неподдерживаемый формат: {ext}")
            os.remove(self.path)

            unpacked = set()
            self._recursive_unpack(self.extract_dir, 0, unpacked)

            formats, classes, specials = self._scan_disk(self.extract_dir)
            self.root.after(0, self._update_display, formats, classes, specials, unpacked)
            self.root.after(0, lambda: self.status_label.config(text="Распаковка завершена успешно"))
        except Exception as e:
            self.root.after(0, lambda: [self.status_label.config(text=f"Ошибка: {e}"), messagebox.showerror("Ошибка", str(e))])

    def _open_zip(self, path):
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

    def _extract_7z(self, path, dest):
        """Extract a .7z archive using py7zr library"""
        try:
            with py7zr.SevenZipFile(path, mode='r') as archive:
                archive.extractall(path=dest)
        except Exception as e:
            messagebox.showerror("Ошибка 7z", f"Не удалось распаковать {path}: {e}")

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
                iext = self._get_extension(full)
                try:
                    if iext == '.gz':
                        gz_name = os.path.splitext(f)[0]
                        target = os.path.join(root, gz_name)
                        with gzip.open(full, 'rb') as f_in, open(target, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                        unpacked.add(iext)
                        os.remove(full)
                        self._recursive_unpack(root, depth+1, unpacked)
                    elif iext == '.7z':
                        target = full[:-len(iext)]
                        self._extract_7z(full, target)
                        unpacked.add(iext)
                        os.remove(full)
                        self._recursive_unpack(target, depth+1, unpacked)
                    elif iext in SPECIAL_EXTENSIONS:
                        target = full[:-len(iext)]
                        zf = self._open_zip(full)
                        zf.extractall(target)
                        zf.close()
                        unpacked.add(iext)
                        os.remove(full)
                        self._recursive_unpack(target, depth+1, unpacked)
                    elif iext in SUPPORTED_FORMATS:
                        target = full[:-len(iext)]
                        if iext.startswith('.tar'):
                            self._extract_tar(full, target)
                        else:
                            shutil.unpack_archive(full, target)
                        unpacked.add(iext)
                        os.remove(full)
                        self._recursive_unpack(target, depth+1, unpacked)
                except Exception:
                    continue

    def _scan_disk(self, directory):
        exts, classes, specials = set(), [], []
        for root, _, files in os.walk(directory):
            if '__MACOSX' in root: continue
            for f in files:
                if f.startswith('._'): continue
                rel = os.path.relpath(os.path.join(root, f), directory)
                le = f.lower()
                if le.endswith(CLASS_EXTENSION): classes.append(rel)
                ext = self._get_extension(rel)
                if ext in SPECIAL_EXTENSIONS or ext == '.gz': specials.append(rel)
                if ext: exts.add(ext)
        return exts, classes, specials

    def _update_display(self, formats, classes, specials, unpacked):
        # Update counters
        self.class_count_label.config(text=f"Классов: {len(classes)}")
        self.special_count_label.config(text=f"Спец. файлов: {len(specials)}")
        # Update text area
        self.text_display.delete('1.0', tk.END)
        if classes:
            self.text_display.insert(tk.END, "Обнаружены .class-файлы:\n")
            for c in classes:
                self.text_display.insert(tk.END, f"  {c}\n")
            self.text_display.insert(tk.END, "\n")
        if specials:
            self.text_display.insert(tk.END, "Сборка кода/приложения:\n")
            for s in specials:
                tag = " (распакован)" if os.path.splitext(s)[1].lower() in unpacked else ""
                self.text_display.insert(tk.END, f"  {s}{tag}\n")
            self.text_display.insert(tk.END, "\n")
        others = sorted(formats - {os.path.splitext(x)[1].lower() for x in classes+specials})
        if others:
            self.text_display.insert(tk.END, "Обнаруженные форматы:\n")
            for ext in others:
                tags = []
                if ext in SPECIAL_EXTENSIONS: tags.append("спец.")
                if ext in unpacked: tags.append("распакован")
                tag_str = f" ({'; '.join(tags)})" if tags else ""
                self.text_display.insert(tk.END, f"  {ext}{tag_str}\n")

    def save_report(self):
        if not self.extract_dir or not os.path.isdir(self.extract_dir):
            messagebox.showwarning("Внимание", "Сначала распакируйте или анализируйте путь")
            return
        rpt = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text files','*.txt')], title='Сохранить отчет')
        if not rpt: return
        exts, classes, specials = self._scan_disk(self.extract_dir)
        with open(rpt, 'w', encoding='utf-8') as rf:
            rf.write("Отчет по файлам форматов: " + ", ".join(sorted(REPORT_EXTENSIONS)) + "\n\n")
            for c in classes: rf.write(f"{c} -> {CLASS_EXTENSION}\n")
            for s in specials: rf.write(f"{s} -> {os.path.splitext(s)[1].lower()}\n")
            for ext in sorted(exts):
                if ext not in REPORT_EXTENSIONS:
                    rf.write(f"* -> {ext}\n")
        messagebox.showinfo("Готово", f"Отчет сохранен: {rpt}")


def main():
    PaxoInsightApp()

if __name__ == "__main__":
    main()
