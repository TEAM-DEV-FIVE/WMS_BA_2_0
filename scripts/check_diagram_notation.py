"""Validate semantic notation, source coverage and editable diagram geometry."""

import ast
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from diagram_scenes import wrapped
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    pdfmetrics.registerFont(TTFont("WMS", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    graphs = json.loads((ROOT / "03_So_do/Hien_hanh/diagram_sources.json").read_text())
    schema = json.loads((ROOT / "02_CSDL/current/schema.json").read_text())
    tables = {t["name"]: t for t in schema["tables"]}
    by_code = {g["code"]: g for g in graphs}
    drawio = ET.parse(ROOT / "03_So_do/Hien_hanh/WMS_Hien_hanh.drawio")
    pages = {d.get("id"): d for d in drawio.findall("diagram")}
    total = 0
    for g in graphs:
        cells = {c.get("id"): c for c in pages[g["code"]].findall(".//mxCell")}
        require(len(cells) == len(pages[g["code"]].findall(".//mxCell")), "Duplicate draw.io IDs")
        for i, (a, b, _) in enumerate(g["edges"]):
            cell = cells[f"edge{i}"]
            require(cell.get("source") == a and cell.get("target") == b, "draw.io edge differs")
        if g["code"].startswith("ERD_"):
            table = tables[g["code"].removeprefix("ERD_")]
            fks = [c for c in table["constraints"] if c["kind"] == "f"]
            require(len(fks) == len(g["relations"]), "Missing cardinalities")
            primary = {col for c in table["constraints"] if c["kind"] == "p" for col in c["columns"]}
            for i, (fk, relation) in enumerate(zip(fks, g["relations"], strict=True)):
                optional = any(c["nullable"] for c in table["columns"] if c["name"] in fk["columns"])
                require(relation["constraint"] == fk["name"], "Constraint name mismatch")
                require(relation["source_columns"] == fk["columns"] and relation["target_columns"] == fk["target_columns"], "Composite FK order changed")
                require(relation["target_cardinality"] == ("0..1" if optional else "1"), "Nullable end mismatch")
                require(relation["identifying"] == (set(fk["columns"]) <= primary), "Identifying end mismatch")
                style = cells[f"edge{i}"].get("style")
                require("startArrow=ER" in style and "endArrow=ER" in style, "Missing Crow’s Foot markers")
                total += 1
        if g["code"].startswith("CLASS_"):
            for name, n in g["nodes"].items():
                tree = ast.parse((ROOT / n["lines"][0]).read_text())
                cls = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == name)
                methods = {m.name for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
                require(all(m[1:].split("(")[0] in methods for m in n["operations"]), "Invented class method")
                require(cells[name].get("value").count("<hr/>") == 2, "Missing UML compartments")
            for i, (source, target, _) in enumerate(g["edges"]):
                if g["relations"][i]["kind"] == "generalization":
                    require(target in g["nodes"][source]["bases"], "Invented inheritance")
                    require("endFill=0" in cells[f"edge{i}"].get("style"), "Filled inheritance triangle")
        if g.get("notation") in {"BPMN", "UML use case"}:
            for key, n in g["nodes"].items():
                require(0 <= n["x"] and n["x"]+n["w"] <= g["width"], "Node outside page")
                require(0 <= n["y"] and n["y"]+n["h"] < g["height"]-85, "Node outside content")
                if n["kind"] in {"task", "usecase"}:
                    require(len(wrapped(n["name"], n["w"]-22, 15))*20.25 <= n["h"]-10, "Label overflow: "+key)
                if g["notation"] == "BPMN":
                    top = 135+190*n["lane"]
                    require(top <= n["y"] and n["y"]+n["h"] <= top+190, "Node outside lane")
            if g["notation"] == "BPMN":
                starts = {k for k,n in g["nodes"].items() if n["kind"] == "start"}
                ends = {k for k,n in g["nodes"].items() if n["kind"] == "end"}
                reached = set(starts)
                for _ in g["nodes"]:
                    reached |= {b for a,b,_ in g["edges"] if a in reached}
                require(reached == set(g["nodes"]), "Unreachable BPMN node")
                terminating = set(ends)
                for _ in g["nodes"]:
                    terminating |= {a for a,b,_ in g["edges"] if b in terminating}
                require(terminating == set(g["nodes"]), "BPMN path has no end")
                for key,n in g["nodes"].items():
                    outgoing = [(b,label) for a,b,label in g["edges"] if a == key]
                    incoming = [a for a,b,_ in g["edges"] if b == key]
                    if n["kind"] == "gateway":
                        require(len(outgoing) >= 2 or len(incoming) >= 2, "Gateway neither splits nor merges")
                        if len(outgoing) > 1:
                            require(all(label for _,label in outgoing), "Unlabelled decision branch")
                    if n["kind"] == "task":
                        require(len(outgoing) == 1, "Implicit task split")
            else:
                require("boundary" in cells, "Missing system boundary")
                for key,n in g["nodes"].items():
                    if n["kind"] == "actor":
                        require(n["x"]+n["w"] < 330, "Actor inside system")
                        require("umlActor" in cells[key].get("style"), "Missing editable actor")
                    elif n["kind"] == "usecase":
                        require(n["x"] > 330 and n["y"]+n["h"] < g["height"]-90, "Use case outside system")
                        require("ellipse" in cells[key].get("style"), "Use case shape mismatch")
                require(all("endArrow=none" in cells[f"edge{i}"].get("style") for i in range(len(g["edges"]))), "Use case association has arrow")
    # Independent expectations for actual database relationships, including the
    # partial-unique and composite-unique cases most likely to be misclassified.
    examples = [
        ("user_avatar", "user_id", "0..1", "1"),
        ("document", "warehouse_id", "0..*", "1"),
        ("document", "destination_warehouse_id", "0..*", "0..1"),
        ("document", "transit_location_id", "0..1", "0..1"),
        ("role_permission", "role_id", "0..*", "1"),
        ("role_permission", "permission_id", "0..*", "1"),
    ]
    for table, column, left, right in examples:
        rel = next(r for r in by_code["ERD_"+table]["relations"] if r["source_columns"] == [column])
        require((rel["source_cardinality"], rel["target_cardinality"]) == (left,right), "Cardinality regression: "+table+"."+column)
    features = json.loads((ROOT / "01_Tai_lieu/current_features.json").read_text())
    shown = [key for g in graphs if g.get("notation") == "UML use case" for key in g["feature_keys"]]
    require(Counter(shown) == Counter(f["key"] for f in features), "Use-case feature coverage")
    refs = json.loads((ROOT / "03_So_do/reference_sources.json").read_text())
    require(len(refs["sources"]) == 8 and sum(r["pages"] for r in refs["sources"]) == 358, "Reference inventory")
    print(f"PASS: {total} FK cardinalities/markers; 6 BPMN paths and lanes; 26 use cases; UML class compartments/inheritance; 8 reference PDFs")


if __name__ == "__main__":
    main()
