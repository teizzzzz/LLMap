#!/usr/bin/env python3
"""Crop後の写真ファイル名から data.csv を再生成するGUIツール."""

import csv
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk


PHOTO_EXTS = {'.jpg', '.jpeg', '.png'}

DEFAULT_FIELDS = [
    'ImageID', 'SignID', '_status', '写真ID', '写真ファイル名', '全景写真ファイル名',
    '緯度', '経度', '採集日時', '名称', '主要言語', '補助言語', '装飾的言語',
    '来源類型', '言説類型', '状態', '設置主体', '担体類型', '多言語関係', '層状性',
    '時間性', '可読性', '視認等級', '想定受容者', '制作品質', '位置描述', '備考',
]

NAME_RE = re.compile(
    r'^(?P<area>[A-Z]{3})-(?P<date>\d{8})-(?P<num>\d{3})(?:-(?P<suffix>[A-Za-z]))?$'
)


def parse_photo(path):
    match = NAME_RE.match(path.stem)
    if not match:
        return None
    data = match.groupdict()
    suffix = data.get('suffix')
    photo_id = f"{data['area']}-{data['date']}-{data['num']}"
    return {
        'path': path,
        'area': data['area'],
        'date': data['date'],
        'num': data['num'],
        'num_int': int(data['num']),
        'suffix': suffix.lower() if suffix else None,
        'photo_id': photo_id,
        'is_crop': bool(suffix),
    }


def load_reference_csv(csv_path):
    if not csv_path or not Path(csv_path).exists():
        return DEFAULT_FIELDS[:], {}, {}, {}

    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames or DEFAULT_FIELDS[:]

    for field in DEFAULT_FIELDS:
        if field not in headers:
            headers.append(field)

    by_file = {}
    by_photo_id = {}
    by_sign_id = {}
    for row in rows:
        if row.get('写真ファイル名'):
            by_file[row['写真ファイル名']] = row
        if row.get('写真ID') and row['写真ID'] not in by_photo_id:
            by_photo_id[row['写真ID']] = row
        if row.get('SignID'):
            by_sign_id[row['SignID']] = row

    return headers, by_file, by_photo_id, by_sign_id


def collect_photo_groups(photos_dir):
    groups = {}
    ignored = []
    for path in sorted(Path(photos_dir).iterdir()):
        if not path.is_file() or path.suffix.lower() not in PHOTO_EXTS:
            continue
        info = parse_photo(path)
        if not info:
            ignored.append(path.name)
            continue
        group = groups.setdefault(info['photo_id'], {
            'area': info['area'],
            'date': info['date'],
            'num': info['num'],
            'num_int': info['num_int'],
            'panorama': None,
            'crops': [],
        })
        if info['is_crop']:
            group['crops'].append(info)
        else:
            group['panorama'] = info

    ordered = sorted(groups.values(), key=lambda g: (g['area'], g['date'], g['num_int']))
    for group in ordered:
        group['crops'].sort(key=lambda item: item['suffix'])
    return ordered, ignored


def build_rows(photos_dir, reference_csv=None):
    headers, by_file, by_photo_id, by_sign_id = load_reference_csv(reference_csv)
    groups, ignored = collect_photo_groups(photos_dir)

    rows = []
    stats = {
        'groups': len(groups),
        'panorama_kept': 0,
        'panorama_replaced': 0,
        'crop_rows': 0,
        'ignored': ignored,
    }

    for group in groups:
        photo_id = f"{group['area']}-{group['date']}-{group['num']}"
        panorama_file = group['panorama']['path'].name if group['panorama'] else f"{photo_id}.jpg"
        source_row = by_photo_id.get(photo_id) or by_file.get(panorama_file) or {}

        if group['crops']:
            stats['panorama_replaced'] += 1
            targets = group['crops']
        elif group['panorama']:
            stats['panorama_kept'] += 1
            targets = [group['panorama']]
        else:
            targets = []

        for item in targets:
            suffix = item['suffix'] or 'a'
            sign_id = f"{group['area']}-S{group['num']}-{suffix}"
            exact = by_file.get(item['path'].name) or by_sign_id.get(sign_id)
            row = {field: '' for field in headers}

            if exact:
                row.update(exact)
            elif item['is_crop']:
                for field in ('緯度', '経度', '採集日時'):
                    row[field] = source_row.get(field, '')
            else:
                row.update(source_row)

            row['SignID'] = sign_id
            row['_status'] = row.get('_status') or 'pending'
            row['写真ID'] = photo_id
            row['写真ファイル名'] = item['path'].name
            row['全景写真ファイル名'] = panorama_file if item['is_crop'] else ''
            rows.append(row)
            if item['is_crop']:
                stats['crop_rows'] += 1

    for idx, row in enumerate(rows, start=1):
        area = str(row.get('SignID', 'UNK'))[:3] or 'UNK'
        row['ImageID'] = f"{area}{idx:05d}"

    return headers, rows, stats


