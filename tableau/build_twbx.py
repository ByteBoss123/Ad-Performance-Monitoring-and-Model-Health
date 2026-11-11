"""Generate a packaged Tableau workbook (.twbx) for the ad CTR monitoring project.

Data: the CSVs in tableau/Data (exported from the pipeline outputs).
Run: python tableau/build_twbx.py  ->  tableau/Ad_CTR_Monitoring.twbx
"""
import csv
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

HERE = Path(__file__).resolve().parent
DATA = HERE / "Data"

# validated categorical slots + reserved status colors
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#b4b3ad"
CRITICAL, SERIOUS = "#d03b3b", "#ec835a"

# datasource key -> (csv, {column: type}); type in string|real|integer|datetime
SOURCES = {
    "hourly": ("hourly_monitor.csv", {
        "event_hour": "datetime", "impressions": "integer", "expected_impressions": "real", "clicks": "real",
        "ctr": "real", "expected_ctr": "real", "z_ctr": "real", "z_volume": "real",
        "alert_type": "string", "scored": "string"}),
    "attrib": ("creative_attribution.csv", {"event_date": "string", "component": "string", "ctr_change": "real"}),
    "model": ("model_health.csv", {"date": "string", "policy": "string", "auc": "real",
                                    "pred_over_actual": "real", "normalized_entropy": "real", "ece": "real"}),
    "drift": ("model_drift.csv", {"date": "string", "unseen_C14_share": "real", "score_psi": "real"}),
}
PALETTES = {
    "hourly": ("alert_type", {"Normal": GRAY, "CTR alert": CRITICAL, "Volume alert": SERIOUS}),
    "attrib": ("component", {"Established creatives movement": BLUE, "New-creative gap": ORANGE}),
    "model": ("policy", {"Frozen model": BLUE, "Frozen + daily recalibration": ORANGE, "Daily retrain": AQUA}),
}
REMOTE_TYPE = {"string": 129, "real": 5, "integer": 20, "datetime": 135}


def ds_name(key):
    return f"federated.{key}"


def guid():
    return "{" + str(uuid.uuid4()).upper() + "}"


def datasource_xml(key):
    fname, cols = SOURCES[key]
    with open(DATA / fname) as f:
        header = next(csv.reader(f))
    assert header == list(cols), (fname, header)
    tbl = fname.replace(".csv", "")
    conn = f"textscan.{key}"
    obj = f"{fname}_{uuid.uuid4().hex.upper()}"
    rel_cols = "".join(
        f"<column datatype='{t}' name='{c}' ordinal='{i}' />" for i, (c, t) in enumerate(cols.items()))
    relation = (f"<relation connection='{conn}' name='{fname}' table='[{tbl}#csv]' type='table'>"
                f"<columns character-set='UTF-8' header='yes' locale='en_US' separator=','>{rel_cols}</columns>"
                f"</relation>")
    md = ("<metadata-record class='capability'><remote-name /><remote-type>0</remote-type>"
          f"<parent-name>[{fname}]</parent-name><remote-alias /><aggregation>Count</aggregation>"
          "<contains-null>true</contains-null><attributes>"
          "<attribute datatype='string' name='character-set'>&quot;UTF-8&quot;</attribute>"
          "<attribute datatype='string' name='collation'>&quot;en_US&quot;</attribute>"
          "<attribute datatype='string' name='field-delimiter'>&quot;,&quot;</attribute>"
          "<attribute datatype='string' name='header-row'>&quot;true&quot;</attribute>"
          "<attribute datatype='string' name='locale'>&quot;en_US&quot;</attribute>"
          "<attribute datatype='string' name='single-char'>&quot;&quot;</attribute>"
          "</attributes></metadata-record>")
    for i, (c, t) in enumerate(cols.items()):
        agg = {"string": "Count", "datetime": "Year"}.get(t, "Sum")
        md += (f"<metadata-record class='column'><remote-name>{c}</remote-name>"
               f"<remote-type>{REMOTE_TYPE[t]}</remote-type><local-name>[{c}]</local-name>"
               f"<parent-name>[{fname}]</parent-name><remote-alias>{c}</remote-alias><ordinal>{i}</ordinal>"
               f"<local-type>{t}</local-type><aggregation>{agg}</aggregation><contains-null>true</contains-null>"
               + ("<scale>1</scale><width>1073741823</width><collation flag='0' name='LEN_RUS' />" if t == "string" else "")
               + f"<object-id>[{obj}]</object-id></metadata-record>")
    col_decl = ""
    for c, t in cols.items():
        role, typ = ("dimension", "nominal") if t == "string" else (
            ("dimension", "ordinal") if t == "datetime" else ("measure", "quantitative"))
        col_decl += (f"<column caption={quoteattr(c.replace('_', ' ').title())} datatype='{t}' name='[{c}]' "
                     f"role='{role}' type='{typ}' />")
    col_decl += (f"<column caption='{fname}' datatype='table' name='[__tableau_internal_object_id__].[{obj}]' "
                 "role='measure' type='quantitative' />")
    style = ""
    if key in PALETTES:
        field, pal = PALETTES[key]
        maps = "".join(f"<map to='{hexv}'><bucket>&quot;{v}&quot;</bucket></map>" for v, hexv in pal.items())
        style = (f"<style><style-rule element='mark'><encoding attr='color' field='[none:{field}:nk]' "
                 f"type='palette'>{maps}</encoding></style-rule></style>")
    caption = {"hourly": "Hourly monitor", "attrib": "Creative attribution", "model": "Model health",
               "drift": "Model drift"}[key]
    return (f"<datasource caption='{caption}' inline='true' name='{ds_name(key)}' version='18.1'>"
            f"<connection class='federated'><named-connections>"
            f"<named-connection caption='{tbl}' name='{conn}'>"
            f"<connection class='textscan' directory='Data' filename='{fname}' password='' server='' />"
            f"</named-connection></named-connections>{relation}<metadata-records>{md}</metadata-records>"
            f"</connection><aliases enabled='yes' />{col_decl}"
            "<layout dim-ordering='alphabetic' measure-ordering='alphabetic' show-structure='true' />"
            f"{style}"
            f"<object-graph><objects><object caption='{fname}' id='{obj}'><properties context=''>{relation}"
            "</properties></object></objects></object-graph></datasource>")


