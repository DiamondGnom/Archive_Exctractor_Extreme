#!/usr/bin/env python3
"""
PaxoInsight 0.2.5: Cross-platform archive extractor without external dependencies
-------------------------------------------------------------------------------

PaxoInsight provides a graphical interface using Tkinter and optionally TkinterDnD2,
relying solely on Python's standard library to unpack archives or analyze folders.
It processes on selection or drag-and-drop, lists formats, highlights special files,
supports reporting, handles nested archives up to a depth, and supports Cyrillic
names on Windows via encoding fallbacks.
"""

import logging
import re
from pathlib import Path
import shutil
import gzip
import zipfile
import tarfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants and configuration
BASE_DIR = Path(__file__).parent / "reports"
BASE_DIR.mkdir(parents=True, exist_ok=True)
SAFE_FILENAME_REGEX = re.compile(r"[A-Za-z0-9._-]+$")

# Drag-and-drop support
DND_BACKEND = None
try:
    from TkinterDnD2 import TkinterDnD, DND_FILES
    DND_BACKEND = 'tkdnd2'
except ImportError as e:
    logger.warning(f"TkinterDnD2 backend (TkinterDnD2) not available: {e}")
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        DND_BACKEND = 'tkdnd2'
    except ImportError as e:
        logger.warning(f"TkinterDnD2 backend (tkinterdnd2) not available: {e}")

# Optional scrolled text
try:
    from tkinter import scrolledtext
except ImportError as e:
    logger.warning(f"ScrolledText widget unavailable: {e}")
    scrolledtext = None

# Supported and special formats
SUPPORTED_FORMATS = {
    '.zip': 'zip', '.tar': 'tar', '.tar.gz': 'gztar', '.tgz': 'gztar',
    '.tar.bz2': 'bztar', '.tbz2': 'bztar', '.tar.xz': 'xztar', '.txz': 'xztar'
}
SPECIAL_EXTENSIONS = {'.jar', '.war', '.exe', '.dll', '.apk', '.ipa', '.so'}
CLASS_EXTENSION = '.class'
REPORT_EXTENSIONS = SPECIAL_EXTENSIONS.union({CLASS_EXTENSION, '.tar.gz', '.tar.bz2', '.tar.xz', '.gz'})
MAX_DEPTH = 5
AUTHOR = 'DiamondGnom'
VERSION = '0.2.5'

# Safe extract utilities
def safe_extract_zip(zip_obj: zipfile.ZipFile, target_dir: Path):
    for member in zip_obj.namelist():
        member_path = (target_dir / member).resolve()
        if not str(member_path).startswith(str(target_dir.resolve())):
            raise SecurityError(f"Unsafe path in ZIP: {member}")
        member_path.parent.mkdir(parents=True, exist_ok=True)
        with zip_obj.open(member) as src, member_path.open('wb') as dst:
            shutil.copyfileobj(src, dst)


def safe_extract_tar(tar_obj: tarfile.TarFile, target_dir: Path):
    for member in tar_obj.getmembers():
        member_path = (target_dir / member.name).resolve()
        if not str(member_path).startswith(str(target_dir.resolve())):
            raise SecurityError(f"Unsafe path in TAR: {member.name}")
        tar_obj.extract(member, target_dir)

