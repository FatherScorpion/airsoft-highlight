# airsoft-highlight

サバゲー（エアソフト）のGoPro等POV動画フォルダから、戦闘シーンとヒットシーンを自動抽出してハイライト動画を作成する **Claude Code スキル**。

音響解析で撃ち合いを検出し、ElevenLabs Scribe の転写から本人のヒットコール（「Nダウン」「やった」「ナイス」等）を拾って命中シーンを網羅する。

設計と試行錯誤の背景は記事を参照: [video-useから始めて、サバゲーのハイライト自動化スキルを作った話](https://zenn.dev/tokium_dev/articles/airsoft-video-use-highlight)

## 導入

Claude Code に次の一行を渡せば、`~/.claude/skills/airsoft-highlight/` に配置されます。

```
Set up https://github.com/FatherScorpion/airsoft-highlight for me.
```

その後、サバゲー動画フォルダを用意して以下のいずれかをトリガーとして話しかけると、スキルが起動します。

- 「サバゲー動画作って」
- 「ハイライト作成」
- 「戦闘シーンつないで」
- 「airsoft highlight」

## 前提

- **ffmpeg** が PATH にあること
- **Python 3** に `numpy` + `librosa`
- （任意・強く推奨）**[video-use](https://github.com/browser-use/video-use)** を導入済み
  - 本スキルは `video-use/helpers/transcribe.py` を流用してヒットコール検出を行います
  - ヒットコール検出を使わない（戦闘音検出のみ）場合は不要
- （ヒットコール検出を使う場合）**ElevenLabs API キー**（Speech to Text 権限）
  - 無料枠 10,000 クレジット/月 ≒ 約150分の転写
  - 月に1回サバゲーに行く程度なら無料枠でいけます

## パイプライン

1. **インベントリ**: GoProの4GB分割（`GH01xxxx`+`GH02xxxx`）を同一録画として束ねる
2. **戦闘検出 (`detect_action.py`)**: RMS + onset 強度の合成スコアで撃ち合い区間を抽出
3. **ヒットコール検出 (`detect_kills.py`)**: 転写から「ダウン」「やった」「ナイス」等の本人発話を拾う
4. **除外検出 (`detect_exclude.py`)**: 退場マーカー「ヒット通ります」、復活カウントダウン、位置報告を除外
5. **組み立て (`assemble.py`)**: クリップを尺指定で選抜・整列
6. **レンダリング (`render.py`)**: ffmpeg で再エンコードして連結

## チューニング

- 撃ち合いの厳選度 → `detect_action.py --pct`
- 完成尺 → `assemble.py --target`（秒）
- ヒットコールの語彙 → `detect_kills.py` の `PATTERNS`（プレイヤーの口癖に合わせて）

## 既知の制約

- **「ナイス」は両義語**: 当てた本人だけでなく、被弾した本人が相手を称える言葉でもある。退場マーカーの前10秒を除外ゾーンに入れることで対処
- **「N人」「入った」は位置報告と衝突**: ヒット宣言ではなく位置報告やカウントダウンで使われていることが多い。除外検出で対処
- **ハンドサインで宣言するヒット数は過小申告されがち**: ラベル数を「上限」ではなく「下限」として扱う設計

## ライセンス

MIT License. 詳細は [LICENSE](./LICENSE) を参照。
