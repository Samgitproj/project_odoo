# apps/voorraad.py
# [SECTION: Imports]
import sys, csv, logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QFileDialog, QMessageBox, QApplication,
    QWidget, QCheckBox, QPushButton, QGridLayout, QHBoxLayout
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor, QBrush
from PyQt6.QtCore import Qt

from gui.MainWindow import Ui_MainWindow  # zorg dat gui/MainWindow.py bestaat via UI→PY

# [END: Imports]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("log.txt", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)

DATA_DIR = Path("resources")
DEFAULT_CSV = DATA_DIR / "products.csv"
DEFAULT_XLSX = DATA_DIR / "products.xlsx"
MIN_STOCK = 5

# Herkenbare kernkolommen (mapping NL/EN) voor zoeken/prijs/voorraad
PREF_COLS: Dict[str, List[str]] = {
    "id": ["id", "ID"],
    "name": ["name", "Naam", "Productnaam"],
    "default_code": ["default_code", "Interne referentie", "Nummer"],
    "barcode": ["barcode", "Barcode"],
    "list_price": ["list_price", "Verkoopprijs"],
    "standard_price": ["standard_price", "Kostprijs"],
    "qty_available": ["qty_available", "Aantal op voorraad", "Aanwezige voorraad"],
    "virtual_available": ["virtual_available", "Beschikbaar aantal", "Virtuele voorraad"],
}

# Volgorde van toonbare kolommen (GUI-checkboxes volgen deze volgorde)
DISPLAY_ORDER = [
    "Naam", "Kan verkocht worden", "Kan gekocht worden", "Productsoort",
    "Facturatiebeleid", "Verkoopprijs", "Verkoop BTW", "Kostprijs",
    "Productcategorie", "Interne referentie", "Barcode", "Maateenheid",
    "Inkoop maateenheid/Maateenheid", "Inkoop maateenheid/ID",
    "Leveranciers", "Inkoop BTW", "Controlebeleid", "Routes",
    "Verantwoordelijke", "Aanwezige voorraad", "Virtuele voorraad",
]

ROUTES_FIELD_CANDIDATES = ["Routes"]  # pas aan als kolomnaam anders is

# [FUNC: first_present]
def first_present(cands: List[str], header: List[str]) -> Optional[str]:
    for c in cands:
        if c in header:
            return c
    return None

# [END: first_present]
# [FUNC: try_load_xlsx]
def try_load_xlsx(path: Path) -> List[Dict[str, Any]]:
    import openpyxl  # requires: pip install openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    data = []
    for r in rows[1:]:
        rec = {}
        for i, h in enumerate(header):
            rec[h] = r[i]
        data.append(rec)
    logging.info(f"XLSX geladen: {path} rijen={len(data)}")
    return data

# [END: try_load_xlsx]
# [FUNC: read_csv_smart]
def read_csv_smart(path: Path) -> List[Dict[str, Any]]:
    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                sample = f.read(4096); f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=[",",";","|","\t"])
                    delim = dialect.delimiter
                except Exception:
                    delim = ";"
                rows = list(csv.DictReader(f, delimiter=delim))
                logging.info(f"CSV geladen met encoding={enc}, delimiter='{delim}', rijen={len(rows)}")
                return rows
        except UnicodeDecodeError:
            continue
    with path.open("r", encoding="cp1252", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
        logging.warning(f"CSV geladen met cp1252 (met vervangtekens), rijen={len(rows)}")
        return rows

# [END: read_csv_smart]
# [FUNC: load_any_products]
def load_any_products(path_csv: Path, path_xlsx: Path) -> List[Dict[str, Any]]:
    if path_csv.exists():
        logging.info(f"CSV laden: {path_csv}")
        return read_csv_smart(path_csv)
    if path_xlsx.exists():
        logging.info(f"XLSX laden: {path_xlsx}")
        return try_load_xlsx(path_xlsx)
    raise FileNotFoundError(f"Geen productbestand in {DATA_DIR}")

# [END: load_any_products]
# [FUNC: normalize_number]
def normalize_number(val) -> float:
    if val is None: return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace("€","").replace(" ","").replace("\xa0","").replace(",",".").replace("%","")
    try: return float(s)
    except: return 0.0

# [END: normalize_number]
# [FUNC: format_bool]
def format_bool(v) -> str:
    s = str(v).strip().lower()
    if s in {"waar","true","1","yes","ja"}: return "✓"
    if s in {"onwaar","false","0","no","nee"}: return "✗"
    return str(v)

# [END: format_bool]
# [FUNC: _split_routes]
def _split_routes(val: str) -> List[str]:
    """Splits een routestring in losse items. Werkt ook als Odoo 1 route per rij geeft."""
    if not val:
        return []
    txt = str(val).strip()
    # meeste exports hebben 1 per rij; soms meerdere met ; of | of ,
    if any(sep in txt for sep in [";", "|", ","]):
        parts = []
        for sep in [";", "|", ","]:
            if sep in txt:
                parts = [p.strip() for p in txt.split(sep)]
                break
    else:
        parts = [txt]
    # uniq + volgorde behouden
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p); out.append(p)
    return out

