import io, re, json
import pdfplumber
import pandas as pd
from flask import Flask, request, jsonify

app = Flask(__name__)

HOEVEELHEIDSV_CORRECT_AS_NEGATIVE = True

def euro_to_float(s: str):
    if s is None:
        return None
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def clean_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

re_regular = re.compile(
    r"""^[A-Z]\s+
        (?P<art>\d+)\s+
        (?P<name>.*?)\s+
        (?P<qty>\d+)\s+
        (?P<unit>\d+,\d{2,3})\s+
        (?P<total>-?\d+,\d{2})$
    """, re.VERBOSE
)
re_weighted = re.compile(
    r"""^[A-Z]\s+
        (?P<art>\d+)\s+
        (?P<left>.*?)\s+
        (?P<weight>\d+,\d{2,3})kg\s+
        (?P<eur_per>\d+,\d{2,3})\s+
        (?P<total>-?\d+,\d{2})$
    """, re.VERBOSE
)
re_discount = re.compile(
    r"""^Korting\ bon[^\S\r\n]*(?P<rawname>.*\S)\s+(?P<total>-?\d+,\d{2})$""",
    re.IGNORECASE
)
re_hoeveelheidsvoordeel = re.compile(
    r"""Hoeveelheidsvoordeel\s+toegekend:\s*€\s*(?P<amount>\d+,\d{2})\s*\(in\s+prijs\s+verrekend\)""",
    re.IGNORECASE
)
re_date = re.compile(r"\b(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}\b")

def parse_pdf_bytes(pdf_bytes: bytes):
    all_rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        lines = []
        for page in pdf.pages:
            t = (page.extract_text() or "")
            lines.extend([ln.rstrip() for ln in t.splitlines()])

    date_match = re_date.search("\n".join(lines))
    receipt_date = date_match.group(1) if date_match else "unknown"

    last_item_name = None
    last_item_art = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        m = re_weighted.match(line)
        if m:
            art = m.group("art")
            name_left = clean_space(m.group("left"))
            weight_kg = euro_to_float(m.group("weight"))
            eur_per_kg = euro_to_float(m.group("eur_per"))
            total = euro_to_float(m.group("total"))
            all_rows.append({
                "Datum": receipt_date, "Art.Nr": art, "Benaming": name_left,
                "Hoev.": None, "Gewicht (kg)": weight_kg,
                "Eenhprijs (EUR)": eur_per_kg, "Bedrag (EUR)": total, "Type": "gewicht"
            })
            last_item_name = name_left; last_item_art = art
            continue

        m = re_regular.match(line)
        if m:
            art = m.group("art")
            name = clean_space(m.group("name"))
            qty = int(m.group("qty"))
            unit = euro_to_float(m.group("unit"))
            total = euro_to_float(m.group("total"))
            all_rows.append({
                "Datum": receipt_date, "Art.Nr": art, "Benaming": name,
                "Hoev.": qty, "Gewicht (kg)": None,
                "Eenhprijs (EUR)": unit, "Bedrag (EUR)": total, "Type": "stuk"
            })
            last_item_name = name; last_item_art = art
            continue

        m = re_discount.match(line)
        if m:
            total = euro_to_float(m.group("total"))
            if total and total > 0:
                total = -total
            benaming_for_discount = last_item_name or "korting op vorig artikel"
            art_for_discount = last_item_art or "0000"
            all_rows.append({
                "Datum": receipt_date, "Art.Nr": art_for_discount,
                "Benaming": benaming_for_discount, "Hoev.": None,
                "Gewicht (kg)": None, "Eenhprijs (EUR)": None,
                "Bedrag (EUR)": total, "Type": "korting"
            })
            continue

        m = re_hoeveelheidsvoordeel.search(line)
        if m:
            amount = euro_to_float(m.group("amount"))
            if amount is not None:
                bedrag = -amount if HOEVEELHEIDSV_CORRECT_AS_NEGATIVE else amount
                all_rows.append({
                    "Datum": receipt_date, "Art.Nr": "0000",
                    "Benaming": "hoeveelheidsvoordeel verrekend in prijs",
                    "Hoev.": None, "Gewicht (kg)": None, "Eenhprijs (EUR)": None,
                    "Bedrag (EUR)": bedrag, "Type": "korting_hoeveelheid"
                })
            continue

    return all_rows

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/", methods=["POST"])
def parse():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    rows = parse_pdf_bytes(f.read())
    return jsonify(rows), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
