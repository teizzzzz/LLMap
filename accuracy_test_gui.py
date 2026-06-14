#!/usr/bin/env python3
"""
AI画像圧縮精度テストツール（量化评分完全体版）
ダブルクリックで起動
"""

import sys
import os
import time
import json
import base64
import threading
import io
import re
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
from pathlib import Path

def check_and_install(packages):
    import subprocess
    for pkg in packages:
        mod = pkg.replace('-','_').lower()
        if mod == 'pillow': mod = 'PIL'
        if pkg == 'google-generativeai': mod = 'google.generativeai'
        try: __import__(mod)
        except ImportError:
            print(f"インストール中: {pkg}")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

check_and_install(['anthropic', 'google-generativeai', 'Pillow', 'pandas', 'piexif'])

import anthropic
import google.generativeai as genai
from PIL import Image
import pandas as pd

PROMPT = """この写真の言語景観サインを分析してください。以下のJSON形式のみで回答：

{
  "名称": "看板の内容を簡潔に",
  "主要言語": "日本語 or 中文 or 韓国語 or 英語 or その他",
  "補助言語": "日本語 or 中文 or 韓国語 or 英語 or その他 or —",
  "設置主体": "行政/公共機関 or 商業 or 個人/非正式 or 不明",
  "担体類型": "建物固定(看板) or 貼付物(ポスター) or 貼付物(ステッカー) or 路面固定 or デジタル表示 or その他",
  "来源類型": "top-down(標準化) or bottom-up(ローカル自作) or 不明",
  "多言語関係": "平行型 or 補完型 or 象徴型 or 単言語型",
  "備考": "特記事項（簡潔に20字以内）"
}"""

DEFAULT_CONFIGS = [
    {'label': '原寸',   'size': 1568, 'quality': 85},
    {'label': '推奨',   'size': 1024, 'quality': 75},
    {'label': '軽量',   'size': 800,  'quality': 70},
    {'label': '超軽量', 'size': 512,  'quality': 60},
]

def resize_image(path, max_size, quality):
    img = Image.open(path)
    try:
        import piexif
        exif_data = img.info.get('exif')
        if exif_data:
            exif = piexif.load(exif_data)
            orientation = exif.get('0th', {}).get(piexif.ImageIFD.Orientation, 1)
            rotation_map = {3: 180, 6: 270, 8: 90}
            if orientation in rotation_map:
                img = img.rotate(rotation_map[orientation], expand=True)
    except: pass
    if img.mode != 'RGB': img = img.convert('RGB')
    orig_w, orig_h = img.size
    if max(orig_w, orig_h) > max_size:
        ratio = max_size / max(orig_w, orig_h)
        img = img.resize((int(orig_w*ratio), int(orig_h*ratio)), Image.LANCZOS)
    new_w, new_h = img.size
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality)
    b64  = base64.standard_b64encode(buf.getvalue()).decode('utf-8')
    kb   = len(buf.getvalue()) / 1024
    est  = round((new_w * new_h) / 750)  # Claude推定式
    return img, b64, new_w, new_h, kb, est

def parse_json(raw):
    if not raw:
        return None
    # 配列パターン [{ ... }] を先にチェック
    try:
        arr_start = raw.find('[')
        arr_end   = raw.rfind(']')
        obj_start = raw.find('{')
        obj_end   = raw.rfind('}')

        # 配列が先にある場合は配列としてパース
        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
            if obj_start == -1 or arr_start < obj_start:
                parsed = json.loads(raw[arr_start:arr_end+1])
                return parsed[0] if isinstance(parsed, list) and parsed else parsed

        # 通常のオブジェクト
        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
            parsed = json.loads(raw[obj_start:obj_end+1])
            return parsed[0] if isinstance(parsed, list) else parsed
    except:
        pass
    return None

