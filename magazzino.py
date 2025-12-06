# magazzino.py
from flask import Flask, render_template, redirect, url_for, request, jsonify, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import func, select
from jinja2 import DictLoader
import os, io, sqlite3

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
    main_size_mm    = db.Column(db.Float, nullable=True)      # viti/torrette=L; rondelle=Ø esterno
    inner_d_mm      = db.Column(db.Float, nullable=True)      # foro interno (rondelle)
    thickness_mm    = db.Column(db.Float, nullable=True)      # spessore (rondelle)
    length_mm       = db.Column(db.Float, nullable=True)      # legacy
    outer_d_mm      = db.Column(db.Float, nullable=True)      # legacy
    # nuovi campi specifici
    drive           = db.Column(db.String(32), nullable=True) # impronta (Viti)
    standoff_config = db.Column(db.String(16), nullable=True) # M/F, F/F, M/M, Passante (Torrette)
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
    label_show_thread   = db.Column(db.Boolean, nullable=False, default=True)

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

def make_full_position(cab_name: str, col_code: str, row_num: int) -> str:
    return f"{cab_name}-{col_code.upper()}{int(row_num)}"

def is_washer(item:Item)->bool:
    return (item.category and item.category.name.lower()=="rondelle")

def is_screw(item:Item)->bool:
    return (item.category and item.category.name.lower()=="viti")

def is_standoff(item:Item)->bool:
    return (item.category and item.category.name.lower()=="torrette")

def auto_name_for(item:Item)->str:
    parts=[]
    if item.category: parts.append(item.category.name)
    if item.subtype: parts.append(item.subtype.name)  # forma testa / forma torrette
    # attributi specifici
    if is_screw(item) and item.drive:
        parts.append(item.drive)
    if is_standoff(item) and item.standoff_config:
        parts.append(item.standoff_config)
    if item.thread_size: parts.append(item.thread_size)
    if item.main_size_mm:
        tag = "Øe" if is_washer(item) else "L="
        val = int(item.main_size_mm) if item.main_size_mm and float(item.main_size_mm).is_integer() else item.main_size_mm
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
    q = Item.query
    if request.args.get("category_id"): q = q.filter(Item.category_id == request.args.get("category_id"))
    if request.args.get("material_id"): q = q.filter(Item.material_id == request.args.get("material_id"))
    if request.args.get("measure"):      q = q.filter(func.lower(Item.thread_size).contains(request.args.get("measure").lower()))
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

    return render_template("index.html",
        items=items, categories=categories, materials=materials, pos_by_item=pos_by_item,
        cabinets=all_cabinets, selected_cab_id=cab_id, grid=grid,
        unplaced_json=unplaced_json, is_admin=current_user.is_authenticated
    )

def build_full_grid(cabinet_id:int):
    cab = db.session.get(Cabinet, cabinet_id)
    if not cab: return {"rows":[], "cols":[], "cells":{}, "cab":None}

    rows = list(range(1, min(128, max(1, int(cab.rows_max))) + 1))
    cols = list(iter_cols_upto(cab.cols_max or "Z"))

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

    return {
        "rows": rows, "cols": cols, "cells": cells,
        "cab": {"id": cab.id, "name": cab.name, "comp": cab.compartments_per_slot}
    }

