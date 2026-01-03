# magazzino.py
from flask import Flask, render_template, redirect, url_for, request, jsonify, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import func, select, or_, text
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from typing import Optional
import json
import os, io, csv

# ===================== DEFAULT ETICHETTE =====================
DEFAULT_LABEL_W_MM = 50
DEFAULT_LABEL_H_MM = 10
DEFAULT_MARG_TB_MM = 15
DEFAULT_MARG_LR_MM = 10
DEFAULT_GAP_MM     = 1
DEFAULT_LABEL_PADDING_MM = 1.5
DEFAULT_LABEL_QR_SIZE_MM = 9
DEFAULT_LABEL_QR_MARGIN_MM = 1
DEFAULT_LABEL_POSITION_WIDTH_MM = 12
DEFAULT_LABEL_POSITION_FONT_PT = 7.0
DEFAULT_ORIENTATION_LANDSCAPE = True
DEFAULT_QR_DEFAULT = True
DEFAULT_QR_BASE_URL = None  # es. "https://magazzino.local"
DEFAULT_MQTT_HOST = "localhost"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_TOPIC = "magazzino/slot"
DEFAULT_MQTT_QOS = 0
DEFAULT_MQTT_RETAIN = False

def mm_to_pt(mm): return mm * 2.8346456693

