from __future__ import annotations

import re


FIELD_DEFAULT = "その他"
FIELD_BASIC = "基礎・安全・情報"
FIELD_NEURO = "神経・頭頸部"
FIELD_MSK = "骨軟部"
FIELD_CHEST = "胸部"
FIELD_CARDIO = "心大血管"
FIELD_BREAST = "乳腺"
FIELD_ABDOMEN = "腹部"
FIELD_URO_GYN = "泌尿器・婦人科"
FIELD_PEDIATRIC = "小児"
FIELD_IVR = "IVR"
FIELD_NUCLEAR = "核医学"


PATTERNS = [
    (
        FIELD_NUCLEAR,
        re.compile(
            r"SPECT|PET|シンチ|核医学|放射性医薬品|放射性|FDG|MIBG|MAG3|DMSA|MIBI|BMIPP|IMP|"
            r"ガリウム|Ga-citrate|Tc-|TcO4|123\s*I|131\s*I|177\s*Lu|67\s*Ga|99m\s*Tc|"
            r"集積|内用療法|甲状腺シンチ|骨シンチ|脳血流"
        ),
    ),
    (
        FIELD_BASIC,
        re.compile(
            r"線量|被ばく|線量計|画質|画像表示|PACS|DICOM|医療情報|情報システム|ランサムウェア|"
            r"Deep learning|AI|畳み込み|臨床研究|MRI 撮像法|MRI撮像法|超音波診断\(装置\)|"
            r"エックス線|X 線に対する|CTDI|陽子線|アーチファクト|品質管理|安全管理"
        ),
    ),
    (
        FIELD_CARDIO,
        re.compile(
            r"心臓|心筋|冠動脈|心電図|左室|右室|心室|心停止|除細動|心筋梗塞|大動脈|"
            r"肺動脈|肺塞栓|心電図同期|シネ MRI|遅延造影 MRI|心筋交感神経"
        ),
    ),
    (
        FIELD_IVR,
        re.compile(
            r"IVR|塞栓|動脈塞栓|血管塞栓|ステント|血管造影|DSA|カテーテル|ドレナージ|穿刺|"
            r"TAE|TACE|RFA|アブレーション|ラジオ波|止血術"
        ),
    ),
    (FIELD_BREAST, re.compile(r"乳房|乳腺|マンモグラフィ|マンモ|乳がん検診|右乳房|左乳房")),
    (
        FIELD_URO_GYN,
        re.compile(
            r"腎|尿管|膀胱|前立腺|精巣|副腎|子宮|卵巣|骨盤部|不正性器出血|妊娠|月経|下腹部|"
            r"子宮頸|子宮体|卵管|腟"
        ),
    ),
    (
        FIELD_ABDOMEN,
        re.compile(
            r"肝|胆|膵|脾|胃|十二指腸|小腸|大腸|直腸|虫垂|腹部|腹痛|嘔吐|腸管|"
            r"上腹部|心窩部|胆道|門脈|EOB|消化管|腹膜|後腹膜"
        ),
    ),
    (
        FIELD_CHEST,
        re.compile(
            r"胸部|肺|縦隔|気管|気管支|胸水|胸膜|気胸|咳嗽|呼吸|喀血|喘鳴|胸痛|"
            r"HRCT|肺野|縦隔条件|胸腔|横隔膜"
        ),
    ),
    (
        FIELD_MSK,
        re.compile(
            r"骨|関節|膝|股関節|足関節|足部|足趾|踵|下肢|上肢|肩|肘|手指|上腕|大腿|下腿|"
            r"前腕|脊椎|椎体|椎間板|"
            r"筋|軟部|骨肉腫|骨折|靭帯|半月板|STIR"
        ),
    ),
    (
        FIELD_NEURO,
        re.compile(
            r"頭部|脳|頭蓋|後頭蓋窩|小脳|大脳|脳室|髄膜|下垂体|視神経|眼窩|副鼻腔|顔面|"
            r"頸部|耳|内耳|咽頭|喉頭|唾液腺|甲状腺|てんかん|けいれん|痙攣|意識障害|認知|"
            r"頭痛|内頸動脈|脳梗塞|脳出血|MRA|FLAIR|拡散強調"
        ),
    ),
    (FIELD_PEDIATRIC, re.compile(r"胎児|新生児|生後|小児|男児|女児|乳児")),
]


def extract_question_number(question: str, explanation: str = "") -> int | None:
    for text in (question, explanation):
        match = re.search(r"問\s*(\d{1,3})", text or "")
        if match:
            return int(match.group(1))
    return None


def classify_by_number(year: str, question_number: int | None) -> str:
    if question_number is None:
        return FIELD_DEFAULT

    try:
        year_number = int(year)
    except (TypeError, ValueError):
        year_number = 0

    n = question_number
    if year_number >= 2024:
        if n <= 10:
            return FIELD_NEURO
        if n <= 20:
            return FIELD_MSK
        if n <= 35:
            return FIELD_CHEST
        if n <= 40:
            return FIELD_CARDIO
        if n <= 44:
            return FIELD_BREAST
        if n <= 49:
            return FIELD_PEDIATRIC
        if n <= 69:
            return FIELD_ABDOMEN
        if n <= 74:
            return FIELD_IVR
        if n <= 95:
            return FIELD_NUCLEAR
        return FIELD_BASIC

    if n <= 5:
        return FIELD_BASIC
    if n <= 18:
        return FIELD_NEURO
    if n <= 24:
        return FIELD_MSK
    if n <= 34:
        return FIELD_CHEST
    if n <= 39:
        return FIELD_CARDIO
    if n <= 42:
        return FIELD_BREAST
    if n <= 59:
        return FIELD_ABDOMEN
    if n <= 64:
        return FIELD_URO_GYN
    if n <= 76:
        return FIELD_NUCLEAR
    return FIELD_BASIC


def classify_question(question: str, year: str = "", question_number: int | None = None) -> str:
    text = re.sub(r"\s+", " ", question or "")
    for field, pattern in PATTERNS:
        if pattern.search(text):
            return field
    return classify_by_number(year, question_number)