def short_cell_text(it:Item)->str:
    parts=[]
    if it.thread_size: parts.append(it.thread_size)
    if it.main_size_mm:
        val = int(it.main_size_mm) if float(it.main_size_mm).is_integer() else it.main_size_mm
        parts.append(("Øe" if is_washer(it) else "L=") + f"{val}")
    if is_standoff(it) and it.standoff_config:
        parts.append(it.standoff_config)
    if is_screw(it) and it.drive:
        parts.append(it.drive.replace(" (", " (")[:6])  # breve
    return " · ".join(parts[:2]) if parts else ""

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
        "main_size_mm": item.main_size_mm,
        "inner_d_mm": item.inner_d_mm, "thickness_mm": item.thickness_mm,
        "material": item.material.name if item.material else None,
        "finish": item.finish.name if item.finish else None,
        "quantity": item.quantity,
        "drive": item.drive,
        "standoff_config": item.standoff_config,
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

    metric_sizes = ["M2","M2.5","M3","M4","M5","M6","M8","M10","M12","M14","M16"]
    unc_sizes    = ["#2-56","#4-40","#6-32","#8-32","#10-24","1/4-20","5/16-18","3/8-16","1/2-13"]
    unf_sizes    = ["#2-64","#4-48","#6-40","#8-36","#10-32","1/4-28","5/16-24","3/8-24","1/2-20"]

    # ID per condizioni UI
    viti = Category.query.filter_by(name="Viti").first()
    torrette = Category.query.filter_by(name="Torrette").first()
    viti_id = viti.id if viti else None
    torrette_id = torrette.id if torrette else None

    # impronte viti e configurazioni torrette
    drive_options = ["Taglio", "Phillips (PH)", "Pozidriv (PZ)", "Torx (TX)", "Esagonale incassato (brugola)", "Robertson (quadra)", "Spanner"]
    standoff_cfgs = ["M/F", "F/F", "M/M", "Passante"]

    subtypes_by_cat = {}
    for s in subtypes:
        subtypes_by_cat.setdefault(s.category_id, []).append({"id": s.id, "name": s.name})

    rondelle = Category.query.filter_by(name="Rondelle").first()
    rondelle_id = rondelle.id if rondelle else None

    return render_template("admin/dashboard.html",
        items=items, categories=categories, materials=materials, finishes=finishes,
        locations=locations, cabinets=cabinets,
        subtypes_by_cat=subtypes_by_cat,
        metric_sizes=metric_sizes, unc_sizes=unc_sizes, unf_sizes=unf_sizes,
        rondelle_id=rondelle_id,
        viti_id=viti_id, torrette_id=torrette_id,
        drive_options=drive_options, standoff_cfgs=standoff_cfgs,
        pos_by_item=pos_by_item
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
    item = Item(
        description=f.get("description") or None,
        category_id=int(f.get("category_id")),
        subtype_id=int(f.get("subtype_id")) if f.get("subtype_id") else None,
        thread_standard=f.get("thread_standard") or None,
        thread_size=f.get("thread_size") or None,
        main_size_mm=float(f.get("main_size_mm")) if f.get("main_size_mm") else None,
        inner_d_mm=float(f.get("inner_d_mm")) if f.get("inner_d_mm") else None,
        thickness_mm=float(f.get("thickness_mm")) if f.get("thickness_mm") else None,
        drive=f.get("drive") or None,
        standoff_config=f.get("standoff_config") or None,
        material_id=int(f.get("material_id")) if f.get("material_id") else None,
        finish_id=int(f.get("finish_id")) if f.get("finish_id") else None,
        quantity=int(f.get("quantity")) if f.get("quantity") else 0,
        label_show_category=bool(f.get("label_show_category")),
        label_show_subtype =bool(f.get("label_show_subtype")),
        label_show_measure =bool(f.get("label_show_measure")),
        label_show_main    =bool(f.get("label_show_main")),
        label_show_material=bool(f.get("label_show_material")),
        label_show_thread  =bool(f.get("label_show_measure")),  # compat
    )
    item.name = auto_name_for(item)
    db.session.add(item); db.session.flush()
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
        item.description = f.get("description") or None
        item.category_id = int(f.get("category_id"))
        item.subtype_id = int(f.get("subtype_id")) if f.get("subtype_id") else None
        item.thread_standard = f.get("thread_standard") or None
        item.thread_size = f.get("thread_size") or None
        item.main_size_mm = float(f.get("main_size_mm")) if f.get("main_size_mm") else None
        item.inner_d_mm = float(f.get("inner_d_mm")) if f.get("inner_d_mm") else None
        item.thickness_mm = float(f.get("thickness_mm")) if f.get("thickness_mm") else None
        item.drive = f.get("drive") or None
        item.standoff_config = f.get("standoff_config") or None
        item.material_id = int(f.get("material_id")) if f.get("material_id") else None
        item.finish_id = int(f.get("finish_id")) if f.get("finish_id") else None
        item.quantity = int(f.get("quantity")) if f.get("quantity") else 0
        item.label_show_category = bool(f.get("label_show_category"))
        item.label_show_subtype  = bool(f.get("label_show_subtype"))
        item.label_show_measure  = bool(f.get("label_show_measure"))
        item.label_show_main     = bool(f.get("label_show_main"))
        item.label_show_material = bool(f.get("label_show_material"))
        item.label_show_thread   = bool(f.get("label_show_measure"))
        item.name = auto_name_for(item)
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

    metric_sizes = ["M2","M2.5","M3","M4","M5","M6","M8","M10","M12","M14","M16"]
    unc_sizes    = ["#2-56","#4-40","#6-32","#8-32","#10-24","1/4-20","5/16-18","3/8-16","1/2-13"]
    unf_sizes    = ["#2-64","#4-48","#6-40","#8-36","#10-32","1/4-28","5/16-24","3/8-24","1/2-20"]

    pos = (db.session.query(Assignment, Slot, Cabinet)
           .join(Slot, Assignment.slot_id == Slot.id)
           .join(Cabinet, Slot.cabinet_id == Cabinet.id)
           .filter(Assignment.item_id == item.id).first())
    current_position = make_full_position(pos[2].name, pos[1].col_code, pos[1].row_num) if pos else None

    viti = Category.query.filter_by(name="Viti").first()
    torrette = Category.query.filter_by(name="Torrette").first()
    viti_id = viti.id if viti else None
    torrette_id = torrette.id if torrette else None
    drive_options = ["Taglio", "Phillips (PH)", "Pozidriv (PZ)", "Torx (TX)", "Esagonale incassato (brugola)", "Robertson (quadra)", "Spanner"]
    standoff_cfgs = ["M/F", "F/F", "M/M", "Passante"]

    rondelle = Category.query.filter_by(name="Rondelle").first()
    rondelle_id = rondelle.id if rondelle else None

    return render_template("admin/edit_item.html",
        item=item, categories=categories, materials=materials, finishes=finishes,
        cabinets=cabinets, subtypes_by_cat=subtypes_by_cat,
        metric_sizes=metric_sizes, unc_sizes=unc_sizes, unf_sizes=unf_sizes,
        rondelle_id=rondelle_id,
        viti_id=viti_id, torrette_id=torrette_id,
        drive_options=drive_options, standoff_cfgs=standoff_cfgs
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
    return render_template(
        "admin/categories.html",
        categories=categories,
        materials=materials,
        finishes=finishes,
        subtypes=subtypes,
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
    return render_template("admin/config.html", locations=locations, cabinets=cabinets, settings=get_settings())

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
    slot = _ensure_slot(cab_id, col, row)
    if Assignment.query.filter_by(slot_id=slot.id).first():
        flash("Impossibile bloccare: cassetto occupato.", "danger")
    else:
        slot.is_blocked = True; db.session.commit(); flash("Cella bloccata.", "success")
    return redirect(url_for("admin_config"))

@app.route("/admin/slots/unblock", methods=["POST"])
@login_required
def unblock_slot():
    cab_id = int(request.form.get("cabinet_id"))
    col    = request.form.get("col_code","").upper().strip()
    row    = int(request.form.get("row_num"))
    if not column_code_valid(col) or not (1<=row<=128):
        return _flash_back("Colonna/riga non validi.", "danger", "admin_config")
    slot = _ensure_slot(cab_id, col, row)
    slot.is_blocked = False; db.session.commit(); flash("Cella sbloccata.", "success")
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

    slot = Slot.query.filter_by(cabinet_id=cab_id, col_code=col_code, row_num=row_num).first()
    if not slot:
        # nessuno slot definito => cella vuota
        return jsonify({"ok": True, "items": []})

    assigns = (
        db.session.query(Assignment, Item, Category)
        .join(Item, Assignment.item_id == Item.id)
        .join(Category, Item.category_id == Category.id, isouter=True)
        .filter(Assignment.slot_id == slot.id)
        .order_by(Assignment.compartment_no)
        .all()
    )

    items = []
    for a, it, cat in assigns:
        items.append({
            "id": it.id,
            "name": auto_name_for(it),
            "quantity": it.quantity,
            "category": cat.name if cat else None,
            "color": cat.color if cat else "#999999",
        })
    return jsonify({"ok": True, "items": items})


@app.route("/admin/slot_items/<int:item_id>/clear", methods=["POST"])
@login_required
def slot_clear_item(item_id):
    Assignment.query.filter_by(item_id=item_id).delete()
    db.session.commit()
    return jsonify({"ok": True})


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

    qr_box = mm_to_pt(9) if include_qr else 0
    qr_margin = mm_to_pt(1)

    for idx, item in enumerate(items):
        col = idx % cols
        row = (idx // cols) % rows
        if idx>0 and idx % (cols*rows) == 0:
            c.showPage()

        x = x0 + col * (lab_w + gap)
        y = y0 - row * (lab_h + gap)

        crop_marks(x, y, lab_w, lab_h)

        # barra colore categoria
        try:
            colhex = item.category.color if item.category else "#000000"
            c.setFillColor(HexColor(colhex)); c.rect(x, y + lab_h-2, lab_w, 2, stroke=0, fill=1)
        except Exception:
            pass

        # area testuale a sinistra del QR
        text_right_limit = lab_w - (qr_box + qr_margin*2 if qr_box else 0) - mm_to_pt(1.5)
        c.setFillColorRGB(0,0,0)

        # 1) categoria
        cat_name = item.category.name if item.category else ""
        cy = y + lab_h - 3.5
        if cat_name:
            c.setFont(cat_font, cat_size)
            c.drawString(x + mm_to_pt(1.5), cy - cat_size, cat_name)
            cy -= (cat_size + 0.6)

        # 2) Nome articolo (max 2 righe)
        name_text = item.name or auto_name_for(item)
        lines = wrap_to_lines(name_text, title_font, title_size, text_right_limit, max_lines=2)
        c.setFont(title_font, title_size)
        for ln in lines:
            c.drawString(x + mm_to_pt(1.5), cy - title_size, ln)
            cy -= (title_size + 0.6)

        # posizione in basso a sinistra (Cassettiera-XY)
        a = (db.session.query(Assignment, Slot, Cabinet)
             .join(Slot, Assignment.slot_id == Slot.id)
             .join(Cabinet, Slot.cabinet_id == Cabinet.id)
             .filter(Assignment.item_id == item.id).first())
        if a:
            pos = make_full_position(a[2].name, a[1].col_code, a[1].row_num)
            c.setFont("Helvetica", 6)
            c.drawString(x+mm_to_pt(1.5), y+1.8, pos)

        # QR a destra
        if qr_box:
            try:
                s = get_settings()
                if s.qr_base_url:
                    url = f"{s.qr_base_url.rstrip('/')}/api/items/{item.id}.json"
                else:
                    url = f"{request.host_url.rstrip('/')}/api/items/{item.id}.json"
                from reportlab.graphics.barcode import qr as qrmod
                from reportlab.graphics.shapes import Drawing
                from reportlab.graphics import renderPDF
                qr_code = qrmod.QrCodeWidget(url)
                bounds = qr_code.getBounds()
                w = bounds[2]-bounds[0]; h = bounds[3]-bounds[1]
                scale = min(qr_box/w, qr_box/h)
                d = Drawing(w, h); d.add(qr_code)
                c.saveState()
                c.translate(x + lab_w - qr_box - qr_margin, y + qr_margin)
                c.scale(scale, scale)
                renderPDF.draw(d, c, 0, 0)
                c.restoreState()
            except Exception:
                pass

    c.save(); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="etichette.pdf", mimetype="application/pdf")

# ===================== TEMPLATES =====================
BASE_TMPL = """\
<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8"><title>Magazzino</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css" rel="stylesheet">
  <style>
    body { background-color: #f8f9fa; }
    .navbar-brand { font-weight: 600; }
    .form-section { background: #fff; border-radius: 10px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
    .badge-color { display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:6px; vertical-align:middle; }
        .grid-wrap {
      overflow:auto;
      border:1px solid #ddd;
      border-radius:8px;
      background:#fff;
      max-height: 65vh;
      width: 100%;
    }
    .grid-table {
      border-collapse: separate;
      border-spacing: 0;
      font-size: 12px;
      width: 100%;
      table-layout: fixed;
    }
    .grid-table th, .grid-table td {
      border: 1px solid #e5e5e5;
      text-align: center;
      min-width: 48px;
      height: 48px; min-height: 48px;
      padding: 0;
      vertical-align: middle;
    }

    .grid-table thead th { position: sticky; top: 0; background: #f1f1f1; z-index: 3; }
    .grid-table .rowhdr { position: sticky; left: 0; background: #f7f7f7; z-index: 2; width: 54px; min-width: 54px; padding-right: 6px; text-align: right; }
    .grid-table thead .rowhdr { z-index: 4; }
    .cell-empty { background: #fafafa; color:#999; cursor: pointer; }
    .cell-blocked { background: #000; color:#fff; }
    .cell-used { cursor: pointer; }
    .cell-inner {
      padding: 4px 6px;
      line-height: 1.05;
      display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
      overflow: hidden;
      font-size: 11px;
      color: #fff;
      font-weight: 600;
      text-shadow: 0 1px 1px rgba(0,0,0,.35);
    }
    .legend span { display:inline-block; width:12px; height:12px; margin-right:6px; border-radius:2px; }
  </style>
</head>
<body>
  <nav class="navbar navbar-dark bg-dark">
    <div class="container-fluid">
      <a class="navbar-brand" href="/">Magazzino</a>
      <div class="d-flex gap-2">
        {% if current_user.is_authenticated %}
          <a href="{{ url_for('index') }}" class="btn btn-outline-light btn-sm">Magazzino principale</a>
          <a href="{{ url_for('admin_items') }}" class="btn btn-outline-light btn-sm">Articoli</a>
          <a href="{{ url_for('to_place') }}" class="btn btn-outline-light btn-sm">Da posizionare</a>
          <a href="{{ url_for('admin_categories') }}" class="btn btn-outline-light btn-sm">Categorie</a>
          <a href="{{ url_for('admin_config') }}" class="btn btn-outline-light btn-sm">Configurazione</a>
          <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm">Logout</a>
        {% else %}
          <a href="{{ url_for('login') }}" class="btn btn-outline-light btn-sm">Login</a>
        {% endif %}
      </div>
    </div>
  </nav>
  <div class="container py-3">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="mb-2">
          {% for cat, msg in messages %}
            <div class="alert alert-{{ cat }} py-2 mb-1">{{ msg }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </div>
  <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
  <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

INDEX_TMPL = """\
{% extends "base.html" %}
{% block content %}
<h3>Elenco articoli</h3>
<form class="row g-2 mb-3">
  <div class="col-md-3">
    <select name="category_id" class="form-select">
      <option value="">Tutte le categorie</option>
      {% for c in categories %}
        <option value="{{ c.id }}" {{ 'selected' if (request.args.get('category_id')|int)==c.id else '' }}>{{ c.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="col-md-3">
    <select name="material_id" class="form-select">
      <option value="">Tutti i materiali</option>
      {% for m in materials %}
        <option value="{{ m.id }}" {{ 'selected' if (request.args.get('material_id')|int)==m.id else '' }}>{{ m.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="col-md-3"><input type="text" name="measure" class="form-control" placeholder="Cerca misura (es. M3, 1/4-20)" value="{{ request.args.get('measure','') }}"></div>
  <div class="col-md-3"><button class="btn btn-primary btn-sm">Filtra</button> <a href="{{ url_for('index') }}" class="btn btn-secondary btn-sm">Reset</a></div>
</form>

<table class="table table-striped table-hover" id="itemsTable">
  <thead><tr>
    <th>ID</th><th>Categoria</th><th>Descrizione</th><th>Misura</th>
    <th>Dim. principale (mm)</th><th>Materiale</th><th>Quantità</th><th>Posizione</th>
  </tr></thead>
  <tbody>
    {% for item in items %}
    <tr>
      <td>{{ item.id }}</td>
      <td>{% if item.category %}<span class="badge-color" style="background:{{ item.category.color }}"></span>{{ item.category.name }}{% endif %}</td>
      <td>{{ compose_caption(item) }}</td>
      <td>{{ item.thread_size }}</td>
      <td>{{ '%.2f'|format(item.main_size_mm) if item.main_size_mm is not none else '' }}</td>
      <td>{{ item.material.name if item.material else '' }}</td>
      <td>{{ item.quantity }}</td>
      <td>{{ pos_by_item.get(item.id, '') }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
<script>$(function(){ if ($.fn.DataTable) $('#itemsTable').DataTable({ pageLength: 25, order:[[1,'asc']] });});</script>

<hr class="my-4">

<h4>Griglia cassettiera</h4>
<form class="row g-2 mb-2">
  <div class="col-md-4">
    <select name="cabinet_id" class="form-select" onchange="this.form.submit()">
      {% for c in cabinets %}
        <option value="{{ c.id }}" {{ 'selected' if c.id==selected_cab_id else '' }}>{{ c.name }}</option>
      {% endfor %}
    </select>
  </div>
</form>

<div class="legend mb-2">
  <span style="background:black"></span> Bloccata
  {% for c in categories %}
    <span style="background:{{ c.color }}; margin-left:12px;"></span> {{ c.name }}
  {% endfor %}
</div>

<div class="grid-wrap p-2">
  {% if grid.rows and grid.cols %}
  <table class="grid-table" id="grid" data-cab="{{ grid.cab.id }}" data-comp="{{ grid.cab.comp }}">
    <thead>
      <tr>
        <th class="rowhdr">r\\c</th>
        {% for col in grid.cols %}
          <th>{{ col }}</th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for r in grid.rows %}
      <tr>
        <th class="rowhdr">{{ r }}</th>
        {% for col in grid.cols %}
          {% set key = col ~ '-' ~ r %}
          {% set cell = grid.cells.get(key) %}
          {% if not cell %}
            <td class="cell-empty" data-col="{{ col }}" data-row="{{ r }}" data-cat="">
              <div class="cell-inner" style="color:#777; text-shadow:none; font-weight:500;">&nbsp;</div>
            </td>
          {% else %}
            {% if cell.blocked %}
              <td class="cell-blocked" data-col="{{ col }}" data-row="{{ r }}" data-cat="blocked">—</td>
            {% elif cell.entries and (cell.entries|length)>0 %}
              {% set colhex = cell.entries[0].color %}
              {% set texts = (cell.entries | map(attribute='text') | list) %}
              <td class="cell-used" style="background: {{ colhex }}" data-col="{{ col }}" data-row="{{ r }}" data-cat="{{ cell.cat_id or '' }}">
                <div class="cell-inner">
                  {% if texts|length>0 %}<div>{{ texts[0] }}</div>{% endif %}
                  {% if texts|length>1 %}<div>{{ texts[1] }}</div>{% endif %}
                  {% if texts|length>2 %}<div>+{{ texts|length-2 }}</div>{% endif %}
                </div>
              </td>
            {% else %}
              <td class="cell-empty" data-col="{{ col }}" data-row="{{ r }}" data-cat="">
                <div class="cell-inner" style="color:#777; text-shadow:none; font-weight:500;">&nbsp;</div>
              </td>
            {% endif %}
          {% endif %}
        {% endfor %}
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
    <div class="text-muted p-3">Configura una cassettiera per visualizzare la griglia.</div>
  {% endif %}
</div>

{% if is_admin %}
<!-- Modal assegnazione -->
<div class="modal fade" id="assignModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-scrollable">
    <div class="modal-content">
      <form id="assignForm">
      <div class="modal-header">
        <h5 class="modal-title">Assegna articolo a <span id="slotLabel"></span></h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Chiudi"></button>
      </div>
      <div class="modal-body">
        <div class="sticky-top">
          <div class="mb-2"><input type="text" id="flt" class="form-control" placeholder="Filtra (testo libero)"></div>
        </div>
        <input type="hidden" name="cabinet_id" id="cab_id" value="{{ grid.cab.id if grid.cab else '' }}">
        <input type="hidden" name="col_code" id="col_code">
        <input type="hidden" name="row_num" id="row_num">
        <div class="mb-2"><small class="text-muted">Mostro solo articoli senza posizione. Se la cella è già occupata, verranno accettati solo articoli della stessa categoria.</small></div>
        <select name="item_id" id="item_id" size="12" class="form-select">
          {% for it in unplaced_json %}
            <option value="{{ it.id }}" data-cat="{{ it.category_id }}">{{ it.caption }}</option>
          {% endfor %}
        </select>
        <div class="mt-2"><small class="text-muted">Totale elementi: <span id="totCnt">{{ unplaced_json|length }}</span></small></div>
        <div id="assignError" class="text-danger small mt-2 d-none"></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary">Assegna</button>
        <button type="button" class="btn btn-outline-secondary" id="btnNewItem">Nuovo articolo…</button>
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annulla</button>
      </div>
      </form>
    </div>
  </div>
</div>

<!-- Modal contenuto cella -->
<div class="modal fade" id="slotModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-scrollable">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Contenuto cella <span id="slotLabel2"></span></h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Chiudi"></button>
      </div>
      <div class="modal-body">
        <input type="hidden" id="slot_cab_id" value="{{ grid.cab.id if grid.cab else '' }}">
        <input type="hidden" id="slot_col_code">
        <input type="hidden" id="slot_row_num">
        <div id="slotEmptyMsg" class="text-muted small d-none">Nessun articolo assegnato a questa cella.</div>
        <table class="table table-sm align-middle mb-0" id="slotItemsTable">
          <thead>
            <tr><th>Articolo</th><th>Q.ta</th><th>Azioni</th></tr>
          </thead>
          <tbody id="slotItemsBody"></tbody>
        </table>
        <div id="slotError" class="text-danger small mt-2 d-none"></div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-outline-secondary" id="btnSlotAdd">Aggiungi articolo senza posizione…</button>
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Chiudi</button>
      </div>
    </div>
  </div>
</div>
{% endif %}


<script>
{% if is_admin %}
const UNPLACED = {{ unplaced_json|tojson }};
const CLEAR_URL_TEMPLATE = '{{ url_for("slot_clear_item", item_id=0) }}';

function openAssignModal(col, row, catFilter){
  const modal = new bootstrap.Modal(document.getElementById('assignModal'));
  document.getElementById('slotLabel').textContent = `${col}${row}`;
  document.getElementById('col_code').value = col;
  document.getElementById('row_num').value = row;
  const sel = document.getElementById('item_id');
  sel.innerHTML = '';
  let list = UNPLACED.slice();
  if (catFilter) list = list.filter(x => x.category_id == parseInt(catFilter));
  list.forEach(x=>{
    const o = document.createElement('option');
    o.value = x.id;
    o.textContent = x.caption;
    o.dataset.cat = x.category_id;
    sel.appendChild(o);
  });
  document.getElementById('totCnt').textContent = list.length;
  document.getElementById('flt').value = '';
  document.getElementById('assignError').classList.add('d-none');
  modal.show();
}

function openSlotModal(col, row){
  const grid = document.getElementById('grid');
  const cabId = document.getElementById('cab_id')?.value || grid?.dataset.cab;
  if (!cabId) return;

  const modalEl = document.getElementById('slotModal');
  const modal = new bootstrap.Modal(modalEl);

  document.getElementById('slotLabel2').textContent = `${col}${row}`;
  document.getElementById('slot_col_code').value = col;
  document.getElementById('slot_row_num').value = row;
  document.getElementById('slotError').classList.add('d-none');
  document.getElementById('slotEmptyMsg').classList.add('d-none');

  const tbody = document.getElementById('slotItemsBody');
  tbody.innerHTML = '<tr><td colspan="3"><small class="text-muted">Caricamento...</small></td></tr>';

  fetch(`{{ url_for("slot_items") }}?cabinet_id=${encodeURIComponent(cabId)}&col_code=${encodeURIComponent(col)}&row_num=${encodeURIComponent(row)}`)
    .then(r => r.json())
    .then(j => {
      tbody.innerHTML = '';
      if (!j.ok) {
        document.getElementById('slotError').textContent = j.error || 'Errore caricamento contenuto.';
        document.getElementById('slotError').classList.remove('d-none');
        return;
      }
      if (!j.items || !j.items.length) {
        document.getElementById('slotEmptyMsg').classList.remove('d-none');
        return;
      }

      j.items.forEach(it => {
        const tr = document.createElement('tr');

        const tdName = document.createElement('td');
        tdName.innerHTML = `<span class="badge-color" style="background:${it.color};"></span> ${it.name}`;

        const tdQty = document.createElement('td');
        tdQty.textContent = (it.quantity !== null && it.quantity !== undefined) ? it.quantity : '';

        const tdActions = document.createElement('td');
        tdActions.className = 'text-nowrap';
        tdActions.innerHTML = `
          <button type="button" class="btn btn-sm btn-outline-primary me-1" data-edit-id="${it.id}">Modifica</button>
          <button type="button" class="btn btn-sm btn-outline-danger" data-remove-id="${it.id}">Rimuovi posizione</button>
        `;

        tr.appendChild(tdName);
        tr.appendChild(tdQty);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
      });

      // azioni: modifica / rimuovi
      tbody.querySelectorAll('button[data-edit-id]').forEach(btn => {
        btn.addEventListener('click', () => {
          const id = btn.getAttribute('data-edit-id');
          window.location.href = '/admin/items/' + id + '/edit';
        });
      });

    tbody.querySelectorAll('button[data-remove-id]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-remove-id');
        if (!confirm('Rimuovere la posizione per questo articolo?')) return;
        try {
          const url = CLEAR_URL_TEMPLATE.replace('0', id);
          const resp = await fetch(url, { method: 'POST' });
          const jj = await resp.json().catch(()=>({ok:false}));
          if (!jj.ok) {
            alert(jj.error || 'Errore nella rimozione.');
            return;
          }
          // chiudo il modal e ricarico la pagina principale
          const modalEl = document.getElementById('slotModal');
          const inst = bootstrap.Modal.getInstance(modalEl);
          if (inst) inst.hide();
          location.reload();
        } catch (e) {
          alert('Errore di comunicazione.');
        }
      });
    });

    })
    .catch(() => {
      tbody.innerHTML = '';
      document.getElementById('slotError').textContent = 'Errore di comunicazione.';
      document.getElementById('slotError').classList.remove('d-none');
    });

  modal.show();
}

document.addEventListener('DOMContentLoaded', function(){
  const grid = document.getElementById('grid');
  if (!grid) return;

  // Click su cella:
  //  - cella bloccata → avviso
  //  - cella occupata → modal contenuto cella
  //  - cella vuota    → modal assegnazione (articoli senza posizione)
  grid.addEventListener('click', function(e){
    const td = e.target.closest('td');
    if (!td) return;
    if (td.classList.contains('cell-blocked')) { alert('Cella bloccata.'); return; }
    if (!{{ 'true' if is_admin else 'false' }}) return;

    const col = td.dataset.col;
    const row = td.dataset.row;
    const cat = td.dataset.cat;

    if (!col || !row) return;
    if (cat === 'blocked') { alert('Cella bloccata.'); return; }

    if (td.classList.contains('cell-used')) {
      openSlotModal(col, row);
    } else {
      openAssignModal(col, row, cat || null);
    }
  });

  // Filtro lista articoli non assegnati
  document.getElementById('flt')?.addEventListener('input', function(){
    const term = this.value.toLowerCase();
    const sel = document.getElementById('item_id');
    let visibleCount = 0;
    Array.from(sel.options).forEach(opt=>{
      const show = !term || opt.textContent.toLowerCase().includes(term);
      opt.hidden = !show;
      if (show) visibleCount++;
    });
    document.getElementById('totCnt').textContent = visibleCount;
  });

  // Submit assegnazione
  document.getElementById('assignForm')?.addEventListener('submit', async function(ev){
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const r = await fetch('{{ url_for("grid_assign") }}', { method:'POST', body: fd });
    const j = await r.json().catch(()=>({ok:false, error:'Errore sconosciuto'}));
    if (!j.ok) {
      const el = document.getElementById('assignError');
      el.textContent = j.error || 'Errore di assegnazione';
      el.classList.remove('d-none');
    } else {
      location.reload();
    }
  });

  // Bottone "Nuovo articolo…" → va alla pagina admin con posizione precompilata
  const btnNewItem = document.getElementById('btnNewItem');
  if (btnNewItem) {
    btnNewItem.addEventListener('click', function () {
      const cabId = document.getElementById('cab_id').value || grid.dataset.cab;
      const col   = document.getElementById('col_code').value;
      const row   = document.getElementById('row_num').value;

      if (!cabId || !col || !row) {
        return;
      }

      const params = new URLSearchParams({
        new_for_cab: cabId,
        new_for_col: col,
        new_for_row: row
      });

      window.location.href = '{{ url_for("admin_items") }}?' + params.toString();
    });
  }

  // Bottone nel modal contenuto cella per aggiungere articolo senza posizione
  const btnSlotAdd = document.getElementById('btnSlotAdd');
  if (btnSlotAdd) {
    btnSlotAdd.addEventListener('click', function () {
      const col = document.getElementById('slot_col_code').value;
      const row = document.getElementById('slot_row_num').value;
      if (!col || !row) return;

      const modalEl = document.getElementById('slotModal');
      const inst = bootstrap.Modal.getInstance(modalEl);
      inst?.hide();

      openAssignModal(col, row, null);
    });
  }
});
{% endif %}
</script>
{% endblock %}
"""


LOGIN_TMPL = """\
{% extends "base.html" %}
{% block content %}
<h3>Login</h3>
<form method="post" class="form-section" style="max-width:420px">
  <div class="mb-3"><label>Username</label><input type="text" class="form-control" name="username" required></div>
  <div class="mb-3"><label>Password</label><input type="password" class="form-control" name="password" required></div>
  <button type="submit" class="btn btn-primary">Login</button>
</form>
{% endblock %}
"""

ADMIN_DASH_TMPL = r"""\
{% extends "base.html" %}
{% block content %}
<h3>Articoli (Admin)</h3>

<div class="form-section mb-3">
  <form id="labelForm" method="post" action="{{ url_for('labels_pdf') }}">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h5 class="mb-0">Elenco</h5>
      <div>
        <button class="btn btn-sm btn-primary">Stampa etichette</button>
      </div>
    </div>
    <table class="table table-striped table-hover" id="admItemsTable">
      <thead>
        <tr>
          <th style="width:36px;"><input type="checkbox" id="chkAll"></th>
          <th>ID</th>
          <th>Categoria</th>
          <th>Nome</th>
          <th>Misura</th>
          <th>Dim. princ. (mm)</th>
          <th>Materiale</th>
          <th>Q.ta</th>
          <th>Posizione</th>
          <th>Azione</th>
        </tr>
      </thead>
      <tbody>
        {% for it in items %}
        <tr>
          <td><input type="checkbox" name="item_ids" value="{{ it.id }}"></td>
          <td>{{ it.id }}</td>
          <td>{% if it.category %}<span class="badge-color" style="background:{{ it.category.color }}"></span>{{ it.category.name }}{% endif %}</td>
          <td>{{ compose_caption(it) }}</td>
          <td>{{ it.thread_size or "" }}</td>
          <td>{{ '%.2f'|format(it.main_size_mm) if it.main_size_mm is not none else '' }}</td>
          <td>{{ it.material.name if it.material else '' }}</td>
          <td>{{ it.quantity }}</td>
          <td>{{ pos_by_item.get(it.id, '') }}</td>
          <td class="text-nowrap">
            <a href="{{ url_for('edit_item', item_id=it.id) }}" class="btn btn-sm btn-outline-primary">Modifica</a>
            <form method="post" action="{{ url_for('delete_item', item_id=it.id) }}" class="d-inline" onsubmit="return confirm('Eliminare articolo?')">
              <button class="btn btn-sm btn-outline-danger">Elimina</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </form>
</div>

<div class="form-section">
  <h5 class="mb-2">Nuovo articolo</h5>
  <form method="post" action="{{ url_for('add_item') }}">
    <div class="row g-2">
      <div class="col-md-6">
        <label class="form-label">Categoria</label>
        <select class="form-select" name="category_id" id="catSel" required>
          <option value="">—</option>
          {% for c in categories %}
            <option value="{{ c.id }}">{{ c.name }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-6">
        <label class="form-label">Sottotipo (forma)</label>
        <select class="form-select" name="subtype_id" id="subtypeSel">
          <option value="">—</option>
        </select>
      </div>

      <div class="col-md-4">
        <label class="form-label">Standard</label>
        <select class="form-select" name="thread_standard" id="stdSel">
          <option value="M" selected>Metrico</option>
          <option value="UNC">UNC</option>
          <option value="UNF">UNF</option>
        </select>
      </div>
      <div class="col-md-8">
        <label class="form-label">Misura (es. M3 / 1/4-20)</label>
        <input class="form-control" name="thread_size" id="sizeInput" list="sizesM">
        <datalist id="sizesM">{% for s in metric_sizes %}<option value="{{ s }}">{% endfor %}</datalist>
        <datalist id="sizesUNC">{% for s in unc_sizes %}<option value="{{ s }}">{% endfor %}</datalist>
        <datalist id="sizesUNF">{% for s in unf_sizes %}<option value="{{ s }}">{% endfor %}</datalist>
      </div>

      <div class="col-md-4">
        <label class="form-label">Impronta (Viti)</label>
        <select class="form-select" name="drive" id="driveSel">
          <option value="">—</option>
          {% for d in drive_options %}<option value="{{ d }}">{{ d }}</option>{% endfor %}
        </select>
      </div>
      <div class="col-md-4">
        <label class="form-label">Configurazione (Torrette)</label>
        <select class="form-select" name="standoff_config" id="standoffSel">
          <option value="">—</option>
          {% for d in standoff_cfgs %}<option value="{{ d }}">{{ d }}</option>{% endfor %}
        </select>
      </div>

      <div class="col-md-4">
        <label class="form-label">Dimensione principale (mm)</label>
        <input type="number" step="0.01" class="form-control" name="main_size_mm" placeholder="L (viti/torrette) o Øe (rondelle)">
      </div>
      <div class="col-md-3 dim-washer">
        <label class="form-label">Ø interno (mm)</label>
        <input type="number" step="0.01" class="form-control" name="inner_d_mm">
      </div>
      <div class="col-md-3 dim-washer">
        <label class="form-label">Spessore (mm)</label>
        <input type="number" step="0.01" class="form-control" name="thickness_mm">
      </div>

      <div class="col-md-6">
        <label class="form-label">Materiale</label>
        <select class="form-select" name="material_id">
          <option value="">—</option>
          {% for m in materials %}<option value="{{ m.id }}">{{ m.name }}</option>{% endfor %}
        </select>
      </div>
      <div class="col-md-6">
        <label class="form-label">Finitura</label>
        <select class="form-select" name="finish_id">
          <option value="">—</option>
          {% for f in finishes %}<option value="{{ f.id }}">{{ f.name }}</option>{% endfor %}
        </select>
      </div>

      <div class="col-md-12">
        <label class="form-label">Descrizione (opz.)</label>
        <input type="text" class="form-control" name="description">
      </div>

      <div class="col-md-4">
        <label class="form-label">Quantità</label>
        <input type="number" min="0" step="1" class="form-control" name="quantity" value="0">
      </div>

      <div class="col-md-8">
        <label class="form-label d-block">Campi in etichetta</label>
        <div class="form-check form-check-inline">
          <input class="form-check-input" type="checkbox" name="label_show_category" checked>
          <label class="form-check-label">Categoria</label>
        </div>
        <div class="form-check form-check-inline">
          <input class="form-check-input" type="checkbox" name="label_show_subtype" checked>
          <label class="form-check-label">Sottotipo</label>
        </div>
        <div class="form-check form-check-inline">
          <input class="form-check-input" type="checkbox" name="label_show_measure" checked>
          <label class="form-check-label">Misura</label>
        </div>
        <div class="form-check form-check-inline">
          <input class="form-check-input" type="checkbox" name="label_show_main" checked>
          <label class="form-check-label">Dim. principale</label>
        </div>
        <div class="form-check form-check-inline">
          <input class="form-check-input" type="checkbox" name="label_show_material" checked>
          <label class="form-check-label">Materiale</label>
        </div>
      </div>

      <div class="col-12"><hr></div>

      <div class="col-md-4">
        <label class="form-label">Cassettiera</label>
        <select class="form-select" name="cabinet_id">
          <option value="">(assegna dopo)</option>
          {% for c in cabinets %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
        </select>
      </div>
      <div class="col-md-4">
        <label class="form-label">Colonna (A..ZZ)</label>
        <input class="form-control" name="col_code" placeholder="es. D">
      </div>
      <div class="col-md-4">
        <label class="form-label">Riga (1..128)</label>
        <input type="number" min="1" max="128" class="form-control" name="row_num">
      </div>

      <div class="col-12 text-end">
        <button class="btn btn-primary">Salva</button>
      </div>
    </div>
  </form>
</div>

<script>
const SUBTYPES = {{ subtypes_by_cat|tojson }};
const RONDELLE_ID = {{ rondelle_id or 'null' }};
const VITI_ID = {{ viti_id or 'null' }};
const TORRETTE_ID = {{ torrette_id or 'null' }};

function populateSubtypes(catId, targetSelId){
  const sel = document.getElementById(targetSelId);
  sel.innerHTML = '<option value="">—</option>';
  if (!catId || !SUBTYPES[catId]) return;
  SUBTYPES[catId].forEach(s=>{
    const o = document.createElement('option');
    o.value = s.id; o.textContent = s.name;
    sel.appendChild(o);
  });
}
function toggleSpecificFields(){
  const catId = parseInt(document.getElementById('catSel').value || 0);
  const isRondelle = (RONDELLE_ID && catId===RONDELLE_ID);
  const isViti = (VITI_ID && catId===VITI_ID);
  const isTorrette = (TORRETTE_ID && catId===TORRETTE_ID);
  document.querySelectorAll('.dim-washer').forEach(el=> el.style.display = isRondelle ? '' : 'none');
  document.getElementById('driveSel').closest('.col-md-4').style.display = isViti ? '' : 'none';
  document.getElementById('standoffSel').closest('.col-md-4').style.display = isTorrette ? '' : 'none';
}
function switchDatalist(stdSelId, inputId){
  const std = document.getElementById(stdSelId).value;
  const inp = document.getElementById(inputId);
  if (std === 'M') inp.setAttribute('list','sizesM');
  else if (std === 'UNC') inp.setAttribute('list','sizesUNC');
  else if (std === 'UNF') inp.setAttribute('list','sizesUNF');
  else inp.removeAttribute('list');
}

document.addEventListener('DOMContentLoaded', ()=>{
  if ($.fn.DataTable) $('#admItemsTable').DataTable({pageLength:25, order:[[1,'asc']]});
  document.getElementById('chkAll')?.addEventListener('change', (e)=>{
    document.querySelectorAll('input[name="item_ids"]').forEach(cb=> cb.checked = e.target.checked);
  });
  toggleSpecificFields();
  document.getElementById('catSel').addEventListener('change', e=>{
    populateSubtypes(parseInt(e.target.value||0), 'subtypeSel');
    toggleSpecificFields();
  });
  document.getElementById('stdSel').addEventListener('change', ()=>switchDatalist('stdSel','sizeInput'));

  // Se arrivo qui da "Nuovo articolo…" sulla griglia,
  // precompilo i campi posizione nel form "Nuovo articolo"
  try {
    const params = new URLSearchParams(window.location.search);
    const cab = params.get('new_for_cab');
    const col = params.get('new_for_col');
    const row = params.get('new_for_row');

    if (cab && col && row) {
      const formNew = document.querySelector('form[action="{{ url_for("add_item") }}"]');
      if (formNew) {
        const cabSel = formNew.querySelector('select[name="cabinet_id"]');
        const colInp = formNew.querySelector('input[name="col_code"]');
        const rowInp = formNew.querySelector('input[name="row_num"]');
        if (cabSel) cabSel.value = cab;
        if (colInp) colInp.value = col;
        if (rowInp) rowInp.value = row;
        cabSel?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  } catch (e) {
    // in caso di browser vecchi senza URLSearchParams, ignoro l'errore
  }
});

</script>
{% endblock %}
"""

ADMIN_EDIT_TMPL = r"""\
{% extends "base.html" %}
{% block content %}
<h3>Modifica articolo #{{ item.id }}</h3>
<form method="post" class="form-section">
  <div class="row g-2">
    <div class="col-md-4">
      <label class="form-label">Categoria</label>
      <select class="form-select" name="category_id" id="catSel" required>
        {% for c in categories %}
          <option value="{{ c.id }}" {{ 'selected' if item.category_id==c.id else '' }}>{{ c.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label">Sottotipo (forma)</label>
      <select class="form-select" name="subtype_id" id="subtypeSel">
        <option value="">—</option>
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label">Standard</label>
      <select class="form-select" name="thread_standard" id="stdSel">
        <option value="M" {{ 'selected' if item.thread_standard=='M' else '' }}>Metrico</option>
        <option value="UNC" {{ 'selected' if item.thread_standard=='UNC' else '' }}>UNC</option>
        <option value="UNF" {{ 'selected' if item.thread_standard=='UNF' else '' }}>UNF</option>
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label">Misura</label>
      <input class="form-control" name="thread_size" id="sizeInput" value="{{ item.thread_size or '' }}" list="sizesM">
      <datalist id="sizesM">{% for s in metric_sizes %}<option value="{{ s }}">{% endfor %}</datalist>
      <datalist id="sizesUNC">{% for s in unc_sizes %}<option value="{{ s }}">{% endfor %}</datalist>
      <datalist id="sizesUNF">{% for s in unf_sizes %}<option value="{{ s }}">{% endfor %}</datalist>
    </div>
    <div class="col-md-4">
      <label class="form-label">Impronta (Viti)</label>
      <select class="form-select" name="drive" id="driveSel">
        <option value="">—</option>
        {% for d in drive_options %}<option value="{{ d }}" {{ 'selected' if item.drive==d else '' }}>{{ d }}</option>{% endfor %}
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label">Configurazione (Torrette)</label>
      <select class="form-select" name="standoff_config" id="standoffSel">
        <option value="">—</option>
        {% for d in standoff_cfgs %}<option value="{{ d }}" {{ 'selected' if item.standoff_config==d else '' }}>{{ d }}</option>{% endfor %}
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label">Dim. principale (mm)</label>
      <input type="number" step="0.01" class="form-control" name="main_size_mm" value="{{ item.main_size_mm or '' }}">
    </div>
    <div class="col-md-2 dim-washer">
      <label class="form-label">Ø interno (mm)</label>
      <input type="number" step="0.01" class="form-control" name="inner_d_mm" value="{{ item.inner_d_mm or '' }}">
    </div>
    <div class="col-md-2 dim-washer">
      <label class="form-label">Spessore (mm)</label>
      <input type="number" step="0.01" class="form-control" name="thickness_mm" value="{{ item.thickness_mm or '' }}">
    </div>

    <div class="col-md-6">
      <label class="form-label">Materiale</label>
      <select class="form-select" name="material_id">
        <option value="">—</option>
        {% for m in materials %}
          <option value="{{ m.id }}" {{ 'selected' if item.material_id==m.id else '' }}>{{ m.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-md-6">
      <label class="form-label">Finitura</label>
      <select class="form-select" name="finish_id">
        <option value="">—</option>
        {% for f in finishes %}
          <option value="{{ f.id }}" {{ 'selected' if item.finish_id==f.id else '' }}>{{ f.name }}</option>
        {% endfor %}
      </select>
    </div>

    <div class="col-md-12">
      <label class="form-label">Descrizione (opz.)</label>
      <input type="text" class="form-control" name="description" value="{{ item.description or '' }}">
    </div>

    <div class="col-md-4">
      <label class="form-label">Quantità</label>
      <input type="number" min="0" step="1" class="form-control" name="quantity" value="{{ item.quantity }}">
    </div>

    <div class="col-md-8">
      <label class="form-label d-block">Campi in etichetta</label>
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" name="label_show_category" {{ 'checked' if item.label_show_category else '' }}>
        <label class="form-check-label">Categoria</label>
      </div>
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" name="label_show_subtype" {{ 'checked' if item.label_show_subtype else '' }}>
        <label class="form-check-label">Sottotipo</label>
      </div>
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" name="label_show_measure" {{ 'checked' if item.label_show_measure else '' }}>
        <label class="form-check-label">Misura</label>
      </div>
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" name="label_show_main" {{ 'checked' if item.label_show_main else '' }}>
        <label class="form-check-label">Dim. principale</label>
      </div>
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" name="label_show_material" {{ 'checked' if item.label_show_material else '' }}>
        <label class="form-check-label">Materiale</label>
      </div>
    </div>

    <div class="col-12"><hr></div>

    <div class="col-md-3">
      <label class="form-label">Posizione attuale</label>
      <input class="form-control" value="{{ current_position or '(non assegnata)' }}" readonly>
    </div>

    <div class="col-md-3">
      <label class="form-label">Cassettiera</label>
      <select class="form-select" id="cabinet_id" name="cabinet_id">
        <option value="">(scegli)</option>
        {% for c in cabinets %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
      </select>
    </div>
    <div class="col-md-2">
      <label class="form-label">Colonna</label>
      <input class="form-control" id="col_code" name="col_code" placeholder="es. D">
    </div>
    <div class="col-md-2">
      <label class="form-label">Riga</label>
      <input type="number" min="1" max="128" class="form-control" id="row_num" name="row_num">
    </div>
    <div class="col-md-2 d-flex align-items-end">
      <button formaction="{{ url_for('set_position', item_id=item.id) }}" formmethod="post" class="btn btn-outline-primary w-100">Imposta</button>
    </div>
    <div class="col-md-3 d-flex align-items-end">
      <button type="button" id="btnSuggest" class="btn btn-outline-secondary w-100">Suggerisci</button>
    </div>
    <div class="col-md-3 d-flex align-items-end">
      <form method="post" action="{{ url_for('clear_position', item_id=item.id) }}" onsubmit="return confirm('Rimuovere posizione?')">
        <button class="btn btn-outline-danger w-100">Rimuovi</button>
      </form>
    </div>

    <div class="col-12 text-end mt-3">
      <button class="btn btn-primary">Salva modifiche</button>
      <a href="{{ url_for('admin_items') }}" class="btn btn-secondary">Chiudi</a>
    </div>
  </div>
</form>

<script>
const SUBTYPES = {{ subtypes_by_cat|tojson }};
const RONDELLE_ID = {{ rondelle_id or 'null' }};
const VITI_ID = {{ viti_id or 'null' }};
const TORRETTE_ID = {{ torrette_id or 'null' }};

function populateSubtypes(catId){
  const sel = document.getElementById('subtypeSel');
  sel.innerHTML = '<option value="">—</option>';
  if (!catId || !SUBTYPES[catId]) return;
  SUBTYPES[catId].forEach(s=>{
    const o = document.createElement('option');
    o.value = s.id; o.textContent = s.name;
    if ({{ item.subtype_id or 'null' }} === s.id) o.selected = true;
    sel.appendChild(o);
  });
}
function toggleSpecificFields(){
  const catId = parseInt(document.getElementById('catSel').value || 0);
  const isRondelle = (RONDELLE_ID && catId===RONDELLE_ID);
  const isViti = (VITI_ID && catId===VITI_ID);
  const isTorrette = (TORRETTE_ID && catId===TORRETTE_ID);
  document.querySelectorAll('.dim-washer').forEach(el=> el.style.display = isRondelle ? '' : 'none');
  document.getElementById('driveSel').closest('.col-md-4').style.display = isViti ? '' : 'none';
  document.getElementById('standoffSel').closest('.col-md-4').style.display = isTorrette ? '' : 'none';
}
function switchDatalist(){
  const std = document.getElementById('stdSel').value;
  const inp = document.getElementById('sizeInput');
  if (std === 'M') inp.setAttribute('list','sizesM');
  else if (std === 'UNC') inp.setAttribute('list','sizesUNC');
  else if (std === 'UNF') inp.setAttribute('list','sizesUNF');
  else inp.removeAttribute('list');
}

document.addEventListener('DOMContentLoaded', ()=>{
  populateSubtypes({{ item.category_id }});
  toggleSpecificFields();
  switchDatalist();
  document.getElementById('catSel').addEventListener('change', ()=>{ populateSubtypes(parseInt(document.getElementById('catSel').value||0)); toggleSpecificFields(); });
  document.getElementById('stdSel').addEventListener('change', switchDatalist);
  document.getElementById('btnSuggest').addEventListener('click', async ()=>{
    const r = await fetch('{{ url_for("suggest_position", item_id=item.id) }}');
    const j = await r.json();
    if (!j.ok) { alert(j.error||'Nessuna posizione trovata'); return; }
    document.getElementById('cabinet_id').value = j.cabinet_id;
    document.getElementById('col_code').value  = j.col_code;
    document.getElementById('row_num').value   = j.row_num;
  });
});
</script>
{% endblock %}
"""

ADMIN_CATS_TMPL = r"""\
{% extends "base.html" %}
{% block content %}
<h3>Categorie, sottotipi, materiali e finiture</h3>

<div class="row">
  <div class="col-lg-6">
    <div class="form-section">
      <h5 class="mb-2">Categorie</h5>
      <table class="table table-striped" id="tblCats">
        <thead>
          <tr><th>ID</th><th>Nome</th><th>Colore</th><th>Azione</th></tr>
        </thead>
        <tbody>
          {% for c in categories %}
          <tr>
            <td>{{ c.id }}</td>
            <td>
              <form method="post" action="{{ url_for('update_category', cat_id=c.id) }}" class="row g-2 align-items-center">
                <div class="col-md-5">
                  <input class="form-control" name="name" value="{{ c.name }}">
                </div>
                <div class="col-md-3">
                  <input type="color" class="form-control form-control-color" name="color" value="{{ c.color }}">
                </div>
                <div class="col-md-4">
                  <button class="btn btn-sm btn-primary">Salva</button>
                  <button formaction="{{ url_for('delete_category', cat_id=c.id) }}" formmethod="post" class="btn btn-sm btn-outline-danger" onclick="return confirm('Eliminare categoria?')">Elimina</button>
                </div>
              </form>
            </td>
            <td><span class="badge-color" style="background:{{ c.color }}"></span>{{ c.color }}</td>
            <td></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <div class="col-lg-6">
    <div class="form-section">
      <h5 class="mb-2">Nuova categoria</h5>
      <form method="post" action="{{ url_for('add_category') }}" class="row g-2">
        <div class="col-md-6">
          <input class="form-control" name="name" placeholder="Nome categoria">
        </div>
        <div class="col-md-3">
          <input type="color" class="form-control form-control-color" name="color" value="#607D8B">
        </div>
        <div class="col-md-3">
          <button class="btn btn-primary w-100">Aggiungi</button>
        </div>
      </form>
    </div>
  </div>
</div>

<hr class="my-3">

<div class="form-section mb-3">
  <h5 class="mb-2">Sottotipi (forme)</h5>

  <form method="post" action="{{ url_for('add_subtype') }}" class="row g-2 mb-2">
    <div class="col-md-4">
      <select class="form-select" name="category_id" required>
        <option value="">Categoria...</option>
        {% for c in categories %}
          <option value="{{ c.id }}">{{ c.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-md-5">
      <input class="form-control" name="name" placeholder="Nome sottotipo (es. Testa cilindrica)">
    </div>
    <div class="col-md-3">
      <button class="btn btn-primary w-100">Aggiungi</button>
    </div>
  </form>

  <table class="table table-sm table-striped" id="tblSubtypes">
    <thead>
      <tr><th>ID</th><th>Categoria</th><th>Nome</th><th>Azione</th></tr>
    </thead>
    <tbody>
      {% for st, c in subtypes %}
      <tr>
        <td>{{ st.id }}</td>
        <td colspan="3">
          <form method="post" action="{{ url_for('update_subtype', st_id=st.id) }}" class="row g-2 align-items-center">
            <div class="col-md-4">
              <select class="form-select" name="category_id">
                {% for cat in categories %}
                  <option value="{{ cat.id }}" {{ 'selected' if cat.id == st.category_id else '' }}>{{ cat.name }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-md-4">
              <input class="form-control" name="name" value="{{ st.name }}">
            </div>
            <div class="col-md-4">
              <button class="btn btn-sm btn-primary">Salva</button>
              <button formaction="{{ url_for('delete_subtype', st_id=st.id) }}" formmethod="post" class="btn btn-sm btn-outline-danger" onclick="return confirm('Eliminare sottotipo?')">Elimina</button>
            </div>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<div class="row">
  <div class="col-lg-6">
    <div class="form-section mb-3">
      <h5 class="mb-2">Materiali</h5>
      <table class="table table-striped" id="tblMaterials">
        <thead>
          <tr><th>ID</th><th>Nome</th><th>Azione</th></tr>
        </thead>
        <tbody>
          {% for m in materials %}
          <tr>
            <td>{{ m.id }}</td>
            <td>
              <form method="post" action="{{ url_for('update_material', mat_id=m.id) }}" class="row g-2 align-items-center">
                <div class="col-md-8">
                  <input class="form-control" name="name" value="{{ m.name }}">
                </div>
                <div class="col-md-4">
                  <button class="btn btn-sm btn-primary">Salva</button>
                  <button formaction="{{ url_for('delete_material', mat_id=m.id) }}" formmethod="post" class="btn btn-sm btn-outline-danger" onclick="return confirm('Eliminare materiale?')">Elimina</button>
                </div>
              </form>
            </td>
            <td></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="form-section">
      <h5 class="mb-2">Nuovo materiale</h5>
      <form method="post" action="{{ url_for('add_material') }}" class="row g-2">
        <div class="col-md-8">
          <input class="form-control" name="name" placeholder="Descrizione materiale">
        </div>
        <div class="col-md-4">
          <button class="btn btn-primary w-100">Aggiungi</button>
        </div>
      </form>
    </div>
  </div>

  <div class="col-lg-6">
    <div class="form-section mb-3">
      <h5 class="mb-2">Finiture</h5>
      <table class="table table-striped" id="tblFinishes">
        <thead>
          <tr><th>ID</th><th>Nome</th><th>Azione</th></tr>
        </thead>
        <tbody>
          {% for f in finishes %}
          <tr>
            <td>{{ f.id }}</td>
            <td>
              <form method="post" action="{{ url_for('update_finish', fin_id=f.id) }}" class="row g-2 align-items-center">
                <div class="col-md-8">
                  <input class="form-control" name="name" value="{{ f.name }}">
                </div>
                <div class="col-md-4">
                  <button class="btn btn-sm btn-primary">Salva</button>
                  <button formaction="{{ url_for('delete_finish', fin_id=f.id) }}" formmethod="post" class="btn btn-sm btn-outline-danger" onclick="return confirm('Eliminare finitura?')">Elimina</button>
                </div>
              </form>
            </td>
            <td></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="form-section">
      <h5 class="mb-2">Nuova finitura</h5>
      <form method="post" action="{{ url_for('add_finish') }}" class="row g-2">
        <div class="col-md-8">
          <input class="form-control" name="name" placeholder="Descrizione finitura">
        </div>
        <div class="col-md-4">
          <button class="btn btn-primary w-100">Aggiungi</button>
        </div>
      </form>
    </div>
  </div>
</div>

<script>
$(function(){
  if ($.fn.DataTable) {
    $('#tblCats').DataTable({pageLength:50, order:[[0,'asc']]});
    $('#tblSubtypes').DataTable({pageLength:50, order:[[0,'asc']]});
    $('#tblMaterials').DataTable({pageLength:50, order:[[0,'asc']]});
    $('#tblFinishes').DataTable({pageLength:50, order:[[0,'asc']]});
  }
});
</script>
{% endblock %}
"""

ADMIN_CONFIG_TMPL = r"""\
{% extends "base.html" %}
{% block content %}
<h3>Configurazione</h3>
<div class="row">
  <div class="col-lg-4">
    <div class="form-section mb-3">
      <h5>Stampa etichette & QR</h5>
      <form method="post" action="{{ url_for('update_settings') }}" class="row g-2">
        <div class="col-6"><label class="form-label">Larghezza (mm)</label><input type="number" step="0.1" class="form-control" name="label_w_mm" value="{{ settings.label_w_mm }}"></div>
        <div class="col-6"><label class="form-label">Altezza (mm)</label><input type="number" step="0.1" class="form-control" name="label_h_mm" value="{{ settings.label_h_mm }}"></div>
        <div class="col-6"><label class="form-label">Margini top/bottom (mm)</label><input type="number" step="0.1" class="form-control" name="margin_tb_mm" value="{{ settings.margin_tb_mm }}"></div>
        <div class="col-6"><label class="form-label">Margini sx/dx (mm)</label><input type="number" step="0.1" class="form-control" name="margin_lr_mm" value="{{ settings.margin_lr_mm }}"></div>
        <div class="col-6"><label class="form-label">Spazio tra etichette (mm)</label><input type="number" step="0.1" class="form-control" name="gap_mm" value="{{ settings.gap_mm }}"></div>
        <div class="col-6">
          <label class="form-label">Orientamento</label>
          <select class="form-select" name="orientation_landscape">
            <option value="1" {{ 'selected' if settings.orientation_landscape else '' }}>Orizzontale</option>
            <option value=""  {{ '' if settings.orientation_landscape else 'selected' }}>Verticale</option>
          </select>
        </div>
        <div class="col-6">
          <label class="form-label">QR attivo di default</label>
          <select class="form-select" name="qr_default">
            <option value="1" {{ 'selected' if settings.qr_default else '' }}>Sì</option>
            <option value="">No</option>
          </select>
        </div>
        <div class="col-12">
          <label class="form-label">QR Base URL (opz.)</label>
          <input class="form-control" name="qr_base_url" placeholder="https://magazzino.local" value="{{ settings.qr_base_url or '' }}">
          <small class="text-muted">Se vuoto, uso l'host corrente.</small>
        </div>
        <div class="col-12 text-end mt-2"><button class="btn btn-primary">Salva impostazioni</button></div>
      </form>
    </div>
  </div>

  <div class="col-lg-8">
    <div class="form-section mb-3">
      <h5>Ubicazioni</h5>
      <form method="post" action="{{ url_for('add_location') }}" class="row g-2 mb-2">
        <div class="col-md-9"><input class="form-control" name="name" placeholder="Nome ubicazione"></div>
        <div class="col-md-3"><button class="btn btn-primary w-100">Aggiungi</button></div>
      </form>
      <table class="table table-sm table-striped">
        <thead><tr><th>ID</th><th>Nome</th><th>Azione</th></tr></thead>
        <tbody>
          {% for l in locations %}
          <tr>
            <td>{{ l.id }}</td>
            <td>
              <form method="post" action="{{ url_for('update_location', loc_id=l.id) }}" class="row g-2">
                <div class="col-md-9"><input class="form-control" name="name" value="{{ l.name }}"></div>
                <div class="col-md-3">
                  <button class="btn btn-sm btn-primary">Salva</button>
                  <button formaction="{{ url_for('delete_location', loc_id=l.id) }}" formmethod="post" class="btn btn-sm btn-outline-danger" onclick="return confirm('Eliminare ubicazione?')">Elimina</button>
                </div>
              </form>
            </td>
            <td></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="form-section">
      <h5>Cassettiere</h5>
      <form method="post" action="{{ url_for('add_cabinet') }}" class="row g-2 mb-2">
        <div class="col-md-4">
          <select class="form-select" name="location_id" required>
            {% for l in locations %}
              <option value="{{ l.id }}">{{ l.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-4"><input class="form-control" name="name" placeholder="Nome cassettiera"></div>
        <div class="col-md-2"><input type="number" min="1" max="128" class="form-control" name="rows_max" value="128"></div>
        <div class="col-md-1"><input class="form-control" name="cols_max" placeholder="ZZ" value="ZZ" maxlength="2"></div>
        <div class="col-md-1"><input type="number" min="1" class="form-control" name="compartments_per_slot" value="6"></div>
        <div class="col-md-12 text-end"><button class="btn btn-primary">Aggiungi</button></div>
      </form>

      <table class="table table-striped">
        <thead><tr><th>ID</th><th>Ubicazione</th><th>Nome</th><th>Righe</th><th>Colonne</th><th>Comp.</th><th>Azione</th></tr></thead>
        <tbody>
          {% for c,l in cabinets %}
          <tr>
            <td>{{ c.id }}</td>
            <td>{{ l.name }}</td>
            <td colspan="5">
              <form method="post" action="{{ url_for('update_cabinet', cab_id=c.id) }}" class="row g-2">
                <div class="col-md-4"><input class="form-control" name="name" value="{{ c.name }}"></div>
                <div class="col-md-2"><input type="number" min="1" max="128" class="form-control" name="rows_max" value="{{ c.rows_max }}"></div>
                <div class="col-md-2"><input class="form-control" name="cols_max" value="{{ c.cols_max }}" maxlength="2"></div>
                <div class="col-md-2"><input type="number" min="1" class="form-control" name="compartments_per_slot" value="{{ c.compartments_per_slot }}"></div>
                <div class="col-md-2">
                  <button class="btn btn-sm btn-primary w-100">Salva</button>
                  <button formaction="{{ url_for('delete_cabinet', cab_id=c.id) }}" formmethod="post" class="btn btn-sm btn-outline-danger w-100 mt-1" onclick="return confirm('Eliminare cassettiera?')">Elimina</button>
                </div>
              </form>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <hr>
      <h5>Sposta / Scambia cassetti</h5>
      <form method="post" action="{{ url_for('move_slot') }}" class="row g-2">
        <div class="col-md-3">
          <label class="form-label">Origine</label>
          <select class="form-select" name="cabinet_from">
            {% for c,l in cabinets %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
          </select>
        </div>
        <div class="col-md-2"><label class="form-label">Col</label><input class="form-control" name="col_from"></div>
        <div class="col-md-2"><label class="form-label">Riga</label><input type="number" class="form-control" name="row_from"></div>

        <div class="col-md-3">
          <label class="form-label">Destinazione</label>
          <select class="form-select" name="cabinet_to">
            {% for c,l in cabinets %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
          </select>
        </div>
        <div class="col-md-2"><label class="form-label">Col</label><input class="form-control" name="col_to"></div>
        <div class="col-md-2"><label class="form-label">Riga</label><input type="number" class="form-control" name="row_to"></div>

        <div class="col-md-2"><label class="form-label"> </label><div class="form-check"><input class="form-check-input" type="checkbox" name="swap" id="swap"> <label class="form-check-label" for="swap">Scambia</label></div></div>
        <div class="col-md-2 align-self-end"><button class="btn btn-primary w-100">Esegui</button></div>
      </form>
    </div>
  </div>
</div>
{% endblock %}
"""

ADMIN_TOPLACE_TMPL = r"""\
{% extends "base.html" %}
{% block content %}
<h3>Articoli da posizionare</h3>
<div class="form-section">
  <table class="table table-striped" id="tbl">
    <thead><tr><th>ID</th><th>Categoria</th><th>Descrizione</th><th>Misura</th><th>Azioni</th></tr></thead>
    <tbody>
      {% for it in items %}
      <tr>
        <td>{{ it.id }}</td>
        <td>{% if it.category %}<span class="badge-color" style="background:{{ it.category.color }}"></span>{{ it.category.name }}{% endif %}</td>
        <td>{{ compose_caption(it) }}</td>
        <td>{{ it.thread_size or '' }}</td>
        <td class="text-nowrap">
          <a href="{{ url_for('edit_item', item_id=it.id) }}" class="btn btn-sm btn-outline-primary">Modifica</a>
          <a href="{{ url_for('admin_items') }}#grid" class="btn btn-sm btn-outline-secondary">Vai alla griglia</a>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
<script>$(function(){ if ($.fn.DataTable) $('#tbl').DataTable({pageLength:50, order:[[1,'asc']]});});</script>
{% endblock %}
"""

# Registra template
app.jinja_loader = DictLoader({
    "base.html": BASE_TMPL,
    "index.html": INDEX_TMPL,
    "login.html": LOGIN_TMPL,
    "admin/dashboard.html": ADMIN_DASH_TMPL,
    "admin/edit_item.html": ADMIN_EDIT_TMPL,
    "admin/categories.html": ADMIN_CATS_TMPL,
    "admin/config.html": ADMIN_CONFIG_TMPL,
    "admin/to_place.html": ADMIN_TOPLACE_TMPL,
})

# ===================== INIT / MIGRAZIONI / SEED =====================
def lite_migrations():
    con = sqlite3.connect(db_path); cur = con.cursor()
    # add columns if existing DB
    cur.execute("PRAGMA table_info(item)"); cols = {row[1] for row in cur.fetchall()}
    alters = []
    if "main_size_mm" not in cols:        alters.append("ALTER TABLE item ADD COLUMN main_size_mm FLOAT")
    if "label_show_measure" not in cols:  alters.append("ALTER TABLE item ADD COLUMN label_show_measure BOOLEAN NOT NULL DEFAULT 1")
    if "label_show_main" not in cols:     alters.append("ALTER TABLE item ADD COLUMN label_show_main BOOLEAN NOT NULL DEFAULT 1")
    if "inner_d_mm" not in cols:          alters.append("ALTER TABLE item ADD COLUMN inner_d_mm FLOAT")
    if "thickness_mm" not in cols:        alters.append("ALTER TABLE item ADD COLUMN thickness_mm FLOAT")
    if "length_mm" not in cols:           alters.append("ALTER TABLE item ADD COLUMN length_mm FLOAT")
    if "outer_d_mm" not in cols:          alters.append("ALTER TABLE item ADD COLUMN outer_d_mm FLOAT")
    if "label_show_thread" not in cols:   alters.append("ALTER TABLE item ADD COLUMN label_show_thread BOOLEAN NOT NULL DEFAULT 1")
    if "drive" not in cols:               alters.append("ALTER TABLE item ADD COLUMN drive TEXT")
    if "standoff_config" not in cols:     alters.append("ALTER TABLE item ADD COLUMN standoff_config TEXT")
    # settings table
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
    if not cur.fetchone():
        cur.execute("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                label_w_mm FLOAT NOT NULL,
                label_h_mm FLOAT NOT NULL,
                margin_tb_mm FLOAT NOT NULL,
                margin_lr_mm FLOAT NOT NULL,
                gap_mm FLOAT NOT NULL,
                orientation_landscape BOOLEAN NOT NULL,
                qr_default BOOLEAN NOT NULL,
                qr_base_url TEXT
            )
        """)
    con.commit()
    # drop legacy columns if exist (short_code, pair_code) — only schema clean if empty db; otherwise ignore
    # (nessuna drop distruttiva automatica per evitare perdita dati involontaria)
    for sql in alters: cur.execute(sql)
    con.commit(); con.close()

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
        lite_migrations()
        seed_if_empty_or_missing()

# ===================== MAIN =====================
if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0")
