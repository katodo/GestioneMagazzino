# magazzino.py
from flask import Flask, render_template, redirect, url_for, request, jsonify, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import func, select, or_, text
import os, io

# ===================== DEFAULT ETICHETTE =====================
DEFAULT_LABEL_W_MM = 50
DEFAULT_LABEL_H_MM = 10
DEFAULT_MARG_TB_MM = 15
DEFAULT_MARG_LR_MM = 10
DEFAULT_GAP_MM     = 1
DEFAULT_ORIENTATION_LANDSCAPE = True
DEFAULT_QR_DEFAULT = True
DEFAULT_QR_BASE_URL = None  # es. "https://magazzino.local"

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
    orientation_landscape = db.Column(db.Boolean, nullable=False, default=DEFAULT_ORIENTATION_LANDSCAPE)
    qr_default = db.Column(db.Boolean, nullable=False, default=DEFAULT_QR_DEFAULT)
    qr_base_url = db.Column(db.String(200), nullable=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#000000")  # HEX

class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class Finish(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class ThreadStandard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(8), unique=True, nullable=False)
    label = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

class ThreadSize(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    standard_id = db.Column(db.Integer, db.ForeignKey("thread_standard.id"), nullable=False)
    value = db.Column(db.String(32), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (db.UniqueConstraint('standard_id', 'value', name='uq_size_per_standard'),)
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
    __table_args__ = (db.UniqueConstraint('category_id', 'field_key', name='uq_field_per_category'),)

class ItemCustomFieldValue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey("custom_field.id"), nullable=False)
    value_text = db.Column(db.String(255), nullable=True)
    __table_args__ = (db.UniqueConstraint('item_id', 'field_id', name='uq_custom_field_value'),)

class Subtype(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    __table_args__ = (db.UniqueConstraint('category_id', 'name', name='uq_subtype_per_category'),)

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)  # solo nome

class Cabinet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    name = db.Column(db.String(80), unique=True, nullable=False)  # univoco globale
    rows_max = db.Column(db.Integer, nullable=False, default=128)
    cols_max = db.Column(db.String(2), nullable=False, default="ZZ")  # A..Z, AA..ZZ
    compartments_per_slot = db.Column(db.Integer, nullable=False, default=6)

class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cabinet_id = db.Column(db.Integer, db.ForeignKey("cabinet.id"), nullable=False)
    row_num = db.Column(db.Integer, nullable=False)         # 1..128
    col_code = db.Column(db.String(2), nullable=False)      # A..Z, AA..ZZ
    is_blocked = db.Column(db.Boolean, nullable=False, default=False)
    __table_args__ = (db.UniqueConstraint('cabinet_id', 'row_num', 'col_code', name='uq_slot_in_cabinet'),)

class DrawerMerge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cabinet_id = db.Column(db.Integer, db.ForeignKey("cabinet.id"), nullable=False)
    row_start = db.Column(db.Integer, nullable=False)
    row_end = db.Column(db.Integer, nullable=False)
    col_start = db.Column(db.String(2), nullable=False)
    col_end = db.Column(db.String(2), nullable=False)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    subtype_id  = db.Column(db.Integer, db.ForeignKey("subtype.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False, default="")  # auto-composizione
    description = db.Column(db.String(255), nullable=True)
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
    label_show_measure  = db.Column(db.Boolean, nullable=False, default=True)
    label_show_main     = db.Column(db.Boolean, nullable=False, default=True)
    label_show_material = db.Column(db.Boolean, nullable=False, default=True)

    category = db.relationship("Category")
    subtype  = db.relationship("Subtype")
    material = db.relationship("Material")
    finish   = db.relationship("Finish")

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("slot.id"), nullable=False)
    compartment_no = db.Column(db.Integer, nullable=False, default=1)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
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

def make_full_position(cab_name: str, col_code: str, row_num: int) -> str:
    return f"{cab_name}-{col_code.upper()}{int(row_num)}"

def is_washer(item:Item)->bool:
    return (item.category and item.category.name.lower()=="rondelle")

def is_screw(item:Item)->bool:
    return (item.category and item.category.name.lower()=="viti")

def is_standoff(item:Item)->bool:
    return (item.category and item.category.name.lower()=="torrette")

def is_spacer(item:Item)->bool:
    return (item.category and item.category.name.lower()=="distanziali")

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

def get_settings()->Settings:
    s = Settings.query.get(1)
    if not s:
        s = Settings(id=1,
                     label_w_mm=DEFAULT_LABEL_W_MM,
                     label_h_mm=DEFAULT_LABEL_H_MM,
                     margin_tb_mm=DEFAULT_MARG_TB_MM,
                     margin_lr_mm=DEFAULT_MARG_LR_MM,
                     gap_mm=DEFAULT_GAP_MM,
                     orientation_landscape=DEFAULT_ORIENTATION_LANDSCAPE,
                     qr_default=DEFAULT_QR_DEFAULT,
                     qr_base_url=DEFAULT_QR_BASE_URL)
        db.session.add(s); db.session.commit()
    return s

@app.context_processor
def inject_utils():
    return dict(compose_caption=auto_name_for, app_settings=get_settings)

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
    if not raw_value:
        return None, None
    value = float(raw_value)
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
@app.route("/")
def index():
    low_stock_threshold = 5
    q = Item.query
    if request.args.get("category_id"): q = q.filter(Item.category_id == request.args.get("category_id"))
    if request.args.get("material_id"): q = q.filter(Item.material_id == request.args.get("material_id"))
    if request.args.get("measure"):      q = q.filter(func.lower(Item.thread_size).contains(request.args.get("measure").lower()))
    if request.args.get("q"):
        term = request.args.get("q").lower()
        q = q.filter(or_(
            func.lower(Item.name).contains(term),
            func.lower(Item.description).contains(term),
            func.lower(Item.thread_size).contains(term),
        ))
    stock = request.args.get("stock")
    if stock == "available":
        q = q.filter(Item.quantity > 0)
    elif stock == "low":
        q = q.filter(Item.quantity <= low_stock_threshold)
    elif stock == "out":
        q = q.filter(Item.quantity <= 0)
    items = q.all()

    categories = Category.query.order_by(Category.name).all()
    materials  = Material.query.order_by(Material.name).all()

    assignments = (
        db.session.query(Assignment.item_id, Cabinet.name, Slot.col_code, Slot.row_num)
        .join(Slot, Assignment.slot_id == Slot.id)
        .join(Cabinet, Slot.cabinet_id == Cabinet.id)
        .all()
    )
    pos_by_item = {a.item_id: make_full_position(a.name, a.col_code, a.row_num) for a in assignments}

    cab_id = request.args.get("cabinet_id", type=int)
    all_cabinets = Cabinet.query.order_by(Cabinet.name).all()
    if not cab_id and all_cabinets: cab_id = all_cabinets[0].id
    grid = build_full_grid(cab_id) if cab_id else {"rows":[], "cols":[], "cells":{}, "cab":None}

    subq = select(Assignment.item_id)
    unplaced = Item.query.filter(Item.id.not_in(subq)).all()
    unplaced_json = [
        {"id": it.id, "caption": auto_name_for(it), "category_id": it.category_id}
        for it in unplaced
    ]

    total_items = Item.query.count()
    total_categories = Category.query.count()
    low_stock_count = Item.query.filter(Item.quantity <= low_stock_threshold).count()

    return render_template("index.html",
        items=items, categories=categories, materials=materials, pos_by_item=pos_by_item,
        cabinets=all_cabinets, selected_cab_id=cab_id, grid=grid,
        unplaced_json=unplaced_json, is_admin=current_user.is_authenticated,
        total_items=total_items, total_categories=total_categories,
        low_stock_count=low_stock_count, unplaced_count=len(unplaced),
        low_stock_threshold=low_stock_threshold
    )

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

    slot_rows = (db.session.query(Slot)
                 .filter(Slot.cabinet_id==cabinet_id)
                 .all())

    assigns = (db.session.query(Assignment, Slot)
               .join(Slot, Assignment.slot_id==Slot.id)
               .filter(Slot.cabinet_id==cabinet_id).all())
    items_by_slot = {}
    for a, s in assigns:
        items_by_slot.setdefault((s.col_code, s.row_num), []).append(a.item_id)

    cells = {}
    for s in slot_rows:
        if s.is_blocked:
            key = f"{s.col_code}-{s.row_num}"
            cells[key] = {"blocked": True, "entries": [], "cat_id": None}

    for (col, row), item_ids in items_by_slot.items():
        key = f"{col}-{row}"
        cell = cells.get(key, {"blocked": False, "entries": [], "cat_id": None})
        for iid in item_ids:
            it = db.session.get(Item, iid)
            if not it: continue
            text = short_cell_text(it)
            color = it.category.color if it.category else "#999"
            cell["entries"].append({"text": text, "color": color})
            if cell["cat_id"] is None and it.category_id:
                cell["cat_id"] = it.category_id
        cells[key] = cell

    for anchor_key, region in merge_regions.items():
        merged_cell = {"blocked": False, "entries": [], "cat_id": None}
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

def short_cell_text(item: Item) -> str:
    # Layout dedicato per le rondelle:
    #   riga 1: Misura / Øi
    #   riga 2: Øe / spessore
    if is_washer(item):
        line1_parts = []
        line2_parts = []

        if item.thread_size:
            line1_parts.append(item.thread_size)

        if item.inner_d_mm:
            v = item.inner_d_mm
            vv = int(v) if abs(v - int(v)) < 0.01 else v
            line1_parts.append(f"Øi{vv}")

        if item.outer_d_mm:
            v = item.outer_d_mm
            vv = int(v) if abs(v - int(v)) < 0.01 else v
            line2_parts.append(f"Øe{vv}")

        if item.length_mm:
            v = item.length_mm
            vv = int(v) if abs(v - int(v)) < 0.01 else v
            line2_parts.append(f"s{vv}")

        lines = []
        if line1_parts:
            lines.append(" ".join(str(p) for p in line1_parts))
        if line2_parts:
            lines.append(" ".join(str(p) for p in line2_parts))

        if not lines:
            lines.append(auto_name_for(item))

        return "\n".join(lines[:2])

    # Layout generico per tutte le altre categorie
    parts = []
    if item.thread_size:
        parts.append(item.thread_size)

    main_value = item.length_mm if (is_screw(item) or is_standoff(item) or is_spacer(item)) else item.outer_d_mm
    if main_value:
        v = main_value
        vv = int(v) if abs(v - int(v)) < 0.01 else v
        if is_standoff(item):
            parts.append(f"L={vv}")
        elif is_screw(item) or is_spacer(item):
            parts.append(f"L={vv}")
        else:
            parts.append(f"Øe{vv}")

    if not parts:
        parts.append(auto_name_for(item))

    return "\n".join(parts[:2])

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
    full_pos = make_full_position(a[2].name, a[1].col_code, a[1].row_num) if a else None
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

# ===================== ADMIN: ARTICOLI =====================
@app.route("/admin")
@login_required
def admin_items():
    items      = Item.query.all()
    categories = Category.query.order_by(Category.name).all()
    subtypes   = Subtype.query.order_by(Subtype.name).all()
    materials  = Material.query.order_by(Material.name).all()
    finishes   = Finish.query.order_by(Finish.name).all()
    locations  = Location.query.order_by(Location.name).all()
    cabinets   = Cabinet.query.order_by(Cabinet.name).all()

    assignments = (
        db.session.query(Assignment.item_id, Cabinet.name, Slot.col_code, Slot.row_num)
        .join(Slot, Assignment.slot_id == Slot.id)
        .join(Cabinet, Slot.cabinet_id == Cabinet.id)
        .all()
    )
    pos_by_item = {a.item_id: make_full_position(a.name, a.col_code, a.row_num) for a in assignments}

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
    low_stock_threshold = 5
    low_stock_count = Item.query.filter(Item.quantity <= low_stock_threshold).count()
    total_items = Item.query.count()
    total_categories = Category.query.count()

    return render_template("admin/dashboard.html",
        items=items, categories=categories, materials=materials, finishes=finishes,
        locations=locations, cabinets=cabinets,
        subtypes_by_cat=subtypes_by_cat,
        thread_standards=thread_standards,
        sizes_by_standard=sizes_by_standard,
        default_standard_code=default_standard_code,
        pos_by_item=pos_by_item,
        custom_fields=serialized_custom_fields,
        category_fields=category_fields,
        unplaced_count=unplaced_count,
        low_stock_count=low_stock_count,
        total_items=total_items,
        total_categories=total_categories,
        low_stock_threshold=low_stock_threshold
    )


@app.route("/admin/to_place")
@login_required
def to_place():
    subq = select(Assignment.item_id)
    items = Item.query.filter(Item.id.not_in(subq)).all()
    cabinets = Cabinet.query.order_by(Cabinet.name).all()
    return render_template("admin/to_place.html", items=items, cabinets=cabinets)

@app.route("/admin/items/add", methods=["POST"])
@login_required
def add_item():
    f = request.form
    length_mm, thickness_mm = parse_length_thickness_value(f.get("length_mm"))
    item = Item(
        description=f.get("description") or None,
        category_id=int(f.get("category_id")),
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
        label_show_category=bool(f.get("label_show_category")),
        label_show_subtype =bool(f.get("label_show_subtype")),
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
    return redirect(url_for("admin_items"))

@app.route("/admin/items/<int:item_id>/edit", methods=["GET","POST"])
@login_required
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)
    if request.method == "POST":
        f = request.form
        length_mm, thickness_mm = parse_length_thickness_value(f.get("length_mm"))
        item.description = f.get("description") or None
        item.category_id = int(f.get("category_id"))
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
        item.label_show_category = bool(f.get("label_show_category"))
        item.label_show_subtype  = bool(f.get("label_show_subtype"))
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
    current_position = make_full_position(pos[2].name, pos[1].col_code, pos[1].row_num) if pos else None

    custom_fields = CustomField.query.filter_by(is_active=True).order_by(CustomField.sort_order, CustomField.name).all()
    serialized_custom_fields = serialize_custom_fields(custom_fields)
    custom_field_values = {
        val.field_id: (val.value_text or "")
        for val in ItemCustomFieldValue.query.filter_by(item_id=item.id).all()
    }
    category_fields = build_category_field_map(categories)

    return render_template("admin/edit_item.html",
        item=item, categories=categories, materials=materials, finishes=finishes,
        cabinets=cabinets, subtypes_by_cat=subtypes_by_cat,
        thread_standards=thread_standards, sizes_by_standard=sizes_by_standard,
        custom_fields=serialized_custom_fields,
        custom_field_values=custom_field_values,
        category_fields=category_fields
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
def _assign_position(item, cabinet_id:int, col_code:str, row_num:int):
    if not column_code_valid(col_code):         raise ValueError("Colonna non valida (A..Z o AA..ZZ).")
    if not (1 <= int(row_num) <= 128):          raise ValueError("Riga non valida (1..128).")
    merge_region = merge_region_for(cabinet_id, col_code, row_num)
    if merge_region:
        col_code = merge_region["anchor_col"]
        row_num = merge_region["anchor_row"]
    slot = Slot.query.filter_by(cabinet_id=cabinet_id, row_num=row_num, col_code=col_code.upper()).first()
    if not slot:
        slot = Slot(cabinet_id=cabinet_id, row_num=row_num, col_code=col_code.upper(), is_blocked=False)
        db.session.add(slot); db.session.flush()
    if slot.is_blocked:                         raise RuntimeError("La cella è bloccata (non assegnabile).")

    same_slot = Assignment.query.filter_by(slot_id=slot.id).all()
    cats = {db.session.get(Item, a.item_id).category_id for a in same_slot} if same_slot else set()
    if cats and (item.category_id not in cats):
        raise RuntimeError("Lo slot selezionato contiene articoli di categoria diversa.")

    cab = db.session.get(Cabinet, int(cabinet_id))
    max_comp = cab.compartments_per_slot if cab else 6
    used = {a.compartment_no for a in same_slot}
    comp_no = next((n for n in range(1, max_comp+1) if n not in used), None)
    if comp_no is None:
        raise RuntimeError("Nessuno scomparto libero nello slot scelto.")

    Assignment.query.filter_by(item_id=item.id).delete()
    db.session.add(Assignment(slot_id=slot.id, compartment_no=comp_no, item_id=item.id))

def _suggest_position(item: Item):
    rows = (db.session.query(Slot, Cabinet)
            .join(Cabinet, Slot.cabinet_id==Cabinet.id)
            .order_by(Cabinet.name, Slot.col_code, Slot.row_num)
            .all())
    for slot, cab in rows:
        if slot.is_blocked: continue
        assigns = Assignment.query.filter_by(slot_id=slot.id).all()
        if not assigns:    continue
        cats = {db.session.get(Item, a.item_id).category_id for a in assigns}
        if cats == {item.category_id}:
            if len(assigns) < (cab.compartments_per_slot or 6):
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
    if not (cab_id and row_num and col_code):
        flash("Compila cabinet, riga e colonna.", "danger"); return redirect(url_for("edit_item", item_id=item.id))
    try:
        _assign_position(item, int(cab_id), col_code, int(row_num))
        db.session.commit()
        flash("Posizione aggiornata.", "success")
    except Exception as e:
        db.session.rollback(); flash(str(e), "danger")
    return redirect(url_for("edit_item", item_id=item.id))

@app.route("/admin/items/<int:item_id>/clear_position", methods=["POST"])
@login_required
def clear_position(item_id):
    Assignment.query.filter_by(item_id=item_id).delete()
    db.session.commit()
    flash("Posizione rimossa.", "success")
    return redirect(url_for("edit_item", item_id=item_id))

# ===================== ADMIN: CATEGORIE =====================
@app.route("/admin/categories")
@login_required
def admin_categories():
    categories = Category.query.order_by(Category.name).all()
    materials  = Material.query.order_by(Material.name).all()
    finishes   = Finish.query.order_by(Finish.name).all()
    # elenco sottotipi con categoria associata (per mostrare ed editare)
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
    return render_template(
        "admin/categories.html",
        categories=categories,
        materials=materials,
        finishes=finishes,
        subtypes=subtypes,
        used_subtypes=used_subtypes,
        used_materials=used_materials,
        used_finishes=used_finishes,
    )

@app.route("/admin/categories/add", methods=["POST"])
@login_required
def add_category():
    name = request.form.get("name","").strip()
    color = request.form.get("color","#000000").strip()
    if len(name) < 2: return _flash_back("Nome categoria troppo corto.", "danger", "admin_categories")
    if Category.query.filter_by(name=name).first(): return _flash_back("Categoria già esistente.", "danger", "admin_categories")
    db.session.add(Category(name=name, color=color)); db.session.commit()
    flash("Categoria aggiunta.", "success"); return redirect(url_for("admin_categories"))

@app.route("/admin/categories/<int:cat_id>/update", methods=["POST"])
@login_required
def update_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    new_name = request.form.get("name","").strip()
    new_color = request.form.get("color","#000000").strip()
    if new_name and new_name != cat.name:
        if Category.query.filter(Category.id != cat.id, Category.name == new_name).first():
            return _flash_back("Esiste già una categoria con questo nome.", "danger", "admin_categories")
        cat.name = new_name
    cat.color = new_color or cat.color
    db.session.commit()
    flash("Categoria aggiornata.", "success"); return redirect(url_for("admin_categories"))

@app.route("/admin/categories/<int:cat_id>/delete", methods=["POST"])
@login_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    used = Item.query.filter_by(category_id=cat.id).first()
    if used:
        flash("Impossibile eliminare: ci sono articoli associati.", "danger")
    else:
        db.session.delete(cat); db.session.commit(); flash("Categoria eliminata.", "success")
    return redirect(url_for("admin_categories"))

def _flash_back(msg, kind, endpoint):
    flash(msg, kind); return redirect(url_for(endpoint))

@app.route("/admin/subtypes/add", methods=["POST"])
@login_required
def add_subtype():
    name = (request.form.get("name") or "").strip()
    try:
        category_id = int(request.form.get("category_id") or 0)
    except Exception:
        category_id = 0

    if category_id <= 0:
        return _flash_back("Seleziona una categoria valida per il sottotipo.", "danger", "admin_categories")
    if len(name) < 2:
        return _flash_back("Nome sottotipo troppo corto.", "danger", "admin_categories")

    # univoco per categoria (rispetta il vincolo uq_subtype_per_category)
    exists = Subtype.query.filter_by(category_id=category_id, name=name).first()
    if exists:
        return _flash_back("Esiste già un sottotipo con questo nome per la categoria selezionata.", "danger", "admin_categories")

    db.session.add(Subtype(category_id=category_id, name=name))
    db.session.commit()
    flash("Sottotipo aggiunto.", "success")
    return redirect(url_for("admin_categories"))


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
        return _flash_back("Nome sottotipo troppo corto.", "danger", "admin_categories")

    # evita duplicati nella stessa categoria
    clash = (
        Subtype.query
        .filter(Subtype.id != st.id,
                Subtype.category_id == category_id,
                Subtype.name == name)
        .first()
    )
    if clash:
        return _flash_back("Esiste già un sottotipo con questo nome per la categoria selezionata.", "danger", "admin_categories")

    st.name = name
    st.category_id = category_id
    db.session.commit()
    flash("Sottotipo aggiornato.", "success")
    return redirect(url_for("admin_categories"))


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
    return redirect(url_for("admin_categories"))

@app.route("/admin/materials/add", methods=["POST"])
@login_required
def add_material():
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        return _flash_back("Nome materiale troppo corto.", "danger", "admin_categories")
    if Material.query.filter_by(name=name).first():
        return _flash_back("Materiale già esistente.", "danger", "admin_categories")

    db.session.add(Material(name=name))
    db.session.commit()
    flash("Materiale aggiunto.", "success")
    return redirect(url_for("admin_categories"))


@app.route("/admin/materials/<int:mat_id>/update", methods=["POST"])
@login_required
def update_material(mat_id):
    mat = Material.query.get_or_404(mat_id)
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        return _flash_back("Nome materiale troppo corto.", "danger", "admin_categories")
    if Material.query.filter(Material.id != mat.id, Material.name == name).first():
        return _flash_back("Esiste già un materiale con questo nome.", "danger", "admin_categories")

    mat.name = name
    db.session.commit()
    flash("Materiale aggiornato.", "success")
    return redirect(url_for("admin_categories"))


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
    return redirect(url_for("admin_categories"))

@app.route("/admin/finishes/add", methods=["POST"])
@login_required
def add_finish():
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        return _flash_back("Nome finitura troppo corto.", "danger", "admin_categories")
    if Finish.query.filter_by(name=name).first():
        return _flash_back("Finitura già esistente.", "danger", "admin_categories")

    db.session.add(Finish(name=name))
    db.session.commit()
    flash("Finitura aggiunta.", "success")
    return redirect(url_for("admin_categories"))


@app.route("/admin/finishes/<int:fin_id>/update", methods=["POST"])
@login_required
def update_finish(fin_id):
    fin = Finish.query.get_or_404(fin_id)
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        return _flash_back("Nome finitura troppo corto.", "danger", "admin_categories")
    if Finish.query.filter(Finish.id != fin.id, Finish.name == name).first():
        return _flash_back("Esiste già una finitura con questo nome.", "danger", "admin_categories")

    fin.name = name
    db.session.commit()
    flash("Finitura aggiornata.", "success")
    return redirect(url_for("admin_categories"))


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
    return redirect(url_for("admin_categories"))

# ===================== ADMIN: CONFIGURAZIONE =====================
@app.route("/admin/config")
@login_required
def admin_config():
    locations = Location.query.order_by(Location.name).all()
    cabinets  = db.session.query(Cabinet, Location).join(Location, Cabinet.location_id==Location.id).order_by(Cabinet.name).all()
    drawer_merges = (
        db.session.query(DrawerMerge, Cabinet)
        .join(Cabinet, DrawerMerge.cabinet_id == Cabinet.id)
        .order_by(Cabinet.name, DrawerMerge.row_start, DrawerMerge.col_start)
        .all()
    )
    categories = Category.query.order_by(Category.name).all()
    custom_fields = CustomField.query.order_by(CustomField.sort_order, CustomField.name).all()
    serialized_custom_fields = serialize_custom_fields(custom_fields)
    field_defs = build_field_definitions(serialized_custom_fields)
    category_fields = build_category_field_map(categories)
    return render_template(
        "admin/config.html",
        locations=locations,
        cabinets=cabinets,
        drawer_merges=drawer_merges,
        settings=get_settings(),
        categories=categories,
        custom_fields=serialized_custom_fields,
        field_defs=field_defs,
        category_fields=category_fields,
    )

@app.route("/admin/config/fields/<int:cat_id>/update", methods=["POST"])
@login_required
def update_category_fields(cat_id):
    category = Category.query.get_or_404(cat_id)
    selected_keys = request.form.getlist("field_keys")
    CategoryFieldSetting.query.filter_by(category_id=category.id).delete()
    if not selected_keys:
        db.session.add(CategoryFieldSetting(category_id=category.id, field_key="__none__", is_enabled=False))
    else:
        for key in selected_keys:
            db.session.add(CategoryFieldSetting(category_id=category.id, field_key=key, is_enabled=True))
    db.session.commit()
    flash(f"Campi aggiornati per {category.name}.", "success")
    return redirect(url_for("admin_config"))

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
        s.orientation_landscape = bool(request.form.get("orientation_landscape"))
        s.qr_default  = bool(request.form.get("qr_default"))
        url = request.form.get("qr_base_url","").strip()
        s.qr_base_url = url or None
        db.session.commit()
        flash("Impostazioni aggiornate.", "success")
    except Exception as e:
        db.session.rollback(); flash(f"Errore salvataggio: {e}", "danger")
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
    items = [db.session.get(Item, a.item_id) for a in Assignment.query.filter_by(slot_id=slot_id).all()]
    return {it.category_id for it in items if it}

def _slot_capacity_ok(cabinet:Cabinet, assigns_count:int) -> bool:
    return assigns_count <= (cabinet.compartments_per_slot or 6)

def _reassign_compartments(slot_id:int, cabinet:Cabinet):
    assigns = Assignment.query.filter_by(slot_id=slot_id).order_by(Assignment.id).all()
    max_comp = cabinet.compartments_per_slot or 6
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
        if not _slot_capacity_ok(cab_to_obj, len(dst_assigns)+len(src_assigns)):
            return _flash_back("Scomparti insufficienti nel cassetto destinazione.", "danger", "admin_config")
        for a in src_assigns: a.slot_id = dst.id
        _reassign_compartments(dst.id, cab_to_obj)
        db.session.commit(); flash("Cassetto spostato.", "success")
    else:
        if not _slot_capacity_ok(cab_to_obj, len(dst_assigns)+len(src_assigns)) or not _slot_capacity_ok(cab_from_obj, len(src_assigns)+len(dst_assigns)):
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
    try:
        _assign_position(item, cabinet_id, col_code, row_num)
        db.session.commit()
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
            "position": f"{slot.col_code}{slot.row_num}",
        })
    return jsonify({"ok": True, "items": items})


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
    skipped_occupied = []   # celle saltate perché già occupate (clear_occupied=False)
    reused_slots = set()    # celle che verranno liberate e riutilizzate (clear_occupied=True)

    for col_code, row_num in _iter_cabinet_walk(cab, start_col, start_row, direction):
        if len(assignments_plan) >= requested:
            break
        slot = Slot.query.filter_by(cabinet_id=cab.id, col_code=col_code, row_num=row_num).first()
        if slot and slot.is_blocked:
            continue
        has_content = False
        if slot:
            has_content = Assignment.query.filter_by(slot_id=slot.id).first() is not None
        if has_content and not clear_occupied:
            skipped_occupied.append((col_code, row_num))
            continue
        if has_content and clear_occupied:
            reused_slots.add((col_code, row_num))
        assignments_plan.append((items[len(assignments_plan)], col_code, row_num))

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

    collisions_count = len(reused_slots) if clear_occupied else len(skipped_occupied)
    return {
        "assigned": assigned,
        "cleared_slots": cleared_slots,
        "collisions": collisions_count,
        "requested": requested,
        "total_unplaced": total_unplaced,
    }


@app.route("/admin/auto_assign", methods=["GET", "POST"])
@login_required
def auto_assign():
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

    if request.method == "POST":
        form = request.form
        try:
            form_cabinet_id  = int(form.get("cabinet_id") or 0)
            form_category_id = int(form.get("category_id") or 0)
            primary_key      = form.get("primary_key") or "length_mm"
            secondary_key    = form.get("secondary_key") or ""
            direction        = (form.get("direction") or "H").upper()
            count_val        = max(1, int(form.get("count") or "1"))
            start_col        = (form.get("start_col") or "").strip().upper()
            start_row        = int(form.get("start_row") or "0")
            clear_occupied   = bool(form.get("clear_occupied"))
        except Exception:
            flash("Parametri non validi per l'assegnamento automatico.", "danger")
            return redirect(url_for("auto_assign"))

        if not (form_cabinet_id and form_category_id and start_col and start_row):
            flash("Seleziona cassettiera, categoria e cella di partenza.", "danger")
            return redirect(url_for(
                "auto_assign",
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
            "auto_assign",
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

    return render_template(
        "admin/auto_assign.html",
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
    )


# ===================== ETICHETTE PDF =====================
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

    def wrap_to_lines(text: str, font_name: str, font_size: float, max_width_pt: float, max_lines: int = 2):
        if not text: return []
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
                            lines.append(piece); cur = ""
                            break
                    if len(lines) == max_lines:
                        return lines
        if cur and len(lines) < max_lines:
            lines.append(cur)
        return lines

    ids = request.form.getlist("item_ids")
    if not ids:
        flash("Seleziona almeno un articolo.", "warning"); return redirect(request.referrer or url_for("admin_items"))
    items = Item.query.filter(Item.id.in_(ids)).all()
    if not items:
        flash("Nessun articolo valido per la stampa.", "warning"); return redirect(request.referrer or url_for("admin_items"))

    assignments = (db.session.query(Assignment.item_id, Cabinet.name, Slot.col_code, Slot.row_num)
                   .join(Slot, Assignment.slot_id == Slot.id)
                   .join(Cabinet, Slot.cabinet_id == Cabinet.id)
                   .filter(Assignment.item_id.in_(ids))
                   .all())
    pos_by_item = {a.item_id: (a.name, a.col_code, a.row_num) for a in assignments}
    original_order = {item.id: idx for idx, item in enumerate(items)}

    def _label_sort_key(item: Item):
        pos = pos_by_item.get(item.id)
        if pos:
            cab_name, col_code, row_num = pos
            return (0, cab_name or "", int(row_num), colcode_to_idx(col_code), original_order[item.id])
        return (1, original_order[item.id])

    items.sort(key=_label_sort_key)

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

    def _fmt_mm(value):
        """Formatta una misura in mm come intero o con una sola cifra decimale."""
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if abs(v - round(v)) < 0.01:
            return str(int(round(v)))
        return f"{v:.1f}".rstrip("0").rstrip(".")

    def _line1(item):
        """
        Riga 1: Categoria + Sottotipo + Misura (thread_size)
        Es: 'Rondelle Piana M8'
        """
        parts = []
        if item.category:
            parts.append(item.category.name)
        if item.subtype:
            parts.append(item.subtype.name)
        if item.thread_size:
            parts.append(item.thread_size)
        return " ".join(parts)

    def _line2(item):
        """
        Riga 2: dati tecnici in base al tipo.
        - Viti:      L<lunghezza>, materiale
        - Rondelle:  Øi<interno>, Øe<esterno>, sp<spessore>
        - Torrette:  config, L<lunghezza>, materiale
        - Altre:     Øe<esterno>, sp<spessore>, materiale
        """
        parts = []

        # Viti
        if is_screw(item):
            v = _fmt_mm(item.length_mm)
            if v:
                parts.append(f"L{v}")
            if item.material:
                parts.append(item.material.name)

        # Rondelle
        elif is_washer(item):
            v_i = _fmt_mm(getattr(item, "inner_d_mm", None))
            if v_i:
                parts.append(f"Øi{v_i}")
            v_e = _fmt_mm(item.outer_d_mm)
            if v_e:
                parts.append(f"Øe{v_e}")
            v_s = _fmt_mm(unified_thickness_value(item))
            if v_s:
                parts.append(f"sp{v_s}")

        # Torrette
        elif is_standoff(item):
            v = _fmt_mm(item.length_mm)
            if v:
                parts.append(f"L{v}")
            if item.material:
                parts.append(item.material.name)

        # Altre tipologie
        else:
            v = _fmt_mm(item.outer_d_mm)
            if v:
                parts.append(f"Øe{v}")
            v_s = _fmt_mm(unified_thickness_value(item))
            if v_s:
                parts.append(f"sp{v_s}")
            if item.material:
                parts.append(item.material.name)

        return " ".join(parts)


    qr_box = mm_to_pt(9) if include_qr else 0
    qr_margin = mm_to_pt(1)

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
                v = _fmt_mm(item.inner_d_mm)
                if v is not None:
                    parts.append(f"Øi{v}")

            if item.outer_d_mm:
                v = _fmt_mm(item.outer_d_mm)
                if v is not None:
                    parts.append(f"Øe{v}")

            v = _fmt_mm(unified_thickness_value(item))
            if v is not None:
                parts.append(f"s{v}")

            if parts:
                return " ".join(parts)

        # Per gli altri oggetti: se c'è spessore, aggiungi un breve "sX"
        v = _fmt_mm(unified_thickness_value(item))
        if v is not None and f"s{v}" not in base:
            base = f"{base} s{v}"

        return base

    def _single_line(text: str, font_name: str, font_size: float, max_width_pt: float) -> str:
        """Restituisce una singola riga che entra nella larghezza disponibile."""
        if not text:
            return ""
        lines = wrap_to_lines(text, font_name, font_size, max_width_pt, max_lines=1)
        return lines[0] if lines else ""

    for idx, item in enumerate(items):
        col = idx % cols
        row = (idx // cols) % rows
        if idx > 0 and idx % (cols * rows) == 0:
            c.showPage()

        x = x0 + col * (lab_w + gap)
        y = y0 - row * (lab_h + gap)

        crop_marks(x, y, lab_w, lab_h)

        # Barra colore categoria in alto
        try:
            colhex = item.category.color if item.category else "#000000"
            c.setFillColor(HexColor(colhex))
            c.rect(x, y + lab_h - 2, lab_w, 2, stroke=0, fill=1)
        except Exception:
            pass

        # area testuale a sinistra del QR
        text_right_limit = lab_w - (qr_box + qr_margin*2 if qr_box else 0) - mm_to_pt(1.5)
        c.setFillColorRGB(0, 0, 0)

        # punto di partenza dall'alto
        cy = y + lab_h - 3.5

        # --- Riga 1: Categoria + Sottotipo + Misura ---
        line1_text = _line1(item)
        if line1_text:
            line1_lines = wrap_to_lines(line1_text, cat_font, cat_size, text_right_limit, max_lines=1)
            if line1_lines:
                c.setFont(cat_font, cat_size)
                c.drawString(x + mm_to_pt(1.5), cy - cat_size, line1_lines[0])
                cy -= (cat_size + 0.6)

        # --- Riga 2: specifiche a seconda della categoria ---
        line2_text = _line2(item)
        if line2_text:
            line2_lines = wrap_to_lines(line2_text, title_font, title_size, text_right_limit, max_lines=1)
            if line2_lines:
                c.setFont(title_font, title_size)
                c.drawString(x + mm_to_pt(1.5), cy - title_size, line2_lines[0])
                cy -= (title_size + 0.6)

        # Fallback: se per qualche motivo non abbiamo scritto nulla, uso il nome completo
        if not line1_text and not line2_text:
            fallback = item.name or auto_name_for(item)
            lines = wrap_to_lines(fallback, title_font, title_size, text_right_limit, max_lines=2)
            c.setFont(title_font, title_size)
            for ln in lines:
                c.drawString(x + mm_to_pt(1.5), cy - title_size, ln)
                cy -= (title_size + 0.6)

        # posizione in basso a sinistra (Cassettiera-XY)
        pos_data = pos_by_item.get(item.id)
        if pos_data:
            pos = make_full_position(pos_data[0], pos_data[1], pos_data[2])
            c.setFont("Helvetica", 6)
            c.drawString(x + mm_to_pt(1.5), y + 1.8, pos)

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

# ===================== INIT / SEED =====================

def seed_if_empty_or_missing():
    if not User.query.filter_by(username="admin").first():
        db.session.add(User(username="admin", password="admin"))
    if not Settings.query.get(1):
        db.session.add(Settings(
            id=1,
            label_w_mm=DEFAULT_LABEL_W_MM, label_h_mm=DEFAULT_LABEL_H_MM,
            margin_tb_mm=DEFAULT_MARG_TB_MM, margin_lr_mm=DEFAULT_MARG_LR_MM,
            gap_mm=DEFAULT_GAP_MM, orientation_landscape=DEFAULT_ORIENTATION_LANDSCAPE,
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
    # categorie (con colori)
    defaults = [
        ("Viti","#2E7D32"), ("Dadi","#1565C0"), ("Rondelle","#F9A825"), ("Torrette","#6A1B9A"),
        ("Grani","#8E24AA"), ("Prigionieri","#3949AB"), ("Inserti e rivetti","#00897B"),
        ("Seeger e spine","#5D4037"), ("Distanziali","#00796B"), ("Boccole","#546E7A"), ("O-Ring","#D84315")
    ]
    for name,color in defaults:
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name, color=color))
    for m in ["Acciaio","Inox A2","Inox A4","Ottone","Alluminio","Rame","Nylon","Ottone nichelato","Bronzo","PTFE","EPDM","Viton","Silicone"]:
        if not Material.query.filter_by(name=m).first():
            db.session.add(Material(name=m))
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
