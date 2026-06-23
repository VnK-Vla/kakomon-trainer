"""核医学専門医試験の出題分野分類。

日本核医学会「核医学専門医試験問題の領域」に準じた 10 分野へ、設問本文と
選択肢のキーワードから分類する。撮像系の汎用ツールである field_classifier.py
（放射線診断専門医向け）とは別系統で、核医学専門医試験専用に用いる。

分類はキーワードによる近似であり、臨床症例問題などは取りこぼしが出る。
個別の誤分類は本体アプリの設問ごとの分野エディタで修正できる。
"""

from __future__ import annotations

import re
import unicodedata


# 表示順（アプリの CATEGORY_ORDERS と揃える）
CAT_SAFETY = "医療安全・関連法規・倫理"
CAT_RADIOPHARM = "放射性医薬品の基礎知識"
CAT_IMAGING = "撮像機器・撮像法"
CAT_RESP_ENDO = "呼吸器・内分泌"
CAT_GI_URO = "消化器・泌尿器"
CAT_HEART = "心臓"
CAT_TUMOR = "腫瘍"
CAT_BONE = "骨・関節・軟部組織・炎症・血液・リンパ"
CAT_CNS = "中枢神経"
CAT_THERAPY = "核医学治療"

NUCLEAR_CATEGORIES = [
    CAT_SAFETY,
    CAT_RADIOPHARM,
    CAT_IMAGING,
    CAT_RESP_ENDO,
    CAT_GI_URO,
    CAT_HEART,
    CAT_TUMOR,
    CAT_BONE,
    CAT_CNS,
    CAT_THERAPY,
]

DEFAULT_CATEGORY = CAT_RADIOPHARM