# ===================== FLASK & DB =====================
app = Flask(__name__, instance_relative_config=True)
app.config['SECRET_KEY'] = "supersecret"
os.makedirs(app.instance_path, exist_ok=True)
db_path = os.path.join(app.instance_path, "magazzino.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ===================== MODELS =====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    label_w_mm = db.Column(db.Float, nullable=False, default=DEFAULT_LABEL_W_MM)
    label_h_mm = db.Column(db.Float, nullable=False, default=DEFAULT_LABEL_H_MM)
    margin_tb_mm = db.Column(db.Float, nullable=False, default=DEFAULT_MARG_TB_MM)
    margin_lr_mm = db.Column(db.Float, nullable=False, default=DEFAULT_MARG_LR_MM)
    gap_mm = db.Column(db.Float, nullable=False, default=DEFAULT_GAP_MM)
    label_padding_mm = db.Column(db.Float, nullable=False, default=DEFAULT_LABEL_PADDING_MM)
    label_qr_size_mm = db.Column(db.Float, nullable=False, default=DEFAULT_LABEL_QR_SIZE_MM)
    label_qr_margin_mm = db.Column(db.Float, nullable=False, default=DEFAULT_LABEL_QR_MARGIN_MM)
    label_position_width_mm = db.Column(db.Float, nullable=False, default=DEFAULT_LABEL_POSITION_WIDTH_MM)
    label_position_font_pt = db.Column(db.Float, nullable=False, default=DEFAULT_LABEL_POSITION_FONT_PT)
    orientation_landscape = db.Column(db.Boolean, nullable=False, default=DEFAULT_ORIENTATION_LANDSCAPE)
    qr_default = db.Column(db.Boolean, nullable=False, default=DEFAULT_QR_DEFAULT)
    qr_base_url = db.Column(db.String(200), nullable=True)

class MqttSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    host = db.Column(db.String(200), nullable=True)
    port = db.Column(db.Integer, nullable=False, default=DEFAULT_MQTT_PORT)
    username = db.Column(db.String(200), nullable=True)
    password = db.Column(db.String(200), nullable=True)
    topic = db.Column(db.String(200), nullable=True)
    qos = db.Column(db.Integer, nullable=False, default=DEFAULT_MQTT_QOS)
    retain = db.Column(db.Boolean, nullable=False, default=DEFAULT_MQTT_RETAIN)
    client_id = db.Column(db.String(120), nullable=True)
    include_cabinet_name = db.Column(db.Boolean, nullable=False, default=True)
    include_cabinet_id = db.Column(db.Boolean, nullable=False, default=True)
    include_location_name = db.Column(db.Boolean, nullable=False, default=True)
    include_location_id = db.Column(db.Boolean, nullable=False, default=False)
    include_row = db.Column(db.Boolean, nullable=False, default=True)
    include_col = db.Column(db.Boolean, nullable=False, default=True)
    include_slot_label = db.Column(db.Boolean, nullable=False, default=True)
    include_items = db.Column(db.Boolean, nullable=False, default=True)
    include_item_id = db.Column(db.Boolean, nullable=False, default=True)
    include_item_name = db.Column(db.Boolean, nullable=False, default=True)
    include_item_category = db.Column(db.Boolean, nullable=False, default=True)
    include_item_category_color = db.Column(db.Boolean, nullable=False, default=False)
    include_item_quantity = db.Column(db.Boolean, nullable=False, default=True)
    include_item_position = db.Column(db.Boolean, nullable=False, default=True)
    include_item_description = db.Column(db.Boolean, nullable=False, default=False)
    include_item_material = db.Column(db.Boolean, nullable=False, default=False)
    include_item_finish = db.Column(db.Boolean, nullable=False, default=False)
    include_empty = db.Column(db.Boolean, nullable=False, default=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#000000")  # HEX
    main_measure_mode = db.Column(db.String(16), nullable=False, default="length")
    __table_args__ = (db.Index("ix_category_name", "name"),)

class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    __table_args__ = (db.Index("ix_material_name", "name"),)

class Finish(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    __table_args__ = (db.Index("ix_finish_name", "name"),)

class ThreadStandard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(8), unique=True, nullable=False)
    label = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (db.Index("ix_thread_standard_code", "code"),)

class ThreadSize(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    standard_id = db.Column(db.Integer, db.ForeignKey("thread_standard.id"), nullable=False)
    value = db.Column(db.String(32), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (
        db.UniqueConstraint('standard_id', 'value', name='uq_size_per_standard'),
        db.Index("ix_thread_size_standard_value", "standard_id", "value"),
    )
    standard = db.relationship("ThreadStandard")

class CustomField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    field_type = db.Column(db.String(16), nullable=False, default="text")
    options = db.Column(db.String(512), nullable=True)
    unit = db.Column(db.String(32), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

class CategoryFieldSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    field_key = db.Column(db.String(64), nullable=False)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (
        db.UniqueConstraint('category_id', 'field_key', name='uq_field_per_category'),
        db.Index("ix_category_field_setting_category", "category_id"),
    )

class ItemCustomFieldValue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey("custom_field.id"), nullable=False)
    value_text = db.Column(db.String(255), nullable=True)
    __table_args__ = (
        db.UniqueConstraint('item_id', 'field_id', name='uq_custom_field_value'),
        db.Index("ix_item_custom_field_value_item", "item_id"),
    )

class Subtype(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    __table_args__ = (
        db.UniqueConstraint('category_id', 'name', name='uq_subtype_per_category'),
        db.Index("ix_subtype_category", "category_id"),
    )

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)  # solo nome
    __table_args__ = (db.Index("ix_location_name", "name"),)

class Cabinet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    name = db.Column(db.String(80), unique=True, nullable=False)  # univoco globale
    rows_max = db.Column(db.Integer, nullable=False, default=128)
    cols_max = db.Column(db.String(2), nullable=False, default="ZZ")  # A..Z, AA..ZZ
    compartments_per_slot = db.Column(db.Integer, nullable=False, default=6)
    __table_args__ = (db.Index("ix_cabinet_location", "location_id"),)

class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cabinet_id = db.Column(db.Integer, db.ForeignKey("cabinet.id"), nullable=False)
    row_num = db.Column(db.Integer, nullable=False)         # 1..128
    col_code = db.Column(db.String(2), nullable=False)      # A..Z, AA..ZZ
    is_blocked = db.Column(db.Boolean, nullable=False, default=False)
    display_label_override = db.Column(db.String(80), nullable=True)
    print_label_override = db.Column(db.String(80), nullable=True)
    __table_args__ = (
        db.UniqueConstraint('cabinet_id', 'row_num', 'col_code', name='uq_slot_in_cabinet'),
        db.Index("ix_slot_cabinet_row_col", "cabinet_id", "row_num", "col_code"),
    )

class DrawerMerge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cabinet_id = db.Column(db.Integer, db.ForeignKey("cabinet.id"), nullable=False)
    row_start = db.Column(db.Integer, nullable=False)
    row_end = db.Column(db.Integer, nullable=False)
    col_start = db.Column(db.String(2), nullable=False)
    col_end = db.Column(db.String(2), nullable=False)
    __table_args__ = (db.Index("ix_drawer_merge_cabinet", "cabinet_id"),)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    subtype_id  = db.Column(db.Integer, db.ForeignKey("subtype.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False, default="")  # auto-composizione
    description = db.Column(db.String(255), nullable=True)
    share_drawer = db.Column(db.Boolean, nullable=False, default=False)
    # filettatura / misura
    thread_standard = db.Column(db.String(8), nullable=True)  # M, UNC, UNF
    thread_size     = db.Column(db.String(32), nullable=True) # "M3", "1/4-20", ...
    # dimensioni principali
    inner_d_mm      = db.Column(db.Float, nullable=True)      # foro interno (rondelle)
    thickness_mm    = db.Column(db.Float, nullable=True)      # spessore (rondelle)
    length_mm       = db.Column(db.Float, nullable=True)      # lunghezza
    outer_d_mm      = db.Column(db.Float, nullable=True)      # Ø esterno
    # materiali/quantità
    material_id     = db.Column(db.Integer, db.ForeignKey("material.id"), nullable=True)
    finish_id       = db.Column(db.Integer, db.ForeignKey("finish.id"), nullable=True)
    quantity        = db.Column(db.Integer, nullable=False, default=0)
    # flag etichetta
    label_show_category = db.Column(db.Boolean, nullable=False, default=True)
    label_show_subtype  = db.Column(db.Boolean, nullable=False, default=True)
    label_show_thread   = db.Column(db.Boolean, nullable=False, default=True)
    label_show_measure  = db.Column(db.Boolean, nullable=False, default=True)
    label_show_main     = db.Column(db.Boolean, nullable=False, default=True)
    label_show_material = db.Column(db.Boolean, nullable=False, default=True)

    category = db.relationship("Category")
    subtype  = db.relationship("Subtype")
    material = db.relationship("Material")
    finish   = db.relationship("Finish")
    __table_args__ = (
        db.Index("ix_item_category", "category_id"),
        db.Index("ix_item_subtype", "subtype_id"),
        db.Index("ix_item_material", "material_id"),
        db.Index("ix_item_finish", "finish_id"),
        db.Index("ix_item_thread_size", "thread_size"),
    )

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("slot.id"), nullable=False)
    compartment_no = db.Column(db.Integer, nullable=False, default=1)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
    __table_args__ = (
        db.Index("ix_assignment_item", "item_id"),
        db.Index("ix_assignment_slot", "slot_id"),
    )
    __table_args__ = (db.UniqueConstraint('slot_id', 'compartment_no', name='uq_compartment_in_slot'),)

# ===================== HELPERS =====================
def column_code_valid(code: str) -> bool:
    if not code: return False
    code = code.strip().upper()
    if len(code) == 1:   return 'A' <= code <= 'Z'
    if len(code) == 2:   return 'A' <= code[0] <= 'Z' and 'A' <= code[1] <= 'Z'
    return False

def colcode_to_idx(code:str)->int:
    code = code.strip().upper()
    if len(code)==1: return ord(code)-64
    if len(code)==2:
        first = ord(code[0]) - 65
        second = ord(code[1]) - 64
        return 26 + first*26 + second
    return 0

def idx_to_colcode(idx:int)->str:
    if idx<=26: return chr(64+idx)
    rem = idx - 26
    first = (rem-1)//26
    second = (rem-1)%26 + 1
    return chr(65+first) + chr(64+second)

def iter_cols_upto(max_code:str):
    max_i = colcode_to_idx(max_code)
    max_i = max(1, min(max_i, 702))
    for i in range(1, max_i+1):
        yield idx_to_colcode(i)

def normalize_merge_bounds(cab: Cabinet, col_start: str, col_end: str, row_start: int, row_end: int):
    if not (column_code_valid(col_start) and column_code_valid(col_end)):
        raise ValueError("Colonna non valida (A..Z o AA..ZZ).")
    if not (1 <= int(row_start) <= 128 and 1 <= int(row_end) <= 128):
        raise ValueError("Riga non valida (1..128).")
    max_col_idx = colcode_to_idx(cab.cols_max or "Z")
    c_start_idx = colcode_to_idx(col_start)
    c_end_idx = colcode_to_idx(col_end)
    if c_start_idx == 0 or c_end_idx == 0:
        raise ValueError("Colonna non valida (A..Z o AA..ZZ).")
    if c_start_idx > c_end_idx:
        c_start_idx, c_end_idx = c_end_idx, c_start_idx
    if row_start > row_end:
        row_start, row_end = row_end, row_start
    if row_start < 1 or row_end > cab.rows_max:
        raise ValueError("Righe fuori dai limiti della cassettiera.")
    if c_start_idx < 1 or c_end_idx > max_col_idx:
        raise ValueError("Colonne fuori dai limiti della cassettiera.")
    if row_start == row_end and c_start_idx == c_end_idx:
        raise ValueError("Seleziona almeno due celle adiacenti.")
    return row_start, row_end, idx_to_colcode(c_start_idx), idx_to_colcode(c_end_idx)

def merge_region_for(cabinet_id: int, col_code: str, row_num: int):
    merges = DrawerMerge.query.filter_by(cabinet_id=cabinet_id).all()
    if not merges:
        return None
    col_idx = colcode_to_idx(col_code)
    for m in merges:
        start_idx = colcode_to_idx(m.col_start)
        end_idx = colcode_to_idx(m.col_end)
        if start_idx > end_idx:
            start_idx, end_idx = end_idx, start_idx
        row_start = min(m.row_start, m.row_end)
        row_end = max(m.row_start, m.row_end)
        if start_idx <= col_idx <= end_idx and row_start <= row_num <= row_end:
            return {
                "anchor_col": idx_to_colcode(start_idx),
                "anchor_row": row_start,
                "row_start": row_start,
                "row_end": row_end,
                "col_start": idx_to_colcode(start_idx),
                "col_end": idx_to_colcode(end_idx),
            }
    return None

def merge_cells_from_region(region):
    if not region:
        return []
    start_idx = colcode_to_idx(region["col_start"])
    end_idx = colcode_to_idx(region["col_end"])
    cells = []
    for row in range(region["row_start"], region["row_end"] + 1):
        for col_idx in range(start_idx, end_idx + 1):
            cells.append((idx_to_colcode(col_idx), row))
    return cells


def _merged_cell_multiplier(cabinet: Cabinet | None, col_code: str, row_num: int) -> int:
    if not cabinet:
        return 1
    region = merge_region_for(cabinet.id, col_code, row_num)
    if not region:
        return 1
    start_idx = colcode_to_idx(region["col_start"])
    end_idx = colcode_to_idx(region["col_end"])
    cols = max(1, end_idx - start_idx + 1)
    rows = max(1, region["row_end"] - region["row_start"] + 1)
    return cols * rows


def _max_compartments_for_slot(cabinet: Cabinet | None, col_code: str, row_num: int) -> int:
    base = cabinet.compartments_per_slot if cabinet else None
    base = base or 6
    multiplier = _merged_cell_multiplier(cabinet, col_code, row_num)
    return max(1, int(base)) * max(1, multiplier)


def _collect_region_assignments(cabinet_id: int, col_code: str, row_num: int, *, ignore_item_id: int | None = None):
    """
    Raccoglie slot e assegnamenti per la cella indicata, includendo tutte le celle fuse.
    Restituisce (anchor_slot, all_slots, assignments, items).
    """
    region = merge_region_for(cabinet_id, col_code, row_num)
    anchor_col = col_code
    anchor_row = row_num
    cells = [(col_code, row_num)]
    if region:
        anchor_col = region["anchor_col"]
        anchor_row = region["anchor_row"]
        cells = merge_cells_from_region(region)

    # Assicura che esista lo slot anchor
    anchor_slot = _ensure_slot(cabinet_id, anchor_col, anchor_row)
    slots = []
    assignments = []
    items = []
    for col, row in cells:
        slot = _ensure_slot(cabinet_id, col, row)
        slots.append(slot)
        assigns, slot_items = _load_slot_assignments(slot.id, ignore_item_id=ignore_item_id)
        assignments.extend(assigns)
        items.extend(slot_items)

    return anchor_slot, slots, assignments, items

def make_full_position(cab_name: str, col_code: str, row_num: int, label_override: str | None = None) -> str:
    base_label = (label_override or f"{col_code.upper()}{int(row_num)}").strip()
    return f"{cab_name}-{base_label}" if cab_name else base_label

def slot_label(slot: Slot | None, *, for_display: bool = True, fallback_col: str | None = None, fallback_row: int | None = None) -> str:
    if slot:
        override = slot.display_label_override if for_display else slot.print_label_override
        col = slot.col_code
        row = slot.row_num
    else:
        override = None
        col = fallback_col
        row = fallback_row
    base = f"{(col or '').upper()}{int(row) if row is not None else ''}".strip()
    if override:
        cleaned = override.strip()
        if cleaned:
            return cleaned
    return base

def slot_full_label(cabinet: Cabinet | None, slot: Slot | None, *, for_print: bool = False, fallback_col: str | None = None, fallback_row: int | None = None) -> str:
    base = slot_label(slot, for_display=not for_print, fallback_col=fallback_col, fallback_row=fallback_row)
    if cabinet and cabinet.name:
        return f"{cabinet.name}-{base}"
    return base

CATEGORY_ROLE_ALIASES = {
    "washer": ["rondelle"],
    "screw": ["viti"],
    "standoff": ["torrette"],
    "spacer": ["distanziali"],
}

_CATEGORY_ROLE_IDS = {}


def _normalize_name(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _category_role_id(role: str) -> Optional[int]:
    cid = _CATEGORY_ROLE_IDS.get(role)
    if cid:
        return cid

    aliases = CATEGORY_ROLE_ALIASES.get(role, [])
    if not aliases:
        return None

    name_to_id = {
        _normalize_name(name): cid
        for cid, name in Category.query.with_entities(Category.id, Category.name)
    }
    for alias in aliases:
        cid = name_to_id.get(_normalize_name(alias))
        if cid:
            _CATEGORY_ROLE_IDS[role] = cid
            return cid
    return None


def reset_category_role_cache() -> None:
    _CATEGORY_ROLE_IDS.clear()


def is_washer(item: Item) -> bool:
    cat_id = _category_role_id("washer")
    return bool(cat_id and item.category_id == cat_id)


def is_screw(item: Item) -> bool:
    cat_id = _category_role_id("screw")
    return bool(cat_id and item.category_id == cat_id)


def is_standoff(item: Item) -> bool:
    cat_id = _category_role_id("standoff")
    return bool(cat_id and item.category_id == cat_id)


def is_spacer(item: Item) -> bool:
    cat_id = _category_role_id("spacer")
    return bool(cat_id and item.category_id == cat_id)

def auto_name_for(item:Item)->str:
    parts=[]
    if item.category: parts.append(item.category.name)
    if item.subtype: parts.append(item.subtype.name)  # forma testa / forma torrette
    if item.thread_size: parts.append(item.thread_size)
    size_value = None
    tag = None
    if is_screw(item) or is_standoff(item) or is_spacer(item):
        size_value = item.length_mm
        tag = "L="
    else:
        size_value = item.outer_d_mm
        tag = "Øe"
    if size_value is not None:
        val = int(size_value) if float(size_value).is_integer() else size_value
        parts.append(f"{tag}{val}mm")
    if item.material: parts.append(item.material.name)
    return " ".join(parts)[:118]

def format_mm_short(value):
    """Restituisce un valore in mm come intero se possibile o con una singola cifra decimale."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if abs(v - round(v)) < 0.01:
        return str(int(round(v)))
    return f"{v:.1f}".rstrip("0").rstrip(".")

MAIN_MEASURE_DEFAULT = "length"
VALID_MEASURE_MODES = {"length", "thickness"}
LENGTH_ABBR = "Lun."
THICKNESS_ABBR = "Spess."


def measure_mode_for_category(cat: Category | None) -> str:
    mode = getattr(cat, "main_measure_mode", None) or MAIN_MEASURE_DEFAULT
    return mode if mode in VALID_MEASURE_MODES else MAIN_MEASURE_DEFAULT


def measure_label_for_mode(mode: str, include_units: bool = True) -> str:
    base = "Spessore" if mode == "thickness" else "Lunghezza"
    return f"{base} (mm)" if include_units else base


def measure_label_for_category(cat: Category | None, include_units: bool = True) -> str:
    return measure_label_for_mode(measure_mode_for_category(cat), include_units)


def main_measure_value(item: Item | None):
    if not item:
        return None
    mode = measure_mode_for_category(item.category)
    if mode == "thickness":
        return item.thickness_mm if item.thickness_mm is not None else item.length_mm
    return item.length_mm if item.length_mm is not None else item.thickness_mm


def formatted_main_measure(item: Item | None) -> str | None:
    return format_mm_short(main_measure_value(item))


def main_measure_info(item: Item) -> dict | None:
    value = formatted_main_measure(item)
    if not value:
        return None
    mode = measure_mode_for_category(item.category)
    return {
        "mode": mode,
        "value": value,
        "label": measure_label_for_mode(mode, include_units=False),
    }


def build_measure_labels(categories):
    return {c.id: measure_label_for_category(c) for c in categories}

def label_line1_text(item: Item) -> str:
    """Testo riga 1 dell'etichetta: Categoria + Sottotipo + Misura filettatura."""
    parts = []
    if item.category:
        parts.append(item.category.name)
    if item.subtype:
        parts.append(item.subtype.name)
    if item.thread_size:
        parts.append(item.thread_size)
    return " ".join(parts)

def label_line2_text(item: Item) -> str:
    """Testo riga 2 dell'etichetta: dati tecnici a seconda della categoria."""
    parts = []

    if is_screw(item):
        v = format_mm_short(item.length_mm)
        if v:
            parts.append(f"{LENGTH_ABBR} {v}")
        if item.material:
            parts.append(item.material.name)
    elif is_washer(item):
        v_i = format_mm_short(getattr(item, "inner_d_mm", None))
        if v_i:
            parts.append(f"Øi{v_i}")
        v_e = format_mm_short(item.outer_d_mm)
        if v_e:
            parts.append(f"Øe{v_e}")
        v_s_raw = unified_thickness_value(item)
        v_s = format_mm_short(v_s_raw)
        if v_s:
            prefix = THICKNESS_ABBR if item.thickness_mm is not None else LENGTH_ABBR
            parts.append(f"{prefix} {v_s}")
    elif is_standoff(item):
        v = format_mm_short(item.length_mm)
        if v:
            parts.append(f"{LENGTH_ABBR} {v}")
        if item.material:
            parts.append(item.material.name)
    else:
        v = format_mm_short(item.outer_d_mm)
        if v:
            parts.append(f"Øe{v}")
        v_s_raw = unified_thickness_value(item)
        v_s = format_mm_short(v_s_raw)
        if v_s:
            prefix = THICKNESS_ABBR if item.thickness_mm is not None else LENGTH_ABBR
            parts.append(f"{prefix} {v_s}")
        if item.material:
            parts.append(item.material.name)

    return " ".join(parts)

def label_lines_for_item(item: Item) -> list[str]:
    """Restituisce le righe di testo da mostrare in cella e in etichetta."""
    lines = []
    line1 = label_line1_text(item)
    line2 = label_line2_text(item)
    if line1:
        lines.append(line1)
    if line2:
        lines.append(line2)
    if not lines:
        fallback = auto_name_for(item)
        if fallback:
            lines.append(fallback)
    return lines

def ensure_settings_columns():
    """Aggiunge le nuove colonne delle impostazioni se mancano nel DB SQLite."""
    try:
        rows = db.session.execute(text("PRAGMA table_info(settings)")).fetchall()
    except Exception:
        return
    existing_cols = {r[1] for r in rows}
    new_cols = [
        ("label_padding_mm", "REAL", DEFAULT_LABEL_PADDING_MM),
        ("label_qr_size_mm", "REAL", DEFAULT_LABEL_QR_SIZE_MM),
        ("label_qr_margin_mm", "REAL", DEFAULT_LABEL_QR_MARGIN_MM),
        ("label_position_width_mm", "REAL", DEFAULT_LABEL_POSITION_WIDTH_MM),
        ("label_position_font_pt", "REAL", DEFAULT_LABEL_POSITION_FONT_PT),
    ]
    added = False
    for col_name, col_type, default_val in new_cols:
        if col_name not in existing_cols:
            try:
                default_sql = f" DEFAULT {default_val}" if default_val is not None else ""
                db.session.execute(text(f"ALTER TABLE settings ADD COLUMN {col_name} {col_type}{default_sql}"))
                added = True
            except Exception:
                db.session.rollback()
                return
    if added:
        db.session.commit()

def ensure_item_columns():
    """Garantisce la presenza delle nuove colonne nella tabella items (compatibilità DB esistenti)."""
    try:
        rows = db.session.execute(text("PRAGMA table_info(item)")).fetchall()
    except Exception:
        return
    existing_cols = {r[1] for r in rows}
    if "share_drawer" not in existing_cols:
        try:
            db.session.execute(text("ALTER TABLE item ADD COLUMN share_drawer BOOLEAN DEFAULT 0"))
            db.session.commit()
        except Exception:
            db.session.rollback()
            return

def ensure_category_columns():
    """Aggiunge colonne mancanti nella tabella category (compatibilità DB esistenti)."""
    try:
        rows = db.session.execute(text("PRAGMA table_info(category)")).fetchall()
    except Exception:
        return
    existing_cols = {r[1] for r in rows}
    if "main_measure_mode" not in existing_cols:
        try:
            db.session.execute(text("ALTER TABLE category ADD COLUMN main_measure_mode VARCHAR(16) DEFAULT 'length'"))
            db.session.commit()
        except Exception:
            db.session.rollback()
            return

def ensure_mqtt_settings_columns():
    """Aggiunge eventuali nuove colonne della configurazione MQTT (compatibilità DB esistenti)."""
    try:
        rows = db.session.execute(text("PRAGMA table_info(mqtt_settings)")).fetchall()
    except Exception:
        return
    existing_cols = {r[1] for r in rows}
    new_cols = [
        ("include_item_category_color", "BOOLEAN", 0),
    ]
    added = False
    for col_name, col_type, default_val in new_cols:
        if col_name not in existing_cols:
            try:
                default_sql = f" DEFAULT {default_val}" if default_val is not None else ""
                db.session.execute(text(f"ALTER TABLE mqtt_settings ADD COLUMN {col_name} {col_type}{default_sql}"))
                added = True
            except Exception:
                db.session.rollback()
                return
    if added:
        db.session.commit()

def ensure_slot_columns():
    """Aggiunge eventuali nuove colonne alla tabella slot (compatibilità DB esistenti)."""
    try:
        rows = db.session.execute(text("PRAGMA table_info(slot)")).fetchall()
    except Exception:
        return
    existing_cols = {r[1] for r in rows}
    new_cols = [
        ("display_label_override", "VARCHAR(80)", None),
        ("print_label_override", "VARCHAR(80)", None),
    ]
    added = False
    for col_name, col_type, default_val in new_cols:
        if col_name not in existing_cols:
            try:
                default_sql = f" DEFAULT '{default_val}'" if default_val is not None else ""
                db.session.execute(text(f"ALTER TABLE slot ADD COLUMN {col_name} {col_type}{default_sql}"))
                added = True
            except Exception:
                db.session.rollback()
                return
    if added:
        db.session.commit()

_schema_checked = False

def ensure_core_schema():
    """Esegue una verifica unica dello schema per aggiungere colonne mancanti."""
    global _schema_checked
    if _schema_checked:
        return
    ensure_settings_columns()
    ensure_item_columns()
    ensure_category_columns()
    ensure_mqtt_settings_columns()
    ensure_slot_columns()
    _schema_checked = True

@app.before_request
def prepare_schema():
    ensure_core_schema()

def get_settings()->Settings:
    ensure_core_schema()
    s = Settings.query.get(1)
    if not s:
        s = Settings(id=1,
                     label_w_mm=DEFAULT_LABEL_W_MM,
                     label_h_mm=DEFAULT_LABEL_H_MM,
                     margin_tb_mm=DEFAULT_MARG_TB_MM,
                     margin_lr_mm=DEFAULT_MARG_LR_MM,
                     gap_mm=DEFAULT_GAP_MM,
                     label_padding_mm=DEFAULT_LABEL_PADDING_MM,
                     label_qr_size_mm=DEFAULT_LABEL_QR_SIZE_MM,
                     label_qr_margin_mm=DEFAULT_LABEL_QR_MARGIN_MM,
                     label_position_width_mm=DEFAULT_LABEL_POSITION_WIDTH_MM,
                     label_position_font_pt=DEFAULT_LABEL_POSITION_FONT_PT,
                     orientation_landscape=DEFAULT_ORIENTATION_LANDSCAPE,
                     qr_default=DEFAULT_QR_DEFAULT,
                     qr_base_url=DEFAULT_QR_BASE_URL)
        db.session.add(s); db.session.commit()
    changed = False
    if s.label_padding_mm is None: s.label_padding_mm = DEFAULT_LABEL_PADDING_MM; changed = True
    if s.label_qr_size_mm is None: s.label_qr_size_mm = DEFAULT_LABEL_QR_SIZE_MM; changed = True
    if s.label_qr_margin_mm is None: s.label_qr_margin_mm = DEFAULT_LABEL_QR_MARGIN_MM; changed = True
    if s.label_position_width_mm is None: s.label_position_width_mm = DEFAULT_LABEL_POSITION_WIDTH_MM; changed = True
    if s.label_position_font_pt is None: s.label_position_font_pt = DEFAULT_LABEL_POSITION_FONT_PT; changed = True
    if changed:
        db.session.commit()
    return s

def get_mqtt_settings() -> MqttSettings:
    ensure_core_schema()
    s = MqttSettings.query.get(1)
    if not s:
        s = MqttSettings(
            id=1,
            enabled=False,
            host=DEFAULT_MQTT_HOST,
            port=DEFAULT_MQTT_PORT,
            topic=DEFAULT_MQTT_TOPIC,
            qos=DEFAULT_MQTT_QOS,
            retain=DEFAULT_MQTT_RETAIN,
        )
        db.session.add(s)
        db.session.commit()
    return s

def mqtt_payload_for_slot(cabinet: Cabinet, col_code: str, row_num: int, settings: MqttSettings):
    if not cabinet:
        return None
    region = merge_region_for(cabinet.id, col_code, row_num)
    if region:
        col_code = region["anchor_col"]
        row_num = region["anchor_row"]
    location = Location.query.get(cabinet.location_id) if cabinet else None
    slot_obj = Slot.query.filter_by(cabinet_id=cabinet.id, col_code=col_code, row_num=row_num).first()
    slot_label_text = slot_label(slot_obj, for_display=True, fallback_col=col_code, fallback_row=row_num)
    payload = {
        "event": "slot_click",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if settings.include_cabinet_name:
        payload["cabinet_name"] = cabinet.name if cabinet else None
    if settings.include_cabinet_id:
        payload["cabinet_id"] = cabinet.id if cabinet else None
    if settings.include_location_name:
        payload["location_name"] = location.name if location else None
    if settings.include_location_id:
        payload["location_id"] = location.id if location else None
    if settings.include_row:
        payload["row"] = row_num
    if settings.include_col:
        payload["col"] = col_code
    if settings.include_slot_label:
        payload["slot"] = slot_label_text

    if settings.include_items:
        region = merge_region_for(cabinet.id, col_code, row_num)
        if region:
            cells = merge_cells_from_region(region)
        else:
            cells = [(col_code, row_num)]
        slots = (
            Slot.query.filter(Slot.cabinet_id == cabinet.id)
            .filter(or_(*[
                (Slot.col_code == col) & (Slot.row_num == row)
                for col, row in cells
            ]))
            .all()
        )
        items_payload = []
        if slots:
            slot_ids = [s.id for s in slots]
            assigns = (
                db.session.query(Assignment, Item, Category, Slot)
                .join(Item, Assignment.item_id == Item.id)
                .join(Category, Item.category_id == Category.id, isouter=True)
                .join(Slot, Assignment.slot_id == Slot.id)
                .filter(Assignment.slot_id.in_(slot_ids))
                .order_by(Slot.col_code, Slot.row_num, Assignment.compartment_no)
                .all()
            )
            for a, it, cat, slot in assigns:
                item_data = {}
                if settings.include_item_id:
                    item_data["id"] = it.id
                if settings.include_item_name:
                    item_data["name"] = auto_name_for(it)
                if settings.include_item_category:
                    item_data["category"] = cat.name if cat else None
                if settings.include_item_category_color:
                    item_data["category_color"] = cat.color if cat else None
                if settings.include_item_quantity:
                    item_data["quantity"] = it.quantity
                if settings.include_item_position:
                    item_data["position"] = slot_label(slot, for_display=True, fallback_col=slot.col_code, fallback_row=slot.row_num)
                if settings.include_item_description:
                    item_data["description"] = it.description
                if settings.include_item_material:
                    item_data["material"] = it.material.name if it.material else None
                if settings.include_item_finish:
                    item_data["finish"] = it.finish.name if it.finish else None
                items_payload.append(item_data)
        if items_payload or settings.include_empty:
            payload["items"] = items_payload
        else:
            return None
    return payload

def publish_mqtt_payload(payload: dict, settings: MqttSettings):
    if not settings.enabled:
        return {"ok": False, "skipped": True, "error": "MQTT disabilitato."}
    if not settings.host or not settings.topic:
        return {"ok": False, "error": "Configurazione MQTT incompleta."}
    from paho.mqtt import publish as mqtt_publish
    auth = None
    if settings.username:
        auth = {"username": settings.username, "password": settings.password or ""}
    try:
        mqtt_publish.single(
            settings.topic,
            json.dumps(payload, ensure_ascii=False),
            hostname=settings.host,
            port=settings.port or DEFAULT_MQTT_PORT,
            qos=settings.qos or DEFAULT_MQTT_QOS,
            retain=bool(settings.retain),
            client_id=settings.client_id or None,
            auth=auth,
        )
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@app.context_processor
def inject_utils():
    return dict(
        compose_caption=auto_name_for,
        app_settings=get_settings,
        measure_label_for_category=measure_label_for_category,
        formatted_main_measure=formatted_main_measure,
        main_measure_value=main_measure_value,
    )

def load_form_options():
    thread_standards = ThreadStandard.query.order_by(ThreadStandard.sort_order, ThreadStandard.label).all()
    thread_sizes = (
        ThreadSize.query.join(ThreadStandard)
        .order_by(ThreadStandard.sort_order, ThreadSize.sort_order, ThreadSize.value)
        .all()
    )
    sizes_by_standard = {}
    for size in thread_sizes:
        sizes_by_standard.setdefault(size.standard.code, []).append(size.value)
    return thread_standards, sizes_by_standard

BUILTIN_FIELD_DEFS = [
    {"key": "subtype_id", "label": "Sottotipo (forma)"},
    {"key": "thread_standard", "label": "Standard"},
    {"key": "thread_size", "label": "Misura"},
    {"key": "outer_d_mm", "label": "Ø esterno (mm)"},
    {"key": "length_mm", "label": "Lunghezza/Spessore (mm)"},
    {"key": "inner_d_mm", "label": "Ø interno (mm)"},
    {"key": "material_id", "label": "Materiale"},
    {"key": "finish_id", "label": "Finitura"},
    {"key": "description", "label": "Descrizione"},
    {"key": "quantity", "label": "Quantità"},
]

def custom_field_key(field_id: int) -> str:
    return f"custom_{field_id}"

def parse_custom_field_options(raw: str) -> list:
    if not raw:
        return []
    lines = raw.replace(",", "\n").splitlines()
    return [opt.strip() for opt in lines if opt.strip()]

def default_fields_for_category(cat_name: str) -> set:
    base = {
        "subtype_id",
        "thread_standard",
        "thread_size",
        "material_id",
        "finish_id",
        "description",
        "quantity",
    }
    if not cat_name:
        base.update({"outer_d_mm", "length_mm"})
        return base
    lower = cat_name.strip().lower()
    if lower in {"viti", "torrette", "distanziali"}:
        base.add("length_mm")
    else:
        base.add("outer_d_mm")
    if lower == "rondelle":
        base.update({"inner_d_mm", "length_mm"})
    return base

def serialize_custom_fields(fields):
    return [
        {
            "id": f.id,
            "name": f.name,
            "field_type": f.field_type,
            "options": parse_custom_field_options(f.options),
            "unit": f.unit,
            "sort_order": f.sort_order,
            "is_active": f.is_active,
        }
        for f in fields
    ]

def build_category_field_map(categories):
    settings = CategoryFieldSetting.query.all()
    enabled_by_cat = {}
    configured_cats = set()
    for setting in settings:
        configured_cats.add(setting.category_id)
        if setting.is_enabled and setting.field_key != "__none__":
            enabled_by_cat.setdefault(setting.category_id, set()).add(setting.field_key)
    for cat_id, enabled_fields in enabled_by_cat.items():
        if "thickness_mm" in enabled_fields:
            enabled_fields.add("length_mm")
    for cat in categories:
        if cat.id not in configured_cats:
            enabled_by_cat[cat.id] = default_fields_for_category(cat.name)
        elif cat.id not in enabled_by_cat:
            enabled_by_cat[cat.id] = set()
    return {cat_id: sorted(keys) for cat_id, keys in enabled_by_cat.items()}

def get_used_field_keys_by_category():
    used = {}
    rows = db.session.query(
        Item.category_id,
        Item.subtype_id,
        Item.thread_standard,
        Item.thread_size,
        Item.outer_d_mm,
        Item.length_mm,
        Item.inner_d_mm,
        Item.material_id,
        Item.finish_id,
        Item.description,
        Item.quantity,
        Item.thickness_mm,
    ).all()

    for (
        category_id,
        subtype_id,
        thread_standard,
        thread_size,
        outer_d_mm,
        length_mm,
        inner_d_mm,
        material_id,
        finish_id,
        description,
        quantity,
        thickness_mm,
    ) in rows:
        cat_used = used.setdefault(category_id, set())
        if subtype_id is not None:
            cat_used.add("subtype_id")
        if thread_standard:
            cat_used.add("thread_standard")
        if thread_size:
            cat_used.add("thread_size")
        if outer_d_mm is not None:
            cat_used.add("outer_d_mm")
        if length_mm is not None:
            cat_used.add("length_mm")
        if thickness_mm is not None:
            cat_used.update({"thickness_mm", "length_mm"})
        if inner_d_mm is not None:
            cat_used.add("inner_d_mm")
        if material_id is not None:
            cat_used.add("material_id")
        if finish_id is not None:
            cat_used.add("finish_id")
        if description:
            cat_used.add("description")
        if quantity is not None:
            cat_used.add("quantity")

    custom_values = (
        db.session.query(Item.category_id, ItemCustomFieldValue.field_id)
        .join(Item, Item.id == ItemCustomFieldValue.item_id)
        .distinct()
        .all()
    )
    for category_id, field_id in custom_values:
        used.setdefault(category_id, set()).add(custom_field_key(field_id))

    return {cat_id: sorted(keys) for cat_id, keys in used.items()}

def build_field_definitions(custom_fields):
    defs = [{"key": f["key"], "label": f["label"], "is_custom": False} for f in BUILTIN_FIELD_DEFS]
    for field in custom_fields:
        label = field["name"]
        if field.get("unit"):
            label = f"{label} ({field['unit']})"
        defs.append({
            "key": custom_field_key(field["id"]),
            "label": f"Personalizzato: {label}",
            "is_custom": True,
        })
    return defs

def parse_length_thickness_value(raw_value):
    if raw_value is None or raw_value == "":
        return None
    return float(raw_value)


def split_main_measure_for_category(category: Category | None, raw_value):
    """Restituisce la misura principale separata in lunghezza o spessore in base alla categoria."""
    value = parse_length_thickness_value(raw_value)
    if value is None:
        return None, None
    mode = measure_mode_for_category(category)
    if mode == "thickness":
        return None, value
    return value, None

def save_custom_field_values(item: Item, form):
    active_fields = CustomField.query.filter_by(is_active=True).all()
    existing = {
        val.field_id: val
        for val in ItemCustomFieldValue.query.filter_by(item_id=item.id).all()
    }
    for field in active_fields:
        form_key = f"custom_field_{field.id}"
        if form_key not in form:
            continue
        raw = (form.get(form_key) or "").strip()
        if not raw:
            if field.id in existing:
                db.session.delete(existing[field.id])
            continue
        if field.id in existing:
            existing[field.id].value_text = raw
        else:
            db.session.add(ItemCustomFieldValue(item_id=item.id, field_id=field.id, value_text=raw))

# ===================== AUTH =====================
@login_manager.user_loader
def load_user(user_id):
    with app.app_context():
        return db.session.get(User, int(user_id))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and user.password == request.form["password"]:
            login_user(user); return redirect(url_for("admin_items"))
        flash("Credenziali non valide", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user(); return redirect(url_for("index"))

# ===================== PUBLIC =====================
def _render_articles_page():
    ensure_core_schema()
    low_stock_threshold = 5
    items_q    = Item.query.options(
        selectinload(Item.category),
        selectinload(Item.material),
        selectinload(Item.finish),
        selectinload(Item.subtype),
    )
    text_q = (request.args.get("q") or "").strip()
    category_id = request.args.get("category_id", type=int)
    subtype_id = request.args.get("subtype_id", type=int)
    material_id = request.args.get("material_id", type=int)
    finish_id = request.args.get("finish_id", type=int)
    measure_q = (request.args.get("measure") or request.args.get("thread_size") or "").strip()
    share_filter = request.args.get("share_drawer")
    stock_filter = request.args.get("stock")
    pos_cabinet_id = request.args.get("pos_cabinet_id", type=int)
    pos_col = (request.args.get("pos_col") or "").strip().upper()
    pos_row = request.args.get("pos_row", type=int)

    if text_q:
        text_q_lower = text_q.lower()
        items_q = items_q.filter(or_(
            func.lower(Item.name).contains(text_q_lower),
            func.lower(Item.description).contains(text_q_lower),
            func.lower(Item.thread_size).contains(text_q_lower),
        ))
    if category_id:
        items_q = items_q.filter(Item.category_id == category_id)
    if subtype_id:
        items_q = items_q.filter(Item.subtype_id == subtype_id)
    if material_id:
        items_q = items_q.filter(Item.material_id == material_id)
    if finish_id:
        items_q = items_q.filter(Item.finish_id == finish_id)
    if measure_q:
        items_q = items_q.filter(func.lower(Item.thread_size).contains(measure_q.lower()))
    if share_filter == "1":
        items_q = items_q.filter(Item.share_drawer.is_(True))
    elif share_filter == "0":
        items_q = items_q.filter(Item.share_drawer.is_(False))
    if stock_filter == "available":
        items_q = items_q.filter(Item.quantity > 0)
    elif stock_filter == "low":
        items_q = items_q.filter(Item.quantity <= low_stock_threshold)
    elif stock_filter == "out":
        items_q = items_q.filter(Item.quantity <= 0)

    if pos_cabinet_id or pos_col or pos_row:
        pos_q = db.session.query(Assignment.item_id).join(Slot, Assignment.slot_id == Slot.id)
        if pos_cabinet_id:
            pos_q = pos_q.filter(Slot.cabinet_id == pos_cabinet_id)
        if pos_col:
            pos_q = pos_q.filter(Slot.col_code == pos_col)
        if pos_row:
            pos_q = pos_q.filter(Slot.row_num == pos_row)
        items_q = items_q.filter(Item.id.in_(pos_q))
    items = items_q.all()

    categories = Category.query.order_by(Category.name).all()
    subtypes   = Subtype.query.order_by(Subtype.name).all()
    materials  = Material.query.order_by(Material.name).all()
    finishes   = Finish.query.order_by(Finish.name).all()
    locations  = Location.query.order_by(Location.name).all()
    cabinets   = Cabinet.query.order_by(Cabinet.name).all()
    measure_labels = build_measure_labels(categories)

    assignments = (
        db.session.query(Assignment.item_id, Cabinet, Slot)
        .join(Slot, Assignment.slot_id == Slot.id)
        .join(Cabinet, Slot.cabinet_id == Cabinet.id)
        .all()
    )
    pos_by_item = {
        item_id: slot_full_label(cab, slot, for_print=False)
        for item_id, cab, slot in assignments
    }

    thread_standards, sizes_by_standard = load_form_options()
    default_standard_code = next(
        (s.code for s in thread_standards if s.code == "M"),
        thread_standards[0].code if thread_standards else "",
    )

    subtypes_by_cat = {}
    for s in subtypes:
        subtypes_by_cat.setdefault(s.category_id, []).append({"id": s.id, "name": s.name})

    custom_fields = CustomField.query.filter_by(is_active=True).order_by(CustomField.sort_order, CustomField.name).all()
    serialized_custom_fields = serialize_custom_fields(custom_fields)
    category_fields = build_category_field_map(categories)

    subq = select(Assignment.item_id)
    unplaced_count = Item.query.filter(Item.id.not_in(subq)).count()
    low_stock_count = Item.query.filter(Item.quantity <= low_stock_threshold).count()
    total_items = Item.query.count()
    total_categories = Category.query.count()

    return render_template("articles.html",
        items=items, categories=categories, materials=materials, finishes=finishes,
        locations=locations, cabinets=cabinets,
        subtypes_by_cat=subtypes_by_cat,
        thread_standards=thread_standards,
        sizes_by_standard=sizes_by_standard,
        default_standard_code=default_standard_code,
        pos_by_item=pos_by_item,
        custom_fields=serialized_custom_fields,
        subtypes=subtypes,
        category_fields=category_fields,
        unplaced_count=unplaced_count,
        low_stock_count=low_stock_count,
        total_items=total_items,
        total_categories=total_categories,
        low_stock_threshold=low_stock_threshold,
        is_admin=current_user.is_authenticated,
        stock_filter=stock_filter,
        measure_q=measure_q,
        measure_labels=measure_labels,
    )

@app.route("/")
def index():
    return _render_articles_page()

@app.route("/articoli")
def articles():
    return _render_articles_page()

def build_full_grid(cabinet_id:int):
    cab = db.session.get(Cabinet, cabinet_id)
    if not cab: return {"rows":[], "cols":[], "cells":{}, "cab":None}

    rows = list(range(1, min(128, max(1, int(cab.rows_max))) + 1))
    cols = list(iter_cols_upto(cab.cols_max or "Z"))
    merge_anchors = {}
    merge_skips = {}
    merge_regions = {}

    merges = DrawerMerge.query.filter_by(cabinet_id=cabinet_id).all()
    for m in merges:
        try:
            row_start, row_end, col_start, col_end = normalize_merge_bounds(
                cab, m.col_start, m.col_end, m.row_start, m.row_end
            )
        except ValueError:
            continue
        start_idx = colcode_to_idx(col_start)
        end_idx = colcode_to_idx(col_end)
        anchor_key = f"{col_start}-{row_start}"
        merge_anchors[anchor_key] = {"rowspan": row_end - row_start + 1, "colspan": end_idx - start_idx + 1}
        merge_regions[anchor_key] = {
            "row_start": row_start,
            "row_end": row_end,
            "col_start": col_start,
            "col_end": col_end,
        }
        for row in range(row_start, row_end + 1):
            for col_idx in range(start_idx, end_idx + 1):
                key = f"{idx_to_colcode(col_idx)}-{row}"
                if key != anchor_key:
                    merge_skips[key] = True

    slot_rows = (
        db.session.query(Slot)
        .filter(Slot.cabinet_id == cabinet_id)
        .all()
    )
    slot_display_labels = {
        f"{s.col_code}-{s.row_num}": slot_label(s, for_display=True)
        for s in slot_rows
    }

    assigns = (
        db.session.query(Assignment, Slot, Item, Category)
        .join(Slot, Assignment.slot_id == Slot.id)
        .join(Item, Assignment.item_id == Item.id)
        .join(Category, Item.category_id == Category.id, isouter=True)
        .filter(Slot.cabinet_id == cabinet_id)
        .all()
    )

    cells = {}
    for s in slot_rows:
        if s.is_blocked:
            key = f"{s.col_code}-{s.row_num}"
            cells[key] = {
                "blocked": True,
                "entries": [],
                "cat_id": None,
                "label": slot_display_labels.get(key) or f"{s.col_code}{s.row_num}",
            }

    for a, s, it, cat in assigns:
        key = f"{s.col_code}-{s.row_num}"
        label = slot_display_labels.get(key) or f"{s.col_code}{s.row_num}"
        cell = cells.get(key, {"blocked": False, "entries": [], "cat_id": None, "label": label})
        text = short_cell_text(it)
        summary = text.replace("\n", " - ")
        color = cat.color if cat else "#999"
        cell["entries"].append({
            "text": summary,
            "color": color,
            "name": auto_name_for(it),
            "description": it.description,
            "quantity": it.quantity,
            "share_drawer": bool(getattr(it, "share_drawer", False)),
            "position": label,
            "thread_size": it.thread_size,
            "main_measure": main_measure_info(it),
        })
        if cell["cat_id"] is None and it.category_id:
            cell["cat_id"] = it.category_id
        if not cell.get("label"):
            cell["label"] = label
        cells[key] = cell

    for anchor_key, region in merge_regions.items():
        merged_cell = {
            "blocked": False,
            "entries": [],
            "cat_id": None,
            "label": slot_display_labels.get(anchor_key) or f"{region['col_start']}{region['row_start']}",
        }
        for col, row in merge_cells_from_region(region):
            key = f"{col}-{row}"
            cell = cells.get(key)
            if cell:
                if cell.get("blocked"):
                    merged_cell["blocked"] = True
                for entry in cell.get("entries", []):
                    merged_cell["entries"].append(entry)
                    if merged_cell["cat_id"] is None:
                        merged_cell["cat_id"] = cell.get("cat_id")
                if merged_cell["cat_id"] is None and cell.get("cat_id"):
                    merged_cell["cat_id"] = cell.get("cat_id")
        cells[anchor_key] = merged_cell

    return {
        "rows": rows, "cols": cols, "cells": cells,
        "cab": {"id": cab.id, "name": cab.name, "comp": cab.compartments_per_slot},
        "merge_anchors": merge_anchors,
        "merge_skips": merge_skips,
    }

@app.route("/cassettiere")
def cassettiere():
    cab_id = request.args.get("cabinet_id", type=int)
    cabinets = Cabinet.query.order_by(Cabinet.name).all()
    if not cab_id and cabinets:
        cab_id = cabinets[0].id
    grid = build_full_grid(cab_id) if cab_id else {"rows": [], "cols": [], "cells": {}, "cab": None}

    categories = Category.query.order_by(Category.name).all()
    subq = select(Assignment.item_id)
    unplaced_json = []
    if current_user.is_authenticated:
        unplaced = Item.query.filter(Item.id.not_in(subq)).all()
        unplaced_json = [
            {"id": it.id, "caption": auto_name_for(it), "category_id": it.category_id}
            for it in unplaced
        ]

    return render_template(
        "cassettiere.html",
        categories=categories,
        cabinets=cabinets,
        selected_cab_id=cab_id,
        grid=grid,
        unplaced_json=unplaced_json,
        is_admin=current_user.is_authenticated,
    )

def short_cell_text(item: Item) -> str:
    lines = label_lines_for_item(item)
    return "\n".join(lines[:2])

def unified_thickness_value(item: Item):
    if item.thickness_mm is not None:
        return item.thickness_mm
    if not (is_screw(item) or is_standoff(item) or is_spacer(item)):
        return item.length_mm
    return None


@app.route("/api/items/<int:item_id>.json")
def api_item(item_id):
    item = Item.query.get_or_404(item_id)
    a = (db.session.query(Assignment, Slot, Cabinet)
         .join(Slot, Assignment.slot_id == Slot.id)
         .join(Cabinet, Slot.cabinet_id == Cabinet.id)
         .filter(Assignment.item_id == item.id).first())
    full_pos = slot_full_label(a[2], a[1], for_print=False) if a else None
    return jsonify({
        "id": item.id,
        "name": auto_name_for(item),
        "description": item.description,
        "category": item.category.name if item.category else None,
        "category_color": item.category.color if item.category else None,
        "subtype": item.subtype.name if item.subtype else None,
        "thread_standard": item.thread_standard, "thread_size": item.thread_size,
        "length_mm": item.length_mm,
        "outer_d_mm": item.outer_d_mm,
        "inner_d_mm": item.inner_d_mm, "thickness_mm": item.thickness_mm,
        "material": item.material.name if item.material else None,
        "finish": item.finish.name if item.finish else None,
        "quantity": item.quantity,
        "position": full_pos
    })

@app.route("/api/slots/lookup")
def api_slot_lookup():
    cab_id = request.args.get("cabinet_id", type=int)
    col_code = (request.args.get("col_code") or "").strip().upper()
    row_num = request.args.get("row_num", type=int)
    if not (cab_id and col_code and row_num):
        return jsonify({"ok": False, "error": "Parametri mancanti."}), 400

    region = merge_region_for(cab_id, col_code, row_num)
    if region:
        col_code = region["anchor_col"]
        row_num = region["anchor_row"]
        cells = merge_cells_from_region(region)
    else:
        cells = [(col_code, row_num)]

    slots = (
        Slot.query.filter(Slot.cabinet_id == cab_id)
        .filter(or_(*[
            (Slot.col_code == col) & (Slot.row_num == row)
            for col, row in cells
        ]))
        .all()
    )
    default_label = f"{col_code}{row_num}"
    label_display = default_label
    label_print = default_label
    if slots:
        anchor_slot = next((s for s in slots if s.col_code == col_code and s.row_num == row_num), slots[0])
        label_display = slot_label(anchor_slot, for_display=True, fallback_col=col_code, fallback_row=row_num)
        label_print = slot_label(anchor_slot, for_display=False, fallback_col=col_code, fallback_row=row_num)
    else:
        return jsonify({"ok": True, "items": [], "slot_label_display": default_label, "slot_label_print": default_label, "default_label": default_label})

    slot_ids = [s.id for s in slots]
    assigns = (
        db.session.query(Assignment, Item, Category, Slot)
        .join(Item, Assignment.item_id == Item.id)
        .join(Category, Item.category_id == Category.id, isouter=True)
        .join(Slot, Assignment.slot_id == Slot.id)
        .filter(Assignment.slot_id.in_(slot_ids))
        .order_by(Slot.col_code, Slot.row_num, Assignment.compartment_no)
        .all()
    )
    items = []
    for a, it, cat, slot in assigns:
        items.append({
            "id": it.id,
            "name": auto_name_for(it),
            "category": cat.name if cat else None,
            "color": cat.color if cat else "#999999",
            "position": slot_label(slot, for_display=True, fallback_col=slot.col_code, fallback_row=slot.row_num),
        })
    return jsonify({"ok": True, "items": items})

# ===================== ADMIN: ARTICOLI =====================
@app.route("/admin")
@login_required
def admin_items():
    return _render_articles_page()

@app.route("/admin/items/export")
@login_required
def export_items_csv():
    items = Item.query.options(
        selectinload(Item.category),
        selectinload(Item.subtype),
        selectinload(Item.material),
        selectinload(Item.finish),
    ).order_by(Item.id).all()

    assignments = (
        db.session.query(Assignment.item_id, Cabinet, Slot)
        .join(Slot, Assignment.slot_id == Slot.id)
        .join(Cabinet, Slot.cabinet_id == Cabinet.id)
        .all()
    )
    pos_by_item = {
        item_id: slot_full_label(cab, slot, for_print=False)
        for item_id, cab, slot in assignments
    }

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "name",
        "category",
        "subtype",
        "thread_standard",
        "thread_size",
        "length_mm",
        "outer_d_mm",
        "inner_d_mm",
        "thickness_mm",
        "material",
        "finish",
        "description",
        "position",
    ])
    for item in items:
        writer.writerow([
            item.id,
            auto_name_for(item),
            item.category.name if item.category else "",
            item.subtype.name if item.subtype else "",
            item.thread_standard or "",
            item.thread_size or "",
            item.length_mm if item.length_mm is not None else "",
            item.outer_d_mm if item.outer_d_mm is not None else "",
            item.inner_d_mm if item.inner_d_mm is not None else "",
            item.thickness_mm if item.thickness_mm is not None else "",
            item.material.name if item.material else "",
            item.finish.name if item.finish else "",
            item.description or "",
            pos_by_item.get(item.id, ""),
        ])
    output.seek(0)
    buffer = io.BytesIO(output.getvalue().encode("utf-8"))
    return send_file(buffer, as_attachment=True, download_name="articoli.csv", mimetype="text/csv")


@app.route("/admin/to_place")
@login_required
def to_place():
    return redirect(url_for("placements"))

@app.route("/admin/items/add", methods=["POST"])
@login_required
def add_item():
    f = request.form
    try:
        category_id = int(f.get("category_id"))
    except Exception:
        flash("Categoria non valida.", "danger")
        return redirect(url_for("admin_items"))
    category = Category.query.get_or_404(category_id)
    try:
        length_mm, thickness_mm = split_main_measure_for_category(category, f.get("length_mm"))
    except ValueError:
        flash("Valore Lunghezza/Spessore non valido.", "danger")
        return redirect(url_for("admin_items"))
    item = Item(
        description=f.get("description") or None,
        category_id=category.id,
        subtype_id=int(f.get("subtype_id")) if f.get("subtype_id") else None,
        thread_standard=f.get("thread_standard") or None,
        thread_size=f.get("thread_size") or None,
        length_mm=length_mm,
        outer_d_mm=float(f.get("outer_d_mm")) if f.get("outer_d_mm") else None,
        inner_d_mm=float(f.get("inner_d_mm")) if f.get("inner_d_mm") else None,
        thickness_mm=thickness_mm,
        material_id=int(f.get("material_id")) if f.get("material_id") else None,
        finish_id=int(f.get("finish_id")) if f.get("finish_id") else None,
        quantity=int(f.get("quantity")) if f.get("quantity") else 0,
        share_drawer=bool(f.get("share_drawer")),
        label_show_category=bool(f.get("label_show_category")),
        label_show_subtype =bool(f.get("label_show_subtype")),
        label_show_thread  =bool(f.get("label_show_thread")),
        label_show_measure =bool(f.get("label_show_measure")),
        label_show_main    =bool(f.get("label_show_main")),
        label_show_material=bool(f.get("label_show_material")),
    )
    item.name = auto_name_for(item)
    db.session.add(item); db.session.flush()
    save_custom_field_values(item, f)
    cab_id  = f.get("cabinet_id"); row_num = f.get("row_num"); col_code = f.get("col_code")
    if cab_id and row_num and col_code:
        _assign_position(item, int(cab_id), col_code, int(row_num))
    db.session.commit()
    flash("Articolo aggiunto", "success")
    keep_params = {
        "keep_category_id": item.category_id,
        "keep_material_id": item.material_id,
        "keep_finish_id": item.finish_id,
        "keep_description": item.description or "",
        "keep_thread_size": item.thread_size or "",
    }
    keep_params = {k: v for k, v in keep_params.items() if v not in (None, "")}
    return redirect(url_for("admin_items", **keep_params))

@app.route("/admin/items/<int:item_id>/edit", methods=["GET","POST"])
@login_required
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)
    if request.method == "POST":
        f = request.form
        try:
            category_id = int(f.get("category_id"))
            category = Category.query.get_or_404(category_id)
            length_mm, thickness_mm = split_main_measure_for_category(category, f.get("length_mm"))
        except ValueError:
            flash("Valore Lunghezza/Spessore non valido.", "danger")
            return redirect(url_for("edit_item", item_id=item.id))
        item.description = f.get("description") or None
        item.category_id = category.id
        item.subtype_id = int(f.get("subtype_id")) if f.get("subtype_id") else None
        item.thread_standard = f.get("thread_standard") or None
        item.thread_size = f.get("thread_size") or None
        item.length_mm = length_mm
        item.outer_d_mm = float(f.get("outer_d_mm")) if f.get("outer_d_mm") else None
        item.inner_d_mm = float(f.get("inner_d_mm")) if f.get("inner_d_mm") else None
        item.thickness_mm = thickness_mm
        item.material_id = int(f.get("material_id")) if f.get("material_id") else None
        item.finish_id = int(f.get("finish_id")) if f.get("finish_id") else None
        item.quantity = int(f.get("quantity")) if f.get("quantity") else 0
        item.share_drawer = bool(f.get("share_drawer"))
        item.label_show_category = bool(f.get("label_show_category"))
        item.label_show_subtype  = bool(f.get("label_show_subtype"))
        item.label_show_thread   = bool(f.get("label_show_thread"))
        item.label_show_measure  = bool(f.get("label_show_measure"))
        item.label_show_main     = bool(f.get("label_show_main"))
        item.label_show_material = bool(f.get("label_show_material"))
        item.name = auto_name_for(item)
        save_custom_field_values(item, f)
        db.session.commit()
        flash("Articolo aggiornato", "success")
        return redirect(url_for("edit_item", item_id=item.id))

    categories = Category.query.order_by(Category.name).all()
    subtypes   = Subtype.query.order_by(Subtype.name).all()
    materials  = Material.query.order_by(Material.name).all()
    finishes   = Finish.query.order_by(Finish.name).all()
    cabinets   = Cabinet.query.order_by(Cabinet.name).all()

    subtypes_by_cat = {}
    for s in subtypes:
        subtypes_by_cat.setdefault(s.category_id, []).append({"id": s.id, "name": s.name})

    thread_standards, sizes_by_standard = load_form_options()

    pos = (db.session.query(Assignment, Slot, Cabinet)
           .join(Slot, Assignment.slot_id == Slot.id)
           .join(Cabinet, Slot.cabinet_id == Cabinet.id)
           .filter(Assignment.item_id == item.id).first())
    current_cabinet_id = pos[2].id if pos else None
    current_col_code = pos[1].col_code if pos else ""
    current_row_num = pos[1].row_num if pos else ""

    custom_fields = CustomField.query.filter_by(is_active=True).order_by(CustomField.sort_order, CustomField.name).all()
    serialized_custom_fields = serialize_custom_fields(custom_fields)
    custom_field_values = {
        val.field_id: (val.value_text or "")
        for val in ItemCustomFieldValue.query.filter_by(item_id=item.id).all()
    }
    category_fields = build_category_field_map(categories)
    measure_labels = build_measure_labels(categories)

    return render_template("admin/edit_item.html",
        item=item, categories=categories, materials=materials, finishes=finishes,
        cabinets=cabinets, subtypes_by_cat=subtypes_by_cat,
        thread_standards=thread_standards, sizes_by_standard=sizes_by_standard,
        custom_fields=serialized_custom_fields,
        custom_field_values=custom_field_values,
        category_fields=category_fields,
        measure_labels=measure_labels,
        current_cabinet_id=current_cabinet_id,
        current_col_code=current_col_code,
        current_row_num=current_row_num
    )

@app.route("/admin/items/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    Assignment.query.filter_by(item_id=item.id).delete()
    db.session.delete(item)
    db.session.commit()
    flash("Articolo eliminato", "success")
    return redirect(url_for("admin_items"))

# ---- Posizione item ----
def _load_slot_assignments(slot_id: int, ignore_item_id: int | None = None):
    assigns = Assignment.query.filter_by(slot_id=slot_id).all()
    filtered = [a for a in assigns if a.item_id != ignore_item_id]
    item_ids = [a.item_id for a in filtered]
    items = Item.query.filter(Item.id.in_(item_ids)).all() if item_ids else []
    return assigns, items

def _normalize_thread_size(val: Optional[str]) -> str:
    return (val or "").strip().lower()

class SharePermissionError(RuntimeError):
    def __init__(self, items: list[Item]):
        super().__init__("Il cassetto contiene articoli che non supportano la condivisione.")
        self.items = items

def _share_slot_status(existing_items: list[Item], new_item: Item):
    if not existing_items:
        return True, []
    measure_new = _normalize_thread_size(getattr(new_item, "thread_size", None))
    category_new = getattr(new_item, "category_id", None)
    measures_ok = all(_normalize_thread_size(getattr(it, "thread_size", None)) == measure_new for it in existing_items)
    categories_ok = all(getattr(it, "category_id", None) == category_new for it in existing_items)
    # Permetti la condivisione se categoria e misura coincidono (comportamento precedente)
    # oppure se tutti condividono la stessa misura (es. M10) anche con categorie diverse.
    if not ((categories_ok and measures_ok) or (measure_new and measures_ok)):
        return False, []
    blockers = [it for it in existing_items if not getattr(it, "share_drawer", False)]
    if not getattr(new_item, "share_drawer", False):
        blockers.append(new_item)
    if blockers:
        return False, blockers
    return True, []

def _can_share_slot(existing_items: list[Item], new_item: Item) -> bool:
    ok, _ = _share_slot_status(existing_items, new_item)
    return ok

def _assign_position(item, cabinet_id:int, col_code:str, row_num:int, *, force_share: bool = False):
    if not column_code_valid(col_code):         raise ValueError("Colonna non valida (A..Z o AA..ZZ).")
    if not (1 <= int(row_num) <= 128):          raise ValueError("Riga non valida (1..128).")
    anchor_slot, slots, assignments, slot_items = _collect_region_assignments(
        cabinet_id, col_code, row_num, ignore_item_id=item.id
    )
    if anchor_slot.is_blocked:                         raise RuntimeError("La cella è bloccata (non assegnabile).")
    Assignment.query.filter_by(item_id=item.id).delete()

    can_share, blockers = _share_slot_status(slot_items, item)
    if not can_share:
        if blockers and force_share:
            for it in blockers:
                it.share_drawer = True
        elif blockers:
            raise SharePermissionError(blockers)
        else:
            raise RuntimeError("Il cassetto contiene articoli che non supportano la condivisione.")

    cab = db.session.get(Cabinet, int(cabinet_id))
    max_comp = _max_compartments_for_slot(cab, anchor_slot.col_code, anchor_slot.row_num)
    if len(assignments) >= max_comp:
        raise RuntimeError("Nessuno scomparto libero nello slot scelto.")

    # Sposta tutti gli assignment della regione nello slot anchor e riassegna i comparti.
    for a in assignments:
        a.slot_id = anchor_slot.id
    db.session.add(Assignment(slot_id=anchor_slot.id, compartment_no=0, item_id=item.id))
    _reassign_compartments(anchor_slot.id, cab)

def _suggest_position(item: Item):
    rows = (
        db.session.query(
            Slot,
            Cabinet,
            func.count(Assignment.id).label("assign_count"),
            func.min(Item.category_id).label("min_cat"),
            func.max(Item.category_id).label("max_cat"),
        )
        .join(Cabinet, Slot.cabinet_id == Cabinet.id)
        .outerjoin(Assignment, Assignment.slot_id == Slot.id)
        .outerjoin(Item, Assignment.item_id == Item.id)
        .group_by(Slot.id, Cabinet.id)
        .order_by(Cabinet.name, Slot.col_code, Slot.row_num)
        .all()
    )
    for slot, cab, assign_count, min_cat, max_cat in rows:
        if slot.is_blocked or assign_count == 0:
            continue
        _, slot_items = _load_slot_assignments(slot.id)
        if not _can_share_slot(slot_items, item):
            continue
        max_comp = _max_compartments_for_slot(cab, slot.col_code, slot.row_num)
        if assign_count < max_comp:
            return cab.id, slot.col_code, slot.row_num
    return None

@app.route("/admin/items/<int:item_id>/suggest_position")
@login_required
def suggest_position(item_id):
    item = Item.query.get_or_404(item_id)
    sug = _suggest_position(item)
    if not sug:
        return jsonify({"ok": False, "error": "Nessuna posizione compatibile trovata dove la categoria è già presente."})
    cab_id, col_code, row_num = sug
    return jsonify({"ok": True, "cabinet_id": cab_id, "col_code": col_code, "row_num": row_num})

@app.route("/admin/items/<int:item_id>/set_position", methods=["POST"])
@login_required
def set_position(item_id):
    item = Item.query.get_or_404(item_id)
    cab_id  = request.form.get("cabinet_id")
    row_num = request.form.get("row_num")
    col_code= request.form.get("col_code")
    force_share = bool(request.form.get("force_share"))
    if not (cab_id and row_num and col_code):
        flash("Compila cabinet, riga e colonna.", "danger"); return redirect(url_for("edit_item", item_id=item.id))
    try:
        _assign_position(item, int(cab_id), col_code, int(row_num), force_share=force_share)
        db.session.commit()
        flash("Posizione aggiornata.", "success")
    except SharePermissionError as e:
        db.session.rollback()
        blocker_names = ", ".join(sorted({auto_name_for(it) for it in e.items}))
        flash(f"Il cassetto contiene articoli che non supportano la condivisione: {blocker_names}.", "danger")
    except Exception as e:
        db.session.rollback(); flash(str(e), "danger")
    return redirect(url_for("edit_item", item_id=item.id))

@app.route("/admin/items/<int:item_id>/set_position.json", methods=["POST"])
@login_required
def set_position_json(item_id):
    item = Item.query.get_or_404(item_id)
    cab_id  = request.form.get("cabinet_id")
    row_num = request.form.get("row_num")
    col_code= request.form.get("col_code")
    force_share = bool(request.form.get("force_share"))
    if not (cab_id and row_num and col_code):
        return jsonify({"ok": False, "error": "Compila cabinet, riga e colonna."}), 400
    try:
        _assign_position(item, int(cab_id), col_code, int(row_num), force_share=force_share)
        db.session.commit()
        return jsonify({"ok": True})
    except SharePermissionError as e:
        db.session.rollback()
        blockers = [{"id": it.id, "name": auto_name_for(it)} for it in e.items]
        return jsonify({"ok": False, "error": str(e), "share_blockers": blockers}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/admin/items/<int:item_id>/clear_position", methods=["POST"])
@login_required
def clear_position(item_id):
    Assignment.query.filter_by(item_id=item_id).delete()
    db.session.commit()
    flash("Posizione rimossa.", "success")
    return redirect(url_for("edit_item", item_id=item_id))

@app.route("/admin/items/<int:item_id>/move_slot", methods=["POST"])
@login_required
def move_item_slot(item_id):
    item = Item.query.get_or_404(item_id)
    cab_to  = request.form.get("cabinet_id")
    col_to  = (request.form.get("col_code") or "").strip().upper()
    row_to  = request.form.get("row_num")
    if not (cab_to and col_to and row_to):
        flash("Compila cabinet, riga e colonna per spostare il cassetto.", "danger")
        return redirect(url_for("edit_item", item_id=item.id))
    try:
        cab_to = int(cab_to)
        row_to = int(row_to)
    except Exception:
        flash("Coordinate destinazione non valide.", "danger")
        return redirect(url_for("edit_item", item_id=item.id))

    assign = Assignment.query.filter_by(item_id=item.id).first()
    if not assign:
        flash("Questo articolo non ha una posizione da spostare.", "warning")
        return redirect(url_for("edit_item", item_id=item.id))
    src_slot = db.session.get(Slot, assign.slot_id)
    if not src_slot:
        flash("Slot origine non trovato.", "danger")
        return redirect(url_for("edit_item", item_id=item.id))

    region_from = merge_region_for(src_slot.cabinet_id, src_slot.col_code, src_slot.row_num)
    if region_from:
        anchor_col = region_from["anchor_col"]
        anchor_row = region_from["anchor_row"]
        src_slot = Slot.query.filter_by(cabinet_id=src_slot.cabinet_id, col_code=anchor_col, row_num=anchor_row).first() or _ensure_slot(src_slot.cabinet_id, anchor_col, anchor_row)

    region_to = merge_region_for(cab_to, col_to, row_to)
    if region_to:
        col_to = region_to["anchor_col"]
        row_to = region_to["anchor_row"]

    dst_slot = _ensure_slot(cab_to, col_to, row_to)
    if dst_slot.is_blocked:
        flash("La destinazione è bloccata.", "danger")
        return redirect(url_for("edit_item", item_id=item.id))
    if src_slot.is_blocked:
        flash("Il cassetto origine è bloccato: impossibile spostare.", "danger")
        return redirect(url_for("edit_item", item_id=item.id))

    src_assigns = Assignment.query.filter_by(slot_id=src_slot.id).all()
    dst_assigns = Assignment.query.filter_by(slot_id=dst_slot.id).all()
    if not src_assigns:
        flash("Nessun contenuto da spostare nel cassetto corrente.", "warning")
        return redirect(url_for("edit_item", item_id=item.id))

    src_cats = _slot_categories(src_slot.id)
    dst_cats = _slot_categories(dst_slot.id)
    if dst_assigns and (src_cats and dst_cats) and (list(src_cats)[0] != list(dst_cats)[0]):
        flash("Le categorie dei cassetti non coincidono.", "danger")
        return redirect(url_for("edit_item", item_id=item.id))

    cab_to_obj = db.session.get(Cabinet, cab_to)
    if not cab_to_obj:
        flash("Cassettiera destinazione non trovata.", "danger")
        return redirect(url_for("edit_item", item_id=item.id))
    if not _slot_capacity_ok(cab_to_obj, len(dst_assigns) + len(src_assigns), dst_slot.col_code, dst_slot.row_num):
        flash("Scomparti insufficienti nel cassetto destinazione.", "danger")
        return redirect(url_for("edit_item", item_id=item.id))

    for a in src_assigns:
        a.slot_id = dst_slot.id
    _reassign_compartments(dst_slot.id, cab_to_obj)
    db.session.commit()
    flash("Cassetto spostato.", "success")
    return redirect(url_for("edit_item", item_id=item.id))

def _admin_config_url(anchor=None):
    base = url_for("admin_config")
    return f"{base}#{anchor}" if anchor else base

# ===================== ADMIN: CATEGORIE =====================
@app.route("/admin/categories")
@login_required
def admin_categories():
    return redirect(_admin_config_url("categorie"))

@app.route("/admin/categories/add", methods=["POST"])
@login_required
def add_category():
    name = request.form.get("name","").strip()
    color = request.form.get("color","#000000").strip()
    mode = (request.form.get("main_measure_mode","") or MAIN_MEASURE_DEFAULT).strip().lower()
    if mode not in VALID_MEASURE_MODES:
        mode = MAIN_MEASURE_DEFAULT
    if len(name) < 2: return _flash_back("Nome categoria troppo corto.", "danger", "admin_config", "categorie")
    if Category.query.filter_by(name=name).first(): return _flash_back("Categoria già esistente.", "danger", "admin_config", "categorie")
    db.session.add(Category(name=name, color=color, main_measure_mode=mode)); db.session.commit()
    flash("Categoria aggiunta.", "success"); return redirect(_admin_config_url("categorie"))

@app.route("/admin/categories/<int:cat_id>/update", methods=["POST"])
@login_required
def update_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    new_name = request.form.get("name","").strip()
    new_color = request.form.get("color","#000000").strip()
    new_mode = request.form.get("main_measure_mode","").strip().lower()
    if new_mode not in VALID_MEASURE_MODES:
        new_mode = measure_mode_for_category(cat)
    if new_name and new_name != cat.name:
        if Category.query.filter(Category.id != cat.id, Category.name == new_name).first():
            return _flash_back("Esiste già una categoria con questo nome.", "danger", "admin_config", "categorie")
        cat.name = new_name
    cat.color = new_color or cat.color
    cat.main_measure_mode = new_mode
    db.session.commit()
    flash("Categoria aggiornata.", "success"); return redirect(_admin_config_url("categorie"))

@app.route("/admin/categories/<int:cat_id>/delete", methods=["POST"])
@login_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    used = Item.query.filter_by(category_id=cat.id).first()
    if used:
        flash("Impossibile eliminare: ci sono articoli associati.", "danger")
    else:
        db.session.delete(cat); db.session.commit(); flash("Categoria eliminata.", "success")
    return redirect(_admin_config_url("categorie"))

def _flash_back(msg, kind, endpoint, anchor=None):
    flash(msg, kind)
    url = url_for(endpoint)
    if anchor:
        url = f"{url}#{anchor}"
    return redirect(url)

@app.route("/admin/subtypes/add", methods=["POST"])
@login_required
def add_subtype():
    name = (request.form.get("name") or "").strip()
    try:
        category_id = int(request.form.get("category_id") or 0)
    except Exception:
        category_id = 0

    if category_id <= 0:
        return _flash_back("Seleziona una categoria valida per il sottotipo.", "danger", "admin_config", "sottotipi")
    if len(name) < 2:
        return _flash_back("Nome sottotipo troppo corto.", "danger", "admin_config", "sottotipi")

    # univoco per categoria (rispetta il vincolo uq_subtype_per_category)
    exists = Subtype.query.filter_by(category_id=category_id, name=name).first()
    if exists:
        return _flash_back("Esiste già un sottotipo con questo nome per la categoria selezionata.", "danger", "admin_config", "sottotipi")

    db.session.add(Subtype(category_id=category_id, name=name))
    db.session.commit()
    flash("Sottotipo aggiunto.", "success")
    return redirect(_admin_config_url("sottotipi"))


@app.route("/admin/subtypes/<int:st_id>/update", methods=["POST"])
@login_required
def update_subtype(st_id):
    st = Subtype.query.get_or_404(st_id)
    name = (request.form.get("name") or "").strip()
    try:
        category_id = int(request.form.get("category_id") or st.category_id)
    except Exception:
        category_id = st.category_id

    if len(name) < 2:
        return _flash_back("Nome sottotipo troppo corto.", "danger", "admin_config", "sottotipi")

    # evita duplicati nella stessa categoria
    clash = (
        Subtype.query
        .filter(Subtype.id != st.id,
                Subtype.category_id == category_id,
                Subtype.name == name)
        .first()
    )
    if clash:
        return _flash_back("Esiste già un sottotipo con questo nome per la categoria selezionata.", "danger", "admin_config", "sottotipi")

    st.name = name
    st.category_id = category_id
    db.session.commit()
    flash("Sottotipo aggiornato.", "success")
    return redirect(_admin_config_url("sottotipi"))


@app.route("/admin/subtypes/<int:st_id>/delete", methods=["POST"])
@login_required
def delete_subtype(st_id):
    st = Subtype.query.get_or_404(st_id)
    used = Item.query.filter_by(subtype_id=st.id).first()
    if used:
        flash("Impossibile eliminare: ci sono articoli associati a questo sottotipo.", "danger")
    else:
        db.session.delete(st)
        db.session.commit()
        flash("Sottotipo eliminato.", "success")
    return redirect(_admin_config_url("sottotipi"))

@app.route("/admin/materials/add", methods=["POST"])
@login_required
def add_material():
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        return _flash_back("Nome materiale troppo corto.", "danger", "admin_config", "materiali")
    if Material.query.filter_by(name=name).first():
        return _flash_back("Materiale già esistente.", "danger", "admin_config", "materiali")

    db.session.add(Material(name=name))
    db.session.commit()
    flash("Materiale aggiunto.", "success")
    return redirect(_admin_config_url("materiali"))


@app.route("/admin/materials/<int:mat_id>/update", methods=["POST"])
@login_required
def update_material(mat_id):
    mat = Material.query.get_or_404(mat_id)
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        return _flash_back("Nome materiale troppo corto.", "danger", "admin_config", "materiali")
    if Material.query.filter(Material.id != mat.id, Material.name == name).first():
        return _flash_back("Esiste già un materiale con questo nome.", "danger", "admin_config", "materiali")

    mat.name = name
    db.session.commit()
    flash("Materiale aggiornato.", "success")
    return redirect(_admin_config_url("materiali"))


@app.route("/admin/materials/<int:mat_id>/delete", methods=["POST"])
@login_required
def delete_material(mat_id):
    mat = Material.query.get_or_404(mat_id)
    used = Item.query.filter_by(material_id=mat.id).first()
    if used:
        flash("Impossibile eliminare: ci sono articoli che usano questo materiale.", "danger")
    else:
        db.session.delete(mat)
        db.session.commit()
        flash("Materiale eliminato.", "success")
    return redirect(_admin_config_url("materiali"))

@app.route("/admin/finishes/add", methods=["POST"])
@login_required
def add_finish():
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        return _flash_back("Nome finitura troppo corto.", "danger", "admin_config", "finiture")
    if Finish.query.filter_by(name=name).first():
        return _flash_back("Finitura già esistente.", "danger", "admin_config", "finiture")

    db.session.add(Finish(name=name))
    db.session.commit()
    flash("Finitura aggiunta.", "success")
    return redirect(_admin_config_url("finiture"))


@app.route("/admin/finishes/<int:fin_id>/update", methods=["POST"])
@login_required
def update_finish(fin_id):
    fin = Finish.query.get_or_404(fin_id)
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        return _flash_back("Nome finitura troppo corto.", "danger", "admin_config", "finiture")
    if Finish.query.filter(Finish.id != fin.id, Finish.name == name).first():
        return _flash_back("Esiste già una finitura con questo nome.", "danger", "admin_config", "finiture")

    fin.name = name
    db.session.commit()
    flash("Finitura aggiornata.", "success")
    return redirect(_admin_config_url("finiture"))


@app.route("/admin/finishes/<int:fin_id>/delete", methods=["POST"])
@login_required
def delete_finish(fin_id):
    fin = Finish.query.get_or_404(fin_id)
    used = Item.query.filter_by(finish_id=fin.id).first()
    if used:
        flash("Impossibile eliminare: ci sono articoli che usano questa finitura.", "danger")
    else:
        db.session.delete(fin)
        db.session.commit()
        flash("Finitura eliminata.", "success")
    return redirect(_admin_config_url("finiture"))

# ===================== ADMIN: CONFIGURAZIONE =====================
@app.route("/admin/config")
@login_required
def admin_config():
    ensure_category_columns()
    locations = Location.query.order_by(Location.name).all()
    cabinets  = db.session.query(Cabinet, Location).join(Location, Cabinet.location_id==Location.id).order_by(Cabinet.name).all()
    drawer_merges = (
        db.session.query(DrawerMerge, Cabinet)
        .join(Cabinet, DrawerMerge.cabinet_id == Cabinet.id)
        .order_by(Cabinet.name, DrawerMerge.row_start, DrawerMerge.col_start)
        .all()
    )
    categories = Category.query.order_by(Category.name).all()
    materials  = Material.query.order_by(Material.name).all()
    finishes   = Finish.query.order_by(Finish.name).all()
    subtypes   = (
        db.session.query(Subtype, Category)
        .join(Category, Subtype.category_id == Category.id)
        .order_by(Category.name, Subtype.name)
        .all()
    )
    used_subtypes = {
        subtype_id
        for (subtype_id,) in db.session.query(Item.subtype_id)
        .filter(Item.subtype_id.isnot(None))
        .distinct()
        .all()
    }
    used_materials = {
        material_id
        for (material_id,) in db.session.query(Item.material_id)
        .filter(Item.material_id.isnot(None))
        .distinct()
        .all()
    }
    used_finishes = {
        finish_id
        for (finish_id,) in db.session.query(Item.finish_id)
        .filter(Item.finish_id.isnot(None))
        .distinct()
        .all()
    }
    used_categories = {
        cat_id
        for (cat_id,) in db.session.query(Item.category_id)
        .filter(Item.category_id.isnot(None))
        .distinct()
        .all()
    }
    custom_fields = CustomField.query.order_by(CustomField.sort_order, CustomField.name).all()
    serialized_custom_fields = serialize_custom_fields(custom_fields)
    field_defs = build_field_definitions(serialized_custom_fields)
    category_fields = build_category_field_map(categories)
    used_category_fields = get_used_field_keys_by_category()
    return render_template(
        "admin/config.html",
        locations=locations,
        cabinets=cabinets,
        drawer_merges=drawer_merges,
        settings=get_settings(),
        mqtt_settings=get_mqtt_settings(),
        categories=categories,
        materials=materials,
        finishes=finishes,
        subtypes=subtypes,
        used_subtypes=used_subtypes,
        used_materials=used_materials,
        used_finishes=used_finishes,
        used_categories=used_categories,
        custom_fields=serialized_custom_fields,
        field_defs=field_defs,
        category_fields=category_fields,
        used_category_fields=used_category_fields,
    )

@app.route("/admin/config/fields/<int:cat_id>/update", methods=["POST"])
@login_required
def update_category_fields(cat_id):
    category = Category.query.get_or_404(cat_id)
    selected_keys = set(request.form.getlist("field_keys"))
    used_fields = get_used_field_keys_by_category().get(category.id, [])
    selected_keys.update(used_fields)
    CategoryFieldSetting.query.filter_by(category_id=category.id).delete()
    if not selected_keys:
        db.session.add(CategoryFieldSetting(category_id=category.id, field_key="__none__", is_enabled=False))
    else:
        for key in sorted(selected_keys):
            db.session.add(CategoryFieldSetting(category_id=category.id, field_key=key, is_enabled=True))
    db.session.commit()
    flash(f"Campi aggiornati per {category.name}.", "success")
    return redirect(_admin_config_url("campi-categoria"))

@app.route("/admin/custom_fields/add", methods=["POST"])
@login_required
def add_custom_field():
    name = (request.form.get("name") or "").strip()
    field_type = (request.form.get("field_type") or "text").strip().lower()
    options = (request.form.get("options") or "").strip() or None
    unit = (request.form.get("unit") or "").strip() or None
    sort_order = int(request.form.get("sort_order") or 0)
    is_active = bool(request.form.get("is_active"))
    if len(name) < 2:
        return _flash_back("Nome campo troppo corto.", "danger", "admin_config")
    if field_type not in {"text", "number", "select"}:
        return _flash_back("Tipo campo non valido.", "danger", "admin_config")
    if CustomField.query.filter_by(name=name).first():
        return _flash_back("Campo personalizzato già esistente.", "danger", "admin_config")
    db.session.add(CustomField(
        name=name,
        field_type=field_type,
        options=options,
        unit=unit,
        sort_order=sort_order,
        is_active=is_active,
    ))
    db.session.commit()
    flash("Campo personalizzato aggiunto.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/custom_fields/<int:field_id>/update", methods=["POST"])
@login_required
def update_custom_field(field_id):
    field = CustomField.query.get_or_404(field_id)
    name = (request.form.get("name") or "").strip()
    field_type = (request.form.get("field_type") or "text").strip().lower()
    options = (request.form.get("options") or "").strip() or None
    unit = (request.form.get("unit") or "").strip() or None
    sort_order = int(request.form.get("sort_order") or 0)
    is_active = bool(request.form.get("is_active"))
    if len(name) < 2:
        return _flash_back("Nome campo troppo corto.", "danger", "admin_config")
    if field_type not in {"text", "number", "select"}:
        return _flash_back("Tipo campo non valido.", "danger", "admin_config")
    if CustomField.query.filter(CustomField.id != field.id, CustomField.name == name).first():
        return _flash_back("Esiste già un campo con questo nome.", "danger", "admin_config")
    field.name = name
    field.field_type = field_type
    field.options = options
    field.unit = unit
    field.sort_order = sort_order
    field.is_active = is_active
    db.session.commit()
    flash("Campo personalizzato aggiornato.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/custom_fields/<int:field_id>/delete", methods=["POST"])
@login_required
def delete_custom_field(field_id):
    field = CustomField.query.get_or_404(field_id)
    ItemCustomFieldValue.query.filter_by(field_id=field.id).delete()
    CategoryFieldSetting.query.filter_by(field_key=custom_field_key(field.id)).delete()
    db.session.delete(field)
    db.session.commit()
    flash("Campo personalizzato eliminato.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/settings/update", methods=["POST"])
@login_required
def update_settings():
    s = get_settings()
    try:
        s.label_w_mm  = float(request.form.get("label_w_mm"))
        s.label_h_mm  = float(request.form.get("label_h_mm"))
        s.margin_tb_mm= float(request.form.get("margin_tb_mm"))
        s.margin_lr_mm= float(request.form.get("margin_lr_mm"))
        s.gap_mm      = float(request.form.get("gap_mm"))
        s.label_padding_mm = float(request.form.get("label_padding_mm"))
        s.label_qr_size_mm = float(request.form.get("label_qr_size_mm"))
        s.label_qr_margin_mm = float(request.form.get("label_qr_margin_mm"))
        s.label_position_width_mm = float(request.form.get("label_position_width_mm"))
        s.label_position_font_pt = float(request.form.get("label_position_font_pt"))
        s.orientation_landscape = bool(request.form.get("orientation_landscape"))
        s.qr_default  = bool(request.form.get("qr_default"))
        url = request.form.get("qr_base_url","").strip()
        s.qr_base_url = url or None
        db.session.commit()
        flash("Impostazioni aggiornate.", "success")
    except Exception as e:
        db.session.rollback(); flash(f"Errore salvataggio: {e}", "danger")
    return redirect(url_for("admin_config"))

@app.route("/admin/mqtt/update", methods=["POST"])
@login_required
def update_mqtt_settings():
    s = get_mqtt_settings()
    try:
        s.enabled = bool(request.form.get("enabled"))
        s.host = (request.form.get("host") or "").strip() or None
        s.port = int(request.form.get("port") or DEFAULT_MQTT_PORT)
        s.username = (request.form.get("username") or "").strip() or None
        password = request.form.get("password") or ""
        if password:
            s.password = password
        if request.form.get("clear_password"):
            s.password = None
        s.topic = (request.form.get("topic") or "").strip() or None
        s.qos = int(request.form.get("qos") or DEFAULT_MQTT_QOS)
        s.retain = bool(request.form.get("retain"))
        s.client_id = (request.form.get("client_id") or "").strip() or None
        s.include_cabinet_name = bool(request.form.get("include_cabinet_name"))
        s.include_cabinet_id = bool(request.form.get("include_cabinet_id"))
        s.include_location_name = bool(request.form.get("include_location_name"))
        s.include_location_id = bool(request.form.get("include_location_id"))
        s.include_row = bool(request.form.get("include_row"))
        s.include_col = bool(request.form.get("include_col"))
        s.include_slot_label = bool(request.form.get("include_slot_label"))
        s.include_items = bool(request.form.get("include_items"))
        s.include_item_id = bool(request.form.get("include_item_id"))
        s.include_item_name = bool(request.form.get("include_item_name"))
        s.include_item_category = bool(request.form.get("include_item_category"))
        s.include_item_category_color = bool(request.form.get("include_item_category_color"))
        s.include_item_quantity = bool(request.form.get("include_item_quantity"))
        s.include_item_position = bool(request.form.get("include_item_position"))
        s.include_item_description = bool(request.form.get("include_item_description"))
        s.include_item_material = bool(request.form.get("include_item_material"))
        s.include_item_finish = bool(request.form.get("include_item_finish"))
        s.include_empty = bool(request.form.get("include_empty"))
        db.session.commit()
        flash("Configurazione MQTT aggiornata.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore salvataggio MQTT: {e}", "danger")
    return redirect(url_for("admin_config"))

@app.route("/admin/locations/add", methods=["POST"])
@login_required
def add_location():
    name = request.form.get("name","").strip()
    if len(name) < 2:
        return _flash_back("Nome ubicazione troppo corto.", "danger", "admin_config")
    if Location.query.filter_by(name=name).first():
        return _flash_back("Ubicazione già esistente.", "danger", "admin_config")
    db.session.add(Location(name=name)); db.session.commit()
    flash("Ubicazione aggiunta.", "success"); return redirect(url_for("admin_config"))

@app.route("/admin/locations/<int:loc_id>/update", methods=["POST"])
@login_required
def update_location(loc_id):
    loc = Location.query.get_or_404(loc_id)
    name = request.form.get("name","").strip()
    if len(name) < 2:
        return _flash_back("Nome ubicazione troppo corto.", "danger", "admin_config")
    if Location.query.filter(Location.id!=loc.id, Location.name==name).first():
        return _flash_back("Esiste già un’ubicazione con questo nome.", "danger", "admin_config")
    loc.name=name; db.session.commit()
    flash("Ubicazione aggiornata.", "success"); return redirect(url_for("admin_config"))

@app.route("/admin/locations/<int:loc_id>/delete", methods=["POST"])
@login_required
def delete_location(loc_id):
    loc = Location.query.get_or_404(loc_id)
    has_cab = Cabinet.query.filter_by(location_id=loc.id).first()
    if has_cab:
        flash("Impossibile eliminare: ci sono cassettiere collegate.", "danger")
    else:
        db.session.delete(loc); db.session.commit(); flash("Ubicazione eliminata.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/cabinets/add", methods=["POST"])
@login_required
def add_cabinet():
    try: location_id = int(request.form.get("location_id"))
    except: return _flash_back("Seleziona ubicazione valida.", "danger", "admin_config")
    name = request.form.get("name","").strip()
    rows = int(request.form.get("rows_max") or 128)
    cols = request.form.get("cols_max","ZZ").strip().upper()
    comps= int(request.form.get("compartments_per_slot") or 6)
    if len(name) < 2:
        return _flash_back("Nome cassettiera troppo corto.", "danger", "admin_config")
    if Cabinet.query.filter_by(name=name).first():
        return _flash_back("Nome cassettiera già in uso.", "danger", "admin_config")
    db.session.add(Cabinet(location_id=location_id, name=name, rows_max=rows, cols_max=cols, compartments_per_slot=comps))
    db.session.commit(); flash("Cassettiera aggiunta.", "success"); return redirect(url_for("admin_config"))

@app.route("/admin/cabinets/<int:cab_id>/update", methods=["POST"])
@login_required
def update_cabinet(cab_id):
    cab = Cabinet.query.get_or_404(cab_id)
    name  = request.form.get("name","").strip()
    rows  = int(request.form.get("rows_max") or cab.rows_max)
    cols  = request.form.get("cols_max","ZZ").strip().upper()
    comps = int(request.form.get("compartments_per_slot") or cab.compartments_per_slot)
    if len(name) < 2:
        return _flash_back("Nome cassettiera troppo corto.", "danger", "admin_config")
    if Cabinet.query.filter(Cabinet.id!=cab.id, Cabinet.name==name).first():
        return _flash_back("Nome cassettiera già in uso.", "danger", "admin_config")
    cab.name=name; cab.rows_max=rows; cab.cols_max=cols; cab.compartments_per_slot=comps
    db.session.commit(); flash("Cassettiera aggiornata.", "success"); return redirect(url_for("admin_config"))

@app.route("/admin/cabinets/<int:cab_id>/delete", methods=["POST"])
@login_required
def delete_cabinet(cab_id):
    cab = Cabinet.query.get_or_404(cab_id)
    has_slots = Slot.query.filter_by(cabinet_id=cab.id).first()
    if has_slots:
        flash("Impossibile eliminare: la cassettiera ha slot assegnati.", "danger")
    else:
        db.session.delete(cab); db.session.commit(); flash("Cassettiera eliminata.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/cabinets/merge_add", methods=["POST"])
@login_required
def add_drawer_merge():
    try:
        cab_id = int(request.form.get("cabinet_id"))
    except Exception:
        return _flash_back("Cassettiera non valida.", "danger", "admin_config")
    cab = Cabinet.query.get_or_404(cab_id)
    col_start = (request.form.get("col_start") or "").strip().upper()
    col_end = (request.form.get("col_end") or "").strip().upper()
    try:
        row_start = int(request.form.get("row_start"))
        row_end = int(request.form.get("row_end"))
        row_start, row_end, col_start, col_end = normalize_merge_bounds(
            cab, col_start, col_end, row_start, row_end
        )
    except Exception as exc:
        return _flash_back(str(exc), "danger", "admin_config")

    new_start_idx = colcode_to_idx(col_start)
    new_end_idx = colcode_to_idx(col_end)
    existing = DrawerMerge.query.filter_by(cabinet_id=cab.id).all()
    for m in existing:
        m_start_idx = colcode_to_idx(m.col_start)
        m_end_idx = colcode_to_idx(m.col_end)
        rows_overlap = not (row_end < m.row_start or row_start > m.row_end)
        cols_overlap = not (new_end_idx < m_start_idx or new_start_idx > m_end_idx)
        if rows_overlap and cols_overlap:
            return _flash_back("La fusione si sovrappone a un'altra già definita.", "danger", "admin_config")

    db.session.add(DrawerMerge(
        cabinet_id=cab.id,
        row_start=row_start,
        row_end=row_end,
        col_start=col_start,
        col_end=col_end,
    ))
    db.session.commit()
    flash("Fusione cassetti aggiunta.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/cabinets/merge/<int:merge_id>/delete", methods=["POST"])
@login_required
def delete_drawer_merge(merge_id):
    merge = DrawerMerge.query.get_or_404(merge_id)
    db.session.delete(merge)
    db.session.commit()
    flash("Fusione cassetti eliminata.", "success")
    return redirect(url_for("admin_config"))

def _ensure_slot(cab_id:int, col_code:str, row_num:int) -> Slot:
    s = Slot.query.filter_by(cabinet_id=cab_id, col_code=col_code.upper(), row_num=row_num).first()
    if not s:
        s = Slot(cabinet_id=cab_id, col_code=col_code.upper(), row_num=row_num, is_blocked=False)
        db.session.add(s); db.session.flush()
    return s

def _slot_categories(slot_id:int) -> set:
    rows = (
        db.session.query(Item.category_id)
        .join(Assignment, Assignment.item_id == Item.id)
        .filter(Assignment.slot_id == slot_id)
        .distinct()
        .all()
    )
    return {cat_id for (cat_id,) in rows if cat_id}

def _slot_capacity_ok(cabinet:Cabinet, assigns_count:int, col_code:str, row_num:int) -> bool:
    max_comp = _max_compartments_for_slot(cabinet, col_code, row_num)
    return assigns_count <= max_comp

def _reassign_compartments(slot_id:int, cabinet:Cabinet):
    assigns = Assignment.query.filter_by(slot_id=slot_id).order_by(Assignment.id).all()
    slot = db.session.get(Slot, slot_id)
    max_comp = _max_compartments_for_slot(cabinet, slot.col_code, slot.row_num)
    n = 1
    for a in assigns:
        if n>max_comp: raise RuntimeError("Capienza scomparti superata.")
        a.compartment_no = n; n += 1

@app.route("/admin/slots/block", methods=["POST"])
@login_required
def block_slot():
    cab_id = int(request.form.get("cabinet_id"))
    col    = request.form.get("col_code","").upper().strip()
    row    = int(request.form.get("row_num"))
    if not column_code_valid(col) or not (1<=row<=128):
        return _flash_back("Colonna/riga non validi.", "danger", "admin_config")
    region = merge_region_for(cab_id, col, row)
    cells = merge_cells_from_region(region) if region else [(col, row)]
    slots = [_ensure_slot(cab_id, c, r) for c, r in cells]
    if any(Assignment.query.filter_by(slot_id=slot.id).first() for slot in slots):
        flash("Impossibile bloccare: cassetto occupato.", "danger")
    else:
        for slot in slots:
            slot.is_blocked = True
        db.session.commit()
        flash("Cella bloccata.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/slots/unblock", methods=["POST"])
@login_required
def unblock_slot():
    cab_id = int(request.form.get("cabinet_id"))
    col    = request.form.get("col_code","").upper().strip()
    row    = int(request.form.get("row_num"))
    if not column_code_valid(col) or not (1<=row<=128):
        return _flash_back("Colonna/riga non validi.", "danger", "admin_config")
    region = merge_region_for(cab_id, col, row)
    cells = merge_cells_from_region(region) if region else [(col, row)]
    for c, r in cells:
        slot = _ensure_slot(cab_id, c, r)
        slot.is_blocked = False
    db.session.commit()
    flash("Cella sbloccata.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/slots/move", methods=["POST"])
@login_required
def move_slot():
    try:
        cab_from = int(request.form.get("cabinet_from"))
        col_from = request.form.get("col_from","").upper().strip()
        row_from = int(request.form.get("row_from"))
        cab_to   = int(request.form.get("cabinet_to"))
        col_to   = request.form.get("col_to","").upper().strip()
        row_to   = int(request.form.get("row_to"))
        do_swap  = bool(request.form.get("swap"))
    except Exception:
        return _flash_back("Parametri non validi.", "danger", "admin_config")
    if not (column_code_valid(col_from) and column_code_valid(col_to) and 1<=row_from<=128 and 1<=row_to<=128):
        return _flash_back("Colonna/riga non validi.", "danger", "admin_config")

    region_from = merge_region_for(cab_from, col_from, row_from)
    if region_from:
        col_from = region_from["anchor_col"]
        row_from = region_from["anchor_row"]
    region_to = merge_region_for(cab_to, col_to, row_to)
    if region_to:
        col_to = region_to["anchor_col"]
        row_to = region_to["anchor_row"]

    src = Slot.query.filter_by(cabinet_id=cab_from, col_code=col_from, row_num=row_from).first()
    if not src: return _flash_back("Slot origine inesistente.", "danger", "admin_config")
    dst = _ensure_slot(cab_to, col_to, row_to)
    if dst.is_blocked: return _flash_back("Destinazione bloccata.", "danger", "admin_config")
    if src.is_blocked: return _flash_back("Origine bloccata.", "danger", "admin_config")

    src_assigns = Assignment.query.filter_by(slot_id=src.id).all()
    dst_assigns = Assignment.query.filter_by(slot_id=dst.id).all()
    if not src_assigns:
        flash("Nessun contenuto nel cassetto origine.", "warning"); return redirect(url_for("admin_config"))

    src_cats = _slot_categories(src.id)
    dst_cats = _slot_categories(dst.id)
    if dst_assigns and (src_cats and dst_cats) and (list(src_cats)[0] != list(dst_cats)[0]):
        return _flash_back("Le categorie dei cassetti non coincidono.", "danger", "admin_config")

    cab_to_obj = db.session.get(Cabinet, cab_to)
    cab_from_obj = db.session.get(Cabinet, cab_from)

    if not do_swap:
        if not _slot_capacity_ok(cab_to_obj, len(dst_assigns)+len(src_assigns), dst.col_code, dst.row_num):
            return _flash_back("Scomparti insufficienti nel cassetto destinazione.", "danger", "admin_config")
        for a in src_assigns: a.slot_id = dst.id
        _reassign_compartments(dst.id, cab_to_obj)
        db.session.commit(); flash("Cassetto spostato.", "success")
    else:
        if (
            not _slot_capacity_ok(cab_to_obj, len(dst_assigns)+len(src_assigns), dst.col_code, dst.row_num)
            or not _slot_capacity_ok(cab_from_obj, len(src_assigns)+len(dst_assigns), src.col_code, src.row_num)
        ):
            return _flash_back("Scomparti insufficienti per lo scambio.", "danger", "admin_config")
        for a in src_assigns: a.slot_id = dst.id
        for a in dst_assigns: a.slot_id = src.id
        _reassign_compartments(dst.id, cab_to_obj)
        _reassign_compartments(src.id, cab_from_obj)
        db.session.commit(); flash("Cassetti scambiati.", "success")
    return redirect(url_for("admin_config"))

# ===================== CLICK-TO-ASSIGN API =====================
@app.route("/admin/unplaced.json")
@login_required
def api_unplaced():
    cat_id = request.args.get("category_id", type=int)
    subq = select(Assignment.item_id)
    q = Item.query.filter(Item.id.not_in(subq))
    if cat_id: q = q.filter(Item.category_id == cat_id)
    items = q.order_by(Item.category_id, Item.id).all()
    return jsonify([{"id":it.id,"caption":auto_name_for(it),"category_id":it.category_id} for it in items])

@app.route("/admin/grid_assign", methods=["POST"])
@login_required
def grid_assign():
    try:
        item_id  = int(request.form.get("item_id"))
        cabinet_id = int(request.form.get("cabinet_id"))
        col_code = request.form.get("col_code","").upper().strip()
        row_num  = int(request.form.get("row_num"))
    except Exception:
        return jsonify({"ok":False, "error":"Parametri non validi."}), 400
    item = Item.query.get(item_id)
    if not item: return jsonify({"ok":False, "error":"Articolo inesistente."}), 404
    force_share = bool(request.form.get("force_share"))
    try:
        _assign_position(item, cabinet_id, col_code, row_num, force_share=force_share)
        db.session.commit()
    except SharePermissionError as e:
        db.session.rollback()
        blockers = [{"id": it.id, "name": auto_name_for(it)} for it in e.items]
        return jsonify({"ok":False, "error":str(e), "share_blockers": blockers}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok":False, "error":str(e)}), 400
    return jsonify({"ok":True})

@app.route("/admin/slot_items")
@login_required
def slot_items():
    cab_id = request.args.get("cabinet_id", type=int)
    col_code = (request.args.get("col_code") or "").strip().upper()
    row_num = request.args.get("row_num", type=int)
    if not (cab_id and col_code and row_num):
        return jsonify({"ok": False, "error": "Parametri mancanti."}), 400

    region = merge_region_for(cab_id, col_code, row_num)
    if region:
        col_code = region["anchor_col"]
        row_num = region["anchor_row"]
        cells = merge_cells_from_region(region)
    else:
        cells = [(col_code, row_num)]

    slots = (
        Slot.query.filter(Slot.cabinet_id == cab_id)
        .filter(or_(*[
            (Slot.col_code == col) & (Slot.row_num == row)
            for col, row in cells
        ]))
        .all()
    )
    if not slots:
        return jsonify({"ok": True, "items": []})

    slot_ids = [s.id for s in slots]
    assigns = (
        db.session.query(Assignment, Item, Category, Slot)
        .join(Item, Assignment.item_id == Item.id)
        .join(Category, Item.category_id == Category.id, isouter=True)
        .join(Slot, Assignment.slot_id == Slot.id)
        .filter(Assignment.slot_id.in_(slot_ids))
        .order_by(Slot.col_code, Slot.row_num, Assignment.compartment_no)
        .all()
    )

    items = []
    for a, it, cat, slot in assigns:
        items.append({
            "id": it.id,
            "name": auto_name_for(it),
            "quantity": it.quantity,
            "category": cat.name if cat else None,
            "color": cat.color if cat else "#999999",
            "position": slot_label(slot, for_display=True, fallback_col=slot.col_code, fallback_row=slot.row_num),
        })
    return jsonify({
        "ok": True,
        "items": items,
        "slot_label_display": label_display,
        "slot_label_print": label_print,
        "default_label": default_label,
    })

@app.route("/admin/slot_label", methods=["GET", "POST"])
@login_required
def slot_label_endpoint():
    cab_id = request.values.get("cabinet_id", type=int)
    col_code = (request.values.get("col_code") or "").strip().upper()
    row_num = request.values.get("row_num", type=int)
    if not (cab_id and col_code and row_num):
        return jsonify({"ok": False, "error": "Parametri mancanti."}), 400
    cabinet = Cabinet.query.get(cab_id)
    if not cabinet:
        return jsonify({"ok": False, "error": "Cassettiera non trovata."}), 404
    region = merge_region_for(cabinet.id, col_code, row_num)
    if region:
        col_code = region["anchor_col"]
        row_num = region["anchor_row"]
    try:
        slot = _ensure_slot(cabinet.id, col_code, int(row_num))
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400

    if request.method == "POST":
        display_label = (request.form.get("display_label") or "").strip()
        print_label = (request.form.get("print_label") or "").strip()
        slot.display_label_override = display_label or None
        slot.print_label_override = print_label or None
        db.session.commit()

    default_label = f"{slot.col_code}{slot.row_num}"
    return jsonify({
        "ok": True,
        "display_label": slot.display_label_override,
        "print_label": slot.print_label_override,
        "default_label": default_label,
        "effective_display_label": slot_label(slot, for_display=True, fallback_col=slot.col_code, fallback_row=slot.row_num),
        "effective_print_label": slot_label(slot, for_display=False, fallback_col=slot.col_code, fallback_row=slot.row_num),
        "cabinet_name": cabinet.name,
    })

@app.route("/admin/mqtt/publish_slot", methods=["POST"])
@login_required
def mqtt_publish_slot():
    payload = request.get_json(silent=True) or {}
    cab_id = payload.get("cabinet_id")
    col_code = (payload.get("col_code") or "").strip().upper()
    row_num = payload.get("row_num")
    try:
        cab_id = int(cab_id)
        row_num = int(row_num)
    except Exception:
        return jsonify({"ok": False, "error": "Parametri non validi."}), 400
    if not col_code:
        return jsonify({"ok": False, "error": "Colonna non valida."}), 400
    cabinet = Cabinet.query.get(cab_id)
    if not cabinet:
        return jsonify({"ok": False, "error": "Cassettiera non trovata."}), 404
    settings = get_mqtt_settings()
    mqtt_payload = mqtt_payload_for_slot(cabinet, col_code, row_num, settings)
    if mqtt_payload is None:
        return jsonify({"ok": False, "skipped": True, "error": "Nessun contenuto da pubblicare."}), 200
    result = publish_mqtt_payload(mqtt_payload, settings)
    status = 200 if result.get("ok") else 500
    if result.get("skipped"):
        status = 200
    return jsonify(result), status


@app.route("/admin/slot_items/<int:item_id>/clear", methods=["POST"])
@login_required
def slot_clear_item(item_id):
    Assignment.query.filter_by(item_id=item_id).delete()
    db.session.commit()
    return jsonify({"ok": True})

# ===================== ASSEGNAMENTO AUTOMATICO =====================
def _iter_cabinet_walk(cabinet: Cabinet, start_col: str, start_row: int, direction: str):
    """
    Generatore di celle a partire da (start_col, start_row) nella cassettiera indicata.
    direction = "H" (orizzontale) o "V" (verticale).
    """
    if not cabinet:
        raise ValueError("Cassettiera inesistente.")
    cols = list(iter_cols_upto(cabinet.cols_max or "Z"))
    rows = list(range(1, min(128, max(1, int(cabinet.rows_max))) + 1))

    start_col = (start_col or "").strip().upper()
    if start_col not in cols:
        raise ValueError("Colonna di partenza fuori dalla cassettiera selezionata.")
    try:
        row_num_int = int(start_row)
    except Exception:
        raise ValueError("Riga di partenza non valida.")
    if row_num_int not in rows:
        raise ValueError("Riga di partenza fuori dalla cassettiera selezionata.")

    col_index0 = cols.index(start_col)
    row_index0 = rows.index(row_num_int)
    direction = (direction or "H").upper()

    if direction == "V":
        # dall'alto verso il basso, poi colonna successiva
        for ci in range(col_index0, len(cols)):
            for ri in range(row_index0 if ci == col_index0 else 0, len(rows)):
                yield cols[ci], rows[ri]
    else:
        # da sinistra a destra, poi riga successiva
        for ri in range(row_index0, len(rows)):
            for ci in range(col_index0 if ri == row_index0 else 0, len(cols)):
                yield cols[ci], rows[ri]


def _auto_assign_category(category_id: int,
                          cabinet_id: int,
                          start_col: str,
                          start_row: int,
                          direction: str,
                          primary_key: str,
                          secondary_key: str,
                          count: int,
                          clear_occupied: bool):
    """
    Esegue l'assegnamento automatico di `count` articoli (non ancora posizionati)
    della categoria indicata, a partire dalla cella indicata nella cassettiera scelta.
    Ritorna un dict con qualche statistica sull'operazione.
    """
    if count <= 0:
        raise ValueError("Il numero di articoli da posizionare deve essere maggiore di zero.")

    cab = db.session.get(Cabinet, int(cabinet_id))
    if not cab:
        raise ValueError("Cassettiera inesistente.")

    # Articoli non ancora posizionati per la categoria
    subq = select(Assignment.item_id)
    q = Item.query.filter(Item.id.not_in(subq), Item.category_id == int(category_id))

    sort_map = {
        "id":           Item.id,
        "thread_size":  Item.thread_size,
        "thickness_mm": Item.thickness_mm,
        "length_mm":    Item.length_mm,
        "outer_d_mm":   Item.outer_d_mm,
        "material":     Item.material_id,
    }
    order_cols = []
    if primary_key in sort_map:
        order_cols.append(sort_map[primary_key])
    if secondary_key in sort_map and secondary_key != primary_key:
        order_cols.append(sort_map[secondary_key])
    if not order_cols:
        order_cols = [Item.id]
    q = q.order_by(*order_cols)

    all_candidates = q.all()
    if not all_candidates:
        raise ValueError("Nessun articolo non posizionato per la categoria selezionata.")
    items = all_candidates[:count]
    requested = len(items)
    total_unplaced = len(all_candidates)

    assignments_plan = []   # (item, col_code, row_num)
    skipped_occupied = set()   # celle saltate perché già occupate (clear_occupied=False)
    reused_slots = set()       # celle che verranno liberate e riutilizzate (clear_occupied=True)
    planned_items = {}         # key -> lista di Item (esistenti + pianificati) per compatibilità
    slot_plan = []             # lista ordinata di slot percorsi con capacità residua e contenuto

    for col_code, row_num in _iter_cabinet_walk(cab, start_col, start_row, direction):
        slot = Slot.query.filter_by(cabinet_id=cab.id, col_code=col_code, row_num=row_num).first()
        if slot and slot.is_blocked:
            continue
        slot_key = (col_code, row_num)
        assigns = []
        slot_items = []
        if slot:
            assigns, slot_items = _load_slot_assignments(slot.id)
        has_content = bool(assigns)
        if has_content and clear_occupied:
            reused_slots.add(slot_key)
            slot_items = []
            existing_count = 0
        else:
            existing_count = len(assigns)

        max_here = _max_compartments_for_slot(cab, col_code, row_num)
        free_here = max_here - existing_count
        if free_here <= 0:
            if has_content and not clear_occupied:
                skipped_occupied.add(slot_key)
            continue

        planned_items.setdefault(slot_key, slot_items.copy())
        slot_plan.append({
            "key": slot_key,
            "col": col_code,
            "row": row_num,
            "has_content": has_content,
            "remaining": free_here,
        })

    if not slot_plan:
        raise ValueError("Nessuna cella disponibile per l'assegnamento automatico.")

    for itm in items:
        placed = False
        # 1) preferisce riutilizzare cassetti già occupati e compatibili
        for info in slot_plan:
            if not info["has_content"]:
                continue
            if info["remaining"] <= 0:
                continue
            if not _can_share_slot(planned_items[info["key"]], itm):
                skipped_occupied.add(info["key"])
                continue
            assignments_plan.append((itm, info["col"], info["row"]))
            planned_items[info["key"]].append(itm)
            info["remaining"] -= 1
            placed = True
            break

        if placed:
            continue

        # 2) altrimenti usa celle vuote (o liberate)
        for info in slot_plan:
            if info["remaining"] <= 0:
                continue
            if not _can_share_slot(planned_items[info["key"]], itm):
                if info["has_content"] and not clear_occupied:
                    skipped_occupied.add(info["key"])
                continue
            assignments_plan.append((itm, info["col"], info["row"]))
            planned_items[info["key"]].append(itm)
            info["remaining"] -= 1
            placed = True
            break

        if not placed:
            break

    if not assignments_plan:
        if skipped_occupied and not clear_occupied:
            raise ValueError("Tutte le celle nel percorso sono già popolate o bloccate; nessun articolo assegnato.")
        raise ValueError("Nessuna cella disponibile per l'assegnamento automatico.")

    cleared_slots = 0
    assigned = 0
    try:
        if clear_occupied and reused_slots:
            for col_code, row_num in sorted(reused_slots):
                slot = Slot.query.filter_by(cabinet_id=cab.id, col_code=col_code, row_num=row_num).first()
                if slot:
                    deleted = Assignment.query.filter_by(slot_id=slot.id).delete()
                    if deleted:
                        cleared_slots += 1

        for item, col_code, row_num in assignments_plan:
            _assign_position(item, cab.id, col_code, row_num)
            assigned += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    collisions_count = len(reused_slots) if clear_occupied else len(set(skipped_occupied))
    return {
        "assigned": assigned,
        "cleared_slots": cleared_slots,
        "collisions": collisions_count,
        "requested": requested,
        "total_unplaced": total_unplaced,
    }


def _deallocate_category_from_cabinet(category_id: int, cabinet_id: int):
    cab = db.session.get(Cabinet, int(cabinet_id))
    if not cab:
        raise ValueError("Cassettiera inesistente.")

    cat = db.session.get(Category, int(category_id))
    if not cat:
        raise ValueError("Categoria inesistente.")

    assigns = (
        db.session.query(Assignment.id, Assignment.slot_id)
        .join(Item, Assignment.item_id == Item.id)
        .join(Slot, Assignment.slot_id == Slot.id)
        .filter(Item.category_id == int(category_id), Slot.cabinet_id == int(cabinet_id))
        .all()
    )

    if not assigns:
        return {
            "removed": 0,
            "slots": 0,
            "cabinet": cab.name,
            "category": cat.name,
        }

    assign_ids = [a.id for a in assigns]
    slot_ids = {a.slot_id for a in assigns}

    deleted = Assignment.query.filter(Assignment.id.in_(assign_ids)).delete(synchronize_session=False)
    db.session.commit()

    return {
        "removed": deleted,
        "slots": len(slot_ids),
        "cabinet": cab.name,
        "category": cat.name,
    }


def _placements_internal():
    cabinets = Cabinet.query.order_by(Cabinet.name).all()
    categories = Category.query.order_by(Category.name).all()
    sort_options = [
        ("length_mm", "Lunghezza/Spessore (mm)"),
        ("outer_d_mm", "Ø esterno (mm)"),
        ("thread_size",  "Filettatura"),
        ("material",     "Materiale"),
        ("id",           "ID articolo"),
    ]

    # Valori di default letti dalla querystring
    form_cabinet_id  = request.args.get("cabinet_id", type=int)
    form_category_id = request.args.get("category_id", type=int)
    primary_key      = request.args.get("primary_key") or "length_mm"
    secondary_key    = request.args.get("secondary_key") or "material"
    direction        = (request.args.get("direction") or "H").upper()
    count_val        = request.args.get("count", type=int) or 10
    start_col        = (request.args.get("start_col") or "").strip().upper()
    start_row        = request.args.get("start_row", type=int)
    clear_occupied   = bool(request.args.get("clear_occupied", type=int))

    if not form_cabinet_id and cabinets:
        form_cabinet_id = cabinets[0].id

    target_endpoint = "placements"

    if request.method == "POST":
        form = request.form
        action = form.get("action") or "auto_assign"
        try:
            form_cabinet_id  = int(form.get("cabinet_id") or 0)
            form_category_id = int(form.get("category_id") or 0)
        except Exception:
            flash("Parametri non validi per l'assegnamento automatico.", "danger")
            return redirect(url_for(target_endpoint))

        primary_key    = form.get("primary_key") or primary_key or "length_mm"
        secondary_key  = form.get("secondary_key") or ""
        direction      = (form.get("direction") or direction or "H").upper()
        count_val      = max(1, int(form.get("count") or (count_val or 1)))
        start_col      = (form.get("start_col") or start_col or "").strip().upper()
        start_row_raw  = form.get("start_row")
        start_row      = int(start_row_raw) if (start_row_raw not in (None, "")) else start_row
        clear_occupied = bool(form.get("clear_occupied"))

        if action == "clear_category":
            if not (form_cabinet_id and form_category_id):
                flash("Seleziona cassettiera e categoria da de-allocare.", "danger")
            else:
                try:
                    res = _deallocate_category_from_cabinet(form_category_id, form_cabinet_id)
                    removed = res["removed"]
                    slots = res["slots"]
                    cat_name = res.get("category")
                    cab_name = res.get("cabinet")
                    if removed:
                        msg = (
                            f"De-allocati {removed} articoli della categoria \"{cat_name}\" "
                            f"dalla cassettiera \"{cab_name}\"."
                        )
                        if slots:
                            msg += f" Cassetti liberati: {slots}."
                        msg += " Dovrai ristampare le etichette e riposizionare i cassetti."
                        flash(msg, "warning")
                    else:
                        flash("Nessun articolo di questa categoria è assegnato nella cassettiera selezionata.", "info")
                except ValueError as e:
                    flash(str(e), "danger")
                except Exception as e:
                    db.session.rollback()
                    flash(f"Errore durante la de-allocazione: {e}", "danger")

            return redirect(url_for(
                target_endpoint,
                cabinet_id=form_cabinet_id or "",
                category_id=form_category_id or "",
                primary_key=primary_key,
                secondary_key=secondary_key,
                direction=direction,
                count=count_val,
                start_col=start_col,
                start_row=start_row or "",
                clear_occupied=int(clear_occupied),
            ))

        if not (form_cabinet_id and form_category_id and start_col and start_row):
            flash("Seleziona cassettiera, categoria e cella di partenza.", "danger")
            return redirect(url_for(
                target_endpoint,
                cabinet_id=form_cabinet_id or "",
                category_id=form_category_id or "",
                primary_key=primary_key,
                secondary_key=secondary_key,
                direction=direction,
                count=count_val,
                start_col=start_col,
                start_row=start_row,
                clear_occupied=int(clear_occupied),
            ))

        try:
            res = _auto_assign_category(
                category_id=form_category_id,
                cabinet_id=form_cabinet_id,
                start_col=start_col,
                start_row=start_row,
                direction=direction,
                primary_key=primary_key,
                secondary_key=secondary_key,
                count=count_val,
                clear_occupied=clear_occupied,
            )
            assigned       = res["assigned"]
            cleared_slots  = res["cleared_slots"]
            collisions     = res["collisions"]
            requested      = res["requested"]
            total_unplaced = res["total_unplaced"]

            if assigned == 0:
                flash("Nessun articolo assegnato: controlla i parametri o la cella di partenza.", "warning")
            else:
                msg = f"Assegnati {assigned} articoli."
                if requested > assigned:
                    msg += f" Solo {assigned} articoli su {requested} richiesti hanno trovato una cella disponibile."
                if cleared_slots:
                    msg += f" De-allocate {cleared_slots} celle precedentemente popolate."
                elif collisions and not clear_occupied:
                    msg += f" {collisions} celle nel percorso erano già popolate e non sono state modificate."
                msg += f" Articoli non posizionati rimanenti per la categoria: {total_unplaced - assigned}."
                flash(msg, "success")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            flash(f"Errore nell'assegnamento automatico: {e}", "danger")

        return redirect(url_for(
            target_endpoint,
            cabinet_id=form_cabinet_id,
            category_id=form_category_id,
            primary_key=primary_key,
            secondary_key=secondary_key,
            direction=direction,
            count=count_val,
            start_col=start_col,
            start_row=start_row,
            clear_occupied=int(clear_occupied),
        ))

    # GET o dopo redirect: preparo i dati per il template
    grid = build_full_grid(form_cabinet_id) if form_cabinet_id else {"rows": [], "cols": [], "cells": {}, "cab": None}

    subq = select(Assignment.item_id)
    unplaced_by_category = dict(
        db.session.query(Item.category_id, func.count(Item.id))
        .filter(Item.id.not_in(subq))
        .group_by(Item.category_id)
        .all()
    )
    unplaced_count = None
    if form_category_id:
        unplaced_count = unplaced_by_category.get(form_category_id, 0)
    items_to_place = Item.query.filter(Item.id.not_in(subq)).all()

    return render_template(
        "admin/placements.html",
        cabinets=cabinets,
        categories=categories,
        sort_options=sort_options,
        grid=grid,
        form_cabinet_id=form_cabinet_id,
        form_category_id=form_category_id,
        primary_key=primary_key,
        secondary_key=secondary_key,
        direction=direction,
        count=count_val,
        start_col=start_col,
        start_row=start_row,
        clear_occupied=clear_occupied,
        unplaced_count=unplaced_count,
        unplaced_by_category=unplaced_by_category,
        items_to_place=items_to_place,
    )

@app.route("/admin/posizionamento", methods=["GET", "POST"])
@login_required
def placements():
    return _placements_internal()

@app.route("/admin/auto_assign", methods=["GET", "POST"])
@login_required
def auto_assign():
    return _placements_internal()


# ===================== ETICHETTE PDF =====================
def wrap_to_lines(text: str, font_name: str, font_size: float, max_width_pt: float, max_lines: int = 2):
    from reportlab.pdfbase import pdfmetrics

    if not text:
        return []
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width_pt:
            cur = test
        else:
            if cur:
                lines.append(cur)
                if len(lines) == max_lines:
                    return lines
                cur = w
            else:
                for i in range(len(w), 0, -1):
                    piece = w[:i] + "…"
                    if pdfmetrics.stringWidth(piece, font_name, font_size) <= max_width_pt:
                        lines.append(piece)
                        cur = ""
                        break
                if len(lines) == max_lines:
                    return lines
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines


@app.route("/admin/labels/pdf", methods=["POST"])
@login_required
def labels_pdf():
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4, landscape, portrait
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF
        from reportlab.lib.colors import HexColor
        from reportlab.graphics.barcode import qr as qrmod
        from reportlab.pdfbase import pdfmetrics
    except Exception:
        flash("Per la stampa etichette installa reportlab: pip install reportlab", "danger")
        return redirect(request.referrer or url_for("admin_items"))

    ids = request.form.getlist("item_ids")
    if not ids:
        ids = [row[0] for row in db.session.query(Item.id).all()]
    items = Item.query.filter(Item.id.in_(ids)).order_by(Item.id).all()
    if not items:
        flash("Nessun articolo valido per la stampa.", "warning"); return redirect(request.referrer or url_for("admin_items"))

    assignments = (db.session.query(Assignment.item_id, Cabinet, Slot)
                   .join(Slot, Assignment.slot_id == Slot.id)
                   .join(Cabinet, Slot.cabinet_id == Cabinet.id)
                   .filter(Assignment.item_id.in_(ids))
                   .all())
    pos_by_item = {a.item_id: (cab, slot) for a, cab, slot in assignments}
    original_order = {item.id: idx for idx, item in enumerate(items)}

    slot_ids = {slot.id for _, slot in pos_by_item.values() if slot and slot.id}
    slot_contents = {}
    if slot_ids:
        rows = (
            db.session.query(Item, Slot, Cabinet)
            .join(Assignment, Assignment.item_id == Item.id)
            .join(Slot, Assignment.slot_id == Slot.id)
            .join(Cabinet, Slot.cabinet_id == Cabinet.id)
            .filter(Assignment.slot_id.in_(slot_ids))
            .all()
        )
        for it, slot, cab in rows:
            key = slot.id
            slot_contents.setdefault(key, []).append(it)

    def _label_sort_key(entry):
        items_in_entry = entry.get("items", [])
        cab, slot = entry.get("position") or (None, None)
        base_order = min((original_order.get(it.id, 0) for it in items_in_entry), default=0)
        if cab and slot:
            col_code = getattr(slot, "col_code", "") or ""
            row_num = getattr(slot, "row_num", 0) or 0
            return (0, cab.name or "", int(row_num), colcode_to_idx(col_code), base_order)
        return (1, base_order)

    def _common_parts(items_list: list[Item]) -> list[str]:
        if not items_list:
            return []
        parts = []
        cats = {it.category.name for it in items_list if it.category}
        if len(cats) == 1:
            parts.append(next(iter(cats)))
        subtypes = {it.subtype.name for it in items_list if it.subtype}
        if len(subtypes) == 1:
            parts.append(next(iter(subtypes)))
        thread_sizes = {it.thread_size for it in items_list if it.thread_size}
        if len(thread_sizes) == 1:
            parts.append(next(iter(thread_sizes)))
        def _main_value(it: Item):
            if is_screw(it) or is_standoff(it) or is_spacer(it):
                return getattr(it, "length_mm", None)
            return getattr(it, "outer_d_mm", None)
        main_values = {format_mm_short(_main_value(it)) for it in items_list if _main_value(it) is not None}
        if len(main_values) == 1:
            mv = next(iter(main_values))
            if mv is not None:
                tag = "L" if any(is_screw(it) or is_standoff(it) or is_spacer(it) for it in items_list) else "Øe"
                parts.append(f"{tag}{mv}")
        materials = {it.material.name for it in items_list if it.material}
        if len(materials) == 1:
            parts.append(next(iter(materials)))
        return parts

    s = get_settings()
    include_qr = s.qr_default

    buf = io.BytesIO()
    page_size = (landscape(A4) if s.orientation_landscape else portrait(A4))
    c = canvas.Canvas(buf, pagesize=page_size)
    page_w, page_h = page_size

    margin_x = mm_to_pt(s.margin_lr_mm)
    margin_y = mm_to_pt(s.margin_tb_mm)
    lab_w = mm_to_pt(s.label_w_mm)
    lab_h = mm_to_pt(s.label_h_mm)
    gap   = mm_to_pt(s.gap_mm)

    cols = int((page_w - 2*margin_x + gap) // (lab_w + gap))
    rows = int((page_h - 2*margin_y + gap) // (lab_h + gap))
    if cols < 1 or rows < 1:
        flash("Configurazione etichette non valida rispetto al formato A4.", "danger")
        return redirect(request.referrer or url_for("admin_items"))

    x0 = margin_x
    y0 = page_h - margin_y - lab_h

    def crop_marks(cx, cy, w, h):
        mark = mm_to_pt(1.2)
        c.setStrokeGray(0.7); c.setLineWidth(0.2)
        c.line(cx,        cy+h, cx+mark, cy+h); c.line(cx+w-mark, cy+h, cx+w,    cy+h)
        c.line(cx,        cy,   cx+mark, cy);   c.line(cx+w-mark, cy,   cx+w,    cy)
        c.line(cx,        cy+h, cx,      cy+h-mark); c.line(cx,  cy,   cx,      cy+mark)
        c.line(cx+w,      cy+h, cx+w,    cy+h-mark); c.line(cx+w,cy,   cx+w,    cy+mark)
        c.setStrokeGray(0.85); c.rect(cx, cy, w, h, stroke=1, fill=0)

    title_font = "Helvetica-Bold"
    title_size = 7.2
    cat_font = "Helvetica-Bold"
    cat_size = 7.4

    padding_x = mm_to_pt(getattr(s, "label_padding_mm", DEFAULT_LABEL_PADDING_MM) or DEFAULT_LABEL_PADDING_MM)
    qr_box = mm_to_pt(getattr(s, "label_qr_size_mm", DEFAULT_LABEL_QR_SIZE_MM) or DEFAULT_LABEL_QR_SIZE_MM) if include_qr else 0
    qr_margin = mm_to_pt(getattr(s, "label_qr_margin_mm", DEFAULT_LABEL_QR_MARGIN_MM) or DEFAULT_LABEL_QR_MARGIN_MM) if qr_box else 0
    qr_area_width = qr_box + (qr_margin * 2 if qr_box else 0)
    base_pos_block_w = mm_to_pt(getattr(s, "label_position_width_mm", DEFAULT_LABEL_POSITION_WIDTH_MM) or DEFAULT_LABEL_POSITION_WIDTH_MM)
    position_font_size = getattr(s, "label_position_font_pt", DEFAULT_LABEL_POSITION_FONT_PT) or DEFAULT_LABEL_POSITION_FONT_PT
    position_line_height = position_font_size + 0.6

    def _type_text(item: Item) -> str:
        # Base: name o descrizione auto-generata, senza la categoria duplicata
        base = item.name or auto_name_for(item)
        cat_name = item.category.name if item.category else ""
        if cat_name and base.lower().startswith(cat_name.lower() + " "):
            base = base[len(cat_name) + 1 :].lstrip()

        # Layout dedicato per le rondelle: tipo + Øi + Øe + spessore
        if is_washer(item):
            parts = []

            # Subtipo, senza ripetere "Rondelle/Rondella"
            if getattr(item, "subtype", None) and item.subtype.name:
                st = item.subtype.name
                lower_st = st.lower()
                if lower_st.startswith("rondell"):
                    # elimina la parola iniziale "Rondelle"/"Rondella"
                    st = st.split(" ", 1)[-1]
                parts.append(st)

            if item.thread_size:
                parts.append(item.thread_size)

            if item.inner_d_mm:
                v = format_mm_short(item.inner_d_mm)
                if v is not None:
                    parts.append(f"Øi{v}")

            if item.outer_d_mm:
                v = format_mm_short(item.outer_d_mm)
                if v is not None:
                    parts.append(f"Øe{v}")

            v = format_mm_short(unified_thickness_value(item))
            if v is not None:
                prefix = THICKNESS_ABBR if item.thickness_mm is not None else LENGTH_ABBR
                parts.append(f"{prefix} {v}")

            if parts:
                return " ".join(parts)

        # Per gli altri oggetti: se c'è spessore, aggiungi un breve "sX"
        v = format_mm_short(unified_thickness_value(item))
        if v is not None:
            prefix = THICKNESS_ABBR if item.thickness_mm is not None else LENGTH_ABBR
            formatted = f"{prefix} {v}"
            if formatted not in base:
                base = f"{base} {formatted}"

        return base

    def _single_line(text: str, font_name: str, font_size: float, max_width_pt: float) -> str:
        """Restituisce una singola riga che entra nella larghezza disponibile."""
        if not text:
            return ""
        lines = wrap_to_lines(text, font_name, font_size, max_width_pt, max_lines=1)
        return lines[0] if lines else ""

    label_entries = []
    seen_slot_keys = set()
    for item in items:
        pos_data = pos_by_item.get(item.id)
        if pos_data:
            cab, slot = pos_data
            slot_key = slot.id if slot else None
            if slot_key and slot_key in seen_slot_keys:
                continue
            if slot_key:
                seen_slot_keys.add(slot_key)
            slot_items = slot_contents.get(slot_key, [item])
            slot_items.sort(key=lambda it: original_order.get(it.id, 10**6))
            label_entries.append({
                "items": slot_items,
                "position": (cab, slot),
                "slot_id": slot_key,
                "is_multi": len(slot_items) > 1,
                "color": slot_items[0].category.color if slot_items and slot_items[0].category else "#000000",
            })
        else:
            label_entries.append({
                "items": [item],
                "position": (None, None),
                "slot_id": None,
                "is_multi": False,
                "color": item.category.color if item.category else "#000000",
            })
    for entry in label_entries:
        if entry["is_multi"]:
            summary_parts = _common_parts(entry["items"])
            summary = " ".join(summary_parts).strip()
            entry["summary"] = f"{summary} - MULTY" if summary else "MULTY"
        else:
            entry["summary"] = None
    label_entries.sort(key=_label_sort_key)

    for idx, entry in enumerate(label_entries):
        items_in_entry = entry["items"]
        if not items_in_entry:
            continue
        item = items_in_entry[0]
        col = idx % cols
        row = (idx // cols) % rows
        if idx > 0 and idx % (cols * rows) == 0:
            c.showPage()

        x = x0 + col * (lab_w + gap)
        y = y0 - row * (lab_h + gap)

        crop_marks(x, y, lab_w, lab_h)

        # Barra colore categoria in alto
        try:
            colhex = entry.get("color") or "#000000"
            c.setFillColor(HexColor(colhex))
            c.rect(x, y + lab_h - 2, lab_w, 2, stroke=0, fill=1)
        except Exception:
            pass

        c.setFillColorRGB(0, 0, 0)

        pos_data = entry.get("position") or (None, None)
        pos_texts = None
        pos_block_w = base_pos_block_w
        cab, slot = pos_data
        if cab or slot:
            col_code = getattr(slot, "col_code", "") or ""
            row_num = getattr(slot, "row_num", None)
            label_txt = slot_label(slot, for_display=False, fallback_col=col_code, fallback_row=row_num)
            if slot and slot.print_label_override:
                pos_texts = (label_txt,)
            elif row_num is not None and col_code:
                pos_texts = (f"Rig: {int(row_num)}", f"Col: {col_code.upper()}")
            if pos_texts:
                required_w = max(pdfmetrics.stringWidth(txt, "Helvetica-Bold", position_font_size) for txt in pos_texts) + mm_to_pt(1)
                pos_block_w = max(pos_block_w, required_w)

        # area testuale a sinistra del blocco posizione/QR
        text_right_limit = lab_w - qr_area_width - pos_block_w - padding_x
        text_right_limit = max(text_right_limit, mm_to_pt(10))
        text_x = x + padding_x

        c.setFillColorRGB(0, 0, 0)

        # punto di partenza dall'alto
        cy = y + lab_h - max(padding_x, mm_to_pt(1.0))

        # --- Riga 1: Categoria + Sottotipo + Misura ---
        base_lines = [] if entry.get("is_multi") else label_lines_for_item(item)
        line1_text = entry.get("summary") if entry.get("is_multi") else (base_lines[0] if base_lines else "")
        if line1_text:
            line1_lines = wrap_to_lines(line1_text, cat_font, cat_size, text_right_limit, max_lines=1)
            if line1_lines:
                c.setFont(cat_font, cat_size)
                c.drawString(text_x, cy - cat_size, line1_lines[0])
                cy -= (cat_size + 0.6)

        # --- Riga 2: specifiche a seconda della categoria ---
        line2_text = None if entry.get("is_multi") else (base_lines[1] if len(base_lines) > 1 else "")
        if line2_text:
            line2_lines = wrap_to_lines(line2_text, title_font, title_size, text_right_limit, max_lines=1)
            if line2_lines:
                c.setFont(title_font, title_size)
                c.drawString(text_x, cy - title_size, line2_lines[0])
                cy -= (title_size + 0.6)

        # Fallback: se per qualche motivo non abbiamo scritto nulla, uso il nome completo
        if not line1_text and not line2_text:
            fallback = entry.get("summary") or item.name or auto_name_for(item)
            lines = wrap_to_lines(fallback, title_font, title_size, text_right_limit, max_lines=2)
            c.setFont(title_font, title_size)
            for ln in lines:
                c.drawString(text_x, cy - title_size, ln)
                cy -= (title_size + 0.6)

        # posizione a sinistra del QR, su due righe
        if pos_texts:
            pos_x = x + lab_w - qr_area_width - pos_block_w
            if qr_box:
                block_height = position_line_height * len(pos_texts)
                start_y = y + qr_margin + max((qr_box - block_height) / 2, 0) + block_height - position_font_size
            else:
                start_y = y + lab_h - padding_x - position_font_size
            c.setFont("Helvetica-Bold", position_font_size)
            line_y = start_y
            for txt in pos_texts:
                c.drawString(pos_x, line_y, txt)
                line_y -= position_line_height

        # QR a destra
        if qr_box:
            try:
                s = get_settings()
                if s.qr_base_url:
                    url = f"{s.qr_base_url.rstrip('/')}/api/items/{item.id}.json"
                else:
                    url = f"{request.host_url.rstrip('/')}/api/items/{item.id}.json"
                qr_code = qrmod.QrCodeWidget(url)
                bounds = qr_code.getBounds()
                w = bounds[2] - bounds[0]
                h = bounds[3] - bounds[1]
                scale = min(qr_box / w, qr_box / h)
                d = Drawing(w, h)
                d.add(qr_code)
                c.saveState()
                c.translate(x + lab_w - qr_box - qr_margin, y + qr_margin)
                c.scale(scale, scale)
                renderPDF.draw(d, c, 0, 0)
                c.restoreState()
            except Exception:
                pass
    c.save(); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="etichette.pdf", mimetype="application/pdf")

@app.route("/admin/cards/pdf", methods=["POST"])
@login_required
def cards_pdf():
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4, portrait
        from reportlab.lib.colors import HexColor
    except Exception:
        flash("Per la stampa cartellini installa reportlab: pip install reportlab", "danger")
        return redirect(request.referrer or url_for("admin_items"))

    ids = request.form.getlist("item_ids")
    if not ids:
        ids = [row[0] for row in db.session.query(Item.id).all()]
    items = Item.query.options(
        selectinload(Item.category),
        selectinload(Item.subtype),
        selectinload(Item.material),
        selectinload(Item.finish),
    ).filter(Item.id.in_(ids)).order_by(Item.id).all()
    if not items:
        flash("Nessun articolo valido per la stampa.", "warning")
        return redirect(request.referrer or url_for("admin_items"))

    assignments = (db.session.query(Assignment.item_id, Cabinet, Slot)
                   .join(Slot, Assignment.slot_id == Slot.id)
                   .join(Cabinet, Slot.cabinet_id == Cabinet.id)
                   .filter(Assignment.item_id.in_(ids))
                   .all())
    pos_by_item = {a.item_id: (cab, slot) for a, cab, slot in assignments}

    page_size = portrait(A4)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=page_size)
    page_w, page_h = page_size

    margin = mm_to_pt(12)
    gap = mm_to_pt(6)
    cols = 2
    card_w = (page_w - (2 * margin) - gap) / cols
    card_h = mm_to_pt(80)
    rows = max(1, int((page_h - 2 * margin + gap) // (card_h + gap)))
    padding = mm_to_pt(5)

    def _fmt_mm(v):
        if v is None:
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if abs(v - round(v)) < 0.01:
            return str(int(round(v)))
        return f"{v:.1f}".rstrip("0").rstrip(".")

    for idx, item in enumerate(items):
        col = idx % cols
        row = (idx // cols) % rows
        if idx > 0 and idx % (cols * rows) == 0:
            c.showPage()
        x = margin + col * (card_w + gap)
        y = page_h - margin - card_h - row * (card_h + gap)

        c.setStrokeGray(0.8)
        c.setLineWidth(0.7)
        c.rect(x, y, card_w, card_h, stroke=1, fill=0)
        cy = y + card_h - padding
        c.setFillColor(HexColor(item.category.color if item.category else "#000000"))
        c.rect(x, y + card_h - 3, card_w, 3, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)

        title_lines = wrap_to_lines(auto_name_for(item), "Helvetica-Bold", 12, card_w - 2 * padding, max_lines=2)
        c.setFont("Helvetica-Bold", 12)
        for ln in title_lines:
            cy -= 12
            c.drawString(x + padding, cy, ln)
            cy -= 2

        meta_parts = []
        if item.category:
            meta_parts.append(item.category.name)
        if item.subtype:
            meta_parts.append(item.subtype.name)
        if item.thread_size:
            meta_parts.append(item.thread_size)
        meta_text = " · ".join(meta_parts)
        if meta_text:
            c.setFont("Helvetica", 10)
            cy -= 10
            c.drawString(x + padding, cy, meta_text)
            cy -= 6

        details = []
        dim = _fmt_mm(item.outer_d_mm if not (is_screw(item) or is_standoff(item) or is_spacer(item)) else item.length_mm)
        if dim:
            prefix = "L" if (is_screw(item) or is_standoff(item) or is_spacer(item)) else "Øe"
            details.append(f"{prefix}: {dim} mm")
        if item.inner_d_mm:
            details.append(f"Øi: {_fmt_mm(item.inner_d_mm)} mm")
        thickness_val = unified_thickness_value(item)
        if thickness_val:
            details.append(f"Spessore: {_fmt_mm(thickness_val)} mm")
        if item.material:
            details.append(f"Materiale: {item.material.name}")
        if item.finish:
            details.append(f"Finitura: {item.finish.name}")
        if details:
            c.setFont("Helvetica", 9.5)
            for det in details:
                cy -= 11
                c.drawString(x + padding, cy, det)
            cy -= 4

        if item.description:
            desc_lines = wrap_to_lines(item.description, "Helvetica-Oblique", 9, card_w - 2 * padding, max_lines=3)
            if desc_lines:
                c.setFont("Helvetica-Oblique", 9)
                for ln in desc_lines:
                    cy -= 11
                    c.drawString(x + padding, cy, ln)
                cy -= 2

        qty_line = f"Quantità: {item.quantity}"
        share_line = f"Condivisione cassetto: {'SI' if item.share_drawer else 'NO'}"
        c.setFont("Helvetica-Bold", 9.5)
        cy -= 12
        c.drawString(x + padding, cy, qty_line)
        cy -= 11
        c.drawString(x + padding, cy, share_line)

        pos_data = pos_by_item.get(item.id)
        if pos_data:
            cab, slot = pos_data
            cy -= 12
            c.drawString(x + padding, cy, f"Posizione: {slot_full_label(cab, slot, for_print=True)}")

    c.save()
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="cartellini.pdf", mimetype="application/pdf")
# ===================== INIT / SEED =====================

def seed_if_empty_or_missing():
    ensure_settings_columns()
    ensure_item_columns()
    ensure_category_columns()
    ensure_slot_columns()
    if not User.query.filter_by(username="admin").first():
        db.session.add(User(username="admin", password="admin"))
    if not Settings.query.get(1):
        db.session.add(Settings(
            id=1,
            label_w_mm=DEFAULT_LABEL_W_MM, label_h_mm=DEFAULT_LABEL_H_MM,
            margin_tb_mm=DEFAULT_MARG_TB_MM, margin_lr_mm=DEFAULT_MARG_LR_MM,
            gap_mm=DEFAULT_GAP_MM, label_padding_mm=DEFAULT_LABEL_PADDING_MM,
            label_qr_size_mm=DEFAULT_LABEL_QR_SIZE_MM, label_qr_margin_mm=DEFAULT_LABEL_QR_MARGIN_MM,
            label_position_width_mm=DEFAULT_LABEL_POSITION_WIDTH_MM,
            label_position_font_pt=DEFAULT_LABEL_POSITION_FONT_PT,
            orientation_landscape=DEFAULT_ORIENTATION_LANDSCAPE,
            qr_default=DEFAULT_QR_DEFAULT, qr_base_url=DEFAULT_QR_BASE_URL
        ))
    thread_standards = [
        ("M", "Metrico", 10),
        ("UNC", "UNC", 20),
        ("UNF", "UNF", 30),
    ]
    for code, label, order in thread_standards:
        if not ThreadStandard.query.filter_by(code=code).first():
            db.session.add(ThreadStandard(code=code, label=label, sort_order=order))

    # categorie/materiali/finiture predefinite solo su db vuoto
    has_categories = Category.query.count() > 0
    has_materials = Material.query.count() > 0
    has_finishes = Finish.query.count() > 0

    if not has_categories:
        defaults = [
            ("Viti","#2E7D32"), ("Dadi","#1565C0"), ("Rondelle","#F9A825"), ("Torrette","#6A1B9A"),
            ("Grani","#8E24AA"), ("Prigionieri","#3949AB"), ("Inserti e rivetti","#00897B"),
            ("Seeger e spine","#5D4037"), ("Distanziali","#00796B"), ("Boccole","#546E7A"), ("O-Ring","#D84315")
        ]
        for name,color in defaults:
            if not Category.query.filter_by(name=name).first():
                db.session.add(Category(name=name, color=color))
    if not has_materials:
        for m in ["Acciaio","Inox A2","Inox A4","Ottone","Alluminio","Rame","Nylon","Ottone nichelato","Bronzo","PTFE","EPDM","Viton","Silicone"]:
            if not Material.query.filter_by(name=m).first():
                db.session.add(Material(name=m))
    if not has_finishes:
        for f in ["Zincato bianco","Zincato nero","Brunitura","Nichelato","Grezzo","Anodizzato"]:
            if not Finish.query.filter_by(name=f).first():
                db.session.add(Finish(name=f))
    db.session.commit()

    standards_by_code = {s.code: s for s in ThreadStandard.query.all()}
    sizes_by_standard = {
        "M": ["M2","M2.5","M3","M4","M5","M6","M8","M10","M12","M14","M16"],
        "UNC": ["#2-56","#4-40","#6-32","#8-32","#10-24","1/4-20","5/16-18","3/8-16","1/2-13"],
        "UNF": ["#2-64","#4-48","#6-40","#8-36","#10-32","1/4-28","5/16-24","3/8-24","1/2-20"],
    }
    for code, values in sizes_by_standard.items():
        standard = standards_by_code.get(code)
        if not standard:
            continue
        for idx, value in enumerate(values, start=1):
            exists = ThreadSize.query.filter_by(standard_id=standard.id, value=value).first()
            if not exists:
                db.session.add(ThreadSize(standard_id=standard.id, value=value, sort_order=idx * 10))

    cat = {c.name: c.id for c in Category.query.all()}

    # Viti — sottotipi (forme testa)
    for nm in ["Svasata (TSP)","Cilindrica","Bombata/Lenticolare","Piatta/Ribassata","Esagonale","Flangiata","Svasata ovale"]:
        if cat.get("Viti") and not Subtype.query.filter_by(category_id=cat["Viti"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Viti"], name=nm))

    # Dadi — sottotipi
    for nm in ["Esagonale","Autobloccante (nylon)","Cieco","Basso (jam)","Flangiato"]:
        if cat.get("Dadi") and not Subtype.query.filter_by(category_id=cat["Dadi"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Dadi"], name=nm))

    # Rondelle
    for nm in ["Piana","Grower (molla)","Dentellata esterna","Dentellata interna","Larga (fender)","Belleville (a tazza)"]:
        if cat.get("Rondelle") and not Subtype.query.filter_by(category_id=cat["Rondelle"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Rondelle"], name=nm))

    # Torrette — forme
    for nm in ["Esagonale","Cilindrica","Flangiata","Snap-in","Press-fit","Adesiva"]:
        if cat.get("Torrette") and not Subtype.query.filter_by(category_id=cat["Torrette"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Torrette"], name=nm))

    # Grani (viti senza testa) — punte
    for nm in ["Punta piana","A coppa","Conica","Dog point"]:
        if cat.get("Grani") and not Subtype.query.filter_by(category_id=cat["Grani"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Grani"], name=nm))

    # Prigionieri
    for nm in ["Doppio filetto","Filettato totale","Filettatura parziale"]:
        if cat.get("Prigionieri") and not Subtype.query.filter_by(category_id=cat["Prigionieri"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Prigionieri"], name=nm))

    # Inserti e rivetti
    for nm in ["Inserto filettato (rivnut)","Inserto filettato (press-fit)","Rivetto cieco standard","Rivetto cieco multigrip"]:
        if cat.get("Inserti e rivetti") and not Subtype.query.filter_by(category_id=cat["Inserti e rivetti"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Inserti e rivetti"], name=nm))

    # Seeger e spine
    for nm in ["Seeger interno","Seeger esterno","Spina elastica","Spina cilindrica","Anello elastico a filo"]:
        if cat.get("Seeger e spine") and not Subtype.query.filter_by(category_id=cat["Seeger e spine"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Seeger e spine"], name=nm))

    # Distanziali (lisci)
    for nm in ["Liscio cilindrico","Liscio esagonale"]:
        if cat.get("Distanziali") and not Subtype.query.filter_by(category_id=cat["Distanziali"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Distanziali"], name=nm))

    # Boccole
    for nm in ["Rettificata","Autolubrificante (sinterizzata)","Polimerica (PA/PTFE)"]:
        if cat.get("Boccole") and not Subtype.query.filter_by(category_id=cat["Boccole"], name=nm).first():
            db.session.add(Subtype(category_id=cat["Boccole"], name=nm))

    # O-Ring
    for nm in ["O-Ring","X-Ring (quad)"]:
        if cat.get("O-Ring") and not Subtype.query.filter_by(category_id=cat["O-Ring"], name=nm).first():
            db.session.add(Subtype(category_id=cat["O-Ring"], name=nm))

    db.session.commit()

    # seed minimo ubicazione/cassettiera
    if not Location.query.first():
        loc = Location(name="Parete A")
        db.session.add(loc); db.session.flush()
        cab = Cabinet(location_id=loc.id, name="Cassettiera 1", rows_max=128, cols_max="ZZ", compartments_per_slot=6)
        db.session.add(cab); db.session.commit()

def init_db():
    with app.app_context():
        db.create_all()
        seed_if_empty_or_missing()

# ===================== MAIN =====================
if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0")