def inst(field, deriv, kind):
    """column-instance (name, xml). deriv: None|Sum|Avg; kind: nk|qk|ok"""
    prefix = {"None": "none", "Sum": "sum", "Avg": "avg"}[deriv]
    typ = {"nk": "nominal", "qk": "quantitative", "ok": "ordinal"}[kind]
    name = f"[{prefix}:{field}:{kind}]"
    return name, (f"<column-instance column='[{field}]' derivation='{deriv}' name='{name}' pivot='key' "
                  f"type='{typ}' />")


def worksheet(name, key, rows, cols, mark, color=None, size=None, tooltips=(), title=None, fmt_rows=None):
    ds = ds_name(key)
    insts = {}
    for spec in [rows, cols, color, size, *tooltips]:
        if spec:
            n, x = inst(*spec)
            insts[n] = x
    used = {spec[0] for spec in [rows, cols, color, size, *tooltips] if spec}
    col_defs = ""
    for c, t in SOURCES[key][1].items():
        if c in used:
            role, typ = ("dimension", "nominal") if t == "string" else (
                ("dimension", "ordinal") if t == "datetime" else ("measure", "quantitative"))
            col_defs += f"<column datatype='{t}' name='[{c}]' role='{role}' type='{typ}' />"
    enc = ""
    if color:
        enc += f"<color column='[{ds}].{inst(*color)[0]}' />"
    if size:
        enc += f"<size column='[{ds}].{inst(*size)[0]}' />"
    for t in tooltips:
        enc += f"<tooltip column='[{ds}].{inst(*t)[0]}' />"
    style = "<style />"
    ttl = (f"<layout-options><title><formatted-text><run bold='true' fontsize='13'>{title or name}</run>"
           "</formatted-text></title></layout-options>")
    ws = (f"<worksheet name={quoteattr(name)}>{ttl}<table><view><datasources><datasource caption='x' "
          f"name='{ds}' /></datasources><datasource-dependencies datasource='{ds}'>{col_defs}"
          f"{''.join(insts.values())}</datasource-dependencies><aggregation value='true' /></view>"
          f"{style}<panes><pane selection-relaxation-option='selection-relaxation-allow'><view>"
          f"<breakdown value='auto' /></view><mark class='{mark}' />"
          f"{'<encodings>' + enc + '</encodings>' if enc else ''}</pane></panes>"
          f"<rows>[{ds}].{inst(*rows)[0]}</rows><cols>[{ds}].{inst(*cols)[0]}</cols></table>"
          f"<simple-id uuid='{guid()}' /></worksheet>")
    win = (f"<window class='worksheet' name={quoteattr(name)}><cards><edge name='left'><strip size='160'>"
           "<card type='pages' /><card type='filters' /><card type='marks' /></strip></edge><edge name='top'>"
           "<strip size='31'><card type='columns' /></strip><strip size='31'><card type='rows' /></strip>"
           f"<strip size='31'><card type='title' /></strip></edge></cards><simple-id uuid='{guid()}' /></window>")
    return ws, win


