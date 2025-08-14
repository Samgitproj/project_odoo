# app_portaal.py
# Hoofdportaal (Launcher) + Slimme zoekfunctie met resultaten in de hoofd-GUI

# [SECTION: Imports]
import sys, csv, logging, re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QWidget, QHBoxLayout, QVBoxLayout,
    QLineEdit, QPushButton, QTableView, QMessageBox
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtCore import Qt

from gui.Launcher import Ui_LauncherWindow  # UI→PY uit Launcher.ui

# [END: Imports]
DATA_DIR = Path("resources")
DEFAULT_CSV = DATA_DIR / "products.csv"
DEFAULT_XLSX = DATA_DIR / "products.xlsx"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("log.txt", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)

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

# [FUNC: first_present]
def first_present(cands: List[str], header: List[str]) -> Optional[str]:
    for c in cands:
        if c in header:
            return c
    return None

# [END: first_present]
# [FUNC: try_load_xlsx]
def try_load_xlsx(path: Path) -> List[Dict[str, Any]]:
    try:
        import openpyxl  # type: ignore
    except ImportError:
        raise RuntimeError("openpyxl niet geïnstalleerd. Installeer met 'pip install openpyxl' of gebruik CSV.")
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
    logging.info(f"XLSX geladen: {path}  rijen={len(data)}")
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
    raise FileNotFoundError(f"Geen productbestand gevonden in {DATA_DIR}. Plaats 'products.csv' of 'products.xlsx'.")

# [END: load_any_products]
# [FUNC: normalize_number]
def normalize_number(val) -> float:
    if val is None: return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace("€", "").replace(" ", "").replace("\xa0", "").replace(",", ".").replace("%", "")
    try: return float(s)
    except: return 0.0

# [END: normalize_number]
# sleutelwoorden → intent
INTENT_KEYWORDS = {
    "stock": ["voorraad", "stock", "qty", "aantal"],
    "price": ["prijs", "verkoopprijs", "list price"],
    "cost":  ["kost", "kostprijs", "cost", "purchase price"],
}

# [FUNC: parse_intent_and_needle]
def parse_intent_and_needle(text: str) -> Tuple[str, str]:
    """
    Bepaal (intent, needle) uit vrije tekst.
    - needle = tekst tussen dubbele aanhalingstekens "..."
    - intent = 'stock' | 'price' | 'cost' | 'generic'
    """
    t = text.strip().lower()
    # 1) needle uit aanhalingstekens
    m = re.search(r'"([^"]+)"', text)
    needle = m.group(1).strip() if m else ""

    # 2) intent uit keywords
    def has_any(words: List[str]) -> bool:
        return any(w in t for w in words)

    if has_any(INTENT_KEYWORDS["stock"]):
        return ("stock", needle)
    if has_any(INTENT_KEYWORDS["price"]):
        return ("price", needle)
    if has_any(INTENT_KEYWORDS["cost"]):
        return ("cost", needle)
    return ("generic", needle)

# [END: parse_intent_and_needle]
# Import van app-vensters met fallback stubs
from PyQt6.QtCore import Qt as _Qt
# [FUNC: _load_app]
def _load_app(modname: str, fallback_title: str):
    try:
        mod = __import__(f"apps.{modname}", fromlist=["Window"])
        return getattr(mod, "Window")
    except Exception:
        class Stub(QMainWindow):
            def __init__(self):
                super().__init__()
                self.setWindowTitle(fallback_title + " – (stub)")
                self.resize(900, 600)
                lbl = QLabel(f"{fallback_title}: GUI + logica komt hier.", self)
                lbl.setAlignment(_Qt.AlignmentFlag.AlignCenter)
                self.setCentralWidget(lbl)
        return Stub

