#!/usr/bin/env python3
"""
言語景観ツール ランチャー
ダブルクリックで起動
"""

import sys
import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import webbrowser
import time
import socket

# ── サーバー状態 ──
server_process = None
server_port = 8080

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def find_python():
    candidates = [
        sys.executable,
        "python",
        "python3",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\python3.11.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"),
    ]
    for p in candidates:
        try:
            result = subprocess.run([p, '--version'],
                                   capture_output=True, timeout=3)
            if result.returncode == 0:
                return p
        except:
            pass
    return None

# ── GUI ──
class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("言語景観ツール ランチャー")
        self.geometry("520x735")
        self.resizable(False, False)
        self.configure(bg='#f5f2ed')

        # BATファイルと同じフォルダを基準にする
        self.base_dir = Path(sys.argv[0]).parent.resolve()
        self.server_running = False
        self.server_proc = None

        self._build_ui()
        self._check_files()

        # 起動時にサーバー自動起動
        self.after(300, self._auto_start_server)

        # 終了時にサーバーを止める
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TLabel',      background='#f5f2ed', font=('Arial',11))
        style.configure('TFrame',      background='#f5f2ed')
        style.configure('TLabelframe', background='#f5f2ed')
        style.configure('TLabelframe.Label', background='#f5f2ed', font=('Arial',11,'bold'))

        pad = {'padx':20, 'pady':8}

        # タイトル
        title_frame = tk.Frame(self, bg='#1a1a1a', height=64)
        title_frame.pack(fill='x')
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="言語景観ツール",
                 bg='#1a1a1a', fg='white',
                 font=('Arial',16,'bold')).pack(side='left', padx=20, pady=16)
        tk.Label(title_frame, text="Linguistic Landscape Toolkit",
                 bg='#1a1a1a', fg='#888',
                 font=('Arial',10)).pack(side='left', pady=16)

        # サーバー状態
        srv_frame = ttk.LabelFrame(self, text="  🌐 ローカルサーバー  ", padding=12)
        srv_frame.pack(fill='x', **pad)

        srv_row = tk.Frame(srv_frame, bg='#f5f2ed')
        srv_row.pack(fill='x')

        self.srv_dot = tk.Label(srv_row, text="●", fg='#ddd',
                                bg='#f5f2ed', font=('Arial',14))
        self.srv_dot.pack(side='left')

        self.srv_label = tk.Label(srv_row, text="停止中",
                                  bg='#f5f2ed', font=('Arial',11), fg='#888')
        self.srv_label.pack(side='left', padx=(6,0))

        self.srv_btn = tk.Button(srv_row, text="起動",
                                  font=('Arial',10), padx=10, pady=3,
                                  bg='#27ae60', fg='white', relief='flat',
                                  cursor='hand2',
                                  command=self._toggle_server)
        self.srv_btn.pack(side='right')

        # ブラウザツール
        web_frame = ttk.LabelFrame(self, text="  🌏 ブラウザで開くツール  ", padding=12)
        web_frame.pack(fill='x', **pad)

        self._web_btn(web_frame, "地図を見る",
                      "index.html",
                      "採集データを地図上に表示します",
                      '#2980b9')

        self._web_btn(web_frame, "クロップツール",
                      "crop_tool.html",
                      "写真からsignを切り出して保存します",
                      '#16a085')

        self._web_btn(web_frame, "レビューツール",
                      "review_tool_v2.html",
                      "AI判定結果を確認・修正・承認します",
                      '#8e44ad')



        # Pythonツール
        py_frame = ttk.LabelFrame(self, text="  🐍 Pythonツール  ", padding=12)
        py_frame.pack(fill='x', **pad)

        self._py_btn(py_frame, "写真リネーム",
                     "ll_rename_gui.py",
                     "写真リネーム・GPS抽出・サムネイル生成",
                     '#e67e22')

        self._py_btn(py_frame, "CSVマージ",
                     "csv_merge.py",
                     "全景行削除・クロップ行追記を自動化",
                     '#27ae60')

        self._py_btn(py_frame, "Crop後CSV再生成",
                     "crop_rebuild_gui.py",
                     "photos内の命名からdata.csvを再構築",
                     '#2c7a7b')

        self._py_btn(py_frame, "AI判定",
                     "ll_ai_judge_gui.py",
                     "AIが写真を分析して分類を推定します",
                     '#c84b31')

        self._py_btn(py_frame, "AI精度テスト",
                     "accuracy_test_gui.py",
                     "Claude/Gemini 圧縮設定ごとの精度・Token比較",
                     '#8e44ad')

        # フォルダ
        folder_frame = ttk.LabelFrame(self, text="  📂 フォルダ  ", padding=12)
        folder_frame.pack(fill='x', **pad)

        folder_row = tk.Frame(folder_frame, bg='#f5f2ed')
        folder_row.pack(fill='x')

        self.folder_label = tk.Label(folder_row,
                                      text=str(self.base_dir),
                                      bg='#f5f2ed', font=('Arial',9),
                                      fg='#888', wraplength=340,
                                      justify='left')
        self.folder_label.pack(side='left', fill='x', expand=True)

        tk.Button(folder_row, text="開く",
                  font=('Arial',10), padx=10, pady=3,
                  bg='#f5f2ed', relief='solid', bd=1,
                  cursor='hand2',
                  command=self._open_folder).pack(side='right')

        # バージョン
        tk.Label(self, text="v1.0  —  言語景観採集・可視化プロジェクト",
                 bg='#f5f2ed', fg='#bbb', font=('Arial',9)).pack(side='bottom', pady=8)

    def _web_btn(self, parent, label, filename, desc, color):
        f = tk.Frame(parent, bg='#f5f2ed')
        f.pack(fill='x', pady=3)

        info = tk.Frame(f, bg='#f5f2ed')
        info.pack(side='left', fill='x', expand=True)
        tk.Label(info, text=label, bg='#f5f2ed',
                 font=('Arial',11,'bold'), fg='#1a1a1a').pack(anchor='w')
        tk.Label(info, text=desc, bg='#f5f2ed',
                 font=('Arial',9), fg='#888').pack(anchor='w')

        btn = tk.Button(f, text="開く",
                        font=('Arial',10,'bold'), padx=14, pady=4,
                        bg=color, fg='white', relief='flat',
                        cursor='hand2',
                        command=lambda fn=filename: self._open_browser(fn))
        btn.pack(side='right', padx=(8,0))
        setattr(self, f'btn_{filename.replace(".","_").replace("-","_")}', btn)

    def _py_btn(self, parent, label, filename, desc, color):
        f = tk.Frame(parent, bg='#f5f2ed')
        f.pack(fill='x', pady=3)

        info = tk.Frame(f, bg='#f5f2ed')
        info.pack(side='left', fill='x', expand=True)
        tk.Label(info, text=label, bg='#f5f2ed',
                 font=('Arial',11,'bold'), fg='#1a1a1a').pack(anchor='w')
        tk.Label(info, text=desc, bg='#f5f2ed',
                 font=('Arial',9), fg='#888').pack(anchor='w')

        btn = tk.Button(f, text="起動",
                        font=('Arial',10,'bold'), padx=14, pady=4,
                        bg=color, fg='white', relief='flat',
                        cursor='hand2',
                        command=lambda fn=filename: self._open_python(fn))
        btn.pack(side='right', padx=(8,0))

    def _check_files(self):
        """ファイルの存在確認"""
        pass

    def _auto_start_server(self):
        """起動時に自動でサーバーを開始"""
        if not is_port_in_use(server_port):
            self._start_server()
        else:
            self.server_running = True
            self._update_server_ui(True)

    def _toggle_server(self):
        if self.server_running:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        python = find_python()
        if not python:
            messagebox.showerror("エラー", "Pythonが見つかりません")
            return

        try:
            self.server_proc = subprocess.Popen(
                [python, '-m', 'http.server', str(server_port)],
                cwd=str(self.base_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            self.server_running = True
            self._update_server_ui(True)
        except Exception as e:
            messagebox.showerror("エラー", f"サーバー起動失敗: {e}")

    def _stop_server(self):
        if self.server_proc:
            self.server_proc.terminate()
            self.server_proc = None
        self.server_running = False
        self._update_server_ui(False)

    def _update_server_ui(self, running):
        if running:
            self.srv_dot.config(fg='#27ae60')
            self.srv_label.config(text=f"起動中  http://localhost:{server_port}",
                                   fg='#27ae60')
            self.srv_btn.config(text="停止", bg='#c84b31')
        else:
            self.srv_dot.config(fg='#ddd')
            self.srv_label.config(text="停止中", fg='#888')
            self.srv_btn.config(text="起動", bg='#27ae60')

    def _open_browser(self, filename):
        path = self.base_dir / filename
        if not path.exists():
            messagebox.showwarning("ファイルなし",
                                   f"{filename} が見つかりません\n{self.base_dir}")
            return
        if not self.server_running:
            self._start_server()
            time.sleep(1)
        webbrowser.open(f"http://localhost:{server_port}/{filename}")

    def _open_python(self, filename):
        path = self.base_dir / filename
        if not path.exists():
            messagebox.showwarning("ファイルなし",
                                   f"{filename} が見つかりません\n{self.base_dir}")
            return
        python = find_python()
        if not python:
            messagebox.showerror("エラー", "Pythonが見つかりません")
            return
        subprocess.Popen([python, str(path)],
                         cwd=str(self.base_dir))

    def _open_folder(self):
        if sys.platform == 'win32':
            os.startfile(str(self.base_dir))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(self.base_dir)])
        else:
            subprocess.run(['xdg-open', str(self.base_dir)])

    def _on_close(self):
        self._stop_server()
        self.destroy()

if __name__ == '__main__':
    app = Launcher()
    app.mainloop()