def _compact(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.replace("ᵐ", "m")
    return re.sub(r"\s+", "", text)


def classify(stem: str, choices: list[str] | None = None) -> str:
    """設問本文から核医学 10 分野のいずれかを返す。

    優先順位の高い（具体的・誤りにくい）判定から順に評価し、最初に一致した
    分野を採用する。判定には設問本文（stem）のみを用いる。「組み合わせ／誤って
    いるのはどれか」型の設問では選択肢に他分野の語が多数並ぶため、選択肢を
    含めると誤分類が増える。choices は呼び出し側の互換性のために受け取るが
    判定には使用しない。
    """

    text = _compact(stem)

    def has(*words: str) -> bool:
        return any(word in text for word in words)

    # --- 物理・計算系の取り違え防止（臓器名を含んでも計算問題なら基礎へ） ---
    if has("数え落とし", "計数率", "分解時間", "cpm"):
        return CAT_IMAGING
    if has("比放射能", "有効半減期", "実効半減期", "生物学的半減期", "物理的半減期"):
        return CAT_RADIOPHARM

    # --- 核医学治療 ---
    if has(
        "内用療法",
        "核医学治療",
        "標的アイソトープ",
        "RI標識抗体療法",
        "抗体療法",
        "退出基準",
        "退出に関する",
        "患者の退出",
        "223Ra",
        "塩化ラジウム",
        "ゾーフィゴ",
        "ラジウム-223",
        "ゼヴァリン",
        "イブリツモマブ",
        "90Y",
        "イットリウム",
        "89Sr",
        "ストロンチウム",
        "メタストロン",
        "153Sm",
        "サマリウム",
        "177Lu",
        "ルテチウム",
        "DOTATATE",
        "PRRT",
    ):
        return CAT_THERAPY
    if has("治療") and has(
        "131I", "I-131", "放射性ヨウ素", "MIBG", "甲状腺癌", "甲状腺がん"
    ):
        return CAT_THERAPY

    # --- 中枢神経（認知症 + 心筋シンチ症例などより先に脳を拾う） ---
    if has(
        "脳血流",
        "脳循環",
        "脳代謝",
        "脳機能",
        "脳核医学",
        "脳神経",
        "脳槽",
        "脳脊髄液",
        "髄液",
        "認知症",
        "アルツハイマー",
        "レビー小体",
        "もの忘れ",
        "物忘れ",
        "記憶障害",
        "幻視",
        "MMSE",
        "認知機能",
        "ドパミントランスポータ",
        "ドーパミントランスポータ",
        "ioflupane",
        "イオフルパン",
        "線条体",
        "DAT",
        "IMP",
        "ECD",
        "HMPAO",
        "アミロイドβ",
        "アミロイドPET",
        "アミロイドイメージング",
        "flutemetamol",
        "PiB",
        "てんかん",
        "発作時脳血流",
        "パーキンソン",
        "もやもや病",
        "アセタゾラミド",
        "ダイアモックス",
        "脳血管反応性",
        "脳梗塞",
        "脳血管障害",
        "一過性脳虚血",
        "中大脳動脈",
        "神経膠腫",
        "貧困灌流",
        "miseryperfusion",
        "15O",
        "H2OPET",
    ):
        return CAT_CNS

    # --- 心臓 ---
    if has(
        "心筋",
        "心臓",
        "心電図同期",
        "心プール",
        "冠動脈",
        "冠攣縮",
        "狭心症",
        "心筋梗塞",
        "心不全",
        "心筋症",
        "心サルコイド",
        "BMIPP",
        "脂肪酸代謝",
        "QGS",
        "心縦隔比",
        "HMR",
        "H/CL",
        "ピロリン酸",
        "pyrophosphate",
        "PYP",
        "たこつぼ",
        "心アミロイド",
        "アミロイドーシス",
        "バイアビリティ",
    ):
        return CAT_HEART
    if has("虚血") and has("負荷", "冠", "心"):
        return CAT_HEART

    # --- 骨・関節・軟部組織・炎症・血液・リンパ ---
    if has(
        "骨シンチ",
        "骨転移",
        "骨折",
        "骨痛",
        "関節",
        "3相骨",
        "三相骨",
        "MDP",
        "HMDP",
        "炎症",
        "感染",
        "発熱",
        "不明熱",
        "サルコイドーシス",
        "ガリウム",
        "67Ga",
        "白血球シンチ",
        "リンパ管",
        "センチネルリンパ",
        "リンパ浮腫",
        "下肢浮腫",
        "浮腫",
        "骨髄",
        "脾腫",
        "脾臓",
    ):
        return CAT_BONE

    # --- 腫瘍 ---
    if has(
        "腫瘍",
        "悪性",
        "癌",
        "がん",
        "リンパ腫",
        "病期",
        "ステージング",
        "原発不明",
        "原発巣",
        "転移",
        "ペンテレオチド",
        "ソマトスタチン",
        "オクトレオ",
        "fluciclovine",
        "メチオニン",
        "PSMA",
        "黒色腫",
        "メラノーマ",
        "SUVmax",
    ):
        return CAT_TUMOR

    # --- 呼吸器・内分泌 ---
    if has(
        "肺血流",
        "肺換気",
        "換気シンチ",
        "換気血流",
        "肺塞栓",
        "肺梗塞",
        "肺シンチ",
        "MAA",
        "81mKr",
        "Kr肺",
    ):
        return CAT_RESP_ENDO
    if has(
        "甲状腺",
        "摂取率",
        "副甲状腺",
        "上皮小体",
        "副腎",
        "アドステロール",
        "褐色細胞腫",
        "高カルシウム血症",
        "パークロレイト",
        "甲状腺刺激",
        "アルドステロン",
    ):
        return CAT_RESP_ENDO

    # --- 消化器・泌尿器 ---
    if has(
        "肝",
        "胆道",
        "胆嚢",
        "肝胆道",
        "GSA",
        "アシアロ",
        "PMT",
        "唾液腺",
        "消化管",
        "蛋白漏出",
        "メッケル",
        "胃粘膜",
    ):
        return CAT_GI_URO
    if has(
        "腎",
        "レノグラム",
        "MAG3",
        "MAG",
        "DTPA",
        "DMSA",
        "利尿",
        "糸球体",
        "膀胱",
        "尿管",
        "GFR",
    ):
        return CAT_GI_URO

    # --- 撮像機器・撮像法 ---
    if has(
        "ガンマカメラ",
        "コリメータ",
        "シンチレータ",
        "検出器",
        "画像再構成",
        "再構成",
        "逐次近似",
        "OSEM",
        "減弱補正",
        "吸収補正",
        "散乱補正",
        "分解能",
        "ドーズキャリブレータ",
        "放射能測定装置",
        "ウェル型",
        "DLP",
        "doselengthproduct",
        "CTDI",
        "リングアーチファクト",
        "アーチファクト",
        "SUV",
        "定量",
        "動態解析",
        "半導体検出器",
    ):
        return CAT_IMAGING
    if re.search(r"(PET|SPECT)装置", text) or "PETについて" in text:
        return CAT_IMAGING

    # --- 医療安全・関連法規・倫理（被ばく・防護・法規は基礎より先に） ---
    if has(
        "被ばく",
        "被曝",
        "線量限度",
        "防護",
        "医療法",
        "施行規則",
        "法令",
        "法規",
        "関係法規",
        "技師法",
        "障害防止",
        "管理区域",
        "廃棄",
        "汚染",
        "安全管理",
        "安全取扱",
        "安全取り扱い",
        "遮へい",
        "遮蔽",
        "禁忌",
        "妊婦",
        "倫理",
        "個人情報",
        "医療事故",
        "保険診療",
        "保険適用",
        "届出",
        "線量記録",
    ):
        return CAT_SAFETY

    # --- 放射性医薬品の基礎知識（既定） ---
    return CAT_RADIOPHARM
