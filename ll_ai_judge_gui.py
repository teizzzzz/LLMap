#!/usr/bin/env python3
"""
言語景観 AI判定ツール（GUI版）
ダブルクリックで起動できます
"""

import sys
import os
import json
import time
import base64
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import io

# ── ライブラリ確認 ──
def check_and_install(packages):
    import subprocess
    for pkg in packages:
        mod = pkg.replace('-','_').lower()
        if mod == 'pillow': mod = 'PIL'
        if pkg == 'google-genai': mod = 'google.genai'
        try:
            __import__(mod)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

check_and_install(['anthropic', 'openai', 'google-genai', 'Pillow', 'pandas'])

import anthropic
from PIL import Image, ImageOps
import pandas as pd

# ────────────────────────────────
# プロンプト
# ────────────────────────────────
SYSTEM_PROMPT = "あなたは言語景観研究の専門家です。都市の公共空間の看板・サイン・貼り紙の写真を分析します。必ずJSON形式のみで回答してください。"

USER_PROMPT = """この写真の看板・サイン・貼り紙を分析してください。
以下のJSON形式のみで回答してください：

{
  "名称": "看板の内容を簡潔に",
  "主要言語": "日本語 or 中文 or 韓国語 or 英語 or その他",
  "補助言語": "日本語 or 中文 or 韓国語 or 英語 or その他 or —",
  "装飾的言語": "英語(ブランド名) or 英語(装飾) or その他 or —",
  "設置主体": "行政/公共機関 or 商業 or 個人/非正式 or 不明",
  "担体類型": "建物固定(看板) or 建物固定(壁画) or 建物固定(門牌) or 移動物体(停車中) or 貼付物(ポスター) or 貼付物(ステッカー) or 路面固定 or デジタル表示(LED) or その他",
  "時間性": "常設 or 臨時/季節的 or 不明",
  "可読性": "完全可読 or 部分可読 or 不可読",
  "来源類型": "top-down(標準化) or bottom-up(ローカル自作) or 不明",
  "視認等級": "歩行可読(<5m) or 近距可読(5-15m) or 遠距可読(>15m)",
  "多言語関係": "平行型 or 補完型 or 象徴型 or 単言語型",
  "想定受容者": "本地住民 or 特定コミュニティ or 観光客・外国人 or 不明",
  "制作品質": "専門印刷 or 半専門(印刷) or 手書き",
  "備考": "特記事項があれば簡潔に"
}"""

# フィールド定義（3層）
FIELDS_CORE = ['名称','主要言語','補助言語','装飾的言語','来源類型','言説類型','状態']
FIELDS_ANALYSIS = ['設置主体','担体類型','多言語関係','層状性']
FIELDS_HUMAN = ['時間性','可読性','視認等級','想定受容者','制作品質','位置描述']
AI_FIELDS = FIELDS_CORE + FIELDS_ANALYSIS  # デフォルト（現場層はAI不可）

FIELD_GUIDE = {
    '名称': '看板の内容を簡潔に',
    '主要言語': '日本語 or 中文 or 韓国語 or 英語 or その他',
    '補助言語': '日本語 or 中文 or 韓国語 or 英語 or その他 or —',
    '装飾的言語': '英語(ブランド名) or 英語(装飾) or その他 or —',
    '来源類型': 'top-down(標準化) or bottom-up(ローカル自作) or 不明',
    '言説類型': '案内 or 禁止・注意 or 広告・宣伝 or 商品・サービス or 政治・行政 or 生活情報 or その他 or 不明',
    '状態': '現役 or 古い/劣化 or 一時掲示 or 不明',
    '設置主体': '行政/公共機関 or 商業 or 個人/非正式 or 不明',
    '担体類型': '建物固定(看板) or 建物固定(壁画) or 建物固定(門牌) or 移動物体(停車中) or 貼付物(ポスター) or 貼付物(ステッカー) or 路面固定 or デジタル表示(LED) or その他',
    '多言語関係': '平行型 or 補完型 or 象徴型 or 単言語型',
    '層状性': '単層 or 多層 or 不明',
    '備考': '特記事項があれば簡潔に',
}

