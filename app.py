# -*- coding: utf-8 -*-
"""
Phonics Pronunciation Trainer (ฝึกออกเสียงภาษาอังกฤษแบบ Phonics + บันทึกคะแนน)
================================================================================
แอปไฟล์เดียวด้วย Flask
  - บทเรียน Phonics 6 กลุ่ม (สระสั้น / digraph / blend / magic e / vowel team / r-controlled)
  - ฟังเสียงตัวอย่าง (Web Speech Synthesis) + ฟังทีละหน่วยเสียง
  - อัดเสียงผู้เรียนผ่านไมค์ (Web Speech Recognition) แล้วส่งมาให้เซิร์ฟเวอร์ตรวจให้คะแนน
  - ให้คะแนน 0-100 ด้วย difflib + Soundex (ความคล้ายเชิงเสียง) พร้อมคำแนะนำเจาะจงตำแหน่งที่ผิด
  - บันทึกทุกครั้งที่ฝึกลง SQLite (phonics.db): สถิติ / ประวัติ / กราฟ / อันดับ / ส่งออก CSV

วิธีใช้:
    pip install flask
    python app.py
    เปิด http://127.0.0.1:5000  (แนะนำ Google Chrome หรือ Microsoft Edge เพราะรองรับไมค์)
"""

import csv
import io
import os
import re
import sqlite3
import difflib
from datetime import datetime, date, timedelta

from flask import Flask, request, jsonify, Response, g

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "phonics.db")

app = Flask(__name__)