class PaxoInsightApp:
    def __init__(self):
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

        frame = tk.Frame(self.root, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        drop_label = tk.Label(frame, text="Перетащите файл или папку сюда",
                              relief=tk.RIDGE, height=3)
        drop_label.pack(fill=tk.X, pady=(0,5))
        if DND_BACKEND == 'tkdnd2':
            drop_label.drop_target_register(DND_FILES)
            drop_label.dnd_bind('<<Drop>>', self._handle_drop)
        else:
            drop_label.config(text="Перетащите файл или папку сюда\n(Установите TkinterDnD2 для DnD)")

        tk.Button(frame, text="Выбрать файл", command=self.select_archive).pack(fill=tk.X, pady=(5,0))
        tk.Button(frame, text="Выбрать папку", command=self.select_folder).pack(fill=tk.X, pady=(0,5))

        counter_frame = tk.Frame(frame)
        counter_frame.pack(fill=tk.X, pady=(5,5))
        self.class_count_label = tk.Label(counter_frame, text="Классов: 0")
        self.class_count_label.pack(side=tk.LEFT, padx=(0,10))
        self.special_count_label = tk.Label(counter_frame, text="Спец. файлов: 0")
        self.special_count_label.pack(side=tk.LEFT)

        tk.Label(frame, text="Форматы файлов и уведомления:").pack(anchor=tk.W, pady=(10,0))
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

        self.status_label = tk.Label(frame, text="Готов к работе", anchor=tk.W)
        self.status_label.pack(fill=tk.X, pady=(5,0))
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
        lp = path.lower()
        candidates = list(SUPPORTED_FORMATS.keys()) + list(SPECIAL_EXTENSIONS) + ['.gz']
        candidates.sort(key=len, reverse=True)
        for ext in candidates:
            if lp.endswith(ext):
                return ext
        return Path(path).suffix.lower()

    def _compute_extract_dir(self, path):
        ext = self._get_extension(path)
        base = Path(path)
        return str(base.with_suffix('')) + "_extracted" if not ext.startswith('.tar') else str(base.with_suffix('').with_suffix('')) + "_extracted"

    def _process_path(self, path):
        self.status_label.config(text="Обработка...")
        self.path = path
        if Path(path).is_dir():
            self.extract_dir = Path(path)
            formats, classes, specials = self._scan_disk(self.extract_dir)
            self._update_display(formats, classes, specials, unpacked=set())
            self.status_label.config(text="Анализ завершён успешно")
        else:
            self.extract_dir = Path(self._compute_extract_dir(path))
            threading.Thread(target=self._extract_and_list, daemon=True).start()

    def _extract_and_list(self):
        try:
            if self.extract_dir.exists(): shutil.rmtree(self.extract_dir)
            self.extract_dir.mkdir(parents=True)
            ext = self._get_extension(self.path)
            unpacked = set()

            if ext == '.gz':
                target_name = Path(self.path).stem
                if not SAFE_FILENAME_REGEX.fullmatch(target_name):
                    raise ValueError(f"Недопустимое имя извлекаемого файла: {target_name}")
                target_path = (self.extract_dir / target_name).resolve()
                if not str(target_path).startswith(str(self.extract_dir.resolve())):
                    raise SecurityError(f"Недопустимый путь: {target_name}")
                with gzip.open(self.path, 'rb') as gz_in, target_path.open('wb') as out:
                    shutil.copyfileobj(gz_in, out)
                unpacked.add(ext)
                Path(self.path).unlink()
                self._recursive_unpack(self.extract_dir, 0, unpacked)

            elif ext in SPECIAL_EXTENSIONS:
                with zipfile.ZipFile(self.path, 'r') as zf:
                    safe_extract_zip(zf, self.extract_dir)
                unpacked.add(ext)
                Path(self.path).unlink()
                self._recursive_unpack(self.extract_dir, 0, unpacked)

            elif ext in SUPPORTED_FORMATS:
                if ext.startswith('.tar'):
                    with tarfile.open(self.path, 'r:*') as tf:
                        safe_extract_tar(tf, self.extract_dir)
                else:
                    with zipfile.ZipFile(self.path, 'r') as zf:
                        safe_extract_zip(zf, self.extract_dir)
                unpacked.add(ext)
                Path(self.path).unlink()
                self._recursive_unpack(self.extract_dir, 0, unpacked)

            else:
                raise ValueError(f"Неподдерживаемый формат: {ext}")

            formats, classes, specials = self._scan_disk(self.extract_dir)
            self.root.after(0, self._update_display, formats, classes, specials, unpacked)
            self.root.after(0, lambda: self.status_label.config(text="Распаковка завершена успешно"))

        except Exception as e:
            logger.error(f"Ошибка при распаковке: {e}")
            self.root.after(0, lambda: self.status_label.config(text=f"Ошибка: {e}"))
            self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))

    def _recursive_unpack(self, directory: Path, depth: int, unpacked: set):
        if depth >= MAX_DEPTH:
            return
        for root, _, files in os.walk(directory):
            if '__MACOSX' in root:
                continue
            for f in files:
                if f.startswith('._'):
                    continue
                full = Path(root) / f
                iext = self._get_extension(str(full))
                if iext in SPECIAL_EXTENSIONS or iext in SUPPORTED_FORMATS or iext == '.gz':
                    target = full.with_suffix('')
                    try:
                        if iext == '.gz':
                            with gzip.open(full, 'rb') as gz_in, target.open('wb') as out:
                                shutil.copyfileobj(gz_in, out)
                        elif iext in SPECIAL_EXTENSIONS:
                            with zipfile.ZipFile(full, 'r') as zf:
                                safe_extract_zip(zf, target)
                        elif iext.startswith('.tar'):
                            with tarfile.open(full, 'r:*') as tf:
                                safe_extract_tar(tf, target)
                        else:
                            with zipfile.ZipFile(full, 'r') as zf:
                                safe_extract_zip(zf, target)
                        unpacked.add(iext)
                        full.unlink()
                        self._recursive_unpack(target, depth+1, unpacked)
                    except Exception as e:
                        logger.warning(f"Ошибка при рекурсивной распаковке {full}: {e}")
                        continue

    def _scan_disk(self, directory: Path):
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
                ext = self._get_extension(rel)
                if ext in SPECIAL_EXTENSIONS or ext == '.gz':
                    specials.append(rel)
                if ext:
                    exts.add(ext)
        return exts, classes, specials

    def _update_display(self, formats, classes, specials, unpacked):
        self.class_count_label.config(text=f"Классов: {len(classes)}")
        self.special_count_label.config(text=f"Спец. файлов: {len(specials)}")
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
                if ext in SPECIAL_EXTENSIONS:
                    tags.append("спец.")
                if ext in unpacked:
                    tags.append("распакован")
                tag_str = f" ({'; '.join(tags)})" if tags else ""
                self.text_display.insert(tk.END, f"  {ext}{tag_str}\n")

    def save_report(self):
        if not self.extract_dir or not self.extract_dir.is_dir():
            messagebox.showwarning("Внимание", "Сначала распакируйте или анализируйте путь")
            return
        rpt = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text files','*.txt')], title='Сохранить отчет')
        if not rpt:
            return
        rpt_path = Path(rpt)
        if not SAFE_FILENAME_REGEX.fullmatch(rpt_path.name):
            raise ValueError(f"Недопустимое имя файла отчета: {rpt_path.name}")
        with rpt_path.open('w', encoding='utf-8') as rf:
            rf.write("Отчет по файлам форматов: " + ", ".join(sorted(REPORT_EXTENSIONS)) + "\n\n")
            exts, classes, specials = self._scan_disk(self.extract_dir)
            for c in classes:
                rf.write(f"{c} -> {CLASS_EXTENSION}\n")
            for s in specials:
                rf.write(f"{s} -> {Path(s).suffix.lower()}\n")
            for ext in sorted(exts):
                if ext not in REPORT_EXTENSIONS:
                    rf.write(f"* -> {ext}\n")
        messagebox.showinfo("Готово", f"Отчет сохранен: {rpt_path}")

if __name__ == "__main__":
    PaxoInsightApp()