# [END: _split_routes]
# [CLASS: Window]
class Window(QMainWindow):
# [FUNC: __init__]
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self._all_rows: List[Dict[str, Any]] = []
        self._header_map: Dict[str, str] = {}
        self._low_stock_mode = False

        # kolomselector-state
        self._col_container: Optional[QWidget] = None
        self._col_checks: Dict[str, QCheckBox] = {}
        self._visible_cols: List[str] = []   # actuele selectie
        self._default_cols: List[str] = []   # reset-doel

        # dynamische route-kolommen (Route 1..N)
        self._route_cols: List[str] = []

        # tabelmodel
        self.model = QStandardItemModel(self)
        self.ui.tableProducts.setModel(self.model)
        self.ui.tableProducts.setSortingEnabled(True)

        # events
        self.ui.lineSearch.textChanged.connect(self.apply_filters)
        self.ui.btnLowStock.clicked.connect(self.toggle_low_stock)
        self.ui.btnCompare.clicked.connect(self.compare_prices)

        # initial load
        self.load_products()
        # kolom-selector opbouwen obv data
        self._build_column_selector()
        self.apply_filters()

# [END: __init__]
# [FUNC: load_products]
    def load_products(self):
        try:
            rows = load_any_products(DEFAULT_CSV, DEFAULT_XLSX)
        except Exception as e:
            QMessageBox.critical(self, "Laden mislukt", str(e))
            rows = []
        if not rows:
            self._all_rows = []; self.refresh_table([]); return

        header = list(rows[0].keys())
        hmap: Dict[str, str] = {}
        for key, cands in PREF_COLS.items():
            found = first_present(cands, header)
            if found: hmap[key] = found
        self._header_map = hmap

        cleaned: List[Dict[str, Any]] = []
        for r in rows:
            rec = dict(r)  # originele CSV-kolommen + we voegen _-keys toe
            id_val = r.get(hmap.get("id",""), None) or r.get(hmap.get("default_code",""), None) or r.get(hmap.get("name",""), "")
            rec["_id"] = id_val
            rec["_name"] = r.get(hmap.get("name",""), "")
            rec["_sku"] = r.get(hmap.get("default_code",""), "")
            rec["_barcode"] = r.get(hmap.get("barcode",""), "")
            rec["_price"] = normalize_number(r.get(hmap.get("list_price",""), 0))
            rec["_cost"]  = normalize_number(r.get(hmap.get("standard_price",""), 0))
            rec["_qty"]   = normalize_number(r.get(hmap.get("qty_available",""), 0))
            rec["_qty_virtual"] = normalize_number(r.get(hmap.get("virtual_available",""), 0))
            cleaned.append(rec)

        # voeg samen per product en explode de Routes-kolom naar Route 1..N
        self._all_rows = self._group_and_explode_routes(cleaned)
        logging.info(f"Ingeladen rijen (na groeperen): {len(self._all_rows)}")