# ==============================================================================
#  ฐานข้อมูล
# ==============================================================================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name   TEXT    NOT NULL,
            group_id    TEXT    NOT NULL,
            word        TEXT    NOT NULL,
            heard       TEXT    NOT NULL DEFAULT '',
            score       INTEGER NOT NULL,
            confidence  REAL    NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL,
            created_day TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_name);
        CREATE INDEX IF NOT EXISTS idx_attempts_word ON attempts(user_name, word);
        CREATE INDEX IF NOT EXISTS idx_attempts_day  ON attempts(user_name, created_day);
        """
    )
    con.commit()
    con.close()


# ==============================================================================
#  บทเรียน Phonics
# ==============================================================================
LESSONS = [
    {
        "id": "short_vowels",
        "title": "สระเสียงสั้น (CVC)",
        "emoji": "🔤",
        "desc": "คำสามตัวอักษร พยัญชนะ + สระ + พยัญชนะ",
        "tip": "ออกเสียงสระให้สั้นและกระชับ ห้ามลากยาว เช่น cat ไม่ใช่ แคท-ท",
        "words": [
            {"w": "cat", "ipa": "/kaet/", "th": "แมว", "ph": [["c", "/k/"], ["a", "/ae/"], ["t", "/t/"]]},
            {"w": "bed", "ipa": "/bed/", "th": "เตียง", "ph": [["b", "/b/"], ["e", "/e/"], ["d", "/d/"]]},
            {"w": "pig", "ipa": "/pig/", "th": "หมู", "ph": [["p", "/p/"], ["i", "/i/"], ["g", "/g/"]]},
            {"w": "dog", "ipa": "/dog/", "th": "สุนัข", "ph": [["d", "/d/"], ["o", "/o/"], ["g", "/g/"]]},
            {"w": "sun", "ipa": "/sun/", "th": "ดวงอาทิตย์", "ph": [["s", "/s/"], ["u", "/u/"], ["n", "/n/"]]},
            {"w": "map", "ipa": "/maep/", "th": "แผนที่", "ph": [["m", "/m/"], ["a", "/ae/"], ["p", "/p/"]]},
            {"w": "hen", "ipa": "/hen/", "th": "แม่ไก่", "ph": [["h", "/h/"], ["e", "/e/"], ["n", "/n/"]]},
            {"w": "fox", "ipa": "/foks/", "th": "สุนัขจิ้งจอก", "ph": [["f", "/f/"], ["o", "/o/"], ["x", "/ks/"]]},
        ],
    },
    {
        "id": "digraphs",
        "title": "ตัวอักษรคู่ (Digraphs)",
        "emoji": "👯",
        "desc": "พยัญชนะสองตัวรวมกันแล้วได้เสียงใหม่หนึ่งเสียง",
        "tip": "th ต้องแลบลิ้นแตะฟันบน / sh ห่อปาก / ch ดันลมออกแรง",
        "words": [
            {"w": "ship", "ipa": "/ship/", "th": "เรือ", "ph": [["sh", "/sh/"], ["i", "/i/"], ["p", "/p/"]]},
            {"w": "chin", "ipa": "/chin/", "th": "คาง", "ph": [["ch", "/ch/"], ["i", "/i/"], ["n", "/n/"]]},
            {"w": "thin", "ipa": "/thin/", "th": "ผอม / บาง", "ph": [["th", "/th/"], ["i", "/i/"], ["n", "/n/"]]},
            {"w": "that", "ipa": "/that/", "th": "สิ่งนั้น", "ph": [["th", "/dh/"], ["a", "/ae/"], ["t", "/t/"]]},
            {"w": "whale", "ipa": "/weil/", "th": "ปลาวาฬ", "ph": [["wh", "/w/"], ["a_e", "/ei/"], ["l", "/l/"]]},
            {"w": "phone", "ipa": "/foun/", "th": "โทรศัพท์", "ph": [["ph", "/f/"], ["o_e", "/ou/"], ["n", "/n/"]]},
            {"w": "ring", "ipa": "/ring/", "th": "แหวน", "ph": [["r", "/r/"], ["i", "/i/"], ["ng", "/ng/"]]},
            {"w": "duck", "ipa": "/duk/", "th": "เป็ด", "ph": [["d", "/d/"], ["u", "/u/"], ["ck", "/k/"]]},
        ],
    },
    {
        "id": "blends",
        "title": "พยัญชนะควบ (Blends)",
        "emoji": "🧩",
        "desc": "พยัญชนะสองตัวติดกัน แต่ยังได้ยินครบทั้งสองเสียง",
        "tip": "ต้องได้ยินครบทุกเสียง เช่น black = b + l + a + ck ห้ามตัดเสียง l ทิ้ง",
        "words": [
            {"w": "black", "ipa": "/blaek/", "th": "สีดำ", "ph": [["bl", "/bl/"], ["a", "/ae/"], ["ck", "/k/"]]},
            {"w": "frog", "ipa": "/frog/", "th": "กบ", "ph": [["fr", "/fr/"], ["o", "/o/"], ["g", "/g/"]]},
            {"w": "stop", "ipa": "/stop/", "th": "หยุด", "ph": [["st", "/st/"], ["o", "/o/"], ["p", "/p/"]]},
            {"w": "swim", "ipa": "/swim/", "th": "ว่ายน้ำ", "ph": [["sw", "/sw/"], ["i", "/i/"], ["m", "/m/"]]},
            {"w": "plant", "ipa": "/plaent/", "th": "ต้นไม้", "ph": [["pl", "/pl/"], ["a", "/ae/"], ["nt", "/nt/"]]},
            {"w": "grass", "ipa": "/graes/", "th": "หญ้า", "ph": [["gr", "/gr/"], ["a", "/ae/"], ["ss", "/s/"]]},
            {"w": "clock", "ipa": "/klok/", "th": "นาฬิกา", "ph": [["cl", "/kl/"], ["o", "/o/"], ["ck", "/k/"]]},
            {"w": "brush", "ipa": "/brush/", "th": "แปรง", "ph": [["br", "/br/"], ["u", "/u/"], ["sh", "/sh/"]]},
        ],
    },
    {
        "id": "magic_e",
        "title": "Magic E (สระเสียงยาว)",
        "emoji": "✨",
        "desc": "e ท้ายคำไม่ออกเสียง แต่ทำให้สระข้างหน้าออกเสียงยาวตามชื่อตัวอักษร",
        "tip": "cap เปลี่ยนเป็น cape สระยาวขึ้น และห้ามออกเสียง e ตัวท้าย",
        "words": [
            {"w": "cake", "ipa": "/keik/", "th": "เค้ก", "ph": [["c", "/k/"], ["a_e", "/ei/"], ["k", "/k/"]]},
            {"w": "bike", "ipa": "/baik/", "th": "จักรยาน", "ph": [["b", "/b/"], ["i_e", "/ai/"], ["k", "/k/"]]},
            {"w": "home", "ipa": "/houm/", "th": "บ้าน", "ph": [["h", "/h/"], ["o_e", "/ou/"], ["m", "/m/"]]},
            {"w": "cute", "ipa": "/kjuut/", "th": "น่ารัก", "ph": [["c", "/k/"], ["u_e", "/juu/"], ["t", "/t/"]]},
            {"w": "note", "ipa": "/nout/", "th": "บันทึก", "ph": [["n", "/n/"], ["o_e", "/ou/"], ["t", "/t/"]]},
            {"w": "five", "ipa": "/faiv/", "th": "ห้า", "ph": [["f", "/f/"], ["i_e", "/ai/"], ["v", "/v/"]]},
            {"w": "rope", "ipa": "/roup/", "th": "เชือก", "ph": [["r", "/r/"], ["o_e", "/ou/"], ["p", "/p/"]]},
            {"w": "name", "ipa": "/neim/", "th": "ชื่อ", "ph": [["n", "/n/"], ["a_e", "/ei/"], ["m", "/m/"]]},
        ],
    },
    {
        "id": "vowel_teams",
        "title": "สระคู่ (Vowel Teams)",
        "emoji": "🤝",
        "desc": "สระสองตัวอยู่ด้วยกัน มักออกเสียงตัวหน้าแบบยาว",
        "tip": "จำกฎ When two vowels go walking, the first one does the talking",
        "words": [
            {"w": "rain", "ipa": "/rein/", "th": "ฝน", "ph": [["r", "/r/"], ["ai", "/ei/"], ["n", "/n/"]]},
            {"w": "boat", "ipa": "/bout/", "th": "เรือ", "ph": [["b", "/b/"], ["oa", "/ou/"], ["t", "/t/"]]},
            {"w": "feet", "ipa": "/fiit/", "th": "เท้า", "ph": [["f", "/f/"], ["ee", "/ii/"], ["t", "/t/"]]},
            {"w": "team", "ipa": "/tiim/", "th": "ทีม", "ph": [["t", "/t/"], ["ea", "/ii/"], ["m", "/m/"]]},
            {"w": "night", "ipa": "/nait/", "th": "กลางคืน", "ph": [["n", "/n/"], ["igh", "/ai/"], ["t", "/t/"]]},
            {"w": "book", "ipa": "/buk/", "th": "หนังสือ", "ph": [["b", "/b/"], ["oo", "/u/"], ["k", "/k/"]]},
            {"w": "moon", "ipa": "/muun/", "th": "ดวงจันทร์", "ph": [["m", "/m/"], ["oo", "/uu/"], ["n", "/n/"]]},
            {"w": "cloud", "ipa": "/klaud/", "th": "เมฆ", "ph": [["cl", "/kl/"], ["ou", "/au/"], ["d", "/d/"]]},
        ],
    },
    {
        "id": "r_controlled",
        "title": "สระผสม R (R-controlled)",
        "emoji": "🚗",
        "desc": "สระที่ตามด้วย r เสียงสระจะถูก r กลืน",
        "tip": "ห้ามรัวลิ้นแบบ ร เรือ ให้ม้วนลิ้นเข้าหาเพดานปากแล้วค้างไว้",
        "words": [
            {"w": "car", "ipa": "/kaar/", "th": "รถยนต์", "ph": [["c", "/k/"], ["ar", "/aar/"]]},
            {"w": "bird", "ipa": "/berd/", "th": "นก", "ph": [["b", "/b/"], ["ir", "/er/"], ["d", "/d/"]]},
            {"w": "horn", "ipa": "/horn/", "th": "แตร", "ph": [["h", "/h/"], ["or", "/or/"], ["n", "/n/"]]},
            {"w": "farm", "ipa": "/faarm/", "th": "ฟาร์ม", "ph": [["f", "/f/"], ["ar", "/aar/"], ["m", "/m/"]]},
            {"w": "turn", "ipa": "/tern/", "th": "เลี้ยว", "ph": [["t", "/t/"], ["ur", "/er/"], ["n", "/n/"]]},
            {"w": "star", "ipa": "/staar/", "th": "ดาว", "ph": [["st", "/st/"], ["ar", "/aar/"]]},
            {"w": "corn", "ipa": "/korn/", "th": "ข้าวโพด", "ph": [["c", "/k/"], ["or", "/or/"], ["n", "/n/"]]},
            {"w": "girl", "ipa": "/gerl/", "th": "เด็กผู้หญิง", "ph": [["g", "/g/"], ["ir", "/er/"], ["l", "/l/"]]},
        ],
    },
]

WORD_INDEX = {}
GROUP_TITLE = {}
for _grp in LESSONS:
    GROUP_TITLE[_grp["id"]] = _grp["title"]
    for _wd in _grp["words"]:
        WORD_INDEX[_wd["w"]] = _grp["id"]

TOTAL_WORDS = len(WORD_INDEX)
PASS_SCORE = 85          # คะแนนที่ถือว่า "ผ่าน" คำนั้นแล้ว


# ==============================================================================
#  ตรรกะการให้คะแนนการออกเสียง
# ==============================================================================
_SOUNDEX_CODE = {}
for _letters, _code in (
    ("bfpv", "1"),
    ("cgjkqsxz", "2"),
    ("dt", "3"),
    ("l", "4"),
    ("mn", "5"),
    ("r", "6"),
):
    for _ch in _letters:
        _SOUNDEX_CODE[_ch] = _code


def soundex(word):
    """คืนรหัส Soundex 4 ตัว ใช้เทียบว่า 'เสียงคล้ายกันไหม'"""
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return ""
    head = w[0].upper()
    tail = []
    prev = _SOUNDEX_CODE.get(w[0], "")
    for ch in w[1:]:
        code = _SOUNDEX_CODE.get(ch, "")
        if code and code != prev:
            tail.append(code)
        if ch not in "hw":
            prev = code
    return (head + "".join(tail) + "000")[:4]


def normalize(text):
    """ตัดอักขระพิเศษ ทำเป็นตัวพิมพ์เล็ก"""
    return re.sub(r"[^a-z\s']", " ", (text or "").lower()).strip()


def similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


# ------------------------------------------------------------------
#  ตัวแปลงสะกด -> หน่วยเสียง (grapheme to phoneme แบบง่ายตามกฎโฟนิกส์)
#  หัวใจของการให้คะแนน: เทียบกันที่ "เสียง" ไม่ใช่ "ตัวสะกด"
#  จึงแยกออกได้ว่า cat/cut (สระผิด) และ thin/tin (th เป็น t) คือคนละคำ
# ------------------------------------------------------------------
_MULTI_GRAPHEMES = [
    ("igh", "Y"), ("tch", "C"), ("dge", "J"),
    ("kn", "n"), ("wr", "r"),
    ("sh", "S"), ("ch", "C"), ("th", "T"), ("ph", "f"), ("wh", "w"),
    ("ng", "N"), ("ck", "k"), ("qu", "kw"),
    ("ee", "E"), ("ea", "E"), ("oo", "U"), ("oa", "O"),
    ("ai", "A"), ("ay", "A"), ("ou", "W"), ("ow", "W"),
    ("oi", "P"), ("oy", "P"), ("au", "o"), ("aw", "o"),
    ("ar", "R"), ("or", "9"), ("er", "3"), ("ir", "3"), ("ur", "3"),
]
_SINGLE_GRAPHEMES = {"c": "k", "x": "ks", "q": "k"}
_LONG_VOWEL = {"a": "A", "e": "E", "i": "Y", "o": "O", "u": "Q"}


def apply_magic_e(word):
    """cake -> cAk  (e ท้ายคำเงียบ แต่ทำให้สระข้างหน้าเป็นเสียงยาว)"""
    if len(word) < 4 or not word.endswith("e"):
        return word
    stem = word[:-1]
    if stem[-1] in "aeiou":
        return word
    i = len(stem) - 1
    while i >= 0 and stem[i] not in "aeiou":
        i -= 1
    if i < 0 or (len(stem) - 1 - i) > 2:
        return word
    return stem[:i] + _LONG_VOWEL[stem[i]] + stem[i + 1:]


def to_phonemes(text):
    """แปลงคำเป็นสายอักขระตัวแทนหน่วยเสียง เช่น thin -> Tin, cake -> kAk"""
    word = re.sub(r"[^a-z]", "", (text or "").lower())
    if not word:
        return ""
    word = apply_magic_e(word)
    out = []
    i = 0
    while i < len(word):
        for graph, phone in _MULTI_GRAPHEMES:
            if word.startswith(graph, i):
                out.append(phone)
                i += len(graph)
                break
        else:
            out.append(_SINGLE_GRAPHEMES.get(word[i], word[i]))
            i += 1
    return re.sub(r"(.)\1+", r"\1", "".join(out))  # ยุบเสียงซ้ำ เช่น ss -> s


# กลุ่มตัวอักษรที่ออกเสียงร่วมกัน ใช้ขยายช่วงที่ผิดให้เป็นหน่วยเสียงเต็ม ๆ
_CHUNKS = {
    "igh", "tch", "dge",
    "sh", "ch", "th", "ph", "wh", "ng", "ck", "qu", "kn", "wr",
    "ee", "ea", "oo", "oa", "ai", "ay", "ou", "ow", "oi", "oy", "au", "aw",
    "ar", "or", "er", "ir", "ur",
    "bl", "br", "cl", "cr", "dr", "fl", "fr", "gl", "gr", "pl", "pr",
    "sc", "sk", "sl", "sm", "sn", "sp", "st", "sw", "tr", "tw",
    "nt", "nd", "mp", "nk", "ss", "ll", "ff",
}


def expand_chunk(word, i1, i2):
    """ถ้าตำแหน่งที่ผิดเป็นส่วนหนึ่งของตัวอักษรคู่ (เช่น h ใน th) ให้คืนทั้งคู่"""
    for size in (3, 2):
        for start in range(max(0, i2 - size), min(i1, len(word) - size) + 1):
            end = start + size
            if start <= i1 and end >= max(i2, i1 + 1) and word[start:end] in _CHUNKS:
                return start, end
    return i1, i2


def where_in_word(word, start, end):
    pos = ((start + end) / 2.0) / max(len(word), 1)
    if pos < 0.34:
        return "เสียงต้นคำ"
    if pos < 0.72:
        return "เสียงสระตรงกลาง"
    return "เสียงท้ายคำ"


def make_hint(target, guess):
    """หาว่าเสียงส่วนไหนของคำที่เพี้ยน (ต้น / กลาง / ท้าย)"""
    if not guess:
        return "ระบบไม่ได้ยินเสียงเลย ลองพูดดังขึ้นและเข้าใกล้ไมค์อีกนิด"
    if guess == target:
        return ""
    if to_phonemes(guess) == to_phonemes(target):
        return "เสียงถูกต้องแล้ว ระบบแค่ถอดเป็นคำพ้องเสียงที่สะกดต่างกัน"

    same_frame = soundex(guess) == soundex(target)
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, target, guess).get_opcodes():
        if tag == "equal":
            continue
        start, end = expand_chunk(target, i1, i2)
        where = where_in_word(target, start, end if end > start else start + 1)
        part = target[start:end] or target[max(start - 1, 0):start + 1]
        if tag == "delete":
            return "ดูเหมือนจะออกเสียง '%s' ไม่ครบ ลองเน้น%sให้ชัดขึ้น" % (part, where)
        if tag == "insert":
            return "มีเสียงแทรกเกินมาที่%s ลองออกเสียงให้กระชับกว่านี้" % where
        if same_frame:
            return "พยัญชนะถูกหมดแล้ว เหลือ%sตรง '%s' ที่ยังไม่ตรง" % (where, part)
        return "ลองแก้ที่%s ตรงตัว '%s' ให้ชัดขึ้น" % (where, part)

    return "ใกล้เคียงมากแล้ว ลองอีกครั้งให้ชัดขึ้นอีกนิด"


def grade(score):
    if score >= 90:
        return "excellent", "ยอดเยี่ยม!", "เสียงชัดเป๊ะมาก เก่งมากเลย 🎉"
    if score >= 75:
        return "good", "ดีมาก!", "ใกล้เคียงเจ้าของภาษาแล้ว ฝึกอีกนิดเดียว 👍"
    if score >= 60:
        return "fair", "พอใช้", "ยังพอฟังออก แต่ยังต้องเก็บรายละเอียดของเสียง 💪"
    return "poor", "ลองใหม่อีกครั้ง", "ฟังเสียงตัวอย่างซ้ำ แล้วออกเสียงตามช้า ๆ ทีละหน่วยเสียง 🔁"


def score_pronunciation(target, heard, alternatives, confidence):
    """
    ให้คะแนน 0-100 จากข้อความที่ระบบรู้จำเสียงถอดออกมาได้

    หลักการ (เทียบกันที่ระดับหน่วยเสียง ไม่ใช่ตัวสะกด)
      - ถอดได้ตรงคำ                -> 88 + 12 x ความมั่นใจของระบบ (พูดชัดยิ่งได้เต็ม)
      - คนละคำแต่หน่วยเสียงตรงกัน  -> 92 (คำพ้องเสียง เช่น night / knight)
      - นอกนั้นคิดจากความคล้ายของสายหน่วยเสียง แล้วยกกำลัง 1.5 เพื่อไม่ให้ใจดีเกินไป
        (ผิดสระ 1 เสียงในคำ 3 เสียง จะเหลือราว 50 คะแนน ตามหลักโฟนิกส์)
      - ขาด / เกินหน่วยเสียง หัก 8 คะแนน  เช่น black อ่านเป็น back
      - ถ้าโครงพยัญชนะ (Soundex) ยังตรง ให้พื้นคะแนนขั้นต่ำ 45 กันท้อ
      - ถ้าคำที่ตรงที่สุดมาจากตัวเลือกสำรอง หักลำดับละ 2 คะแนน (สูงสุด 6)
    """
    target = normalize(target)
    target_ph = to_phonemes(target)
    target_sdx = soundex(target)

    try:
        conf = min(max(float(confidence), 0.0), 1.0)
    except (TypeError, ValueError):
        conf = 0.0

    candidates = []  # (ข้อความ, ลำดับตัวเลือก)
    for rank, text in enumerate([heard] + list(alternatives or [])):
        norm = normalize(text)
        if not norm:
            continue
        candidates.append((norm, rank))
        for token in norm.split():
            if token and token != norm:
                candidates.append((token, rank))

    if not candidates:
        return 0, "", "ไม่ได้ยินเสียงพูด ลองตรวจสอบไมโครโฟนแล้วพูดอีกครั้ง"

    best_score = -1.0
    best_text = candidates[0][0]

    for cand, rank in candidates:
        if cand == target:
            value = 100.0 if conf <= 0 else 88.0 + 12.0 * conf
        else:
            cand_ph = to_phonemes(cand)
            if cand_ph and cand_ph == target_ph:
                value = 92.0
            else:
                value = 100.0 * (similarity(target_ph, cand_ph) ** 1.5)
                if len(cand_ph) != len(target_ph):
                    value -= 8.0
                if soundex(cand) == target_sdx:
                    value = max(value, 45.0)
        value -= min(rank * 2.0, 6.0)
        if value > best_score:
            best_score = value
            best_text = cand

    final = int(max(0, min(100, round(best_score))))
    return final, best_text, make_hint(target, best_text)


# ==============================================================================
#  คิวรีสถิติ
# ==============================================================================
def calc_streak(days):
    """นับจำนวนวันติดต่อกันที่ฝึก (นับถอยจากวันนี้หรือเมื่อวาน)"""
    if not days:
        return 0
    day_set = {datetime.strptime(d, "%Y-%m-%d").date() for d in days}
    today = date.today()
    cursor = today if today in day_set else today - timedelta(days=1)
    if cursor not in day_set:
        return 0
    streak = 0
    while cursor in day_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def user_stats(user):
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) n, COALESCE(AVG(score),0) avg, COALESCE(MAX(score),0) best "
        "FROM attempts WHERE user_name=?",
        (user,),
    ).fetchone()

    today_row = db.execute(
        "SELECT COUNT(*) n, COALESCE(AVG(score),0) avg FROM attempts "
        "WHERE user_name=? AND created_day=?",
        (user, date.today().isoformat()),
    ).fetchone()

    mastered = db.execute(
        "SELECT COUNT(*) n FROM (SELECT word FROM attempts WHERE user_name=? "
        "GROUP BY word HAVING MAX(score)>=?)",
        (user, PASS_SCORE),
    ).fetchone()["n"]

    by_word = {
        r["word"]: r["best"]
        for r in db.execute(
            "SELECT word, MAX(score) best FROM attempts WHERE user_name=? GROUP BY word",
            (user,),
        )
    }

    by_group = {}
    for r in db.execute(
        "SELECT group_id, COUNT(*) n, AVG(score) avg FROM attempts "
        "WHERE user_name=? GROUP BY group_id",
        (user,),
    ):
        by_group[r["group_id"]] = {"n": r["n"], "avg": round(r["avg"], 1)}

    recent = [
        {"word": r["word"], "score": r["score"], "at": r["created_at"][11:16]}
        for r in db.execute(
            "SELECT word, score, created_at FROM attempts WHERE user_name=? "
            "ORDER BY id DESC LIMIT 12",
            (user,),
        )
    ]

    days = [
        r["created_day"]
        for r in db.execute(
            "SELECT DISTINCT created_day FROM attempts WHERE user_name=? "
            "ORDER BY created_day DESC LIMIT 400",
            (user,),
        )
    ]

    return {
        "total": row["n"],
        "avg": round(row["avg"], 1),
        "best": row["best"],
        "today": today_row["n"],
        "today_avg": round(today_row["avg"], 1),
        "mastered": mastered,
        "total_words": TOTAL_WORDS,
        "streak": calc_streak(days),
        "by_word": by_word,
        "by_group": by_group,
        "recent": recent,
        "trend": [r["score"] for r in reversed(recent)],
    }


# ==============================================================================
#  API
# ==============================================================================
@app.get("/api/lessons")
def api_lessons():
    return jsonify({"lessons": LESSONS, "pass_score": PASS_SCORE, "total_words": TOTAL_WORDS})


@app.post("/api/attempt")
def api_attempt():
    data = request.get_json(silent=True) or {}
    user = (data.get("user") or "").strip()[:40] or "guest"
    word = (data.get("word") or "").strip().lower()

    if word not in WORD_INDEX:
        return jsonify({"error": "ไม่พบคำศัพท์นี้ในบทเรียน"}), 400

    heard = (data.get("heard") or "").strip()[:120]
    alts = [str(a)[:120] for a in (data.get("alternatives") or [])][:8]
    conf = data.get("confidence", 0)

    score, matched, hint = score_pronunciation(word, heard, alts, conf)
    level, title, message = grade(score)

    now = datetime.now()
    db = get_db()
    db.execute(
        "INSERT INTO attempts (user_name, group_id, word, heard, score, confidence, "
        "created_at, created_day) VALUES (?,?,?,?,?,?,?,?)",
        (
            user,
            WORD_INDEX[word],
            word,
            heard,
            score,
            float(conf or 0),
            now.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d"),
        ),
    )
    db.commit()

    return jsonify(
        {
            "word": word,
            "heard": heard,
            "matched": matched,
            "score": score,
            "level": level,
            "title": title,
            "message": message,
            "hint": hint,
            "passed": score >= PASS_SCORE,
            "stats": user_stats(user),
        }
    )


@app.get("/api/stats")
def api_stats():
    user = (request.args.get("user") or "guest").strip()[:40]
    return jsonify(user_stats(user))


@app.get("/api/history")
def api_history():
    user = (request.args.get("user") or "guest").strip()[:40]
    limit = min(int(request.args.get("limit", 50) or 50), 300)
    rows = get_db().execute(
        "SELECT word, group_id, heard, score, created_at FROM attempts "
        "WHERE user_name=? ORDER BY id DESC LIMIT ?",
        (user, limit),
    )
    return jsonify(
        [
            {
                "word": r["word"],
                "group": GROUP_TITLE.get(r["group_id"], r["group_id"]),
                "heard": r["heard"],
                "score": r["score"],
                "at": r["created_at"],
            }
            for r in rows
        ]
    )


@app.get("/api/leaderboard")
def api_leaderboard():
    rows = get_db().execute(
        "SELECT user_name, COUNT(*) n, ROUND(AVG(score),1) avg, "
        "(SELECT COUNT(*) FROM (SELECT word FROM attempts a2 WHERE a2.user_name=a.user_name "
        " GROUP BY word HAVING MAX(score)>=?)) mastered "
        "FROM attempts a GROUP BY user_name HAVING n >= 3 "
        "ORDER BY mastered DESC, avg DESC LIMIT 10",
        (PASS_SCORE,),
    )
    return jsonify(
        [
            {"user": r["user_name"], "attempts": r["n"], "avg": r["avg"], "mastered": r["mastered"]}
            for r in rows
        ]
    )


@app.post("/api/reset")
def api_reset():
    data = request.get_json(silent=True) or {}
    user = (data.get("user") or "").strip()[:40]
    if not user:
        return jsonify({"error": "ต้องระบุชื่อผู้เรียน"}), 400
    db = get_db()
    cur = db.execute("DELETE FROM attempts WHERE user_name=?", (user,))
    db.commit()
    return jsonify({"deleted": cur.rowcount, "stats": user_stats(user)})


@app.get("/api/export.csv")
def api_export():
    user = (request.args.get("user") or "guest").strip()[:40]
    rows = get_db().execute(
        "SELECT created_at, word, group_id, heard, score, confidence FROM attempts "
        "WHERE user_name=? ORDER BY id",
        (user,),
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["datetime", "word", "phonics_group", "recognized", "score", "confidence"])
    for r in rows:
        writer.writerow(
            [
                r["created_at"],
                r["word"],
                GROUP_TITLE.get(r["group_id"], r["group_id"]),
                r["heard"],
                r["score"],
                round(r["confidence"], 3),
            ]
        )
    csv_bytes = ("﻿" + buf.getvalue()).encode("utf-8")
    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="phonics_%s.csv"' % user},
    )


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html; charset=utf-8")


# ==============================================================================
#  หน้าเว็บ (HTML + Tailwind CDN + JavaScript)
# ==============================================================================
PAGE = r"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phonics Trainer - ฝึกออกเสียงภาษาอังกฤษ</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='88'>&#128266;</text></svg>">
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Thai:wght@400;500;700&family=Fredoka:wght@500;600;700&display=swap" rel="stylesheet">
<script>
tailwind.config = {
  theme: {
    extend: {
      fontFamily: {
        sans: ['Noto Sans Thai', 'system-ui', 'sans-serif'],
        word: ['Fredoka', 'system-ui', 'sans-serif']
      },
      colors: {
        brand: { 50:'#eef6ff',100:'#d9ecff',200:'#bcdcff',300:'#8ec5ff',400:'#59a4ff',
                 500:'#3382fb',600:'#1d63f0',700:'#164ddc',800:'#183fb2',900:'#1a3a8c' }
      },
      keyframes: {
        pop: { '0%':{transform:'scale(.85)',opacity:'0'}, '100%':{transform:'scale(1)',opacity:'1'} },
        pulsemic: { '0%,100%':{ boxShadow:'0 0 0 0 rgba(239,68,68,.55)' },
                    '50%':{ boxShadow:'0 0 0 18px rgba(239,68,68,0)' } }
      },
      animation: { pop:'pop .25s ease-out', mic:'pulsemic 1.4s infinite' }
    }
  }
}
</script>
<style>
  body { background:
      radial-gradient(1100px 480px at 10% -10%, #dbeafe 0%, transparent 60%),
      radial-gradient(900px 420px at 100% 0%, #fae8ff 0%, transparent 55%),
      #f6f8fc; }
  ::-webkit-scrollbar { width: 9px; height: 9px; }
  ::-webkit-scrollbar-thumb { background: #c9d3e4; border-radius: 9px; }
  .card { background: rgba(255,255,255,.85); backdrop-filter: blur(6px); }
</style>
</head>
<body class="font-sans text-slate-800 min-h-screen">

<!-- ===== หน้าต่างใส่ชื่อ ===== -->
<div id="nameModal" class="fixed inset-0 z-50 hidden items-center justify-center bg-slate-900/50 p-4">
  <div class="w-full max-w-sm rounded-3xl bg-white p-7 shadow-2xl animate-pop">
    <div class="text-5xl text-center">🦜</div>
    <h2 class="mt-3 text-center text-xl font-bold">ยินดีต้อนรับสู่ Phonics Trainer</h2>
    <p class="mt-1 text-center text-sm text-slate-500">ใส่ชื่อผู้เรียน เพื่อบันทึกคะแนนการอ่านออกเสียง</p>
    <input id="nameInput" maxlength="40" placeholder="เช่น น้องมะปราง"
           class="mt-5 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200">
    <button onclick="saveName()"
            class="mt-4 w-full rounded-xl bg-brand-600 py-3 font-bold text-white transition hover:bg-brand-700">
      เริ่มฝึกเลย
    </button>
  </div>
</div>

<!-- ===== แถบหัว ===== -->
<header class="sticky top-0 z-40 border-b border-white/60 bg-white/75 backdrop-blur">
  <div class="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3">
    <div class="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-fuchsia-500 text-2xl shadow-lg shadow-brand-500/25">🔊</div>
    <div class="mr-auto">
      <h1 class="text-lg font-bold leading-tight">Phonics Trainer</h1>
      <p class="hidden text-xs text-slate-500 sm:block">ฝึกออกเสียงภาษาอังกฤษแบบโฟนิกส์ พร้อมบันทึกคะแนน</p>
    </div>
    <div id="streakChip" class="hidden items-center gap-1 whitespace-nowrap rounded-full bg-amber-100 px-3 py-1.5 text-sm font-bold text-amber-700">
      🔥 <span id="streakVal">0</span> วันติด
    </div>
    <button onclick="openName()"
            class="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold shadow-sm hover:bg-slate-50">
      <span class="grid h-6 w-6 place-items-center rounded-full bg-brand-100 text-brand-700" id="avatar">?</span>
      <span id="userChip">ผู้เรียน</span>
    </button>
  </div>
</header>

<main class="mx-auto grid max-w-7xl gap-5 p-4 lg:grid-cols-3">

  <!-- ================= คอลัมน์ซ้าย : บทเรียน ================= -->
  <section class="space-y-5 lg:col-span-2">

    <!-- เลือกกลุ่มโฟนิกส์ -->
    <div class="card rounded-3xl border border-white p-4 shadow-sm">
      <h2 class="mb-3 text-sm font-bold text-slate-500">เลือกกลุ่มเสียง</h2>
      <div id="groupTabs" class="grid grid-cols-2 gap-2 sm:grid-cols-3"></div>
      <div id="groupTip" class="mt-3 hidden rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <span class="font-bold">เคล็ดลับ: </span><span id="groupTipText"></span>
      </div>
    </div>

    <!-- แผงฝึกออกเสียง -->
    <div id="practice" class="card rounded-3xl border border-white p-6 text-center shadow-sm">
      <p class="text-slate-400">เลือกคำศัพท์ด้านล่างเพื่อเริ่มฝึกออกเสียง</p>
    </div>

    <!-- ตารางคำศัพท์ -->
    <div class="card rounded-3xl border border-white p-4 shadow-sm">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-bold text-slate-500">คำศัพท์ในบทนี้</h2>
        <span class="text-xs text-slate-400">✓ = เคยทำได้ตั้งแต่ 85 คะแนนขึ้นไป</span>
      </div>
      <div id="wordGrid" class="grid grid-cols-2 gap-3 sm:grid-cols-4"></div>
    </div>
  </section>

  <!-- ================= คอลัมน์ขวา : คะแนน ================= -->
  <aside class="space-y-5">

    <div class="card rounded-3xl border border-white p-5 shadow-sm">
      <h2 class="mb-4 text-sm font-bold text-slate-500">สรุปผลการฝึก</h2>
      <div class="grid grid-cols-2 gap-3">
        <div class="rounded-2xl bg-brand-50 p-3">
          <div class="text-2xl font-bold text-brand-700" id="stTotal">0</div>
          <div class="text-xs text-slate-500">ครั้งที่ฝึกทั้งหมด</div>
        </div>
        <div class="rounded-2xl bg-emerald-50 p-3">
          <div class="text-2xl font-bold text-emerald-700" id="stAvg">0</div>
          <div class="text-xs text-slate-500">คะแนนเฉลี่ย</div>
        </div>
        <div class="rounded-2xl bg-fuchsia-50 p-3">
          <div class="text-2xl font-bold text-fuchsia-700" id="stBest">0</div>
          <div class="text-xs text-slate-500">คะแนนสูงสุด</div>
        </div>
        <div class="rounded-2xl bg-amber-50 p-3">
          <div class="text-2xl font-bold text-amber-700" id="stToday">0</div>
          <div class="text-xs text-slate-500">ฝึกวันนี้ (ครั้ง)</div>
        </div>
      </div>

      <div class="mt-4">
        <div class="mb-1 flex justify-between text-xs font-semibold text-slate-500">
          <span>คำที่ผ่านแล้ว</span><span id="masteredLabel">0 / 0</span>
        </div>
        <div class="h-3 w-full overflow-hidden rounded-full bg-slate-200">
          <div id="masteredBar" class="h-full w-0 rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600 transition-all duration-500"></div>
        </div>
      </div>
    </div>

    <div class="card rounded-3xl border border-white p-5 shadow-sm">
      <h2 class="mb-3 text-sm font-bold text-slate-500">กราฟคะแนนล่าสุด</h2>
      <div id="trend" class="flex h-28 items-end gap-1.5"></div>
    </div>

    <div class="card rounded-3xl border border-white p-5 shadow-sm">
      <h2 class="mb-3 text-sm font-bold text-slate-500">ความก้าวหน้าแต่ละกลุ่มเสียง</h2>
      <div id="groupProgress" class="space-y-3 text-sm"></div>
    </div>

    <div class="card rounded-3xl border border-white p-5 shadow-sm">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-bold text-slate-500">ประวัติล่าสุด</h2>
        <button onclick="loadHistory()" class="text-xs font-semibold text-brand-600 hover:underline">รีเฟรช</button>
      </div>
      <div id="recentList" class="max-h-72 space-y-2 overflow-y-auto pr-1 text-sm"></div>
    </div>

    <div class="card rounded-3xl border border-white p-5 shadow-sm">
      <h2 class="mb-3 text-sm font-bold text-slate-500">🏆 อันดับผู้เรียน</h2>
      <div id="board" class="space-y-2 text-sm"></div>
    </div>

    <div class="flex gap-2">
      <a id="exportLink" href="#"
         class="flex-1 rounded-2xl border border-slate-200 bg-white py-2.5 text-center text-sm font-semibold shadow-sm hover:bg-slate-50">
        ⬇️ ส่งออก CSV
      </a>
      <button onclick="resetScores()"
              class="flex-1 rounded-2xl border border-rose-200 bg-white py-2.5 text-sm font-semibold text-rose-600 shadow-sm hover:bg-rose-50">
        🗑️ ล้างคะแนน
      </button>
    </div>
  </aside>
</main>

<div id="toast" class="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white opacity-0 shadow-xl transition-opacity"></div>

<script>
// ============================ สถานะของแอป ============================
const S = {
  user: localStorage.getItem('phonics_user') || '',
  lessons: [],
  group: null,
  word: null,
  stats: null,
  passScore: 85,
  listening: false,
  rec: null
};

const $ = (id) => document.getElementById(id);

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.style.opacity = '1';
  clearTimeout(t._t);
  t._t = setTimeout(() => { t.style.opacity = '0'; }, 2200);
}

// ============================ ชื่อผู้เรียน ============================
function openName() {
  $('nameInput').value = S.user;
  $('nameModal').classList.remove('hidden');
  $('nameModal').classList.add('flex');
  setTimeout(() => $('nameInput').focus(), 50);
}
function saveName() {
  const v = $('nameInput').value.trim();
  if (!v) { toast('กรุณาใส่ชื่อก่อนนะ'); return; }
  S.user = v;
  localStorage.setItem('phonics_user', v);
  $('nameModal').classList.add('hidden');
  $('nameModal').classList.remove('flex');
  applyUser();
  refreshAll();
}
function applyUser() {
  $('userChip').textContent = S.user || 'ผู้เรียน';
  $('avatar').textContent = (S.user || '?').trim().charAt(0).toUpperCase();
  $('exportLink').href = '/api/export.csv?user=' + encodeURIComponent(S.user);
}
$('nameInput').addEventListener('keydown', e => { if (e.key === 'Enter') saveName(); });

// ============================ เสียงตัวอย่าง ============================
let voice = null;
function pickVoice() {
  const vs = speechSynthesis.getVoices().filter(v => /^en(-|_)/i.test(v.lang));
  voice = vs.find(v => /US/i.test(v.lang) && /female|zira|samantha|aria/i.test(v.name)) || vs[0] || null;
}
pickVoice();
speechSynthesis.onvoiceschanged = pickVoice;

// เสียงตัวอย่างของแต่ละหน่วยเสียง (ถ้าให้ TTS อ่าน "b" เดี่ยว ๆ มันจะอ่านชื่อตัวอักษรว่า "บี" ซึ่งผิดหลักโฟนิกส์)
const SOUND_DEMO = {
  b:'buh', d:'duh', f:'fff', g:'guh', h:'huh', j:'yuh', k:'kuh', l:'lll', m:'mmm',
  n:'nnn', p:'puh', r:'ruh', s:'sss', t:'tuh', v:'vuh', w:'wuh', z:'zzz',
  ks:'ks', sh:'shhh', ch:'chuh', th:'thh', dh:'thuh', ng:'ng',
  bl:'bluh', br:'bruh', fr:'fruh', gr:'gruh', kl:'kluh', pl:'pluh', st:'stuh', sw:'swuh', nt:'nt',
  ae:'aa', e:'eh', i:'ih', o:'awe', u:'uh',
  ei:'ay', ai:'eye', ou:'oh', juu:'you', ii:'ee', uu:'oo', au:'ow',
  aar:'are', er:'ur', or:'or'
};

function speakSound(sound) {
  const demo = SOUND_DEMO[String(sound).replace(/\//g, '')];
  if (demo) speak(demo, 0.6);
  else if (S.word) speak(S.word.w, 0.45);   // ไม่มีตัวอย่าง ให้ฟังทั้งคำแบบช้าแทน
}

function speak(text, rate) {
  if (!('speechSynthesis' in window)) { toast('เบราว์เซอร์นี้ไม่รองรับการอ่านออกเสียง'); return; }
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'en-US';
  u.rate = rate || 0.9;
  if (voice) u.voice = voice;
  speechSynthesis.speak(u);
}

// ============================ โหลดบทเรียน ============================
async function loadLessons() {
  const r = await fetch('/api/lessons');
  const d = await r.json();
  S.lessons = d.lessons;
  S.passScore = d.pass_score;
  S.group = S.lessons[0];
  renderTabs();
  renderWords();
}

function renderTabs() {
  $('groupTabs').innerHTML = S.lessons.map(g => {
    const on = S.group && g.id === S.group.id;
    return '<button onclick="selectGroup(\'' + g.id + '\')" class="rounded-2xl border px-3 py-3 text-left transition ' +
      (on ? 'border-brand-500 bg-brand-50 shadow-sm ring-2 ring-brand-200'
          : 'border-slate-200 bg-white hover:border-brand-300 hover:bg-brand-50/40') + '">' +
      '<div class="text-xl">' + g.emoji + '</div>' +
      '<div class="mt-1 text-sm font-bold leading-tight">' + g.title + '</div>' +
      '<div class="mt-0.5 text-[11px] leading-snug text-slate-500">' + g.desc + '</div>' +
      '</button>';
  }).join('');
  $('groupTip').classList.remove('hidden');
  $('groupTipText').textContent = S.group.tip;
}

function selectGroup(id) {
  S.group = S.lessons.find(g => g.id === id);
  S.word = null;
  renderTabs();
  renderWords();
  $('practice').innerHTML = '<p class="text-slate-400">เลือกคำศัพท์ด้านล่างเพื่อเริ่มฝึกออกเสียง</p>';
}

function renderWords() {
  const best = (S.stats && S.stats.by_word) || {};
  $('wordGrid').innerHTML = S.group.words.map(w => {
    const b = best[w.w] || 0;
    const done = b >= S.passScore;
    const active = S.word && S.word.w === w.w;
    return '<button onclick="selectWord(\'' + w.w + '\')" class="relative rounded-2xl border p-3 text-left transition ' +
      (active ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-200' : 'border-slate-200 bg-white hover:-translate-y-0.5 hover:shadow-md') + '">' +
      (done ? '<span class="absolute right-2 top-2 grid h-5 w-5 place-items-center rounded-full bg-emerald-500 text-[11px] text-white">✓</span>' : '') +
      '<div class="font-word text-xl font-semibold">' + w.w + '</div>' +
      '<div class="text-xs text-slate-400">' + w.ipa + '</div>' +
      '<div class="mt-1 text-xs text-slate-500">' + w.th + '</div>' +
      (b ? '<div class="mt-1 text-[11px] font-bold ' + scoreColor(b) + '">สูงสุด ' + b + '</div>' : '') +
      '</button>';
  }).join('');
}

function scoreColor(s) {
  if (s >= 90) return 'text-emerald-600';
  if (s >= 75) return 'text-brand-600';
  if (s >= 60) return 'text-amber-600';
  return 'text-rose-600';
}

// ============================ แผงฝึกออกเสียง ============================
function selectWord(w) {
  S.word = S.group.words.find(x => x.w === w);
  renderWords();
  renderPractice();
  speak(S.word.w, 0.85);
  $('practice').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function renderPractice() {
  const w = S.word;
  const chips = w.ph.map(p =>
    '<button onclick="speakSound(\'' + p[1] + '\')" title="กดเพื่อฟังเสียงนี้" ' +
    'class="rounded-xl border border-slate-200 bg-white px-3 py-2 text-center transition hover:border-brand-400 hover:bg-brand-50">' +
    '<div class="font-word text-lg font-semibold">' + p[0] + '</div>' +
    '<div class="text-[11px] text-slate-500">' + p[1] + '</div></button>'
  ).join('');

  $('practice').innerHTML =
    '<div class="animate-pop">' +
      '<div class="text-xs font-semibold uppercase tracking-widest text-brand-500">' + S.group.title + '</div>' +
      '<div class="mt-1 font-word text-6xl font-bold tracking-tight">' + w.w + '</div>' +
      '<div class="mt-1 text-slate-500">' + w.ipa + ' &nbsp;•&nbsp; ' + w.th + '</div>' +
      '<div class="mt-4 flex flex-wrap justify-center gap-2">' + chips + '</div>' +
      '<div class="mt-5 flex flex-wrap justify-center gap-2">' +
        '<button onclick="speak(S.word.w,0.9)" class="rounded-full bg-slate-900 px-5 py-3 font-semibold text-white transition hover:bg-slate-700">🔈 ฟังเสียง</button>' +
        '<button onclick="speak(S.word.w,0.5)" class="rounded-full border border-slate-300 bg-white px-5 py-3 font-semibold transition hover:bg-slate-50">🐢 ฟังแบบช้า</button>' +
        '<button id="micBtn" onclick="toggleMic()" class="rounded-full bg-rose-500 px-6 py-3 font-bold text-white shadow-lg shadow-rose-500/30 transition hover:bg-rose-600">🎤 กดแล้วพูด</button>' +
      '</div>' +
      '<button onclick="manualMode()" class="mt-3 text-xs text-slate-400 underline hover:text-slate-600">ไมค์ใช้ไม่ได้? พิมพ์คำที่อ่านแทน</button>' +
      '<div id="result" class="mt-5"></div>' +
    '</div>';
}

// ============================ ระบบฟังเสียง ============================
function makeRecognizer() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.lang = 'en-US';
  r.interimResults = false;
  r.continuous = false;
  r.maxAlternatives = 5;
  return r;
}

function micUI(on) {
  S.listening = on;
  const b = $('micBtn');
  if (!b) return;
  b.textContent = on ? '⏹ กำลังฟัง... พูดเลย' : '🎤 กดแล้วพูด';
  b.className = on
    ? 'animate-mic rounded-full bg-rose-600 px-6 py-3 font-bold text-white shadow-lg'
    : 'rounded-full bg-rose-500 px-6 py-3 font-bold text-white shadow-lg shadow-rose-500/30 transition hover:bg-rose-600';
}

function toggleMic() {
  if (!S.word) return;
  if (S.listening && S.rec) { S.rec.stop(); return; }

  const rec = makeRecognizer();
  if (!rec) {
    toast('เบราว์เซอร์นี้ไม่รองรับไมค์ ลองใช้ Chrome หรือ Edge');
    manualMode();
    return;
  }
  S.rec = rec;
  $('result').innerHTML = '<p class="text-sm text-slate-400">กำลังฟัง... ออกเสียงคำว่า "' + S.word.w + '" ให้ชัด ๆ</p>';

  rec.onstart = () => micUI(true);
  rec.onend = () => { micUI(false); S.rec = null; };
  rec.onerror = (e) => {
    micUI(false);
    const msg = {
      'not-allowed': 'ยังไม่ได้อนุญาตให้ใช้ไมโครโฟน กรุณากดอนุญาตที่แถบเบราว์เซอร์',
      'no-speech': 'ไม่ได้ยินเสียงเลย ลองพูดดังขึ้นอีกนิด',
      'audio-capture': 'ไม่พบไมโครโฟนในเครื่อง',
      'network': 'การเชื่อมต่ออินเทอร์เน็ตมีปัญหา (ระบบรู้จำเสียงต้องใช้เน็ต)'
    }[e.error] || ('เกิดข้อผิดพลาด: ' + e.error);
    $('result').innerHTML = '<p class="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">' + msg + '</p>';
  };
  rec.onresult = (e) => {
    const res = e.results[0];
    const alts = [];
    for (let i = 0; i < res.length; i++) alts.push(res[i].transcript);
    submitAttempt(alts[0] || '', alts.slice(1), res[0].confidence || 0);
  };
  try { rec.start(); } catch (err) { micUI(false); }
}

function manualMode() {
  if (!S.word) return;
  const typed = prompt('พิมพ์คำที่คุณอ่านออกเสียง (โหมดสำรองสำหรับทดสอบ):', '');
  if (typed !== null && typed.trim()) submitAttempt(typed.trim(), [], 0);
}

// ============================ ส่งผลไปเก็บคะแนน ============================
async function submitAttempt(heard, alternatives, confidence) {
  $('result').innerHTML = '<p class="text-sm text-slate-400">กำลังตรวจคะแนน...</p>';
  const r = await fetch('/api/attempt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user: S.user, word: S.word.w, heard, alternatives, confidence })
  });
  const d = await r.json();
  if (d.error) { toast(d.error); return; }
  renderResult(d);
  S.stats = d.stats;
  renderStats();
  renderWords();
  loadHistory();
  loadBoard();
}

function renderResult(d) {
  const C = 2 * Math.PI * 52;
  const off = C * (1 - d.score / 100);
  const ring = { excellent: '#10b981', good: '#3382fb', fair: '#f59e0b', poor: '#f43f5e' }[d.level];
  const bg = { excellent: 'bg-emerald-50', good: 'bg-brand-50', fair: 'bg-amber-50', poor: 'bg-rose-50' }[d.level];

  $('result').innerHTML =
    '<div class="animate-pop rounded-3xl ' + bg + ' p-5">' +
      '<div class="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:text-left">' +
        '<svg viewBox="0 0 120 120" class="h-28 w-28 shrink-0 -rotate-90">' +
          '<circle cx="60" cy="60" r="52" fill="none" stroke="#e2e8f0" stroke-width="12"/>' +
          '<circle cx="60" cy="60" r="52" fill="none" stroke="' + ring + '" stroke-width="12" stroke-linecap="round" ' +
            'stroke-dasharray="' + C + '" stroke-dashoffset="' + off + '"/>' +
          '<text x="60" y="52" transform="rotate(90 60 60)" text-anchor="middle" dominant-baseline="middle" ' +
            'font-size="30" font-weight="700" fill="#0f172a">' + d.score + '</text>' +
          '<text x="60" y="76" transform="rotate(90 60 60)" text-anchor="middle" font-size="12" fill="#64748b">คะแนน</text>' +
        '</svg>' +
        '<div class="flex-1">' +
          '<div class="text-xl font-bold">' + d.title + (d.passed ? ' <span class="align-middle text-sm text-emerald-600">ผ่านคำนี้แล้ว ✓</span>' : '') + '</div>' +
          '<div class="mt-1 text-sm text-slate-600">' + d.message + '</div>' +
          '<div class="mt-3 rounded-xl bg-white/70 px-3 py-2 text-sm">' +
            '<span class="text-slate-500">ระบบได้ยินว่า: </span>' +
            '<span class="font-word font-semibold">' + (d.heard ? escapeHtml(d.heard) : '(ไม่มีเสียง)') + '</span>' +
            '<span class="text-slate-400"> / เป้าหมาย: </span><span class="font-word font-semibold">' + d.word + '</span>' +
            (d.matched && d.matched !== (d.heard || '').toLowerCase()
              ? '<div class="mt-1 text-xs text-slate-500">ให้คะแนนจากตัวเลือกที่ใกล้ที่สุดของระบบ: <span class="font-word font-semibold">' + escapeHtml(d.matched) + '</span></div>'
              : '') +
          '</div>' +
          (d.hint ? '<div class="mt-2 text-sm text-slate-600">💡 ' + d.hint + '</div>' : '') +
          '<div class="mt-3 flex gap-2">' +
            '<button onclick="speak(S.word.w,0.6)" class="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-slate-50">🔈 ฟังซ้ำช้า ๆ</button>' +
            '<button onclick="toggleMic()" class="rounded-full bg-rose-500 px-4 py-2 text-sm font-bold text-white hover:bg-rose-600">🔁 ลองอีกครั้ง</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ============================ สถิติ / ประวัติ / อันดับ ============================
async function loadStats() {
  const r = await fetch('/api/stats?user=' + encodeURIComponent(S.user));
  S.stats = await r.json();
  renderStats();
  renderWords();
}

function renderStats() {
  const s = S.stats;
  if (!s) return;
  $('stTotal').textContent = s.total;
  $('stAvg').textContent = s.avg;
  $('stBest').textContent = s.best;
  $('stToday').textContent = s.today;
  $('masteredLabel').textContent = s.mastered + ' / ' + s.total_words;
  $('masteredBar').style.width = (s.total_words ? (s.mastered / s.total_words * 100) : 0) + '%';

  $('streakVal').textContent = s.streak;
  $('streakChip').classList.toggle('hidden', s.streak <= 0);
  $('streakChip').classList.toggle('flex', s.streak > 0);

  // กราฟแท่งคะแนนล่าสุด
  const tr = s.trend || [];
  $('trend').innerHTML = tr.length
    ? tr.map(v => '<div class="group relative flex h-full flex-1 items-end">' +
        '<div class="w-full rounded-t-md transition-all duration-500 ' + barColor(v) + '" style="height:' + Math.max(6, v) + '%"></div>' +
        '<div class="absolute inset-x-0 -top-1 text-center text-[10px] font-bold text-slate-600 opacity-0 transition group-hover:opacity-100">' + v + '</div>' +
        '</div>').join('')
    : '<p class="w-full self-center text-center text-sm text-slate-400">ยังไม่มีข้อมูล</p>';

  // ความก้าวหน้าแต่ละกลุ่ม
  $('groupProgress').innerHTML = S.lessons.map(g => {
    const total = g.words.length;
    const done = g.words.filter(w => (s.by_word[w.w] || 0) >= S.passScore).length;
    const gAvg = s.by_group[g.id] ? s.by_group[g.id].avg : 0;
    return '<div>' +
      '<div class="mb-1 flex justify-between text-xs">' +
        '<span class="font-semibold">' + g.emoji + ' ' + g.title + '</span>' +
        '<span class="text-slate-500">' + done + '/' + total + (gAvg ? ' • เฉลี่ย ' + gAvg : '') + '</span>' +
      '</div>' +
      '<div class="h-2 overflow-hidden rounded-full bg-slate-200">' +
        '<div class="h-full rounded-full bg-brand-500 transition-all duration-500" style="width:' + (done / total * 100) + '%"></div>' +
      '</div></div>';
  }).join('');
}

function barColor(v) {
  if (v >= 90) return 'bg-emerald-500';
  if (v >= 75) return 'bg-brand-500';
  if (v >= 60) return 'bg-amber-400';
  return 'bg-rose-400';
}

async function loadHistory() {
  const r = await fetch('/api/history?user=' + encodeURIComponent(S.user) + '&limit=40');
  const rows = await r.json();
  $('recentList').innerHTML = rows.length
    ? rows.map(h =>
        '<div class="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2">' +
          '<span class="font-word font-semibold">' + h.word + '</span>' +
          '<span class="truncate text-xs text-slate-400">' + escapeHtml(h.heard || '-') + '</span>' +
          '<span class="ml-auto text-[11px] text-slate-400">' + h.at.slice(5, 16) + '</span>' +
          '<span class="w-9 text-right font-bold ' + scoreColor(h.score) + '">' + h.score + '</span>' +
        '</div>').join('')
    : '<p class="text-sm text-slate-400">ยังไม่มีประวัติการฝึก</p>';
}

async function loadBoard() {
  const r = await fetch('/api/leaderboard');
  const rows = await r.json();
  const medal = ['🥇', '🥈', '🥉'];
  $('board').innerHTML = rows.length
    ? rows.map((b, i) =>
        '<div class="flex items-center gap-2 rounded-xl px-3 py-2 ' + (b.user === S.user ? 'bg-brand-50 ring-1 ring-brand-200' : 'bg-slate-50') + '">' +
          '<span class="w-6">' + (medal[i] || (i + 1)) + '</span>' +
          '<span class="truncate font-semibold">' + escapeHtml(b.user) + '</span>' +
          '<span class="ml-auto text-xs text-slate-500">ผ่าน ' + b.mastered + ' คำ</span>' +
          '<span class="w-10 text-right font-bold text-brand-700">' + b.avg + '</span>' +
        '</div>').join('')
    : '<p class="text-sm text-slate-400">ฝึกครบ 3 ครั้งเพื่อขึ้นกระดานอันดับ</p>';
}

async function resetScores() {
  if (!confirm('ต้องการลบคะแนนทั้งหมดของ "' + S.user + '" ใช่หรือไม่? การลบนี้ย้อนกลับไม่ได้')) return;
  const r = await fetch('/api/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user: S.user })
  });
  const d = await r.json();
  if (d.error) { toast(d.error); return; }
  toast('ลบคะแนนแล้ว ' + d.deleted + ' รายการ');
  refreshAll();
  $('practice').innerHTML = '<p class="text-slate-400">เลือกคำศัพท์ด้านล่างเพื่อเริ่มฝึกออกเสียง</p>';
  S.word = null;
}

function refreshAll() {
  loadStats();
  loadHistory();
  loadBoard();
}

// ============================ เริ่มทำงาน ============================
(async function init() {
  applyUser();
  await loadLessons();
  if (!S.user) openName(); else refreshAll();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    # คอนโซลของ Windows บางเครื่องเป็น cp874/cp1252 พิมพ์ภาษาไทยแล้วพัง จึงบังคับเป็น UTF-8
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    init_db()
    print("=" * 66)
    print(" Phonics Pronunciation Trainer")
    print(" เปิดเบราว์เซอร์ที่  http://127.0.0.1:5000")
    print(" ฐานข้อมูลคะแนน: %s" % DB_PATH)
    print(" แนะนำให้ใช้ Chrome หรือ Edge เพราะต้องใช้ไมโครโฟน")
    print("=" * 66)
    app.run(host="127.0.0.1", port=5000, debug=True)
