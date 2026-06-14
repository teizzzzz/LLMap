#!/usr/bin/env python3
"""
CSVマージツール
===============
機能:
  - data.csvの全景行を自動削除（クロップが存在する場合）
  - crop_rows.csvの行を追記
  - ImageIDを自動採番
  - data_merged.csvとして出力

使い方:
  python csv_merge.py --data data.csv --crop HAS-20260531-003_crop_rows.csv --photos photos/
  python csv_merge.py --data data.csv --crop *.csv --photos photos/  # 複数クロップCSV
"""

import sys
import os
import glob
import argparse
import io
import shutil
import subprocess
import threading
import contextlib
from pathlib import Path
from datetime import datetime

def check_and_install(packages):
    import subprocess
    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

check_and_install(['pandas'])
import pandas as pd

def is_crop_photo_file(photo_file):
    stem = Path(str(photo_file)).stem
    parts = stem.split('-')
    return len(parts) > 1 and len(parts[-1]) == 1 and parts[-1].isalpha()

def has_crop(photo_file, photos_dir):
    """全景写真に対応するクロップが存在するか確認"""
    stem = Path(photo_file).stem
    if is_crop_photo_file(photo_file):
        return False  # 自分自身がクロップ
    # クロップが存在するか確認
    return any(
        f.stem.startswith(stem + '-') and
        len(f.stem.split('-')[-1]) == 1 and
        f.stem.split('-')[-1].isalpha()
        for f in Path(photos_dir).iterdir()
        if f.suffix.lower() in {'.jpg','.jpeg','.png'}
    )

def merge(data_csv, crop_csvs, photos_dir, output_csv):
    # data.csv読み込み
    df = pd.read_csv(data_csv, encoding='utf-8-sig', dtype=str).fillna('')
    source_df = df.copy()
    print(f"[読み込み] data.csv: {len(df)}件")

    # クロップCSVを先に読み込み、対応する全景行も削除対象にする。
    # photos/ にクロップ画像がまだ移動されていない場合でも、CSVだけで安全に置き換えられる。
    crop_dfs = []
    crop_photo_ids = set()
    crop_panorama_files = set()
    for crop_csv in crop_csvs:
        if not Path(crop_csv).exists():
            print(f"[警告] {crop_csv} が見つかりません")
            continue
        crop_df = pd.read_csv(crop_csv, encoding='utf-8-sig', dtype=str).fillna('')
        if '写真ID' in crop_df.columns:
            crop_photo_ids.update(v for v in crop_df['写真ID'].astype(str).str.strip() if v)
        if '全景写真ファイル名' in crop_df.columns:
            crop_panorama_files.update(v for v in crop_df['全景写真ファイル名'].astype(str).str.strip() if v)
        crop_df = inherit_panorama_fields(crop_df, source_df)
        print(f"[追記] {Path(crop_csv).name}: {len(crop_df)}件")
        crop_dfs.append(crop_df)

    # クロップが存在する全景行を削除
    def should_remove_panorama(row):
        photo_file = row.get('写真ファイル名', '')
        if is_crop_photo_file(photo_file):
            return False
        photo_id = str(row.get('写真ID', '')).strip() or Path(photo_file).stem
        return (
            has_crop(photo_file, photos_dir)
            or photo_id in crop_photo_ids
            or str(photo_file).strip() in crop_panorama_files
        )

    if '写真ファイル名' not in df.columns:
        raise ValueError("data.csv に「写真ファイル名」列がありません")
    skip_mask = df.apply(should_remove_panorama, axis=1)
    skipped = df[skip_mask]
    df = df[~skip_mask]
    if len(skipped) > 0:
        print(f"[削除] クロップが存在する全景行: {len(skipped)}件")
        for _, row in skipped.iterrows():
            print(f"  - {row['写真ファイル名']}")

    if crop_dfs:
        all_crops = pd.concat(crop_dfs, ignore_index=True)
        # 列を揃える。crop側だけにある標準列も落とさない。
        all_columns = list(df.columns) + [col for col in all_crops.columns if col not in df.columns]
        for col in all_columns:
            if col not in df.columns:
                df[col] = ''
            if col not in all_crops.columns:
                all_crops[col] = ''
        df = df[all_columns]
        all_crops = all_crops[all_columns]
        df = pd.concat([df, all_crops], ignore_index=True)

    # ImageIDを再採番（エリアコードを保持）
    if 'ImageID' in df.columns:
        # エリアコードを取得
        def renum_id(row, idx):
            area = str(row.get('SignID', 'UNK'))[:3]
            return f"{area}{idx+1:05d}"
        df['ImageID'] = [renum_id(row, i) for i, (_, row) in enumerate(df.iterrows())]

    # 出力
    df.to_csv(output_csv, index=False, encoding='utf-8-sig')
    print(f"\n[完了] 出力: {output_csv}  合計: {len(df)}件")
    return df