def make_row(label, w, h, quality, kb, elapsed, in_tok, out_tok, est_tok, score, result):
    return {
        'ラベル':       label,
        'サイズ(px)':   f"{w}×{h}",
        '品質':         quality,
        'KB':           round(kb, 1),
        '秒':           elapsed,
        '入力Token':    in_tok,
        '出力Token':    out_tok,
        'Token推定':    est_tok,
        'スコア(%)':    score if score is not None else '—',
        '名称':         result.get('名称','')       if result else '',
        '主要言語':     result.get('主要言語','—')   if result else '—',
        '補助言語':     result.get('補助言語','—')   if result else '—',
        '設置主体':     result.get('設置主体','—')   if result else '—',
        '担体類型':     result.get('担体類型','—')   if result else '—',
        '来源類型':     result.get('来源類型','—')   if result else '—',
        '多言語関係':   result.get('多言語関係','—') if result else '—',
        '備考':         result.get('備考','')       if result else '',
    }

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI画像圧縮精度テスト（量化完全体版）")
        self.geometry("820x750")
        self.resizable(True, True)
        self.configure(bg='#f5f2ed')

        self.photo_path   = tk.StringVar()
        self.provider     = tk.StringVar(value='gemini') # 默认直接切到稳定的 Gemini
        self.claude_key   = tk.StringVar()
        self.gemini_key   = tk.StringVar()
        self.gemini_model = tk.StringVar(value='gemini-2.5-flash')
        self.results      = []
        self.baseline     = None

        _base = Path(sys.argv[0]).parent.resolve()
        photos = _base / 'photos'
        if photos.exists():
            files = list(photos.glob('*.jpg'))
            if files: self.photo_path.set(str(files[0]))

        self._build_ui()
        self._update_provider()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TLabel',       background='#f5f2ed', font=('Arial',11))
        style.configure('TFrame',       background='#f5f2ed')
        style.configure('TLabelframe',  background='#f5f2ed')
        style.configure('TLabelframe.Label', background='#f5f2ed', font=('Arial',11,'bold'))
        style.configure('TCheckbutton', background='#f5f2ed', font=('Arial',10))
        style.configure('TRadiobutton', background='#f5f2ed', font=('Arial',11))
        style.configure('TProgressbar', troughcolor='#e0dbd3', background='#27ae60')

        pad = {'padx':14, 'pady':5}

        # 写真
        file_frame = ttk.LabelFrame(self, text="  テスト写真  ", padding=10)
        file_frame.pack(fill='x', **pad)
        r = ttk.Frame(file_frame); r.pack(fill='x')
        ttk.Label(r, text="写真:").pack(side='left')
        ttk.Entry(r, textvariable=self.photo_path,
                  font=('Arial',10)).pack(side='left', fill='x', expand=True, padx=(6,6))
        ttk.Button(r, text="選択", width=4,
                   command=self._browse).pack(side='left')

        # API設定
        api_frame = ttk.LabelFrame(self, text="  API設定  ", padding=10)
        api_frame.pack(fill='x', **pad)

        # プロバイダー選択
        prov_row = ttk.Frame(api_frame); prov_row.pack(fill='x', pady=(0,8))
        ttk.Label(prov_row, text="プロバイダー:").pack(side='left')
        ttk.Radiobutton(prov_row, text="Claude (Anthropic)",
                        variable=self.provider, value='claude',
                        command=self._update_provider).pack(side='left', padx=(10,0))
        ttk.Radiobutton(prov_row, text="Google Gemini",
                        variable=self.provider, value='gemini',
                        command=self._update_provider).pack(side='left', padx=(10,0))

        # Claude設定
        self.claude_frame = ttk.Frame(api_frame)
        self.claude_frame.pack(fill='x', pady=(0,4))
        ttk.Label(self.claude_frame, text="APIキー: ").pack(side='left')
        self.claude_entry = ttk.Entry(self.claude_frame, textvariable=self.claude_key,
                                       show='*', font=('Arial',10))
        self.claude_entry.pack(side='left', fill='x', expand=True, padx=(0,6))
        ttk.Button(self.claude_frame, text="表示", width=4,
                   command=lambda: self._toggle(self.claude_entry)).pack(side='left')
        ttk.Label(self.claude_frame, text="console.anthropic.com",
                  foreground='#888', font=('Arial',9)).pack(side='left', padx=(8,0))

        # Gemini設定
        self.gemini_frame = ttk.Frame(api_frame)
        self.gemini_frame.pack(fill='x', pady=(0,4))
        ttk.Label(self.gemini_frame, text="APIキー: ").pack(side='left')
        self.gemini_entry = ttk.Entry(self.gemini_frame, textvariable=self.gemini_key,
                                       show='*', font=('Arial',10))
        self.gemini_entry.pack(side='left', fill='x', expand=True, padx=(0,6))
        ttk.Button(self.gemini_frame, text="表示", width=4,
                   command=lambda: self._toggle(self.gemini_entry)).pack(side='left')
        ttk.Label(self.gemini_frame, text="aistudio.google.com",
                  foreground='#888', font=('Arial',9)).pack(side='left', padx=(8,0))

        self.model_frame = ttk.Frame(api_frame)
        self.model_frame.pack(fill='x')
        ttk.Label(self.model_frame, text="モデル:  ").pack(side='left')
        for m in ['gemini-2.5-flash','gemini-2.5-flash-lite','gemini-2.5-pro']:
            ttk.Radiobutton(self.model_frame, text=m,
                            variable=self.gemini_model, value=m).pack(side='left', padx=(6,0))

        # 圧縮設定
        cfg_frame = ttk.LabelFrame(self, text="  テストする圧縮設定  ", padding=10)
        cfg_frame.pack(fill='x', **pad)

        self.gemini_note = ttk.Label(cfg_frame,
            text="※ GeminiはToken固定のためサイズ変更はToken節約にならない。转送速度和前端加载明显提升。",
            foreground='#856404', font=('Arial',9))
        self.claude_note = ttk.Label(cfg_frame,
            text="※ ClaudeはToken=w×h/750のため圧縮するほどToken節約できる。",
            foreground='#155724', font=('Arial',9))

        self.cfg_vars = []
        for cfg in DEFAULT_CONFIGS:
            row = ttk.Frame(cfg_frame); row.pack(fill='x', pady=2)
            var      = tk.BooleanVar(value=True)
            size_var = tk.IntVar(value=cfg['size'])
            qual_var = tk.IntVar(value=cfg['quality'])
            cfg['size_var'] = size_var
            cfg['qual_var'] = qual_var
            self.cfg_vars.append((var, cfg))

            ttk.Checkbutton(row, text=cfg['label'], variable=var,
                            width=8).pack(side='left')
            ttk.Label(row, text="最大", foreground='#888',
                      font=('Arial',10)).pack(side='left', padx=(4,2))
            ttk.Spinbox(row, from_=200, to=1568, increment=100,
                        textvariable=size_var, width=5,
                        font=('Arial',10)).pack(side='left')
            ttk.Label(row, text="px  品質", foreground='#888',
                      font=('Arial',10)).pack(side='left', padx=(4,2))
            ttk.Spinbox(row, from_=50, to=95, increment=5,
                        textvariable=qual_var, width=4,
                        font=('Arial',10)).pack(side='left')
            est_lbl = ttk.Label(row, text="", foreground='#2980b9', font=('Arial',9))
            est_lbl.pack(side='left', padx=(10,0))
            cfg['est_lbl'] = est_lbl

        # 進捗
        prog_frame = ttk.LabelFrame(self, text="  進捗  ", padding=8)
        prog_frame.pack(fill='x', **pad)
        self.progress = ttk.Progressbar(prog_frame, mode='determinate')
        self.progress.pack(fill='x', pady=(0,4))
        self.prog_lbl = ttk.Label(prog_frame, text="待機中",
                                   foreground='#888', font=('Arial',10))
        self.prog_lbl.pack(anchor='w')

        # ボタン
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill='x', padx=14, pady=4)
        self.run_btn = ttk.Button(btn_frame, text="▶  テスト実行", command=self._start)
        self.run_btn.pack(side='left', ipadx=10)
        self.save_btn = ttk.Button(btn_frame, text="CSV保存",
                                    command=self._save_csv, state='disabled')
        self.save_btn.pack(side='left', padx=(8,0))

        # ログ
        log_frame = ttk.LabelFrame(self, text="  結果ログ  ", padding=8)
        log_frame.pack(fill='both', expand=True, padx=14, pady=(0,12))
        self.log = scrolledtext.ScrolledText(
            log_frame, font=('Courier',10),
            bg='#1a1a1a', fg='#e0e0e0', relief='flat', state='disabled')
        self.log.pack(fill='both', expand=True)

    def _update_provider(self):
        p = self.provider.get()
        if p == 'claude':
            self.claude_frame.pack(fill='x', pady=(0,4))
            self.gemini_frame.pack_forget()
            self.model_frame.pack_forget()
            self.claude_note.pack(anchor='w', pady=(0,6))
            self.gemini_note.pack_forget()
        else:
            self.gemini_frame.pack(fill='x', pady=(0,4))
            self.model_frame.pack(fill='x')
            self.claude_frame.pack_forget()
            self.gemini_note.pack(anchor='w', pady=(0,6))
            self.claude_note.pack_forget()
        for var, cfg in self.cfg_vars:
            size = cfg['size_var'].get()
            if p == 'claude':
                est = round((size * int(size * 0.75)) / 750)
                cfg['est_lbl'].config(text=f"推定 {est} tok")
            else:
                cfg['est_lbl'].config(text="Gemini固定: ~464tok")

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("画像", "*.jpg *.jpeg *.png")])
        if p: self.photo_path.set(p)

    def _toggle(self, entry):
        entry.config(show='' if entry.cget('show') == '*' else '*')

    def _log(self, msg, color=None):
        self.log.config(state='normal')
        if color:
            tag = f'c{color.replace("#","")}'
            self.log.tag_config(tag, foreground=color)
            self.log.insert('end', msg+'\n', tag)
        else:
            self.log.insert('end', msg+'\n')
        self.log.see('end')
        self.log.config(state='disabled')

    def _start(self):
        p = self.provider.get()
        key = self.claude_key.get().strip() if p == 'claude' else self.gemini_key.get().strip()
        if not self.photo_path.get():
            messagebox.showwarning("未設定", "テスト写真を選択してください"); return
        if not key:
            messagebox.showwarning("未設定", "APIキーを入力してください"); return
        self.run_btn.config(state='disabled')
        self.save_btn.config(state='disabled')
        self.results = []
        self.baseline = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            photo    = Path(self.photo_path.get())
            provider = self.provider.get()
            configs  = [cfg for var, cfg in self.cfg_vars if var.get()]
            if not configs:
                messagebox.showwarning("未選択", "設定を1つ以上選択してください"); return

            if provider == 'claude':
                client = anthropic.Anthropic(api_key=self.claude_key.get().strip())
            else:
                genai.configure(api_key=self.gemini_key.get().strip())
                model = genai.GenerativeModel(self.gemini_model.get())

            self.progress['maximum'] = len(configs)
            self._log(f"テスト対象: {photo.name}")
            self._log(f"プロバイダー: {provider}" +
                      (f" / {self.gemini_model.get()}" if provider=='gemini' else " / claude-haiku-4-5-20251001"))
            self._log(f"設定数: {len(configs)}\n")

            # ── 核心逻辑重构：先跑第一组建立基准线 ──
            for i, cfg in enumerate(configs):
                label   = cfg['label']
                size    = cfg['size_var'].get()
                quality = cfg['qual_var'].get()

                self._log(f"[{label}] {size}px / Q{quality} 処理中...")
                self.prog_lbl.config(text=f"{i+1}/{len(configs)} — {label}")

                try:
                    img, b64, w, h, kb, est_tok = resize_image(str(photo), size, quality)

                    if provider == 'claude':
                        t0 = time.time()
                        resp = client.messages.create(
                            model="claude-haiku-4-5-20251001",
                            max_tokens=600,
                            messages=[{"role":"user","content":[
                                {"type":"image","source":{
                                    "type":"base64","media_type":"image/jpeg","data":b64}},
                                {"type":"text","text":PROMPT}
                            ]}]
                        )
                        elapsed  = round(time.time()-t0, 1)
                        in_tok   = resp.usage.input_tokens
                        out_tok  = resp.usage.output_tokens
                        raw      = resp.content[0].text
                    else:  # gemini
                        max_retries = 5
                        resp = None
                        t0 = time.time()
                        for attempt in range(max_retries):
                            try:
                                resp = model.generate_content(
                                    [PROMPT, img],
                                    generation_config={'max_output_tokens':2048}
                                )
                                break
                            except Exception as e:
                                err = str(e)
                                if any(x in err for x in ['429','503','UNAVAILABLE','quota','high demand']) \
                                   and attempt < max_retries-1:
                                    import re
                                    m = re.search(r'seconds:\s*(\d+)', err)
                                    wait = int(m.group(1))+5 if m else 30
                                    self._log(f"  [待機] {wait}秒待機して再試行({attempt+1}/{max_retries})", '#f39c12')
                                    time.sleep(wait)
                                else:
                                    raise e
                        elapsed = round(time.time()-t0, 1)
                        try:
                            in_tok  = resp.usage_metadata.prompt_token_count
                            out_tok = resp.usage_metadata.candidates_token_count
                        except:
                            in_tok = out_tok = '—'
                        # Gemini 2.5のthinking mode対応
                        try:
                            parts = resp.candidates[0].content.parts
                            # partsの内容をデバッグ表示
                            debug_info = []
                            for pi, p in enumerate(parts):
                                txt = p.text if hasattr(p, 'text') else ''
                                thought = getattr(p, 'thought', False)
                                debug_info.append(f"part{pi}:thought={thought},len={len(txt or '')}")
                            self._log(f"  [PARTS] {', '.join(debug_info)}", '#444444')
                            # thought=Falseのpartのみ使用
                            raw = ''.join(
                                p.text for p in parts
                                if hasattr(p, 'text') and p.text
                                and not getattr(p, 'thought', False)
                            )
                            if not raw:
                                # thought属性がない場合は全部結合
                                raw = ''.join(
                                    p.text for p in parts
                                    if hasattr(p, 'text') and p.text
                                )
                        except Exception as pe:
                            self._log(f"  [PARTS ERROR] {pe}", '#f39c12')
                            raw = resp.text or ''

                    result = parse_json(raw)

                    # ── 精准量化评分算法 ──
                    score = None
                    if result:
                        if self.baseline is None:
                            # 第一组（通常是原图）强制确立为 100% 的学术基准线
                            self.baseline = result
                            score = 100
                        else:
                            # 对比核心学术属性的重合度
                            keys = ['主要言語','補助言語','設置主体','担体類型','来源類型','多言語関係']
                            match = sum(1 for k in keys if str(result.get(k, '')).strip() == str(self.baseline.get(k, '')).strip())
                            score = round(match / len(keys) * 100)

                    # 实时渲染判定状态日志
                    if result:
                        self._log(
                            f"  [OK] {elapsed}秒 | 入力:{in_tok}tok(推定:{est_tok}) | "
                            f"出力:{out_tok}tok | {kb:.0f}KB | スコア:{score}%",
                            '#27ae60'
                        )
                        self._log(
                            f"     判明データ: {result.get('主要言語','?')} / "
                            f"{result.get('担体類型','?')} / "
                            f"{result.get('来源類型','?')}",
                            '#888888'
                        )
                    else:
                        self._log(f"  [パース失敗] AIの応答がJSON形式として解析できませんでした", '#f39c12')
                        # 全文表示してデバッグ
                        for chunk in [raw[i:i+200] for i in range(0, min(len(raw),800), 200)]:
                            self._log(f"  {chunk}", '#555555')
                        # 手動パース試行
                        start = raw.find('{')
                        end   = raw.rfind('}')
                        self._log(f"  [DEBUG] raw長={len(raw)} start={start} end={end}", '#f39c12')

                    self.results.append(make_row(
                        label, w, h, quality, kb, elapsed,
                        in_tok, out_tok, est_tok, score, result
                    ))

                except Exception as e:
                    self._log(f"  [NG] {e}", '#c84b31')
                    self.results.append({'ラベル':label,'スコア(%)':'エラー','備考':str(e)})

                self.progress['value'] = i+1
                time.sleep(0.5)

            # ── 渲染可视化サマリー（彩色高亮看板） ──
            self._log(f"\n{'='*65}", '#888888')
            self._log(" ⚖️  画像圧縮精度 総合比較サマリー", '#ffffff')
            self._log(f"{'='*65}", '#888888')
            self._log(f"{'ラベル':7} {'サイズ(px)':13} {'KB':6} {'秒':5} {'入力tok':9} {'推定tok':7} {'スコア'}")
            self._log('-'*68, '#888888')
            for r in self.results:
                s_val = r.get('スコア(%)','—')
                s_str = f"{s_val}%" if isinstance(s_val, int) else str(s_val)
                
                # 学术阶梯高亮颜色分配
                if s_val == 100: col = '#27ae60'     # 完美完美对齐（绿色）
                elif isinstance(s_val, int) and s_val >= 80: col = '#2980b9'  # 极佳高重合（蓝色）
                elif isinstance(s_val, int) and s_val >= 60: col = '#f39c12'  # 尚可轻微扰动（黄色）
                else: col = '#c84b31'                 # 产生了偏差或错误（红色）

                self._log(
                    f"{str(r.get('ラベル','')):7} "
                    f"{str(r.get('サイズ(px)','')):13} "
                    f"{str(r.get('KB','')):6} "
                    f"{str(r.get('秒','')):5} "
                    f"{str(r.get('入力Token','')):9} "
                    f"{str(r.get('Token推定','')):7} "
                    f"{s_str}", col
                )

            self.prog_lbl.config(text="すべてのテスト完了")
            self.save_btn.config(state='normal')

        except Exception as e:
            self._log(f"\n[NG] 致命的システムエラー: {e}", '#c84b31')
        finally:
            self.run_btn.config(state='normal')

    def _save_csv(self):
        if not self.results: return
        stem = Path(self.photo_path.get()).stem
        prov = self.provider.get()
        path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            initialfile=f"{stem}_{prov}_test.csv",
            filetypes=[("CSV","*.csv")]
        )
        if path:
            pd.DataFrame(self.results).to_csv(path, index=False, encoding='utf-8-sig')
            messagebox.showinfo("保存完了", f"保存しました:\n{path}")

if __name__ == '__main__':
    app = App()
    app.mainloop()
