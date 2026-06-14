#!/usr/bin/env python3
"""
言語景観 写真リネームツール（GUI版）
ダブルクリックで起動できます
"""

import sys
import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime
import csv

def check_and_install(packages):
    for pkg in packages:
        mod = pkg.replace('-','_').lower()
        if mod == 'pillow': mod = 'PIL'
        try:
            __import__(mod)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

check_and_install(['Pillow', 'piexif'])

from PIL import Image
import piexif

HEIC_AVAILABLE = False
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    pass

# ── GPS変換 ──
def dms_to_decimal(dms, ref):
    try:
        d = dms[0][0]/dms[0][1]; m = dms[1][0]/dms[1][1]; s = dms[2][0]/dms[2][1]
        dec = d + m/60 + s/3600
        if ref in ['S','W']: dec = -dec
        return round(dec, 7)
    except: return None

def extract_exif(path):
    r = {'datetime':None,'lat':None,'lng':None}
    try:
        img = Image.open(path)
        raw = img.info.get('exif')
        if not raw: return r
        exif = piexif.load(raw)
        dt = exif.get('Exif',{}).get(piexif.ExifIFD.DateTimeOriginal)
        if dt: r['datetime'] = dt.decode('utf-8', errors='ignore')
        gps = exif.get('GPS',{})
        if gps:
            ld=gps.get(piexif.GPSIFD.GPSLatitude); lr=gps.get(piexif.GPSIFD.GPSLatitudeRef)
            nd=gps.get(piexif.GPSIFD.GPSLongitude); nr=gps.get(piexif.GPSIFD.GPSLongitudeRef)
            if ld and lr and nd and nr:
                lr = lr.decode() if isinstance(lr,bytes) else lr
                nr = nr.decode() if isinstance(nr,bytes) else nr
                r['lat'] = dms_to_decimal(ld,lr); r['lng'] = dms_to_decimal(nd,nr)
    except: pass
    return r