def inherit_panorama_fields(crop_df, source_df):
    """クロップ行に全景写真の位置・日時を引き継ぐ。"""
    if '写真ID' not in crop_df.columns or '写真ID' not in source_df.columns:
        return crop_df

    lookup = source_df.drop_duplicates('写真ID').set_index('写真ID')
    inherit_cols = ['緯度', '経度', '採集日時']

    for idx, row in crop_df.iterrows():
        photo_id = row.get('写真ID', '')
        if photo_id not in lookup.index:
            continue
        source = lookup.loc[photo_id]
        for col in inherit_cols:
            if col in crop_df.columns and not str(crop_df.at[idx, col]).strip():
                crop_df.at[idx, col] = source.get(col, '')
        if '全景写真ファイル名' in crop_df.columns and not str(crop_df.at[idx, '全景写真ファイル名']).strip():
            crop_df.at[idx, '全景写真ファイル名'] = source.get('写真ファイル名', '')

    return crop_df

def expand_crop_paths(crop_csvs):
    expanded = []
    for c in crop_csvs:
        matches = glob.glob(c)
        expanded.extend(matches or [c])
    return expanded

def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    class MergeGui(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("CSVマージツール")
            self.geometry("760x620")
            self.minsize(700, 560)
            self.configure(bg='#f5f2ed')

            base = Path(__file__).resolve().parent
            self.data_path = tk.StringVar(value=str(base / 'data.csv'))
            self.photos_path = tk.StringVar(value=str(base / 'photos'))
            self.output_mode = tk.StringVar(value='overwrite')
            self.output_path = tk.StringVar(value=str(base / 'data_merged.csv'))
            self.crop_paths = []
            self.last_output = None

            self._build_ui()
            self._auto_detect_crop_csvs()

        def _build_ui(self):
            style = ttk.Style(self)
            style.theme_use('clam')
            style.configure('TFrame', background='#f5f2ed')
            style.configure('TLabel', background='#f5f2ed', font=('Arial', 10))
            style.configure('TLabelframe', background='#f5f2ed')
            style.configure('TLabelframe.Label', background='#f5f2ed', font=('Arial', 11, 'bold'))
            style.configure('TButton', font=('Arial', 10), padding=5)
            style.configure('Run.TButton', font=('Arial', 12, 'bold'), padding=9,
                            background='#27ae60', foreground='white')
            style.map('Run.TButton', background=[('active', '#219653')])

            top = tk.Frame(self, bg='#1a1a1a', height=58)
            top.pack(fill='x')
            top.pack_propagate(False)
            tk.Label(top, text="CSVマージ", bg='#1a1a1a', fg='white',
                     font=('Arial', 16, 'bold')).pack(side='left', padx=18, pady=14)
            tk.Label(top, text="crop CSV → data.csv", bg='#1a1a1a', fg='#aaa',
                     font=('Arial', 10)).pack(side='left', pady=18)

            file_frame = ttk.LabelFrame(self, text="  入力  ", padding=10)
            file_frame.pack(fill='x', padx=14, pady=(12, 6))
            self._path_row(file_frame, "元CSV", self.data_path,
                           lambda: self._browse_file(self.data_path, [('CSV', '*.csv')]))
            self._path_row(file_frame, "写真フォルダ", self.photos_path,
                           lambda: self._browse_dir(self.photos_path))

            crop_frame = ttk.LabelFrame(self, text="  crop CSV（複数可）  ", padding=10)
            crop_frame.pack(fill='both', expand=True, padx=14, pady=6)
            list_row = ttk.Frame(crop_frame)
            list_row.pack(fill='both', expand=True)
            self.crop_list = tk.Listbox(list_row, height=6, font=('Consolas', 10),
                                        selectmode='extended', relief='flat')
            self.crop_list.pack(side='left', fill='both', expand=True)
            scroll = ttk.Scrollbar(list_row, orient='vertical', command=self.crop_list.yview)
            scroll.pack(side='right', fill='y')
            self.crop_list.configure(yscrollcommand=scroll.set)

            btn_row = ttk.Frame(crop_frame)
            btn_row.pack(fill='x', pady=(8, 0))
            ttk.Button(btn_row, text="追加", command=self._add_crop_csvs).pack(side='left')
            ttk.Button(btn_row, text="削除", command=self._remove_selected).pack(side='left', padx=6)
            ttk.Button(btn_row, text="自動検出", command=self._auto_detect_crop_csvs).pack(side='left')
            ttk.Label(btn_row, text="プロジェクト直下と Downloads から *_crop_rows.csv を探します",
                      foreground='#777').pack(side='left', padx=12)

            out_frame = ttk.LabelFrame(self, text="  出力  ", padding=10)
            out_frame.pack(fill='x', padx=14, pady=6)
            ttk.Radiobutton(out_frame, text="data.csv を更新（実行前に自動バックアップ）",
                            variable=self.output_mode, value='overwrite').pack(anchor='w')
            custom_row = ttk.Frame(out_frame)
            custom_row.pack(fill='x', pady=(6, 0))
            ttk.Radiobutton(custom_row, text="別ファイルに保存",
                            variable=self.output_mode, value='custom').pack(side='left')
            ttk.Entry(custom_row, textvariable=self.output_path, font=('Arial', 10)).pack(
                side='left', fill='x', expand=True, padx=8)
            ttk.Button(custom_row, text="選択",
                       command=lambda: self._browse_save(self.output_path)).pack(side='left')

            run_row = ttk.Frame(self)
            run_row.pack(fill='x', padx=14, pady=8)
            self.run_btn = ttk.Button(run_row, text="▶ マージ実行",
                                      style='Run.TButton', command=self._start_merge)
            self.run_btn.pack(side='left')
            self.open_btn = ttk.Button(run_row, text="出力フォルダを開く",
                                       command=self._open_output_folder, state='disabled')
            self.open_btn.pack(side='right')

            log_frame = ttk.LabelFrame(self, text="  ログ  ", padding=8)
            log_frame.pack(fill='both', expand=True, padx=14, pady=(0, 12))
            self.log = scrolledtext.ScrolledText(
                log_frame, font=('Consolas', 10), bg='#1a1a1a', fg='#e6e6e6',
                insertbackground='white', relief='flat', state='disabled')
            self.log.pack(fill='both', expand=True)

        def _path_row(self, parent, label, var, command):
            row = ttk.Frame(parent)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=label, width=12).pack(side='left')
            ttk.Entry(row, textvariable=var, font=('Arial', 10)).pack(
                side='left', fill='x', expand=True, padx=(4, 8))
            ttk.Button(row, text="選択", command=command).pack(side='left')

        def _browse_file(self, var, filetypes):
            path = filedialog.askopenfilename(filetypes=filetypes)
            if path:
                var.set(path)

        def _browse_dir(self, var):
            path = filedialog.askdirectory()
            if path:
                var.set(path)

        def _browse_save(self, var):
            path = filedialog.asksaveasfilename(
                defaultextension='.csv', filetypes=[('CSV', '*.csv')])
            if path:
                var.set(path)
                self.output_mode.set('custom')

        def _add_crop_csvs(self):
            paths = filedialog.askopenfilenames(filetypes=[('CSV', '*.csv')])
            for path in paths:
                self._add_crop_path(Path(path))

        def _auto_detect_crop_csvs(self):
            base = Path(__file__).resolve().parent
            candidates = list(base.glob('*_crop_rows.csv'))
            downloads = Path.home() / 'Downloads'
            if downloads.exists():
                candidates.extend(downloads.glob('*_crop_rows.csv'))
            for path in sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True):
                self._add_crop_path(path)
            self._log(f"[検出] crop CSV: {len(self.crop_paths)}件")

        def _add_crop_path(self, path):
            path = Path(path).resolve()
            if path not in self.crop_paths:
                self.crop_paths.append(path)
                self.crop_list.insert('end', str(path))

        def _remove_selected(self):
            for idx in reversed(self.crop_list.curselection()):
                self.crop_list.delete(idx)
                del self.crop_paths[idx]

        def _log(self, message):
            self.log.config(state='normal')
            self.log.insert('end', message + '\n')
            self.log.see('end')
            self.log.config(state='disabled')

        def _start_merge(self):
            data = Path(self.data_path.get().strip())
            photos = Path(self.photos_path.get().strip())
            if not data.exists():
                messagebox.showwarning("未設定", "元CSVが見つかりません")
                return
            if not photos.exists():
                messagebox.showwarning("未設定", "写真フォルダが見つかりません")
                return
            if not self.crop_paths:
                messagebox.showwarning("未設定", "crop CSVを選択してください")
                return
            if self.output_mode.get() == 'overwrite':
                ok = messagebox.askyesno(
                    "確認",
                    "data.csv を更新します。実行前に backup CSV を作成します。\n続行しますか？")
                if not ok:
                    return

            self.run_btn.config(state='disabled')
            self.open_btn.config(state='disabled')
            threading.Thread(target=self._run_merge, daemon=True).start()

        def _run_merge(self):
            try:
                data = Path(self.data_path.get().strip())
                photos = Path(self.photos_path.get().strip())
                if self.output_mode.get() == 'overwrite':
                    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                    temp_output = data.with_name(f"{data.stem}_merge_tmp_{stamp}.csv")
                    final_output = data
                else:
                    final_output = Path(self.output_path.get().strip())
                    temp_output = final_output

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    merge(str(data), [str(p) for p in self.crop_paths], str(photos), str(temp_output))

                if self.output_mode.get() == 'overwrite':
                    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                    backup = data.with_name(f"{data.stem}_backup_before_merge_{stamp}{data.suffix}")
                    shutil.copy2(data, backup)
                    shutil.move(str(temp_output), str(final_output))
                    extra = f"[バックアップ] {backup}\n[更新] {final_output}"
                else:
                    extra = f"[保存] {final_output}"

                self.last_output = final_output
                self.after(0, lambda: self._finish(buf.getvalue() + extra))
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda msg=message: self._fail(msg))

        def _finish(self, text):
            self._log(text.rstrip())
            self._log("[完了] マージしました")
            self.run_btn.config(state='normal')
            self.open_btn.config(state='normal')
            messagebox.showinfo("完了", "CSVマージが完了しました")

        def _fail(self, text):
            self._log("[エラー] " + text)
            self.run_btn.config(state='normal')
            messagebox.showerror("エラー", text)

        def _open_output_folder(self):
            target = self.last_output or Path(self.data_path.get().strip())
            folder = Path(target).parent
            if sys.platform == 'win32':
                os.startfile(str(folder))
            elif sys.platform == 'darwin':
                subprocess.run(['open', str(folder)])
            else:
                subprocess.run(['xdg-open', str(folder)])

    MergeGui().mainloop()

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        launch_gui()
        return

    parser = argparse.ArgumentParser(description='CSVマージツール')
    parser.add_argument('--data',   '-d', required=True, help='元のdata.csvパス')
    parser.add_argument('--crop',   '-c', nargs='+',     help='クロップCSVパス（複数可）')
    parser.add_argument('--photos', '-p', required=True, help='photosフォルダパス')
    parser.add_argument('--output', '-o', default=None,  help='出力CSVパス（省略時はdata_merged.csv）')
    args = parser.parse_args(argv)

    output = args.output or str(Path(args.data).parent / 'data_merged.csv')
    crop_csvs = expand_crop_paths(args.crop or [])

    merge(args.data, crop_csvs, args.photos, output)

if __name__ == '__main__':
    main()