SHEETS = [
    # name, datasource, rows, cols, mark, color, size, tooltips, title
    ("Hourly CTR Monitor", "hourly", ("ctr", "Avg", "qk"), ("event_hour", "None", "qk"), "Circle",
     ("alert_type", "None", "nk"), ("impressions", "Sum", "qk"),
     [("expected_ctr", "Avg", "qk"), ("z_ctr", "Avg", "qk")],
     "Hourly CTR: every hour scored against the same hour on prior days (red = CTR alert)"),
    ("Hourly Volume Monitor", "hourly", ("impressions", "Sum", "qk"), ("event_hour", "None", "qk"), "Bar",
     ("alert_type", "None", "nk"), None,
     [("expected_impressions", "Avg", "qk"), ("z_volume", "Avg", "qk")],
     "Hourly impressions: Oct 24 evening traffic collapse caught by the volume monitor"),
    ("Why CTR Moved", "attrib", ("ctr_change", "Sum", "qk"), ("event_date", "None", "nk"), "Bar",
     ("component", "None", "nk"), None, [],
     "Day-over-day CTR change: new-creative gap vs established creatives"),
    ("Creative Churn", "drift", ("unseen_C14_share", "Avg", "qk"), ("date", "None", "nk"), "Bar",
     None, None, [("score_psi", "Avg", "qk")],
     "Share of impressions on creatives the model never saw in training"),
    ("Model AUC", "model", ("auc", "Avg", "qk"), ("date", "None", "nk"), "Line",
     ("policy", "None", "nk"), None, [("normalized_entropy", "Avg", "qk")],
     "CTR model AUC by scoring day"),
    ("Model Calibration", "model", ("pred_over_actual", "Avg", "qk"), ("date", "None", "nk"), "Line",
     ("policy", "None", "nk"), None, [("ece", "Avg", "qk")],
     "Calibration: predicted CTR / actual CTR (1.0 = calibrated)"),
]


def dashboard(name):
    # 100000-based grid. Title 5%, then rows: CTR 27%, volume 22%, two pairs 23% each.
    z = [0]

    def nid():
        z[0] += 1
        return z[0] + 100

    rows = [(5000, 27000, ["Hourly CTR Monitor"]), (32000, 22000, ["Hourly Volume Monitor"]),
            (54000, 23000, ["Why CTR Moved", "Creative Churn"]), (77000, 23000, ["Model AUC", "Model Calibration"])]
    inner = f"<zone h='5000' id='{nid()}' is-fixed='true' type-v2='title' w='100000' x='0' y='0' />"
    flow = ""
    for y, h, sheets in rows:
        w = 100000 // len(sheets)
        kids = "".join(f"<zone h='{h}' id='{nid()}' name={quoteattr(s)} w='{w}' x='{i * w}' y='{y}' />"
                       for i, s in enumerate(sheets))
        flow += f"<zone h='{h}' id='{nid()}' param='horz' type-v2='layout-flow' w='100000' x='0' y='{y}'>{kids}</zone>"
    inner += f"<zone h='95000' id='{nid()}' param='vert' type-v2='layout-flow' w='100000' x='0' y='5000'>{flow}</zone>"
    db = (f"<dashboard name={quoteattr(name)}><layout-options><title><formatted-text>"
          "<run bold='true' fontsize='18'>Ad CTR Monitoring and Model Health</run><run fontsize='11'>"
          "   |   Real Avazu mobile-ad click logs, 200,000-impression sample, Oct 21-30 2014</run>"
          "</formatted-text></title></layout-options>"
          "<style /><size maxheight='1300' maxwidth='1400' minheight='1300' minwidth='1400' sizing-mode='fixed' />"
          "<datasources /><zones>"
          f"<zone h='100000' id='{nid()}' type-v2='layout-basic' w='100000' x='0' y='0'>{inner}</zone>"
          f"</zones><simple-id uuid='{guid()}' /></dashboard>")
    vps = "".join(f"<viewpoint name={quoteattr(s[0])} />" for s in SHEETS)
    win = (f"<window class='dashboard' maximized='true' name={quoteattr(name)}><viewpoints>{vps}</viewpoints>"
           f"<active id='-1' /><simple-id uuid='{guid()}' /></window>")
    return db, win


def build():
    sheets, wins = [], []
    for name, key, rows, cols, mark, color, size, tips, title in SHEETS:
        ws, win = worksheet(name, key, rows, cols, mark, color, size, tips, title)
        sheets.append(ws)
        wins.append(win)
    db, dbwin = dashboard("Ad CTR Monitor")
    twb = ("<?xml version='1.0' encoding='utf-8' ?>\n<!-- build 20262.26.0528.2205 -->\n"
           "<workbook original-version='18.1' source-build='2026.2.0 (20262.26.0528.2205)' source-platform='mac' "
           "version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>"
           "<document-format-change-manifest><ObjectModelEncapsulateLegacy /><ObjectModelTableType />"
           "<SchemaViewerObjectModel /><SheetIdentifierTracking /><SortTagCleanup />"
           "<WindowsPersistSimpleIdentifiers /></document-format-change-manifest><preferences />"
           f"<datasources>{''.join(datasource_xml(k) for k in SOURCES)}</datasources>"
           f"<worksheets>{''.join(sheets)}</worksheets><dashboards>{db}</dashboards>"
           f"<windows source-height='30'>{''.join(wins)}{dbwin}</windows></workbook>")
    (HERE / "Ad_CTR_Monitoring.twb").write_text(twb)
    out = HERE / "Ad_CTR_Monitoring.twbx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Ad_CTR_Monitoring.twb", twb)
        for k in SOURCES:
            z.write(DATA / SOURCES[k][0], f"Data/{SOURCES[k][0]}")
    return out


if __name__ == "__main__":
    print(build())