# [END: _load_app]
# [CLASS: AppPortaal]
class AppPortaal(QMainWindow):
# [FUNC: __init__]
    def __init__(self):
        super().__init__()
        self.ui = Ui_LauncherWindow()
        self.ui.setupUi(self)

        # Hou open vensters bij (launcher->apps)
        self._windows = []

        self._build_smart_ui()

        try:
            raw = load_any_products(DEFAULT_CSV, DEFAULT_XLSX)
        except Exception as e:
            raw = []
            logging.error(f"Kon producten niet laden: {e}")

        self.products: List[Dict[str, Any]] = []
        self._header_map: Dict[str, str] = {}

        if raw:
            header = list(raw[0].keys())
            for key, cands in PREF_COLS.items():
                f = first_present(cands, header)
                if f:
                    self._header_map[key] = f

            cleaned = []
            for r in raw:
                rec = dict(r)
                rec["_id"]    = r.get(self._header_map.get("id",""), None) or r.get(self._header_map.get("default_code",""), None) or r.get(self._header_map.get("name",""), "")
                rec["_name"]  = r.get(self._header_map.get("name",""), "")
                rec["_sku"]   = r.get(self._header_map.get("default_code",""), "")
                rec["_barcode"] = r.get(self._header_map.get("barcode",""), "")
                rec["_price"] = normalize_number(r.get(self._header_map.get("list_price",""), 0))
                rec["_cost"]  = normalize_number(r.get(self._header_map.get("standard_price",""), 0))
                rec["_qty"]   = normalize_number(r.get(self._header_map.get("qty_available",""), 0))
                rec["_vqty"]  = normalize_number(r.get(self._header_map.get("virtual_available",""), 0))
                cleaned.append(rec)
            self.products = cleaned

        VoorraadWin     = _load_app("voorraad",     "Voorraad")
        ContactenWin    = _load_app("contacten",    "Contacten")
        VerkoopWin      = _load_app("verkoop",      "Verkoop")
        ProjectWin      = _load_app("project",      "Project")
        BuitendienstWin = _load_app("buitendienst", "Buitendienst")
        HelpdeskWin     = _load_app("helpdesk",     "Helpdesk")
        InkoopWin       = _load_app("inkoop",       "Inkoop")
        BarcodeWin      = _load_app("barcode",      "Barcode")
        ReparatiesWin   = _load_app("reparaties",   "Reparaties")
        WerknemersWin   = _load_app("werknemers",   "Werknemers")

        self.ui.btnVoorraad.clicked.connect(lambda: self.open_window(VoorraadWin))
        self.ui.btnContacten.clicked.connect(lambda: self.open_window(ContactenWin))
        self.ui.btnVerkoop.clicked.connect(lambda: self.open_window(VerkoopWin))
        self.ui.btnProject.clicked.connect(lambda: self.open_window(ProjectWin))
        self.ui.btnBuitendienst.clicked.connect(lambda: self.open_window(BuitendienstWin))
        self.ui.btnHelpdesk.clicked.connect(lambda: self.open_window(HelpdeskWin))
        self.ui.btnInkoop.clicked.connect(lambda: self.open_window(InkoopWin))
        self.ui.btnBarcode.clicked.connect(lambda: self.open_window(BarcodeWin))
        self.ui.btnReparaties.clicked.connect(lambda: self.open_window(ReparatiesWin))
        self.ui.btnWerknemers.clicked.connect(lambda: self.open_window(WerknemersWin))

# [END: __init__]
# [FUNC: _build_smart_ui]
    def _build_smart_ui(self):
        # Bovenaan, vóór label/titel: een rij met zoekveld + knop
        top_layout: QVBoxLayout = self.ui.centralwidget.layout()  # hoofd-VBox
        bar = QWidget(self)
        hb = QHBoxLayout(bar); hb.setContentsMargins(0, 0, 0, 0)
        self.lineSmart = QLineEdit(bar)
        self.lineSmart.setPlaceholderText('Typ bv.: kijk hoeveel voorraad we nog hebben van "black eagle HD"')
        btn = QPushButton("Zoek", bar)
        hb.addWidget(self.lineSmart, 1)
        hb.addWidget(btn, 0)
        top_layout.insertWidget(0, bar)

        # Onder de grid met tegels: resultaten (tabel + label)
        self.tblResults = QTableView(self)
        self.tblModel = QStandardItemModel(self)
        self.tblResults.setModel(self.tblModel)
        self.tblResults.setSortingEnabled(True)
        self.tblResults.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tblResults.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        top_layout.addWidget(self.tblResults)
        self.lblSummary = QLabel(" ", self)
        top_layout.addWidget(self.lblSummary)

        # events
        btn.clicked.connect(self._on_smart_search)
        self.lineSmart.returnPressed.connect(self._on_smart_search)