def write_csv(output_path, headers, rows):
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


class RebuildGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Crop後 data.csv 再生成")
        self.geometry("780x640")
        self.minsize(720, 580)
        self.configure(bg='#f5f2ed')

        base = Path(__file__).resolve().parent
        self.photos_path = tk.StringVar(value=str(base / 'photos'))
        self.reference_csv = tk.StringVar(value=str(base / 'data.csv'))
        self.output_csv = tk.StringVar(value=str(base / 'data.csv'))
        self.last_output = None
        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TFrame', background='#f5f2ed')
        style.configure('TLabel', background='#f5f2ed', font=('Arial', 10))
        style.configure('TLabelframe', background='#f5f2ed')
        style.configure('TLabelframe.Label', background='#f5f2ed', font=('Arial', 11, 'bold'))
        style.configure('TButton', font=('Arial', 10), padding=5)
        style.configure('Run.TButton', font=('Arial', 12, 'bold'), padding=9,
                        background='#c84b31', foreground='white')
        style.map('Run.TButton', background=[('active', '#a83928')])

        top = tk.Frame(self, bg='#1a1a1a', height=58)
        top.pack(fill='x')
        top.pack_propagate(False)
        tk.Label(top, text="Crop後 data.csv 再生成", bg='#1a1a1a', fg='white',
                 font=('Arial', 16, 'bold')).pack(side='left', padx=18, pady=14)
        tk.Label(top, text="photos のファイル名から再構築", bg='#1a1a1a', fg='#aaa',
                 font=('Arial', 10)).pack(side='left', pady=18)

        path_frame = ttk.LabelFrame(self, text="  入出力  ", padding=10)
        path_frame.pack(fill='x', padx=14, pady=(12, 6))
        self._path_row(path_frame, "写真フォルダ", self.photos_path, self._browse_photos)
        self._path_row(path_frame, "参照CSV", self.reference_csv, self._browse_reference)
        self._path_row(path_frame, "出力CSV", self.output_csv, self._browse_output)

        note = ttk.LabelFrame(self, text="  生成ルール  ", padding=10)
        note.pack(fill='x', padx=14, pady=6)
        ttk.Label(note, text="HAS-20260531-010.jpg → HAS-S010-a").pack(anchor='w')
        ttk.Label(note, text="HAS-20260531-010-a.jpg / -b.jpg がある場合、全景行は出さず crop 行だけ作ります").pack(anchor='w')
        ttk.Label(note, text="緯度・経度・採集日時は参照CSVの同じ 写真ID から引き継ぎます",
                  foreground='#666').pack(anchor='w')

        action = ttk.Frame(self)
        action.pack(fill='x', padx=14, pady=8)
        self.preview_btn = ttk.Button(action, text="プレビュー", command=lambda: self._start(preview=True))
        self.preview_btn.pack(side='left')
        self.run_btn = ttk.Button(action, text="▶ data.csv 再生成",
                                  style='Run.TButton', command=lambda: self._start(preview=False))
        self.run_btn.pack(side='left', padx=8)
        self.open_btn = ttk.Button(action, text="出力フォルダを開く",
                                   command=self._open_output_folder, state='disabled')
        self.open_btn.pack(side='right')

        log_frame = ttk.LabelFrame(self, text="  ログ  ", padding=8)
        log_frame.pack(fill='both', expand=True, padx=14, pady=(0, 12))
        self.log = scrolledtext.ScrolledText(log_frame, font=('Consolas', 10),
                                             bg='#1a1a1a', fg='#e6e6e6',
                                             insertbackground='white', relief='flat',
                                             state='disabled')
        self.log.pack(fill='both', expand=True)

    def _path_row(self, parent, label, var, command):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text=label, width=12).pack(side='left')
        ttk.Entry(row, textvariable=var, font=('Arial', 10)).pack(
            side='left', fill='x', expand=True, padx=(4, 8))
        ttk.Button(row, text="選択", command=command).pack(side='left')

    def _browse_photos(self):
        path = filedialog.askdirectory()
        if path:
            self.photos_path.set(path)

    def _browse_reference(self):
        path = filedialog.askopenfilename(filetypes=[('CSV', '*.csv')])
        if path:
            self.reference_csv.set(path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if path:
            self.output_csv.set(path)

    def _log(self, message):
        self.log.config(state='normal')
        self.log.insert('end', message + '\n')
        self.log.see('end')
        self.log.config(state='disabled')

    def _start(self, preview):
        photos = Path(self.photos_path.get().strip())
        output = Path(self.output_csv.get().strip())
        if not photos.exists():
            messagebox.showwarning("未設定", "写真フォルダが見つかりません")
            return
        if not output.name:
            messagebox.showwarning("未設定", "出力CSVを指定してください")
            return
        if not preview and output.exists():
            ok = messagebox.askyesno(
                "確認",
                f"{output.name} を更新します。\n実行前に backup CSV を作成します。\n続行しますか？")
            if not ok:
                return

        self.preview_btn.config(state='disabled')
        self.run_btn.config(state='disabled')
        threading.Thread(target=self._run, args=(preview,), daemon=True).start()

    def _run(self, preview):
        try:
            photos = Path(self.photos_path.get().strip())
            reference = self.reference_csv.get().strip()
            output = Path(self.output_csv.get().strip())
            headers, rows, stats = build_rows(photos, reference)

            lines = [
                f"[写真フォルダ] {photos}",
                f"[参照CSV] {reference or '(なし)'}",
                f"[出力CSV] {output}",
                f"[集計] 写真ID: {stats['groups']} / 全景のまま: {stats['panorama_kept']} / crop置換: {stats['panorama_replaced']} / crop行: {stats['crop_rows']}",
                f"[生成予定] {len(rows)} 行",
            ]
            if stats['ignored']:
                preview_names = ', '.join(stats['ignored'][:10])
                suffix = ' ...' if len(stats['ignored']) > 10 else ''
                lines.append(f"[対象外] {len(stats['ignored'])} 件: {preview_names}{suffix}")

            if preview:
                lines.append("[プレビュー完了] CSVはまだ書き換えていません")
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists():
                    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                    backup = output.with_name(f"{output.stem}_backup_before_rebuild_{stamp}{output.suffix}")
                    shutil.copy2(output, backup)
                    lines.append(f"[バックアップ] {backup}")
                write_csv(output, headers, rows)
                self.last_output = output
                lines.append("[完了] data.csv を再生成しました")

            self.after(0, lambda: self._finish('\n'.join(lines), preview))
        except Exception as exc:
            message = str(exc)
            self.after(0, lambda msg=message: self._fail(msg))

    def _finish(self, text, preview):
        self._log(text)
        self._log("")
        self.preview_btn.config(state='normal')
        self.run_btn.config(state='normal')
        if not preview:
            self.open_btn.config(state='normal')
            messagebox.showinfo("完了", "data.csv の再生成が完了しました")

    def _fail(self, text):
        self._log("[エラー] " + text)
        self.preview_btn.config(state='normal')
        self.run_btn.config(state='normal')
        messagebox.showerror("エラー", text)

    def _open_output_folder(self):
        target = self.last_output or Path(self.output_csv.get().strip())
        folder = Path(target).parent
        if sys.platform == 'win32':
            os.startfile(str(folder))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(folder)])
        else:
            subprocess.run(['xdg-open', str(folder)])


if __name__ == '__main__':
    RebuildGui().mainloop()