# [END: load_products]
# [FUNC: _group_and_explode_routes]
    def _group_and_explode_routes(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Vouw vervolgregels samen per product en zet Routes naast elkaar als Route 1..N."""
        if not rows:
            self._route_cols = []
            return rows

        header = list(rows[0].keys())
        routes_col = next((c for c in ROUTES_FIELD_CANDIDATES if c in header), None)
        if not routes_col:
            # geen Routes-kolom aanwezig
            self._route_cols = []
            return rows

        def key_of(r: Dict[str, Any]) -> str:
            return (str(r.get("_id") or "").strip()
                    or str(r.get("_sku") or "").strip()
                    or str(r.get("_name") or "").strip())

        # groepeer basisrij + verzamel routes
        groups: Dict[str, Dict[str, Any]] = {}
        routes_map: Dict[str, List[str]] = {}
        for r in rows:
            k = key_of(r)
            if not k:
                # sla rijen zonder sleutel over
                continue
            groups.setdefault(k, dict(r))  # eerste rij als basis
            vals = _split_routes(str(r.get(routes_col) or ""))
            if vals:
                acc = routes_map.setdefault(k, [])
                for v in vals:
                    if v not in acc:
                        acc.append(v)

        # bepaal max aantal routes over alle producten
        max_routes = max((len(v) for v in routes_map.values()), default=0)
        # NB: jij gaf aan dat er 4 elementen zijn -> dit vangt dat automatisch af.
        self._route_cols = [f"Route {i}" for i in range(1, max_routes + 1)]

        # bouw eindrijen: basis + Route 1..N (verwijder originele 'Routes')
        out: List[Dict[str, Any]] = []
        for k, base in groups.items():
            routes = routes_map.get(k, [])
            row = dict(base)
            row.pop(routes_col, None)  # oorspronkelijke kolom weghalen
            for i in range(max_routes):
                row[f"Route {i+1}"] = routes[i] if i < len(routes) else ""
            out.append(row)

        return out

# [END: _group_and_explode_routes]
# [FUNC: _build_column_selector]
    def _build_column_selector(self):
        # verwijder bestaande selector (bij herladen)
        if self._col_container is not None:
            self.ui.centralwidget.layout().removeWidget(self._col_container)
            self._col_container.deleteLater()
            self._col_container = None
            self._col_checks.clear()

        # bepaal welke kolommen beschikbaar zijn in de data
        base = (self._all_rows[0] if self._all_rows else {})
        # eerst vaste volgorde
        available = [col for col in DISPLAY_ORDER if col in base]
        # dan dynamische Route-kolommen erachter
        for rc in self._route_cols:
            if rc in base and rc not in available:
                available.append(rc)

        # standaardselectie = alle beschikbare (zoals eerder gedrag)
        self._default_cols = available[:]
        # behoud bestaande selectie; anders start met default
        self._visible_cols = self._visible_cols or available[:]

        # UI opbouwen
        container = QWidget(self)
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        # checkboxes in 3 kolommen
        cols_per_row = 3
        for i, name in enumerate(available):
            cb = QCheckBox(name, container)
            cb.setChecked(name in self._visible_cols)
            self._col_checks[name] = cb
            row = i // cols_per_row
            col = i % cols_per_row
            grid.addWidget(cb, row, col)

        # knoppen rechts: Alles / Geen / Reset / Toepassen
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)
        btn_all = QPushButton("Alles", container)
        btn_none = QPushButton("Geen", container)
        btn_reset = QPushButton("Reset", container)
        btn_apply = QPushButton("Toepassen", container)
        btn_bar.addWidget(btn_all)
        btn_bar.addWidget(btn_none)
        btn_bar.addWidget(btn_reset)
        btn_bar.addStretch(1)
        btn_bar.addWidget(btn_apply)

        last_row = (len(available) - 1) // cols_per_row + 1
        grid.addLayout(btn_bar, last_row, 0, 1, cols_per_row)

        # events
        btn_all.clicked.connect(lambda: self._set_all_checks(True))
        btn_none.clicked.connect(lambda: self._set_all_checks(False))
        btn_reset.clicked.connect(self._reset_checks)
        btn_apply.clicked.connect(self._apply_checks)

        # voeg onder de topBar toe (index 1 in de hoofd-VBox)
        self.ui.centralwidget.layout().insertWidget(1, container)
        self._col_container = container

# [END: _build_column_selector]
# [FUNC: _set_all_checks]
    def _set_all_checks(self, state: bool):
        for cb in self._col_checks.values():
            cb.setChecked(state)

# [END: _set_all_checks]
# [FUNC: _reset_checks]
    def _reset_checks(self):
        for name, cb in self._col_checks.items():
            cb.setChecked(name in self._default_cols)

# [END: _reset_checks]
# [FUNC: _apply_checks]
    def _apply_checks(self):
        # lees vinkjes uit en ververs tabel
        self._visible_cols = [name for name, cb in self._col_checks.items() if cb.isChecked()]
        self.apply_filters()

# [END: _apply_checks]
# [FUNC: apply_filters]
    def apply_filters(self):
        q = self.ui.lineSearch.text().strip().lower()
        rows = self._all_rows

        if q:
            rows = [
                r for r in rows
                if q in str(r.get("_name", "")).lower()
                or q in str(r.get("_sku", "")).lower()
                or q in str(r.get("_barcode", "")).lower()
            ]
        if self._low_stock_mode:
            rows = [r for r in rows if r.get("_qty", 0) < MIN_STOCK]

        self.refresh_table(rows)

# [END: apply_filters]
# [FUNC: refresh_table]
    def refresh_table(self, rows: List[Dict[str, Any]]):
        # aanwezige kolommen in data
        base = rows[0] if rows else (self._all_rows[0] if self._all_rows else {})
        # eerst vaste volgorde
        available = [col for col in DISPLAY_ORDER if col in base]
        # dan dynamische Route-kolommen erbij
        for rc in self._route_cols:
            if rc in base and rc not in available:
                available.append(rc)

        # te tonen kolommen = selectie (of default als leeg)
        present = [c for c in self._visible_cols if c in available] or available

        headers = present + ["Nieuwe prijs", "Δ prijs"]

        self.model.clear()
        self.model.setHorizontalHeaderLabels(headers)

        for r in rows:
            items: List[QStandardItem] = []
            for col in present:
                val = r.get(col, "")
                if col in ("Kan verkocht worden", "Kan gekocht worden"):
                    val = format_bool(val)
                if col in ("Verkoopprijs", "Kostprijs", "Aanwezige voorraad", "Virtuele voorraad"):
                    try:
                        num = normalize_number(r.get(col))
                        val = f"{num:.2f}"
                    except Exception:
                        pass
                items.append(QStandardItem("" if val is None else str(val)))

            new_price = r.get("_new_price")
            delta = None
            if new_price is not None:
                delta = float(new_price) - float(r.get("_price", 0))
            item_new = QStandardItem("" if new_price is None else f"{new_price:.2f}")
            item_delta = QStandardItem("" if delta is None else f"{delta:+.2f}")
            if delta is not None and delta != 0:
                brush = QBrush(QColor("red" if delta > 0 else "green"))
                item_delta.setData(brush, Qt.ItemDataRole.BackgroundRole)

            for it in items + [item_new, item_delta]:
                it.setEditable(False)
            self.model.appendRow(items + [item_new, item_delta])

        total = len(rows)
        avg_price = (sum(float(r.get("_price", 0)) for r in rows) / max(1, len(rows))) if rows else 0.0
        total_value = sum(float(r.get("_price", 0)) * float(r.get("_qty", 0)) for r in rows) if rows else 0.0
        self.ui.lblStats.setText(
            f"Aantal: {total} | Gem. prijs: €{avg_price:.2f} | Voorraadwaarde: €{total_value:.2f}"
        )
        self.ui.tableProducts.resizeColumnsToContents()
        self.ui.tableProducts.horizontalHeader().setStretchLastSection(True)

# [END: refresh_table]
# [FUNC: toggle_low_stock]
    def toggle_low_stock(self):
        any_qty = any(r.get("_qty", 0) > 0 for r in self._all_rows) or any(r.get("_qty_virtual", 0) > 0 for r in self._all_rows)
        if not any_qty:
            QMessageBox.information(
                self, "Geen voorraadkolommen",
                "Je CSV bevat geen 'Aanwezige voorraad' of 'Virtuele voorraad'."
            )
            self.ui.btnLowStock.setChecked(False)
            self._low_stock_mode = False
            self.apply_filters()
            return
        self._low_stock_mode = not self._low_stock_mode
        self.ui.btnLowStock.setChecked(self._low_stock_mode)
        self.ui.btnLowStock.setText("Lage voorraad (aan)" if self._low_stock_mode else "Lage voorraad")
        self.apply_filters()

# [END: toggle_low_stock]
# [FUNC: compare_prices]
    def compare_prices(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Kies tweede export (CSV/XLSX)", str(Path.cwd()),
            "Spreadsheets (*.csv *.xlsx);;Alle bestanden (*.*)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                rows2 = read_csv_smart(Path(path))
            else:
                rows2 = try_load_xlsx(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Fout bij inladen", str(e))
            return
        if not rows2:
            QMessageBox.information(self, "Leeg bestand", "Geen rijen in tweede export.")
            return

        header2 = list(rows2[0].keys())
        hmap2: Dict[str, str] = {}
        for key, cands in PREF_COLS.items():
            f = first_present(cands, header2)
            if f:
                hmap2[key] = f

        def key_for(rec: Dict[str, Any]) -> str:
            for k in ("id", "default_code", "name"):
                col = hmap2.get(k)
                if col:
                    v = rec.get(col)
                    if v is not None and str(v).strip():
                        return str(v).strip()
            return ""

        price_by_key: Dict[str, float] = {}
        for rec in rows2:
            k = key_for(rec)
            if not k:
                continue
            p = normalize_number(rec.get(hmap2.get("list_price", ""), 0))
            price_by_key[k] = p

        for r in self._all_rows:
            k = (str(r.get("_id") or "").strip()
                 or str(r.get("_sku") or "").strip()
                 or str(r.get("_name") or "").strip())
            new_price = price_by_key.get(k)
            if new_price is not None:
                r["_new_price"] = new_price
            else:
                r.pop("_new_price", None)

        self.apply_filters()

# [END: compare_prices]
# [END: Window]
# Optioneel: los draaien voor test
# [SECTION: CLI / Entrypoint]
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    sys.exit(app.exec())
# [END: CLI / Entrypoint]