def build_prompt(fields):
    body = ",\n".join(
        f'  "{field}": "{FIELD_GUIDE.get(field, "判定結果")}"'
        for field in fields
    )
    return f"""この写真の看板・サイン・貼り紙を分析してください。
以下のJSON形式のみで回答してください。前置き・説明・マークダウンは不要です：

{{
{body}
}}"""

# ────────────────────────────────
# AI処理
# ────────────────────────────────
def image_to_base64(path, max_size=1568, quality=85):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    w, h = img.size
    if max(w, h) > max_size:
        r = max_size / max(w, h)
        img = img.resize((int(w*r), int(h*r)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality)
    return base64.standard_b64encode(buf.getvalue()).decode('utf-8')

def judge_claude(client, b64):
    res = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role":"user","content":[
            {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
            {"type":"text","text":USER_PROMPT}
        ]}]
    )
    return res.content[0].text


def judge_gemini(api_key, b64):
    from google import genai as google_genai
    from google.genai import types
    import PIL.Image
    import re

    client = google_genai.Client(api_key=api_key)
    buf = io.BytesIO(base64.b64decode(b64))
    img = PIL.Image.open(buf)

    # 自動リトライ（429エラー時に待機して再試行）
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[SYSTEM_PROMPT + "\n\n" + USER_PROMPT, img],
            )
            return response.text
        except Exception as e:
            err_str = str(e)
            if any(x in err_str for x in ['429', '503', 'RESOURCE_EXHAUSTED', 'UNAVAILABLE', 'quota', 'high demand']):
                wait = 60
                m = re.search(r'retryDelay[^0-9]*([0-9]+)', err_str)
                if not m:
                    m = re.search(r'retry_delay.*?seconds:\s*(\d+)', err_str)
                if m:
                    wait = int(m.group(1)) + 5
                if attempt < max_retries - 1:
                    # コールバックでGUIログに表示
                    if hasattr(judge_gemini, '_log_cb') and judge_gemini._log_cb:
                        judge_gemini._log_cb(f"    [待機] レート制限 → {wait}秒待機して再試行 ({attempt+1}/{max_retries})", '#f39c12')
                    for _ in range(wait):
                        time.sleep(1)
                    continue
            raise e
    raise Exception("最大リトライ回数に達しました")

def parse_result(text):
    try:
        clean = text.strip()
        if '```' in clean:
            clean = clean.split('```')[1]
            if clean.startswith('json'): clean = clean[4:]
        return json.loads(clean.strip())
    except:
        return None

