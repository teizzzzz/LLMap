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
from pathlib import Path

def check_and_install(packages):
    import subprocess
    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

check_and_install(['pandas'])
import pandas as pd

def has_crop(photo_file, photos_dir):
    """全景写真に対応するクロップが存在するか確認"""
    stem = Path(photo_file).stem
    parts = stem.split('-')
    # クロップファイル：最後の部分が1文字アルファベット
    is_crop = len(parts[-1]) == 1 and parts[-1].isalpha()
    if is_crop:
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

    # クロップが存在する全景行を削除
    skip_mask = df['写真ファイル名'].apply(lambda f: has_crop(f, photos_dir))
    skipped = df[skip_mask]
    df = df[~skip_mask]
    if len(skipped) > 0:
        print(f"[削除] クロップが存在する全景行: {len(skipped)}件")
        for _, row in skipped.iterrows():
            print(f"  - {row['写真ファイル名']}")

    # クロップCSVを追記
    crop_dfs = []
    for crop_csv in crop_csvs:
        if not Path(crop_csv).exists():
            print(f"[警告] {crop_csv} が見つかりません")
            continue
        crop_df = pd.read_csv(crop_csv, encoding='utf-8-sig', dtype=str).fillna('')
        crop_df = inherit_panorama_fields(crop_df, source_df)
        print(f"[追記] {Path(crop_csv).name}: {len(crop_df)}件")
        crop_dfs.append(crop_df)

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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CSVマージツール')
    parser.add_argument('--data',   '-d', required=True, help='元のdata.csvパス')
    parser.add_argument('--crop',   '-c', nargs='+',     help='クロップCSVパス（複数可）')
    parser.add_argument('--photos', '-p', required=True, help='photosフォルダパス')
    parser.add_argument('--output', '-o', default=None,  help='出力CSVパス（省略時はdata_merged.csv）')
    args = parser.parse_args()

    output = args.output or str(Path(args.data).parent / 'data_merged.csv')
    crop_csvs = args.crop or []

    # ワイルドカード展開
    expanded = []
    for c in crop_csvs:
        expanded.extend(glob.glob(c))
    crop_csvs = expanded

    merge(args.data, crop_csvs, args.photos, output)