# [END: _build_smart_ui]
# [FUNC: _on_smart_search]
    def _on_smart_search(self):
        q = self.lineSmart.text().strip()
        if not q:
            return
        intent, needle = parse_intent_and_needle(q)
        matched = self._search_products(needle)
        self._show_results(matched, intent, needle)

# [END: _on_smart_search]
# [FUNC: _search_products]
    def _search_products(self, needle: str) -> List[Dict[str, Any]]:
        if not self.products:
            QMessageBox.information(self, "Geen data", "Kan geen producten laden (resources/products.csv?).")
            return []
        if not needle:
            # als geen aanhalingstekens gegeven zijn, zoek op hele zin
            needle = self.lineSmart.text().strip()
        s = needle.lower()
        return [
            r for r in self.products
            if s in str(r.get("_name","")).lower()
            or s in str(r.get("_sku","")).lower()
            or s in str(r.get("_barcode","")).lower()
        ]

# [END: _search_products]
# [FUNC: _show_results]
    def _show_results(self, rows: List[Dict[str, Any]], intent: str, needle: str):
        # kolommen afhankelijk van intent
        if intent == "stock":
            headers = ["Naam", "Interne referentie", "Aanwezige voorraad", "Virtuele voorraad", "Verkoopprijs"]
        elif intent == "price":
            headers = ["Naam", "Interne referentie", "Verkoopprijs", "Kostprijs"]
        elif intent == "cost":
            headers = ["Naam", "Interne referentie", "Kostprijs", "Verkoopprijs"]
        else:
            headers = ["Naam", "Interne referentie", "Barcode", "Verkoopprijs"]

        self.tblModel.clear()
        self.tblModel.setHorizontalHeaderLabels(headers)

        for r in rows:
            name = str(r.get("_name",""))
            sku  = str(r.get("_sku",""))
            bc   = str(r.get("_barcode",""))
            price = f"{float(r.get('_price',0)):.2f}"
            cost  = f"{float(r.get('_cost',0)):.2f}"
            qty   = f"{float(r.get('_qty',0)):.2f}"
            vqty  = f"{float(r.get('_vqty',0)):.2f}"

            if intent == "stock":
                values = [name, sku, qty, vqty, price]
            elif intent == "price":
                values = [name, sku, price, cost]
            elif intent == "cost":
                values = [name, sku, cost, price]
            else:
                values = [name, sku, bc, price]

            items = [QStandardItem(v) for v in values]
            for it in items: it.setEditable(False)
            self.tblModel.appendRow(items)

        self.tblResults.resizeColumnsToContents()
        self.tblResults.horizontalHeader().setStretchLastSection(True)

        # samenvatting
        n = len(rows)
        if intent == "stock":
            total_qty = sum(float(r.get("_qty",0)) for r in rows)
            self.lblSummary.setText(f'Resultaten: {n} voor "{needle}". Totaal aanwezige voorraad: {total_qty:.2f}.')
        else:
            self.lblSummary.setText(f'Resultaten: {n} voor "{needle}".')

# [END: _show_results]
# [FUNC: open_window]
    def open_window(self, cls):
        win = cls()
        self._windows.append(win)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        win.destroyed.connect(lambda _: self._windows.remove(win) if win in self._windows else None)
        win.show()

# [END: open_window]
# [END: AppPortaal]
# [FUNC: start]
def start():
    app = QApplication(sys.argv)
    w = AppPortaal()
    w.show()
    sys.exit(app.exec())

# [END: start]
# [SECTION: CLI / Entrypoint]
if __name__ == "__main__":
    start()
# [END: CLI / Entrypoint]