# ────────────────────────────────
# GUI
# ────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("言語景観 AI判定ツール")
        self.geometry("680x640")
        self.resizable(True, True)
        self.configure(bg='#f5f2ed')

        # デフォルトパス（data_ai.csv があればそちらを優先）
        _base = Path(sys.argv[0]).parent.resolve()
        _ai_csv      = _base / 'data_ai.csv'
        _default_csv = _base / 'data.csv'
        _best_csv    = _ai_csv if _ai_csv.exists() else _default_csv
        _default_photos = _base / 'photos'

        self.csv_path    = tk.StringVar(value=str(_best_csv)       if _best_csv.exists()       else '')
        self.photos_path = tk.StringVar(value=str(_default_photos) if _default_photos.exists() else '')
        self.provider    = tk.StringVar(value='claude')
        self.api_key     = tk.StringVar()
        self.resume_var  = tk.BooleanVar(value=False)
        self.img_size    = tk.IntVar(value=1024)   # AI送信用の最大ピクセル数
        self.img_quality = tk.IntVar(value=75)     # JPEG品質（推奨75）
        self.overwrite   = tk.BooleanVar(value=True)   # 上書きモード
        self.output_name = tk.StringVar()              # カスタム出力ファイル名
        self.delay_var   = tk.DoubleVar(value=40.0)
        self.batch_size  = tk.IntVar(value=0)   # 0 = すべて処理
        # フィールド選択
        self.use_core     = tk.BooleanVar(value=True)
        self.use_analysis = tk.BooleanVar(value=True)
        self.use_備考     = tk.BooleanVar(value=False)
        self.running     = False
        self.stop_flag   = False
        self.df          = None

        self._build_ui()

    def _build_ui(self):
        # ── スタイル ──
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TLabel',    background='#f5f2ed', font=('Arial', 11))
        style.configure('TButton',   font=('Arial', 11), padding=6)
        style.configure('TEntry',    font=('Arial', 11), padding=4)
        style.configure('TFrame',    background='#f5f2ed')
        style.configure('TLabelframe', background='#f5f2ed', font=('Arial', 11, 'bold'))
        style.configure('TLabelframe.Label', background='#f5f2ed', font=('Arial', 11, 'bold'))
        style.configure('TRadiobutton', background='#f5f2ed', font=('Arial', 11))
        style.configure('TCheckbutton', background='#f5f2ed', font=('Arial', 11))
        style.configure('Accent.TButton', font=('Arial', 11, 'bold'), padding=8)
        style.configure('TProgressbar', troughcolor='#e0dbd3', background='#27ae60')

        pad = {'padx': 16, 'pady': 6}

        # ── ファイル選択 ──
        file_frame = ttk.LabelFrame(self, text="  [フォルダ] ファイル設定  ", padding=12)
        file_frame.pack(fill='x', **pad)

        self._file_row(file_frame, "CSVファイル", self.csv_path,
                       lambda: self._browse_file("CSVファイル", [("CSV","*.csv")], self.csv_path), 0)
        self._file_row(file_frame, "写真フォルダ", self.photos_path,
                       lambda: self._browse_dir(self.photos_path), 1)

        # 出力設定
        out_row = ttk.Frame(file_frame)
        out_row.pack(fill='x', pady=(6,0))
        ttk.Label(out_row, text="出力設定:").pack(side='left')
        ttk.Radiobutton(out_row, text="上書き保存（同じファイル名）",
                        variable=self.overwrite, value=True,
                        command=self._toggle_output).pack(side='left', padx=(8,0))
        ttk.Radiobutton(out_row, text="新規作成",
                        variable=self.overwrite, value=False,
                        command=self._toggle_output).pack(side='left', padx=(12,0))

        name_row = ttk.Frame(file_frame)
        name_row.pack(fill='x', pady=(4,0))
        ttk.Label(name_row, text="ファイル名:").pack(side='left')
        self.out_name_entry = ttk.Entry(name_row, textvariable=self.output_name,
                                         font=('Arial',10), width=30, state='disabled')
        self.out_name_entry.pack(side='left', padx=(8,0))
        ttk.Label(name_row, text=".csv", foreground='#888',
                  font=('Arial',10)).pack(side='left')
        self.out_hint = ttk.Label(name_row, text="← 上書きモード",
                                   foreground='#888', font=('Arial',9))
        self.out_hint.pack(side='left', padx=(8,0))

        # ── API設定 ──
        api_frame = ttk.LabelFrame(self, text="  [AI] API設定  ", padding=12)
        api_frame.pack(fill='x', **pad)

        provider_row = ttk.Frame(api_frame)
        provider_row.pack(fill='x', pady=(0,8))
        ttk.Label(provider_row, text="プロバイダー:").pack(side='left')
        ttk.Radiobutton(provider_row, text="Claude (Anthropic)", variable=self.provider,
                        value='claude', command=self._update_hint).pack(side='left', padx=(12,0))
        ttk.Radiobutton(provider_row, text="Google Gemini (無料枠)", variable=self.provider,
                        value='gemini', command=self._update_hint).pack(side='left', padx=(12,0))

        key_row = ttk.Frame(api_frame)
        key_row.pack(fill='x', pady=(0,6))
        ttk.Label(key_row, text="APIキー:").pack(side='left')
        self.key_entry = ttk.Entry(key_row, textvariable=self.api_key, show='*', width=48)
        self.key_entry.pack(side='left', padx=(8,0), fill='x', expand=True)
        ttk.Button(key_row, text="表示", width=4,
                   command=self._toggle_key).pack(side='left', padx=(4,0))

        self.hint_label = ttk.Label(api_frame, text="", foreground='#888888',
                                     font=('Arial', 10), wraplength=580)
        self.hint_label.pack(anchor='w')
        self._update_hint()

        # ── オプション ──
        opt_frame = ttk.LabelFrame(self, text="  ⚙ オプション  ", padding=12)
        opt_frame.pack(fill='x', **pad)

        opt_row = ttk.Frame(opt_frame)
        opt_row.pack(fill='x', pady=(0,6))
        ttk.Checkbutton(opt_row, text="再開モード（未判定のみ処理）",
                        variable=self.resume_var).pack(side='left')
        ttk.Label(opt_row, text="   処理間隔(秒):").pack(side='left')
        ttk.Spinbox(opt_row, from_=0.3, to=120.0, increment=1.0,
                    textvariable=self.delay_var, width=5,
                    font=('Arial', 11)).pack(side='left', padx=(4,0))

        # フィールド選択（AI判定対象）
        field_frame = ttk.LabelFrame(self, text="  AI判定フィールド選択  ", padding=10)
        field_frame.pack(fill='x', padx=16, pady=(0,5))

        f_row1 = ttk.Frame(field_frame)
        f_row1.pack(fill='x', pady=(0,4))
        ttk.Checkbutton(f_row1, text="[必須] コア層: 名称・主要言語・補助言語・装飾的言語・来源類型・言説類型・状態",
                        variable=self.use_core, state='disabled').pack(anchor='w')

        f_row2 = ttk.Frame(field_frame)
        f_row2.pack(fill='x', pady=(0,4))
        ttk.Checkbutton(f_row2, text="[推奨] 分析層: 設置主体・担体類型・多言語関係・層状性",
                        variable=self.use_analysis,
                        command=self._update_ai_fields).pack(anchor='w')

        f_row3 = ttk.Frame(field_frame)
        f_row3.pack(fill='x')
        ttk.Checkbutton(f_row3, text="[任意] 備考（Token増加注意）",
                        variable=self.use_備考,
                        command=self._update_ai_fields).pack(anchor='w')

        self.field_hint = ttk.Label(field_frame,
                                     text="", foreground='#2980b9', font=('Arial',9))
        self.field_hint.pack(anchor='w', pady=(4,0))
        self._update_ai_fields()

        # 画像圧縮設定
        img_row = ttk.Frame(opt_frame)
        img_row.pack(fill='x', pady=(6,0))
        ttk.Label(img_row, text="AI送信画像:").pack(side='left')
        ttk.Label(img_row, text="最大サイズ(px):", foreground='#888',
                  font=('Arial',10)).pack(side='left', padx=(10,4))
        ttk.Spinbox(img_row, from_=400, to=1568, increment=100,
                    textvariable=self.img_size, width=5,
                    font=('Arial',11)).pack(side='left')
        ttk.Label(img_row, text="品質:", foreground='#888',
                  font=('Arial',10)).pack(side='left', padx=(10,4))
        ttk.Spinbox(img_row, from_=50, to=95, increment=5,
                    textvariable=self.img_quality, width=4,
                    font=('Arial',11)).pack(side='left')
        self.size_hint = ttk.Label(img_row, text="",
                                    foreground='#2980b9', font=('Arial',9))
        self.size_hint.pack(side='left', padx=(8,0))
        self.img_size.trace_add('write', lambda *_: self._update_size_hint())
        self.img_quality.trace_add('write', lambda *_: self._update_size_hint())
        self._update_size_hint()

        # 一度に処理する件数
        batch_row = ttk.Frame(opt_frame)
        batch_row.pack(fill='x')
        ttk.Label(batch_row, text="一度に処理する件数:").pack(side='left')
        ttk.Spinbox(batch_row, from_=0, to=9999, increment=10,
                    textvariable=self.batch_size, width=6,
                    font=('Arial', 11)).pack(side='left', padx=(6,8))
        ttk.Label(batch_row,
                  text="（0 = すべて処理。例: 50 なら50件処理して停止）",
                  foreground='#888', font=('Arial',10)).pack(side='left')

        # ── 進捗 ──
        prog_frame = ttk.LabelFrame(self, text="  [進捗] 進捗  ", padding=12)
        prog_frame.pack(fill='x', **pad)

        self.progress = ttk.Progressbar(prog_frame, mode='determinate', style='TProgressbar')
        self.progress.pack(fill='x', pady=(0,6))

        self.prog_label = ttk.Label(prog_frame, text="待機中", foreground='#888888',
                                     font=('Arial', 10))
        self.prog_label.pack(anchor='w')

        # ── ログ ──
        log_frame = ttk.LabelFrame(self, text="  [対象] ログ  ", padding=8)
        log_frame.pack(fill='both', expand=True, padx=16, pady=(0,6))

        self.log = scrolledtext.ScrolledText(
            log_frame, height=10, font=('Courier', 10),
            bg='#1a1a1a', fg='#e0e0e0', insertbackground='white',
            relief='flat', state='disabled'
        )
        self.log.pack(fill='both', expand=True)

        # ── ボタン ──
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill='x', padx=16, pady=(0,16))

        self.run_btn = ttk.Button(btn_frame, text="▶  AI判定を開始",
                                   style='Accent.TButton', command=self._start)
        self.run_btn.pack(side='left')

        self.stop_btn = ttk.Button(btn_frame, text="[停止]  停止",
                                    command=self._stop, state='disabled')
        self.stop_btn.pack(side='left', padx=(8,0))

        self.open_btn = ttk.Button(btn_frame, text="[フォルダ]  出力CSVを開く",
                                    command=self._open_output, state='disabled')
        self.open_btn.pack(side='right')

        self.out_path = None

    def _update_ai_fields(self):
        global AI_FIELDS, USER_PROMPT
        fields = list(FIELDS_CORE)
        if self.use_analysis.get():
            fields += FIELDS_ANALYSIS
        if self.use_備考.get():
            fields.append('備考')
        AI_FIELDS = fields
        USER_PROMPT = build_prompt(fields)
        self.field_hint.config(text=f"判定フィールド数: {len(fields)}個  推定Token: +{len(fields)*15}程度/枚")

    def _update_size_hint(self):
        try:
            size = self.img_size.get()
            q    = self.img_quality.get()
            # おおよそのファイルサイズ見積もり（800px≈50KB、1568px≈200KB）
            est_kb = int((size / 800) ** 2 * 50 * (q / 75))
            self.size_hint.config(text=f"≈ {est_kb}KB/枚")
        except:
            pass

    def _toggle_output(self):
        if self.overwrite.get():
            self.out_name_entry.config(state='disabled')
            self.out_hint.config(text="← 上書きモード")
        else:
            self.out_name_entry.config(state='normal')
            # デフォルト名を提案
            csv_p = Path(self.csv_path.get())
            if csv_p.stem.endswith('_ai'):
                self.output_name.set(csv_p.stem)
            else:
                self.output_name.set(csv_p.stem + '_ai')
            self.out_hint.config(text="← 拡張子(.csv)は自動付与")

    def _file_row(self, parent, label, var, cmd, row):
        f = ttk.Frame(parent)
        f.pack(fill='x', pady=3)
        ttk.Label(f, text=f"{label}:", width=12).pack(side='left')
        ttk.Entry(f, textvariable=var, font=('Arial', 10)).pack(side='left', fill='x', expand=True, padx=(0,6))
        ttk.Button(f, text="選択", width=4, command=cmd).pack(side='left')

    def _browse_file(self, title, types, var):
        p = filedialog.askopenfilename(title=title, filetypes=types)
        if p: var.set(p)

    def _browse_dir(self, var):
        p = filedialog.askdirectory(title="写真フォルダを選択")
        if p: var.set(p)

    def _toggle_key(self):
        self.key_entry.config(show='' if self.key_entry.cget('show') == '*' else '*')

    def _update_hint(self):
        hints = {
            'claude': "取得先: console.anthropic.com → API Keys\n料金目安: 100枚 ≈ $0.05〜$0.15（約8〜23円）\nデフォルト間隔: 0.5秒（高速）",
            'gemini': "モデル: gemini-2.5-flash\n料金目安: 120枚 ≈ $0.04（約6円）\nデフォルト間隔: 1秒（約2分で120枚完了）",
        }
        # モデルに応じてデフォルト間隔を自動変更
        default_delays = {'claude': 0.5, 'gemini': 1.0}
        self.delay_var.set(default_delays.get(self.provider.get(), 5.0))
        self.hint_label.config(text=hints.get(self.provider.get(), ''))

    def _log(self, msg, color=None):
        self.log.config(state='normal')
        tag = None
        if color:
            tag = f'color_{color}'
            self.log.tag_config(tag, foreground=color)
        self.log.insert('end', msg + '\n', tag)
        self.log.see('end')
        self.log.config(state='disabled')

    def _start(self):
        # バリデーション
        if not self.csv_path.get():
            messagebox.showwarning("未設定", "CSVファイルを選択してください")
            return
        if not self.photos_path.get():
            messagebox.showwarning("未設定", "写真フォルダを選択してください")
            return
        if not self.api_key.get().strip():
            messagebox.showwarning("未設定", "APIキーを入力してください")
            return

        self.running   = True
        self.stop_flag = False
        self.run_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.open_btn.config(state='disabled')

        threading.Thread(target=self._run, daemon=True).start()

    def _stop(self):
        self.stop_flag = True
        self._log("[停止] 停止リクエスト...", '#f39c12')

    def _run(self):
        try:
            csv_p    = Path(self.csv_path.get())
            photos_p = Path(self.photos_path.get())
            provider = self.provider.get()
            api_key  = self.api_key.get().strip()
            resume     = self.resume_var.get()
            delay      = self.delay_var.get()
            batch_size = self.batch_size.get()

            self._log(f"[CSV] {csv_p.name}")
            self._log(f"[写真] {photos_p}")
            self._log(f"[AI] プロバイダー: {provider}")
            self._log("")

            # CSV読み込み
            df = pd.read_csv(csv_p, encoding='utf-8-sig', dtype=str).fillna('')
            if '_status' not in df.columns: df['_status'] = 'pending'
            for f in AI_FIELDS:
                if f not in df.columns: df[f] = ''

            # 対象（再開モード or 全件）
            all_targets = df[df['_status']=='pending'].index.tolist() if resume else df.index.tolist()

            # バッチ件数制限
            if batch_size > 0:
                targets = all_targets[:batch_size]
                self._log(f"[対象] {len(all_targets)} 件中 {len(targets)} 件を処理します")
                self._log(f"   残り {len(all_targets) - len(targets)} 件は次回実行時に処理できます\n")
            else:
                targets = all_targets
                self._log(f" {len(targets)} 件をすべて処理します\n")

            total = len(targets)

            if not targets:
                self._log(" 処理対象がありません", '#27ae60')
                return

            # API初期化
            if provider == 'claude':
                client   = anthropic.Anthropic(api_key=api_key)
                judge_fn = lambda b64: judge_claude(client, b64)
            elif provider == 'gemini':
                judge_gemini._log_cb = self._log
                judge_fn = lambda b64: judge_gemini(api_key, b64)
            else:
                raise ValueError(f"未対応のプロバイダー: {provider}")

            # 出力パス
            # 出力パスの決定
            if self.overwrite.get():
                # 上書きモード：入力CSVをそのまま上書き
                out_path = csv_p
            else:
                # 新規作成モード
                custom_name = self.output_name.get().strip()
                if custom_name:
                    out_name = custom_name if custom_name.endswith('.csv') else custom_name + '.csv'
                elif csv_p.stem.endswith('_ai'):
                    out_name = csv_p.stem + '_v2.csv'
                else:
                    out_name = csv_p.stem + '_ai.csv'
                out_path = csv_p.parent / out_name
            self.out_path = out_path
            success = failed = 0

            self.progress['maximum'] = total

            for i, idx in enumerate(targets):
                if self.stop_flag: break
                row        = df.loc[idx]
                photo_file = row.get('写真ファイル名','')
                sign_id    = row.get('SignID', f'#{idx}')
                photo_path = photos_p / photo_file

                # UI更新
                pct = int((i / total) * 100)
                self.progress['value'] = i
                self.prog_label.config(text=f"{i+1} / {total}  ({pct}%)  — {sign_id}")

                if not photo_file or not photo_path.exists():
                    self._log(f"    {sign_id}: 写真なし", '#f39c12')
                    failed += 1
                    continue

                try:
                    b64    = image_to_base64(photo_path, max_size=self.img_size.get(), quality=self.img_quality.get())
                    raw    = judge_fn(b64)
                    result = parse_result(raw)

                    if result:
                        for field in AI_FIELDS:
                            if field in result and result[field]:
                                df.at[idx, field] = str(result[field])
                        df.at[idx, '_status'] = 'ai'
                        lang = result.get('主要言語','?')
                        src  = result.get('来源類型','?')
                        self._log(f"   {sign_id}  {lang} / {src}", '#27ae60')
                        success += 1
                    else:
                        self._log(f"   {sign_id}: パース失敗", '#c84b31')
                        failed += 1

                except Exception as e:
                    self._log(f"   {sign_id}: {e}", '#c84b31')
                    failed += 1

                # 10件ごと中間保存
                if (i + 1) % 10 == 0:
                    df.to_csv(out_path, index=False, encoding='utf-8-sig')
                    self._log(f"   中間保存 ({i+1}件)", '#888888')

                time.sleep(delay)

            # 最終保存
            df.to_csv(out_path, index=False, encoding='utf-8-sig')
            self.progress['value'] = total
            self.prog_label.config(text=f"完了: {success} 件成功 / {failed} 件失敗")

            self._log("")
            self._log(f"------------------------------", '#888888')
            self._log(f" 完了！  成功: {success}件  失敗: {failed}件", '#27ae60')
            self._log(f"[出力] {out_path}", '#2980b9')
            self._log(f"------------------------------", '#888888')
            self.open_btn.config(state='normal')

        except Exception as e:
            self._log(f"\n エラー: {e}", '#c84b31')

        finally:
            self.running = False
            self.run_btn.config(state='normal')
            self.stop_btn.config(state='disabled')

    def _open_output(self):
        if self.out_path and self.out_path.exists():
            import subprocess, platform
            if platform.system() == 'Darwin':
                subprocess.run(['open', str(self.out_path)])
            elif platform.system() == 'Windows':
                os.startfile(str(self.out_path))
            else:
                subprocess.run(['xdg-open', str(self.out_path)])

if __name__ == '__main__':
    app = App()
    app.mainloop()