# ────────────────────────────────
# GUI
# ────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("言語景観 写真リネームツール")
        self.geometry("700x700")
        self.minsize(600, 600)
        self.configure(bg='#f5f2ed')

        _base = Path(sys.argv[0]).parent.resolve()
        self.input_path  = tk.StringVar(value=str(_base / 'photos') if (_base / 'photos').exists() else '')
        self.output_path = tk.StringVar()
        self.area_code   = tk.StringVar(value='HAS')
        self.dry_run     = tk.BooleanVar(value=True)
        self.out_path    = None

        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TLabel',      background='#f5f2ed', font=('Arial',11))
        style.configure('TButton',     font=('Arial',11), padding=6)
        style.configure('TEntry',      font=('Arial',11), padding=4)
        style.configure('TFrame',      background='#f5f2ed')
        style.configure('TLabelframe', background='#f5f2ed')
        style.configure('TLabelframe.Label', background='#f5f2ed', font=('Arial',11,'bold'))
        style.configure('TCheckbutton', background='#f5f2ed', font=('Arial',11))
        style.configure('TProgressbar', troughcolor='#e0dbd3', background='#27ae60')
        style.configure('Run.TButton', font=('Arial',12,'bold'), padding=10,
                        background='#c84b31', foreground='white')
        style.map('Run.TButton', background=[('active','#a83928')])

        pad = {'padx':14, 'pady':5}

        # ── 入力フォルダ ──
        in_frame = ttk.LabelFrame(self, text="  📂 入力：写真フォルダ  ", padding=10)
        in_frame.pack(fill='x', **pad)
        r = ttk.Frame(in_frame); r.pack(fill='x')
        ttk.Label(r, text="フォルダ:").pack(side='left')
        ttk.Entry(r, textvariable=self.input_path,
                  font=('Arial',10)).pack(side='left', fill='x', expand=True, padx=(6,6))
        ttk.Button(r, text="選択", width=5,
                   command=lambda: self._browse_dir(self.input_path)).pack(side='left')

        if not HEIC_AVAILABLE:
            ttk.Label(in_frame,
                text="⚠️  HEICを変換するには: pip install pillow-heif",
                foreground='#856404', font=('Arial',10)).pack(anchor='w', pady=(4,0))

        # ── 出力フォルダ ──
        out_frame = ttk.LabelFrame(self, text="  💾 出力：保存先フォルダ  ", padding=10)
        out_frame.pack(fill='x', **pad)
        r2 = ttk.Frame(out_frame); r2.pack(fill='x')
        ttk.Label(r2, text="フォルダ:").pack(side='left')
        ttk.Entry(r2, textvariable=self.output_path,
                  font=('Arial',10)).pack(side='left', fill='x', expand=True, padx=(6,6))
        ttk.Button(r2, text="選択", width=5,
                   command=lambda: self._browse_dir(self.output_path)).pack(side='left')
        ttk.Label(out_frame,
                  text="※ 空欄の場合は入力フォルダと同じ場所に「フォルダ名_renamed」を作成します",
                  foreground='#888', font=('Arial',9)).pack(anchor='w', pady=(4,0))

        # ── 設定 ──
        cfg_frame = ttk.LabelFrame(self, text="  ⚙️ 設定  ", padding=10)
        cfg_frame.pack(fill='x', **pad)

        area_row = ttk.Frame(cfg_frame); area_row.pack(fill='x', pady=(0,6))
        ttk.Label(area_row, text="エリアコード:").pack(side='left')
        ttk.Entry(area_row, textvariable=self.area_code,
                  width=8, font=('Arial',12,'bold')).pack(side='left', padx=(6,14))
        ttk.Label(area_row, text="プリセット:").pack(side='left')
        for code, label in [('HAS','橋本'),('YKH','横浜中華街'),('SKO','新大久保')]:
            ttk.Button(area_row, text=label, width=9,
                       command=lambda c=code: self.area_code.set(c)).pack(side='left', padx=2)

        self.preview_lbl = ttk.Label(cfg_frame, text='', foreground='#2980b9', font=('Arial',10))
        self.preview_lbl.pack(anchor='w', pady=(0,4))
        self._upd_preview()
        self.area_code.trace_add('write', lambda *_: self._upd_preview())

        ttk.Checkbutton(cfg_frame,
                        text="プレビューモード（確認のみ・ファイルを変更しない）",
                        variable=self.dry_run).pack(anchor='w')

        # ── 進捗 ──
        prog_frame = ttk.LabelFrame(self, text="  📊 進捗  ", padding=10)
        prog_frame.pack(fill='x', **pad)
        self.progress = ttk.Progressbar(prog_frame, mode='determinate')
        self.progress.pack(fill='x', pady=(0,4))
        self.prog_lbl = ttk.Label(prog_frame, text="待機中", foreground='#888', font=('Arial',10))
        self.prog_lbl.pack(anchor='w')

        # ── ボタン（ログより上に固定）──
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill='x', padx=14, pady=6)

        self.run_btn = ttk.Button(btn_frame, text="▶  実行",
                                   style='Run.TButton', command=self._start)
        self.run_btn.pack(side='left', ipadx=10)

        ttk.Label(btn_frame,
                  text="← まずプレビューで確認 → チェックを外して本実行",
                  foreground='#666', font=('Arial',10)).pack(side='left', padx=12)

        self.open_btn = ttk.Button(btn_frame, text="📂 出力フォルダを開く",
                                    command=self._open_output, state='disabled')
        self.open_btn.pack(side='right')

        # ── ログ ──
        log_frame = ttk.LabelFrame(self, text="  📋 ログ  ", padding=8)
        log_frame.pack(fill='both', expand=True, padx=14, pady=(0,12))

        self.log = scrolledtext.ScrolledText(
            log_frame, font=('Courier',10),
            bg='#1a1a1a', fg='#e0e0e0', insertbackground='white',
            relief='flat', state='disabled')
        self.log.pack(fill='both', expand=True)

    def _browse_dir(self, var):
        p = filedialog.askdirectory()
        if p: var.set(p)

    def _upd_preview(self):
        code  = self.area_code.get() or 'HAS'
        today = datetime.now().strftime('%Y%m%d')
        self.preview_lbl.config(
            text=f"ファイル名プレビュー:  {code}-{today}-001.jpg  {code}-{today}-002.jpg  ...")

    def _log(self, msg, color=None):
        self.log.config(state='normal')
        tag = None
        if color:
            tag = f'c{color.replace("#","")}'
            self.log.tag_config(tag, foreground=color)
        self.log.insert('end', msg+'\n', tag)
        self.log.see('end')
        self.log.config(state='disabled')

    def _start(self):
        if not self.input_path.get():
            messagebox.showwarning("未設定", "写真フォルダを選択してください")
            return
        if not self.area_code.get().strip():
            messagebox.showwarning("未設定", "エリアコードを入力してください")
            return
        self.run_btn.config(state='disabled')
        self.open_btn.config(state='disabled')
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            input_p = Path(self.input_path.get())
            area    = self.area_code.get().strip().upper()
            dry     = self.dry_run.get()

            # 出力フォルダ決定
            if self.output_path.get().strip():
                out_p = Path(self.output_path.get().strip())
            else:
                out_p = input_p.parent / (input_p.name + '_renamed')
            photos_p = out_p / 'photos'

            self._log(f"📂 入力: {input_p}")
            self._log(f"💾 出力: {out_p}")
            self._log(f"🏷  エリア: {area}")
            self._log(f"{'🔍 プレビューモード' if dry else '✏️  本実行モード'}")
            self._log("")

            if not dry:
                photos_p.mkdir(parents=True, exist_ok=True)
                thumbs_p = out_p / 'thumbs'
                thumbs_p.mkdir(parents=True, exist_ok=True)
            else:
                thumbs_p = out_p / 'thumbs'

            exts  = {'.jpg','.jpeg','.png','.heic','.heif'}
            files = [f for f in input_p.iterdir()
                     if f.suffix.lower() in exts and f.is_file()]

            if not files:
                self._log("❌ 対象ファイルが見つかりません", '#c84b31')
                return

            heic = [f for f in files if f.suffix.lower() in {'.heic','.heif'}]
            if heic and not HEIC_AVAILABLE:
                self._log(f"⚠️  HEIC {len(heic)}枚はスキップ", '#f39c12')
                files = [f for f in files if f.suffix.lower() not in {'.heic','.heif'}]

            self._log(f"📷 {len(files)} 枚を処理します\n")
            self.progress['maximum'] = len(files)

            # Exif & ソート
            file_info = []
            for f in files:
                exif = extract_exif(f)
                dt   = None
                if exif['datetime']:
                    for fmt in ['%Y:%m:%d %H:%M:%S','%Y-%m-%d %H:%M:%S']:
                        try: dt = datetime.strptime(exif['datetime'], fmt); break
                        except: pass
                if dt is None:
                    dt = datetime.fromtimestamp(f.stat().st_mtime)
                    self._log(f"  ⚠️  {f.name}: Exifなし → 更新日時を使用", '#f39c12')
                file_info.append({'path':f,'datetime':dt,'lat':exif['lat'],'lng':exif['lng']})

            file_info.sort(key=lambda x: x['datetime'])

            csv_rows = []
            for i, info in enumerate(file_info, 1):
                date_str = info['datetime'].strftime('%Y%m%d')
                photo_id = f"{area}-{date_str}-{i:03d}"
                new_name = f"{photo_id}.jpg"
                out_file = photos_p / new_name
                dt_disp  = info['datetime'].strftime('%Y-%m-%d %H:%M:%S')
                lat = info['lat'] if info['lat'] is not None else ''
                lng = info['lng'] if info['lng'] is not None else ''
                gps = f"{lat},{lng}" if lat and lng else "GPS なし"

                col = None if dry else '#27ae60'
                self._log(f"  {'[DRY]' if dry else '✅'} "
                          f"{info['path'].name:28s} → {new_name}  {gps}", col)

                if not dry:
                    try:
                        img = Image.open(info['path'])
                        # Exifの回転情報を適用（縦向き写真が横にならないよう）
                        try:
                            import piexif
                            exif_data = img.info.get('exif')
                            if exif_data:
                                exif = piexif.load(exif_data)
                                orientation = exif.get('0th', {}).get(piexif.ImageIFD.Orientation, 1)
                                rotation_map = {3: 180, 6: 270, 8: 90}
                                if orientation in rotation_map:
                                    img = img.rotate(rotation_map[orientation], expand=True)
                        except:
                            pass
                        if img.mode != 'RGB': img = img.convert('RGB')
                        img.save(out_file, 'JPEG', quality=92)
                        # サムネイル生成（Web表示用）
                        thumb = img.copy()
                        tw, th = thumb.size
                        if max(tw, th) > 800:
                            r = 800 / max(tw, th)
                            thumb = thumb.resize((int(tw*r), int(th*r)), Image.LANCZOS)
                        thumb.save(thumbs_p / new_name, 'JPEG', quality=80)
                    except Exception as e:
                        self._log(f"     ❌ {e}", '#c84b31'); continue

                csv_rows.append({
                    'ImageID':          f"{area}{i:05d}",  # 例: HAS00001
                    'SignID':           f"{area}-S{i:03d}-a",
                    '_status':          'pending',
                    '写真ID':           photo_id,
                    '写真ファイル名':    new_name,
                    '全景写真ファイル名': '',
                    '緯度': lat, '経度': lng, '採集日時': dt_disp,
                    # コア層
                    '名称':       '',
                    '主要言語':   '',
                    '補助言語':   '',
                    '装飾的言語': '',
                    '来源類型':   '',
                    '言説類型':   '',
                    '状態':       '',
                    # 分析層
                    '設置主体':   '',
                    '担体類型':   '',
                    '多言語関係': '',
                    '層状性':     '',
                    # 現場層（人間が記録）
                    '時間性':     '',
                    '可読性':     '',
                    '視認等級':   '',
                    '想定受容者': '',
                    '制作品質':   '',
                    '位置描述':   '',
                    '備考':       '',
                })
                self.progress['value'] = i
                self.prog_lbl.config(text=f"{i} / {len(file_info)}  —  {new_name}")

            if csv_rows and not dry:
                csv_path = out_p / 'data.csv'
                with open(csv_path,'w',newline='',encoding='utf-8-sig') as f:
                    w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
                    w.writeheader(); w.writerows(csv_rows)
                self.out_path = out_p
                self._log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━", '#888')
                self._log(f"✅ 完了！  {len(csv_rows)} 枚", '#27ae60')
                self._log(f"📁 写真:  {photos_p}", '#2980b9')
                self._log(f"📄 CSV:   {csv_path}", '#2980b9')
                self._log("━━━━━━━━━━━━━━━━━━━━━━━━━━", '#888')
                self.open_btn.config(state='normal')
            elif dry:
                self._log("\n🔍 プレビュー完了", '#2980b9')
                self._log("問題なければチェックを外して再実行してください")

            self.prog_lbl.config(text="完了")

        except Exception as e:
            self._log(f"\n❌ エラー: {e}", '#c84b31')
        finally:
            self.run_btn.config(state='normal')

    def _open_output(self):
        if self.out_path and self.out_path.exists():
            import platform
            if platform.system() == 'Windows':
                os.startfile(str(self.out_path))
            elif platform.system() == 'Darwin':
                subprocess.run(['open', str(self.out_path)])
            else:
                subprocess.run(['xdg-open', str(self.out_path)])

if __name__ == '__main__':
    app = App()
    app.mainloop()
