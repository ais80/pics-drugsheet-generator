"""
Core Drug Sheet Generator Engine
Gathers data from BNF, EMC, dm+d, Birmingham Formulary, and knowledge base files.
Performs rule-based analysis and compiles into drugsheet output formats.
"""

import asyncio
import json
import os
import re
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pdfplumber
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = (
    PROJECT_ROOT / "Knowledge_base"
    if (PROJECT_ROOT / "Knowledge_base").exists()
    else PROJECT_ROOT / "Knowledge base"
)
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Controlled Drug reference (from dmd_server.py)
# ---------------------------------------------------------------------------
CD_CATEGORIES = {
    "0000": {"schedule": None, "description": "No Controlled Drug Status"},
    "0001": {"schedule": 1, "description": "Schedule 1 (CD Lic)"},
    "0002": {"schedule": 2, "description": "Schedule 2 (CD)"},
    "0003": {"schedule": 2, "description": "Schedule 2 (CD Exempt Safe Custody)"},
    "0004": {"schedule": 3, "description": "Schedule 3 (CD No Register)"},
    "0005": {"schedule": 3, "description": "Schedule 3 (CD No Register Exempt Safe Custody)"},
    "0006": {"schedule": 3, "description": "Schedule 3 (CD No Register Phenobarbital)"},
    "0007": {"schedule": 3, "description": "Schedule 3 (CD No Register Temazepam)"},
    "0008": {"schedule": 4, "description": "Schedule 4 Part I (CD Anab)"},
    "0009": {"schedule": 4, "description": "Schedule 4 Part II (CD Benz)"},
    "0010": {"schedule": 5, "description": "Schedule 5 (CD Inv)"},
}

KNOWN_CONTROLLED_DRUGS = {
    "morphine": 2, "diamorphine": 2, "oxycodone": 2, "fentanyl": 2,
    "methadone": 2, "pethidine": 2, "alfentanil": 2, "remifentanil": 2,
    "sufentanil": 2, "tapentadol": 2, "hydromorphone": 2, "dipipanone": 2,
    "cocaine": 2, "amphetamine": 2, "dexamphetamine": 2, "lisdexamfetamine": 2,
    "methylphenidate": 2, "secobarbital": 2, "nabilone": 2,
    "buprenorphine": 3, "tramadol": 3, "gabapentin": 3, "pregabalin": 3,
    "phenobarbital": 3, "temazepam": 3, "midazolam": 3, "flunitrazepam": 3,
    "diazepam": 4, "lorazepam": 4, "nitrazepam": 4, "oxazepam": 4,
    "chlordiazepoxide": 4, "clonazepam": 4, "clobazam": 4, "zolpidem": 4,
    "zopiclone": 4, "zaleplon": 4,
    "testosterone": 4, "nandrolone": 4, "stanozolol": 4,
    "codeine": 5, "dihydrocodeine": 5, "pholcodine": 5,
    "cannabis": 1, "lsd": 1, "psilocybin": 1, "mescaline": 1,
}

# BNF section IDs (from server.py)
BNF_SECTIONS = {
    "indications_and_dose": "indicationsAndDose",
    "contraindications": "contraIndications",
    "cautions": "cautions",
    "interactions": "interactionsLinks",
    "side_effects": "sideEffects",
    "pregnancy": "pregnancy",
    "breast_feeding": "breastFeeding",
    "hepatic_impairment": "hepaticImpairment",
    "renal_impairment": "renalImpairment",
    "monitoring_requirements": "monitoringRequirements",
    "prescribing_and_dispensing": "prescribingAndDispensingInformation",
    "medicinal_forms": "medicinalForms",
}

# EMC SmPC sections
EMC_SECTIONS = {
    "4.2_posology": "4.2",
    "4.3_contraindications": "4.3",
    "4.4_special_warnings": "4.4",
    "4.5_interactions": "4.5",
    "4.6_fertility_pregnancy": "4.6",
    "4.8_undesirable_effects": "4.8",
}


# ===========================================================================
# PDF EXTRACTION
# ===========================================================================
def extract_pdf_text(file_path_or_bytes, filename: str = "") -> dict:
    """Extract text from a PDF file. Returns dict with text per page."""
    result = {"filename": filename, "pages": [], "full_text": ""}
    try:
        if isinstance(file_path_or_bytes, (str, Path)):
            pdf = pdfplumber.open(file_path_or_bytes)
        else:
            import io
            pdf = pdfplumber.open(io.BytesIO(file_path_or_bytes))

        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            result["pages"].append({"page": i + 1, "text": text})
            result["full_text"] += text + "\n"
        pdf.close()
    except Exception as e:
        result["error"] = str(e)
    return result


# ===========================================================================
# KNOWLEDGE BASE LOADING
# ===========================================================================
class KnowledgeBase:
    """Loads and provides access to the Excel knowledge base files."""

    def __init__(self):
        self.drugs_to_classes: pd.DataFrame | None = None
        self.form_route: pd.DataFrame | None = None
        self.icd10_usage: pd.DataFrame | None = None
        self.tfqav_summary: pd.DataFrame | None = None
        self._loaded = False

    def load(self):
        if self._loaded:
            return

        # Prefer cleaned versions
        cleaned = KB_DIR / "cleaned"

        try:
            dtc_path = cleaned / "drugs_to_classes.xlsx" if (cleaned / "drugs_to_classes.xlsx").exists() else KB_DIR / "drugsToClasses.xls"
            self.drugs_to_classes = pd.read_excel(dtc_path)
        except Exception:
            self.drugs_to_classes = pd.DataFrame()

        try:
            fr_path = cleaned / "form_route.xlsx" if (cleaned / "form_route.xlsx").exists() else KB_DIR / "FormRoute.xlsx"
            self.form_route = pd.read_excel(fr_path)
        except Exception:
            self.form_route = pd.DataFrame()

        try:
            icd_path = cleaned / "icd10_usage.xlsx" if (cleaned / "icd10_usage.xlsx").exists() else KB_DIR / "ICD10_usage.xlsx"
            self.icd10_usage = pd.read_excel(icd_path)
        except Exception:
            self.icd10_usage = pd.DataFrame()

        try:
            tfq_path = cleaned / "tfqav_summary.xlsx" if (cleaned / "tfqav_summary.xlsx").exists() else KB_DIR / "TFQavSummary.xlsx"
            self.tfqav_summary = pd.read_excel(tfq_path)
        except Exception:
            self.tfqav_summary = pd.DataFrame()

        self._loaded = True

    def find_drug_classes(self, drug_name: str) -> list[dict]:
        """Find matching drug classes from drugsToClasses."""
        if self.drugs_to_classes is None or self.drugs_to_classes.empty:
            return []
        name_lower = re.escape(drug_name.lower())
        matches = self.drugs_to_classes[
            self.drugs_to_classes["drugDesc"].str.lower().str.contains(name_lower, na=False, regex=True)
            | self.drugs_to_classes["GENERIC"].str.lower().str.contains(name_lower, na=False, regex=True)
            | self.drugs_to_classes["TRADE"].str.lower().str.contains(name_lower, na=False, regex=True)
        ]
        results = []
        seen_classes = set()
        for _, row in matches.iterrows():
            cls_code = str(row.get("DRUGCLS", "")).strip()
            cls_desc = str(row.get("classDesc", "")).strip()
            # Filter out nan/empty entries
            if not cls_code or cls_code.lower() == "nan" or not cls_desc or cls_desc.lower() == "nan":
                continue
            if cls_code not in seen_classes:
                seen_classes.add(cls_code)
                results.append({
                    "drug_class": cls_code,
                    "class_description": cls_desc,
                    "matched_drug": str(row.get("drugDesc", "")),
                })
        return results

    def find_interacting_drug_class(self, drug_name: str) -> dict | None:
        """Check if an interacting drug belongs to a known drug class."""
        if self.drugs_to_classes is None or self.drugs_to_classes.empty:
            return None
        name_lower = re.escape(drug_name.lower())
        matches = self.drugs_to_classes[
            self.drugs_to_classes["drugDesc"].str.lower().str.contains(name_lower, na=False, regex=True)
            | self.drugs_to_classes["GENERIC"].str.lower().str.contains(name_lower, na=False, regex=True)
        ]
        if not matches.empty:
            row = matches.iloc[0]
            return {
                "drug_class": str(row.get("DRUGCLS", "")),
                "class_description": str(row.get("classDesc", "")),
                "is_class": True,
            }
        return None

    def find_icd10_mapping(self, condition: str) -> dict | None:
        """Find an existing ICD-10 mapping for a condition."""
        if self.icd10_usage is None or self.icd10_usage.empty:
            return None
        cond_lower = condition.lower()
        for col in self.icd10_usage.columns:
            matches = self.icd10_usage[
                self.icd10_usage[col].astype(str).str.lower().str.contains(re.escape(cond_lower), na=False)
            ]
            if not matches.empty:
                row = matches.iloc[0]
                return {
                    "icd10_code": str(row.iloc[1]) if len(row) > 1 else "",
                    "description": str(row.iloc[2]) if len(row) > 2 else "",
                    "drugsheet": str(row.iloc[3]) if len(row) > 3 else "",
                }
        return None

    def get_tfqav_info(self, drug_name: str) -> list[dict]:
        """Get trade/form/quantity info from TFQavSummary."""
        if self.tfqav_summary is None or self.tfqav_summary.empty:
            return []
        name_lower = re.escape(drug_name.lower())
        matches = self.tfqav_summary[
            self.tfqav_summary["gDesc"].str.lower().str.contains(name_lower, na=False, regex=True)
            | self.tfqav_summary["tDesc"].str.lower().str.contains(name_lower, na=False, regex=True)
        ]
        results = []
        for _, row in matches.head(20).iterrows():
            results.append({
                "generic": str(row.get("GENERIC", "")),
                "generic_desc": str(row.get("gDesc", "")),
                "trade": str(row.get("TRADE", "")),
                "trade_desc": str(row.get("tDesc", "")),
                "form": str(row.get("FORM", "")),
                "form_desc": str(row.get("formDscn", "")),
                "quantity_desc": str(row.get("qDesc", "")),
                "value": str(row.get("VALUE", "")),
                "units": str(row.get("UNITS", "")),
                "is_dmd": str(row.get("isDMD", "")),
            })
        return results


# ===========================================================================
# DATA GATHERING — BNF
# ===========================================================================
async def gather_bnf_data(client: httpx.AsyncClient, drug_name: str) -> dict:
    """Scrape BNF drug page for clinical data."""
    slug = drug_name.lower().replace(" ", "-")
    url = f"https://bnf.nice.org.uk/drugs/{slug}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    result = {"source": url, "drug": drug_name, "status": "pending"}

    try:
        resp = await client.get(url, headers=headers, follow_redirects=True, timeout=20.0)
        if resp.status_code != 200:
            result["status"] = "not_found"
            result["error"] = f"HTTP {resp.status_code}"
            return result

        soup = BeautifulSoup(resp.text, "html.parser")
        result["status"] = "ok"

        # BNF uses h2 headings (no section IDs on divs). Extract content
        # between consecutive h2 tags.
        h2_map = {}  # heading text -> content
        all_h2 = soup.find_all("h2")
        for i, h2 in enumerate(all_h2):
            heading = h2.get_text(strip=True).lower()
            # Collect all siblings until the next h2
            content_parts = []
            for sibling in h2.find_next_siblings():
                if sibling.name == "h2":
                    break
                text = sibling.get_text(separator=" | ", strip=True)
                if text:
                    content_parts.append(text)
            h2_map[heading] = " | ".join(content_parts)

        # Map BNF headings to our keys
        heading_to_key = {
            "indications and dose": "indications_and_dose",
            "contraindications": "contraindications",
            "cautions": "cautions",
            "interactions": "interactions",
            "side-effects": "side_effects",
            "pregnancy": "pregnancy",
            "breast feeding": "breast_feeding",
            "hepatic impairment": "hepatic_impairment",
            "renal impairment": "renal_impairment",
            "monitoring requirements": "monitoring_requirements",
            "prescribing and dispensing information": "prescribing_and_dispensing",
            "directions for administration": "directions_for_administration",
            "medicinal forms": "medicinal_forms",
            "allergy and cross-sensitivity": "allergy_cross_sensitivity",
            "important safety information": "important_safety",
            "unlicensed use": "unlicensed_use",
            "patient and carer advice": "patient_carer_advice",
            "drug action": "drug_action",
        }

        for heading_text, content in h2_map.items():
            for pattern, key in heading_to_key.items():
                if pattern in heading_text:
                    result[key] = content
                    break

        # Extract drug title
        title = soup.find("h1")
        if title:
            result["title"] = title.get_text(strip=True)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


# ===========================================================================
# DATA GATHERING — BNF INTERACTIONS
# ===========================================================================
async def gather_bnf_interactions(client: httpx.AsyncClient, drug_name: str) -> dict:
    """Scrape BNF interactions page for detailed interaction data.

    The BNF site is a Gatsby static site with CSS Modules (mangled class names).
    We use attribute-substring selectors like [class*="..."] to match elements.
    """
    slug = drug_name.lower().replace(" ", "-")
    url = f"https://bnf.nice.org.uk/interactions/{slug}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    result = {"source": url, "interactions": []}

    try:
        resp = await client.get(url, headers=headers, follow_redirects=True, timeout=20.0)
        if resp.status_code != 200:
            return result

        soup = BeautifulSoup(resp.text, "html.parser")

        # CSS Modules mangle class names. Use attribute substring selectors.
        # Each interaction is an <li> inside <ol class*="interactionsList">
        interaction_items = soup.select('li[class*="interactionsListItem"]')

        # Fallback: try finding <h3> headings that link to drug monographs
        if not interaction_items:
            interaction_items = []
            for h3 in soup.find_all("h3"):
                cls = " ".join(h3.get("class", []))
                if "interactant" in cls.lower() or "title" in cls.lower():
                    interaction_items.append(h3.parent)
                    continue
                # Also try by link pattern
                link = h3.find("a", href=lambda x: x and "/drugs/" in x)
                if link and h3.find_parent("ol"):
                    interaction_items.append(h3.parent)

        # Second fallback: find the ordered list and get all <li> children
        if not interaction_items:
            ol = soup.find("ol")
            if ol:
                interaction_items = ol.find_all("li", recursive=False)

        for item in interaction_items:
            # Drug name from <h3> heading (may contain a link to /drugs/slug/)
            h3 = item.find("h3")
            if not h3:
                continue
            interacting_drug = h3.get_text(strip=True)
            if not interacting_drug or len(interacting_drug) < 2:
                continue

            # Each interaction can have multiple messages in <ul>/<li>
            message_items = item.select('li[class*="message"]')
            if not message_items:
                # Fallback: find <ul> inside this item and get <li> children
                ul = item.find("ul")
                if ul:
                    message_items = ul.find_all("li", recursive=False)

            if not message_items:
                # No structured messages; take the item text minus the heading
                text = item.get_text(separator=" ", strip=True)
                text = text.replace(interacting_drug, "", 1).strip()
                if text:
                    result["interactions"].append({
                        "interacting_drug": interacting_drug,
                        "severity": "unknown",
                        "evidence": "",
                        "detail": text[:500],
                    })
                continue

            for msg_item in message_items:
                # Extract message text (the description of the interaction)
                # The message content uses non-mangled classes: substance-primary,
                # effectQualifier, effect, parameter, action
                detail = msg_item.get_text(separator=" ", strip=True)

                # Extract severity from <dl> supplementary info
                severity = "Normal"
                evidence = ""
                dl = msg_item.find("dl")
                if dl:
                    dts = dl.find_all("dt")
                    dds = dl.find_all("dd")
                    for dt, dd in zip(dts, dds):
                        label = dt.get_text(strip=True).lower().rstrip(":")
                        value = dd.get_text(strip=True)
                        if "severity" in label:
                            severity = value
                        elif "evidence" in label:
                            evidence = value
                    # Remove the dl text from the detail
                    dl_text = dl.get_text(separator=" ", strip=True)
                    detail = detail.replace(dl_text, "").strip()

                # Check for severe styling
                severe_div = msg_item.select_one('div[class*="severeMessage"]')
                if severe_div and severity == "Normal":
                    severity = "Severe"

                result["interactions"].append({
                    "interacting_drug": interacting_drug,
                    "severity": severity,
                    "evidence": evidence,
                    "detail": detail[:500],
                })

    except Exception as e:
        result["error"] = str(e)

    return result


# ===========================================================================
# DATA GATHERING — EMC SmPC
# ===========================================================================
async def gather_emc_data(client: httpx.AsyncClient, drug_name: str) -> dict:
    """Scrape EMC for SmPC data."""
    search_url = f"https://www.medicines.org.uk/emc/search?q={drug_name}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    result = {"drug": drug_name, "status": "pending"}

    try:
        # 1. Search
        search_resp = await client.get(search_url, headers=headers, follow_redirects=True, timeout=20.0)
        soup = BeautifulSoup(search_resp.text, "html.parser")

        # Find first SmPC product link (class name varies, use href pattern)
        smpc_links = soup.find_all("a", href=lambda x: x and "/emc/product/" in x and "/smpc" in x)
        if not smpc_links:
            # Fallback: any product link
            smpc_links = soup.find_all("a", href=lambda x: x and "/emc/product/" in x)
        if not smpc_links:
            result["status"] = "not_found"
            return result

        href = smpc_links[0]["href"]
        product_url = "https://www.medicines.org.uk" + href
        if "/smpc" not in product_url:
            product_url += "/smpc"
        result["source"] = product_url
        result["product_name"] = smpc_links[0].get_text(strip=True)

        # 2. Fetch SmPC
        smpc_resp = await client.get(product_url, headers=headers, follow_redirects=True, timeout=20.0)
        smpc_soup = BeautifulSoup(smpc_resp.text, "html.parser")

        result["status"] = "ok"

        for key, section_num in EMC_SECTIONS.items():
            header = smpc_soup.find(
                lambda tag: tag.name in ["h2", "h3"] and section_num in tag.text
            )
            if header:
                content = []
                for sibling in header.find_next_siblings():
                    if sibling.name in ["h2", "h3"]:
                        break
                    content.append(sibling.get_text(strip=True))
                result[key] = " ".join(content)
            else:
                result[key] = None

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


# ===========================================================================
# DATA GATHERING — BIRMINGHAM FORMULARY
# ===========================================================================
async def gather_formulary_data(client: httpx.AsyncClient, drug_name: str, drug_form: str | None = None) -> dict:
    """Check Birmingham and Surrounds Formulary.

    The formulary site uses traffic light images to indicate status:
    - TrafficLightsGreenV2.gif = Green (Formulary)
    - TrafficLightsAmberIV2.gif = Amber Specialist Initiation
    - TrafficLightsAmberRV2.gif = Amber Specialist Recommendation
    - TrafficLightsAmberSCV2.gif = Amber Shared Care (ESCA)
    - TrafficLightsRedV2.gif = Red (Restricted/Specialist only)

    Each drug entry is in a table row (<tr>) with the drug name and its traffic
    light image. We find the row matching the drug name and read its status.
    """
    import urllib.parse
    base = "https://www.birminghamandsurroundsformulary.nhs.uk"
    search_url = f"{base}/searchresults.asp?SearchVar={urllib.parse.quote(drug_name)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    result = {"drug": drug_name, "status": "pending", "all_entries": []}

    try:
        resp = await client.get(search_url, headers=headers, follow_redirects=True, timeout=20.0)
        if resp.status_code != 200:
            result["status"] = "error"
            return result

        soup = BeautifulSoup(resp.text, "html.parser")
        # Search results may link to chaptersSubDetails or drug pages
        links = soup.find_all("a", href=lambda x: x and ("drug_details" in str(x) or "chaptersSubDetails" in str(x) or "drugmatch" in str(x)))

        if not links:
            result["status"] = "not_found"
            result["formulary_status"] = "Not listed"
            return result

        # Visit ALL unique detail pages to find every formulary entry for this drug
        seen_urls = set()
        all_entries = []
        drug_lower = drug_name.lower()
        form_lower = (drug_form or "").lower()

        for link in links:
            href = link["href"]
            detail_url = f"{base}/{href}" if not href.startswith("http") else href
            # Normalise URL (remove fragment)
            base_url = detail_url.split("#")[0]
            if base_url in seen_urls:
                continue
            seen_urls.add(base_url)

            try:
                detail_resp = await client.get(detail_url, headers=headers, follow_redirects=True, timeout=20.0)
                detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
            except Exception:
                continue

            # Find all table rows containing the drug name
            for tr in detail_soup.find_all("tr"):
                row_text = tr.get_text(strip=True)
                if drug_lower not in row_text.lower():
                    continue

                # Extract traffic light from this row's images
                status = None
                amber_subtype = None
                for img in tr.find_all("img"):
                    src = str(img.get("src", "")).lower()
                    alt = str(img.get("alt", "")).strip()

                    if "trafficlightsgreen" in src:
                        status = "Green (Formulary)"
                    elif "trafficlightsambersc" in src:
                        status = "Amber (Shared Care/ESCA)"
                        amber_subtype = "ESCA"
                    elif "trafficlightsamberi" in src:
                        status = "Amber (Specialist Initiation)"
                        amber_subtype = "Specialist Initiation"
                    elif "trafficlightsamberr" in src:
                        status = "Amber (Specialist Recommendation)"
                        amber_subtype = "Specialist Recommendation"
                    elif "trafficlightsred" in src:
                        status = "Red (Restricted/Specialist only)"
                    elif "trafficlightsgrey" in src:
                        status = "Grey (Special Commissioning)"
                    elif "trafficlightspurple" in src:
                        status = "Purple (NICE TA pending)"
                    elif "trafficlightsblack" in src:
                        status = "Black (Non-Formulary)"

                if status:
                    # Extract the specific drug entry text (form info, notes)
                    entry_text = row_text[:300]

                    # Filter out page chrome/legend rows — these contain
                    # site-wide boilerplate text, not actual drug entries
                    if any(phrase in entry_text.lower() for phrase in [
                        "incorporating the bsse", "maintained by midlands",
                        "homeaboutadmin", "chaptersmedic", "newsmobilereport",
                        "contact ussearch", "prescribing in children",
                        "statusdescription", "netformulary",
                    ]):
                        continue

                    # Check for ESCA/RiCAD in the row text
                    row_lower = row_text.lower()
                    if amber_subtype is None:
                        if "esca" in row_lower:
                            amber_subtype = "ESCA"
                        elif "ricad" in row_lower:
                            amber_subtype = "RiCAD"

                    entry = {
                        "status": status,
                        "amber_subtype": amber_subtype,
                        "text": entry_text,
                        "source_url": detail_url,
                    }
                    all_entries.append(entry)

        # Deduplicate entries by status + first 60 chars of text
        seen_entries = set()
        deduped_entries = []
        for entry in all_entries:
            key = (entry["status"], entry["text"][:60])
            if key not in seen_entries:
                seen_entries.add(key)
                deduped_entries.append(entry)
        result["all_entries"] = deduped_entries
        all_entries = deduped_entries

        if not all_entries:
            result["formulary_status"] = "Unknown"
            result["status"] = "ok"
            # Still try to find ESCA/RiCAD in the page text as fallback
            for link in links:
                href = link["href"]
                detail_url = f"{base}/{href}" if not href.startswith("http") else href
                try:
                    detail_resp = await client.get(detail_url, headers=headers, follow_redirects=True, timeout=20.0)
                    full_text = detail_resp.text.lower()
                    if drug_lower in full_text:
                        drug_pos = full_text.find(drug_lower)
                        context = full_text[drug_pos:drug_pos + 2000]
                        if "esca" in context:
                            result["amber_type"] = "ESCA"
                            result["formulary_status"] = "Amber (ESCA)"
                        elif "ricad" in context:
                            result["amber_type"] = "RiCAD"
                            result["formulary_status"] = "Amber (RiCAD)"
                        break
                except Exception:
                    continue
            result["source"] = links[0]["href"] if links else ""
            return result

        # Choose the best entry: prefer oral/standard forms, then match requested form
        best = all_entries[0]
        for entry in all_entries:
            entry_lower = entry["text"].lower()
            # If a form was requested, prefer entries matching that form
            if form_lower and form_lower in entry_lower:
                best = entry
                break
            # Prefer oral presentations as the "main" formulary entry
            if "oral" in entry_lower and "oral" not in best["text"].lower():
                best = entry

        result["formulary_status"] = best["status"]
        result["amber_type"] = best.get("amber_subtype")
        result["source"] = best.get("source_url", links[0]["href"])
        result["local_notes"] = best["text"][:500]
        result["status"] = "ok"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


# ===========================================================================
# CONTROLLED DRUG CHECK
# ===========================================================================
def check_controlled_drug(drug_name: str, bnf_data: dict, supplementary_text: str = "") -> dict:
    """Check if drug is a controlled drug using multiple strategies."""
    result = {"is_controlled": False, "schedule": None, "description": ""}

    # Strategy 1: Known drugs table
    name_lower = drug_name.lower().strip()
    for known, sched in KNOWN_CONTROLLED_DRUGS.items():
        if known in name_lower or name_lower in known:
            result["is_controlled"] = True
            result["schedule"] = sched
            result["description"] = f"Schedule {sched} Controlled Drug"
            result["source"] = "Known CD reference table"
            return result

    # Strategy 2: BNF page text
    if bnf_data:
        for key, value in bnf_data.items():
            if isinstance(value, str) and "controlled drug" in value.lower():
                result["is_controlled"] = True
                match = re.search(r"schedule\s+(\d)", value, re.IGNORECASE)
                if match:
                    result["schedule"] = int(match.group(1))
                    result["description"] = f"Schedule {result['schedule']} Controlled Drug"
                result["source"] = "BNF page"
                return result

    # Strategy 3: Uploaded documents
    if supplementary_text and "controlled drug" in supplementary_text.lower():
        result["is_controlled"] = True
        match = re.search(r"schedule\s+(\d)", supplementary_text, re.IGNORECASE)
        if match:
            result["schedule"] = int(match.group(1))
            result["description"] = f"Schedule {result['schedule']} Controlled Drug"
        result["source"] = "Uploaded document"
        return result

    result["description"] = "Not a Controlled Drug"
    return result


# ===========================================================================
# ANALYSIS — CONTRAINDICATIONS & ICD-10 MAPPING
# ===========================================================================
def analyze_contraindications(bnf_data: dict, emc_data: dict, kb: KnowledgeBase, supplementary_text: str = "") -> list[dict]:
    """Extract contraindications and cautions, map to ICD-10."""
    items = []

    # Always include pregnancy/lactation
    items.append({
        "type": "contraindication",
        "condition": "Pregnancy and Lactation",
        "icd10_code": "BNF_F10_55",
        "description": "contraindication: Pregnancy and Lactation",
        "warning_level": 2,
        "source": "Standard",
        "pics_message_code": "[TO BE COMPLETED]",
    })

    # Extract from BNF
    for section_key, prefix, default_level in [
        ("contraindications", "contraindication", 2),
        ("cautions", "caution", 1),
    ]:
        text = bnf_data.get(section_key, "") or ""
        if text:
            # Split on common delimiters
            conditions = re.split(r"[|;·•]", text)
            for cond in conditions:
                cond = cond.strip()
                if len(cond) < 3 or cond.lower() in ["contraindications", "cautions"]:
                    continue
                # Try ICD-10 mapping
                icd_map = kb.find_icd10_mapping(cond)
                items.append({
                    "type": section_key.rstrip("s"),  # "contraindication" or "caution"
                    "condition": cond,
                    "icd10_code": icd_map["icd10_code"] if icd_map else "[NEEDS ICD-10 MAPPING]",
                    "description": f"{prefix}: {cond}",
                    "warning_level": default_level,
                    "source": "BNF",
                    "pics_message_code": "[TO BE COMPLETED]",
                })

    # Extract from EMC Section 4.3
    emc_contra = emc_data.get("4.3_contraindications", "") or ""
    if emc_contra:
        conditions = re.split(r"[.;]", emc_contra)
        for cond in conditions:
            cond = cond.strip()
            if len(cond) < 5:
                continue
            # Check if already captured from BNF
            already = any(
                cond.lower()[:20] in item["condition"].lower()
                for item in items
            )
            if not already:
                icd_map = kb.find_icd10_mapping(cond)
                items.append({
                    "type": "contraindication",
                    "condition": cond,
                    "icd10_code": icd_map["icd10_code"] if icd_map else "[NEEDS ICD-10 MAPPING]",
                    "description": f"contraindication: {cond}",
                    "warning_level": 2,
                    "source": "EMC SmPC 4.3",
                    "pics_message_code": "[TO BE COMPLETED]",
                })

    # Extract from uploaded documents
    if supplementary_text:
        # Look for contraindication/caution sections in uploaded PDFs
        for pattern, ci_type, level in [
            (r"(?:contraindicated?\s+in|must\s+not\s+be\s+(?:used|given|administered)\s+(?:in|to|if))\s+(.+?)(?:\.|$)", "contraindication", 2),
            (r"(?:caution\s+(?:in|with|if)|use\s+with\s+caution\s+in)\s+(.+?)(?:\.|$)", "caution", 1),
        ]:
            matches = re.findall(pattern, supplementary_text, re.IGNORECASE | re.MULTILINE)
            for cond in matches:
                cond = cond.strip()
                if len(cond) < 5 or len(cond) > 200:
                    continue
                already = any(
                    cond.lower()[:20] in item["condition"].lower()
                    for item in items
                )
                if not already:
                    icd_map = kb.find_icd10_mapping(cond)
                    items.append({
                        "type": ci_type,
                        "condition": cond,
                        "icd10_code": icd_map["icd10_code"] if icd_map else "[NEEDS ICD-10 MAPPING]",
                        "description": f"{ci_type}: {cond}",
                        "warning_level": level,
                        "source": "Uploaded document",
                        "pics_message_code": "[TO BE COMPLETED]",
                    })

    return items


# ===========================================================================
# ANALYSIS — INTERACTIONS
# ===========================================================================
def analyze_interactions(
    bnf_interactions: dict, bnf_data: dict, emc_data: dict, kb: KnowledgeBase
) -> dict:
    """Analyze interactions: map to drug classes, identify trends, assign warning levels."""
    interactions = []
    class_coverage = {}
    unclassed_drugs = []

    raw_interactions = bnf_interactions.get("interactions", [])

    for ix in raw_interactions:
        interacting = ix.get("interacting_drug", "")
        severity = ix.get("severity", "unknown")
        detail = ix.get("detail", "")

        # Assign warning level from severity
        if any(w in severity.lower() for w in ["contraindicated", "severe", "avoid"]):
            warning_level = 3
        elif any(w in severity.lower() for w in ["serious", "significant"]):
            warning_level = 2
        elif any(w in severity.lower() for w in ["moderate"]):
            warning_level = 1
        else:
            warning_level = 0

        # Check if interacting drug belongs to a known class
        drug_class = kb.find_interacting_drug_class(interacting)
        if drug_class:
            cls = drug_class["drug_class"]
            if cls not in class_coverage:
                class_coverage[cls] = {
                    "class_code": cls,
                    "class_description": drug_class["class_description"],
                    "drugs": [],
                    "all_covered": True,
                }
            class_coverage[cls]["drugs"].append(interacting)
        else:
            unclassed_drugs.append(interacting)

        interactions.append({
            "interacting_drug": interacting,
            "drug_class": drug_class["drug_class"] if drug_class else None,
            "is_class": "C" if drug_class else "",
            "severity": severity,
            "warning_level": warning_level,
            "detail": detail[:300],
            "pics_message_code": "[TO BE COMPLETED]",
            "message": detail[:200],
        })

    # Check coverage — flag if majority but not all drugs in a class
    human_review_flags = []
    for cls_code, info in class_coverage.items():
        # A simplistic check: if there are unclassed drugs that might belong
        for uc in unclassed_drugs:
            # Could this drug belong to this class?
            if any(keyword in uc.lower() for keyword in info["class_description"].lower().split()):
                human_review_flags.append(
                    f"[HUMAN REVIEW REQUIRED: '{uc}' may belong to class "
                    f"'{info['class_description']}' ({cls_code}) but was not found in the lookup]"
                )

    # Trend analysis — group by pharmacological effect keywords
    effect_keywords = {
        "hypokalaemia": ["potassium", "hypokalaemia", "hypokalemia"],
        "QT prolongation": ["qt", "qtc", "arrhythmia", "torsade"],
        "serotonin syndrome": ["serotonin", "ssri", "serotonergic"],
        "bleeding risk": ["bleed", "anticoagulant", "antiplatelet", "warfarin"],
        "CNS depression": ["sedation", "cns depression", "drowsiness", "respiratory depression"],
        "nephrotoxicity": ["renal", "nephrotoxic", "kidney"],
        "hepatotoxicity": ["hepatotoxic", "liver", "hepatic"],
        "hypotension": ["hypotension", "blood pressure"],
    }

    trends = []
    for effect, keywords in effect_keywords.items():
        matching = [
            ix for ix in interactions
            if any(kw in ix["detail"].lower() for kw in keywords)
        ]
        if len(matching) >= 2:
            trends.append({
                "effect": effect,
                "drug_count": len(matching),
                "suggestion": f"[SUGGESTED NEW CLASS: 'Drugs that can cause {effect}']"
                if not any(effect.lower() in str(v).lower() for v in class_coverage.values())
                else None,
            })

    return {
        "interactions": interactions,
        "class_coverage": class_coverage,
        "unclassed_drugs": unclassed_drugs,
        "human_review_flags": human_review_flags,
        "trends": trends,
    }


# ===========================================================================
# ANALYSIS — DOSE LIMITS
# ===========================================================================
def extract_dose_limits(bnf_data: dict, emc_data: dict, supplementary_text: str = "") -> dict:
    """Extract dose limits from BNF and EMC data.

    Parses the BNF indications_and_dose section which uses pipe-separated
    content from h2 heading extraction. Splits into meaningful dose entries
    and categorises as adult vs paediatric.
    """
    result = {
        "adult": [],
        "paediatric": [],
        "prn": [],
        "same_paediatric_as_adult": True,
    }

    dose_text = bnf_data.get("indications_and_dose", "") or ""
    emc_dose = emc_data.get("4.2_posology", "") or ""

    if not dose_text and not emc_dose:
        return result

    # The BNF dose text comes as pipe-separated content. Split into segments.
    segments = [s.strip() for s in re.split(r"\s*\|\s*", dose_text) if s.strip()]

    # Track current context (indication, route, age group)
    current_indication = ""
    current_route = ""
    current_age = ""

    for seg in segments:
        seg_lower = seg.lower()

        # Detect indication headings (typically capitalized or contain keywords)
        if re.match(r"^(?:For\s+)?[A-Z][\w\s]+(?:infection|disease|prophylaxis|treatment|eradication)", seg):
            current_indication = seg
            continue

        # Detect route
        route_match = re.match(r"^By\s+([\w\s]+?)(?:\s*$|\s*\|)", seg, re.IGNORECASE)
        if route_match:
            current_route = route_match.group(1).strip()
            # If the segment continues after the route, keep the rest
            remaining = seg[route_match.end():].strip()
            if remaining and len(remaining) > 10:
                seg = remaining
            else:
                continue

        # Detect age group
        is_adult = bool(re.search(r"\b(?:adult|18\s*years?\s*and\s*over|over\s*18)\b", seg_lower))
        is_paediatric = bool(re.search(
            r"\b(?:child|paediatric|neonat|infant|month|year)\b.*\b(?:\d+\s*(?:mg|g|mcg|ml)|\d+\s*times?\s*a?\s*day|every\s*\d+\s*hours?)\b",
            seg_lower
        ))
        # Check for age range patterns like "Child 1-11 months", "Child 5-17 years"
        has_child_age = bool(re.search(r"\b(?:child|neonat|infant)\s+\d", seg_lower))

        # Only include segments that contain actual dose information
        has_dose = bool(re.search(
            r"\d+[\.\d]*\s*(?:mg|g|mcg|micrograms?|ml|units?|nanograms?)\b",
            seg_lower
        ))

        if not has_dose:
            # This might be a heading or route — save context
            if "adult" in seg_lower:
                current_age = "adult"
            elif any(w in seg_lower for w in ["child", "paediatric", "neonat"]):
                current_age = "paediatric"
            continue

        # Build a clean dose entry
        entry = {
            "source": "BNF",
        }

        # Compose a readable dose line
        parts = []
        if current_indication:
            parts.append(current_indication)
        if current_route:
            parts.append(f"By {current_route}")

        # Clean up the dose text — remove redundant pipes
        clean_dose = seg.strip()
        parts.append(clean_dose)

        entry["raw_text"] = " | ".join(parts) if len(parts) > 1 else clean_dose

        # Categorise
        if has_child_age or is_paediatric or current_age == "paediatric":
            result["paediatric"].append(entry)
            result["same_paediatric_as_adult"] = False
        else:
            result["adult"].append(entry)

    # Deduplicate adult entries (exact text match)
    seen_adult = set()
    deduped_adult = []
    for a in result["adult"]:
        key = a.get("raw_text", "")[:100]
        if key not in seen_adult:
            seen_adult.add(key)
            deduped_adult.append(a)
    result["adult"] = deduped_adult

    # Deduplicate paediatric entries
    seen_paed = set()
    deduped_paed = []
    for p in result["paediatric"]:
        key = p.get("raw_text", "")[:100]
        if key not in seen_paed:
            seen_paed.add(key)
            deduped_paed.append(p)
    result["paediatric"] = deduped_paed

    # Extract max dose values from both sources
    max_patterns = [
        r"(?:max(?:imum)?\.?\s*(?:single\s*)?dose?)[:\s]*(\d+[\.\d]*\s*(?:mg|g|mcg|ml|units?))",
        r"(?:max(?:imum)?\.?\s*(?:daily|per\s*day))[:\s]*(\d+[\.\d]*\s*(?:mg|g|mcg|ml|units?))",
        r"(?:max(?:imum)?\.?\s*(?:total|per\s*(?:24|day)))[:\s]*(\d+[\.\d]*\s*(?:mg|g|mcg|ml|units?))",
    ]
    for pattern in max_patterns:
        for text in [dose_text, emc_dose, supplementary_text]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                result["adult"].append({"max_dose": m, "source": "BNF/EMC"})

    return result


# ===========================================================================
# ANALYSIS — RESULT WARNINGS
# ===========================================================================
def extract_result_warnings(bnf_data: dict, emc_data: dict, supplementary_text: str = "") -> list[dict]:
    """Extract result-based warnings (eGFR, ALT, etc.) and format as PICS syntax."""
    warnings = []
    texts = [
        bnf_data.get("renal_impairment", "") or "",
        bnf_data.get("hepatic_impairment", "") or "",
        bnf_data.get("monitoring_requirements", "") or "",
        emc_data.get("4.4_special_warnings", "") or "",
        emc_data.get("4.2_posology", "") or "",
        supplementary_text,
    ]

    combined = " ".join(texts)

    # Patterns for result-based thresholds
    result_patterns = [
        (r"(?:eGFR|GFR)\s*[<>≤≥]\s*(\d+)\s*(?:ml/min|mL/min)", "eGFR", "ml/min"),
        (r"(?:creatinine\s*clearance|CrCl)\s*[<>≤≥]\s*(\d+)\s*(?:ml/min|mL/min)", "CrCl", "ml/min"),
        (r"(?:ALT|alanine\s*transaminase)\s*[>≥]\s*(\d+)\s*(?:times?|x|×)\s*(?:ULN|upper)", "ALT", "x ULN"),
        (r"(?:AST|aspartate)\s*[>≥]\s*(\d+)\s*(?:times?|x|×)\s*(?:ULN|upper)", "AST", "x ULN"),
        (r"(?:platelet|plt)\s*(?:count)?\s*[<>≤≥]\s*(\d+)", "Platelets", "x10^9/L"),
        (r"(?:neutrophil)\s*(?:count)?\s*[<>≤≥]\s*(\d+[\.\d]*)", "Neutrophils", "x10^9/L"),
        (r"(?:potassium|K\+?)\s*[<>≤≥]\s*(\d+[\.\d]*)\s*(?:mmol)", "Potassium", "mmol/L"),
        (r"(?:age|aged?)\s*[>≥]\s*(\d+)\s*(?:years?|yrs?)", "Age", "years"),
        (r"(?:weight|body\s*weight)\s*[<>≤≥]\s*(\d+)\s*(?:kg)", "Weight", "kg"),
    ]

    for pattern, result_name, units in result_patterns:
        matches = re.finditer(pattern, combined, re.IGNORECASE)
        for match in matches:
            value = match.group(1)
            # Get surrounding context for the message
            start = max(0, match.start() - 100)
            end = min(len(combined), match.end() + 200)
            context = combined[start:end].strip()

            # Determine comparator from original text
            comparator_match = re.search(r"[<>≤≥]=?", match.group(0))
            comparator = comparator_match.group(0) if comparator_match else "<"

            # Determine action from context
            action = "Review dose"
            if re.search(r"(?:discontinue|stop|withhold|avoid|contraindicated)", context, re.I):
                action = "Discontinue treatment"
                level = 3
            elif re.search(r"(?:reduce|decrease|lower|halve)", context, re.I):
                action = "Reduce dose"
                level = 2
            elif re.search(r"(?:caution|monitor|consider)", context, re.I):
                action = "Use with caution — monitor closely"
                level = 1
            else:
                level = 2

            warnings.append({
                "result": result_name,
                "comparator": comparator,
                "value": value,
                "units": units,
                "message": action,
                "target": "Doctor",
                "warning_level": level,
                "validity_days": 7,
                "pics_syntax": f"{{{{{{{result_name}{comparator}{value}{units}, {action}, Doctor, Level {level}, Validity 7 days}}}}}}",
                "context": context[:200],
            })

    return warnings


# ===========================================================================
# ANALYSIS — FORMS & ROUTES
# ===========================================================================
def extract_forms_and_routes(bnf_data: dict, emc_data: dict, kb: KnowledgeBase) -> list[dict]:
    """Extract available forms and routes from BNF/EMC and cross-ref with FormRoute."""
    forms = []

    # From BNF medicinal forms
    med_forms_text = bnf_data.get("medicinal_forms", "") or ""
    # Common form names
    form_patterns = [
        "tablet", "capsule", "oral solution", "oral suspension", "injection",
        "infusion", "cream", "ointment", "gel", "eye drops", "ear drops",
        "nasal spray", "inhaler", "suppository", "pessary", "patch",
        "powder for solution", "granules", "chewable tablet", "dispersible tablet",
        "modified-release tablet", "modified-release capsule", "effervescent tablet",
    ]

    for form_name in form_patterns:
        if form_name.lower() in med_forms_text.lower():
            # Determine likely routes for this form
            routes = _form_to_routes(form_name)
            for route in routes:
                forms.append({
                    "form": form_name.title(),
                    "route": route,
                    "licensed": "Y",
                    "formulary_status": "[CHECK]",
                })

    # Add enteral routes for oral forms
    oral_forms = [f for f in forms if f["route"] == "Oral"]
    for of in oral_forms:
        for enteral in ["Nasogastric", "Gastrostomy", "Nasojejunal", "Jejunostomy"]:
            forms.append({
                "form": of["form"],
                "route": enteral,
                "licensed": "N",
                "formulary_status": "[CHECK]",
            })

    return forms


def _form_to_routes(form_name: str) -> list[str]:
    """Map a dosage form to its primary routes."""
    form_lower = form_name.lower()
    if any(w in form_lower for w in ["tablet", "capsule", "solution", "suspension", "granule", "dispersible", "effervescent", "chewable"]):
        return ["Oral"]
    if "injection" in form_lower:
        return ["Intravenous", "Intramuscular", "Subcutaneous"]
    if "infusion" in form_lower:
        return ["Intravenous Infusion"]
    if any(w in form_lower for w in ["cream", "ointment", "gel"]):
        return ["Topical"]
    if "eye drop" in form_lower:
        return ["Both Eyes"]
    if "ear drop" in form_lower:
        return ["Both Ears"]
    if "nasal" in form_lower:
        return ["Both Nostrils"]
    if "inhaler" in form_lower:
        return ["Inhaled"]
    if "suppository" in form_lower:
        return ["Rectal"]
    if "pessary" in form_lower:
        return ["Vaginal"]
    if "patch" in form_lower:
        return ["Topical"]
    return ["Oral"]


# ===========================================================================
# ANALYSIS — UNCONDITIONAL MESSAGES
# ===========================================================================
def extract_unconditional_messages(bnf_data: dict, emc_data: dict, supplementary_text: str = "") -> list[dict]:
    """Extract messages that should always be displayed (no trigger condition).

    Filters out BNF navigation/reference text and only keeps genuine clinical messages.
    """
    messages = []

    # Noise phrases to filter out — these are BNF navigation text, chapter headings,
    # or cross-reference boilerplate that should not appear as clinical messages
    noise_patterns = [
        r"^for\s+choice\s+of\s+antibacterial\s+therapy",
        r"^for\s+choice\s+of\s+anti",
        r"^antibacterials?,?\s*use\s+for\s+prophylaxis$",
        r"^in\s+(?:children|adults):?$",
        r"^(?:chapter|section)\s+\d",
        r"^(?:see\s+)?(?:bnf|nice|mhra)\b",
        r"^(?:for|see)\s+(?:further|more)\s+information",
        r"^(?:treatment|management)\s+summary",
        r"^search\b",
        r"^home\b",
        r"^about\b",
        r"^contact\b",
        r"^related\s+(?:drugs|treatment)",
        r"^https?://",
        r"^back\s+to\s+top",
        r"^\d+\.\d+",  # Section numbers like "5.1"
    ]
    noise_res = [re.compile(p, re.IGNORECASE) for p in noise_patterns]

    # Exact-match noise phrases
    noise_exact = {
        "prescribing and dispensing information",
        "patient and carer advice",
        "medicinal forms",
        "monitoring requirements",
        "national funding/access decisions",
        "less suitable for prescribing",
        "exceptions to legal category",
        "profession specific information",
        "dental practitioners' formulary",
    }

    def _is_noise(text: str) -> bool:
        """Return True if the text is navigation/reference noise."""
        t = text.lower().strip()
        if t in noise_exact:
            return True
        for nr in noise_res:
            if nr.search(t):
                return True
        # Too short to be a meaningful clinical message
        if len(t) < 15:
            return True
        # Generic cross-reference headings (e.g. "Ear infections, antibacterial therapy")
        if t.endswith("antibacterial therapy") and len(t) < 60:
            return True
        # Bare indication names that are just cross-reference headings
        bare_indication_keywords = [
            "infections,", "prophylaxis", "peptic ulceration",
            "helicobacter pylori", "lyme disease", "oral bacterial infections",
            "urinary-tract infections", "oropharyngeal infections",
        ]
        # Only filter if text is JUST the heading (short) — not if it contains dosing detail
        if any(kw in t for kw in bare_indication_keywords) and len(t) < 60:
            return True
        return False

    # Extract from BNF prescribing and dispensing info
    prescribing = bnf_data.get("prescribing_and_dispensing", "") or ""
    if prescribing:
        # Split on pipe (our h2 content separator) and periods
        sentences = re.split(r"[|]", prescribing)
        for s in sentences:
            s = s.strip()
            if _is_noise(s):
                continue
            target = "N" if any(w in s.lower() for w in ["administer", "give", "infuse", "inject"]) else "P"
            messages.append({
                "message": s[:200],
                "target": target,
                "form": "ALL",
                "warning_level": 0,
                "pics_message_code": "[TO BE COMPLETED]",
                "source": "BNF",
            })

    # Extract from BNF important safety information
    safety = bnf_data.get("important_safety", "") or ""
    if safety:
        sentences = re.split(r"[|]", safety)
        for s in sentences:
            s = s.strip()
            if _is_noise(s) or len(s) < 20:
                continue
            messages.append({
                "message": s[:200],
                "target": "P",
                "form": "ALL",
                "warning_level": 1,
                "pics_message_code": "[TO BE COMPLETED]",
                "source": "BNF Important Safety",
            })

    # Extract from BNF patient and carer advice
    patient_advice = bnf_data.get("patient_carer_advice", "") or ""
    if patient_advice:
        sentences = re.split(r"[|]", patient_advice)
        for s in sentences:
            s = s.strip()
            if _is_noise(s) or len(s) < 20:
                continue
            messages.append({
                "message": s[:200],
                "target": "P",
                "form": "ALL",
                "warning_level": 0,
                "pics_message_code": "[TO BE COMPLETED]",
                "source": "BNF Patient Advice",
            })

    # Check EMC 4.4 for key warnings
    warnings_text = emc_data.get("4.4_special_warnings", "") or ""
    must_show_patterns = [
        r"((?:must|should)\s+(?:not\s+)?be\s+(?:withdrawn|stopped|discontinued)\s+(?:suddenly|abruptly)[\w\s,.]*)",
        r"((?:swallow|take)\s+(?:whole|with\s+(?:water|food|plenty))[\w\s,.]*)",
        r"((?:do\s+not\s+(?:crush|chew|break|split))[\w\s,.]*)",
        r"((?:take\s+(?:on\s+an?\s+empty\s+stomach|with\s+food|before\s+food|after\s+food))[\w\s,.]*)",
        r"((?:patients?\s+should\s+be\s+(?:advised|warned|told|counselled)\s+[\w\s,.]{10,}))",
    ]
    for pattern in must_show_patterns:
        matches = re.findall(pattern, warnings_text, re.IGNORECASE)
        for m in matches:
            messages.append({
                "message": m.strip()[:200],
                "target": "P",
                "form": "ALL",
                "warning_level": 1,
                "pics_message_code": "[TO BE COMPLETED]",
                "source": "EMC 4.4",
            })

    # Extract key warnings from uploaded documents
    if supplementary_text:
        doc_patterns = [
            r"((?:must|should)\s+(?:not\s+)?be\s+(?:withdrawn|stopped|discontinued)\s+(?:suddenly|abruptly)[\w\s,.]*)",
            r"((?:do\s+not\s+(?:crush|chew|break|split|halve))[\w\s,.]*)",
            r"((?:swallow|take)\s+(?:whole|with\s+(?:water|food|plenty))[\w\s,.]*)",
            r"((?:patients?\s+should\s+be\s+(?:advised|warned|told|counselled)\s+[\w\s,.]{10,}))",
            r"((?:black\s+triangle|additional\s+monitoring|▼)[\w\s,.]*)",
            r"((?:MHRA|NPSA|patient\s+safety)\s+(?:alert|warning|advice)[:\s]+[\w\s,.]{10,})",
        ]
        for pattern in doc_patterns:
            matches = re.findall(pattern, supplementary_text, re.IGNORECASE)
            for m in matches:
                m = m.strip()
                if len(m) < 15 or len(m) > 300:
                    continue
                # Check not already captured
                already = any(m[:30].lower() in msg["message"].lower() for msg in messages)
                if not already:
                    messages.append({
                        "message": m[:200],
                        "target": "P",
                        "form": "ALL",
                        "warning_level": 1,
                        "pics_message_code": "[TO BE COMPLETED]",
                        "source": "Uploaded document",
                    })

    return messages


# ===========================================================================
# COMPILE — FULL DRUGSHEET
# ===========================================================================
async def generate_drugsheet(
    drug_name: str,
    drug_form: str | None = None,
    uploaded_pdfs: list[dict] | None = None,
    progress_callback=None,
) -> dict:
    """
    Main orchestrator: gathers all data, runs analysis, compiles drugsheet.
    Returns a complete drugsheet dict.
    """
    today = date.today().isoformat()
    kb = KnowledgeBase()
    kb.load()

    drugsheet = {
        "drug_name": drug_name,
        "drug_form": drug_form,
        "generated_date": today,
        "references": [],
        "human_review_flags": [],
    }

    def _progress(msg):
        if progress_callback:
            progress_callback(msg)

    # Process uploaded PDFs
    if uploaded_pdfs:
        _progress("Processing uploaded documents...")
        drugsheet["supplementary_documents"] = []
        for pdf_info in uploaded_pdfs:
            extracted = extract_pdf_text(
                pdf_info["bytes"], pdf_info.get("name", "unknown.pdf")
            )
            drugsheet["supplementary_documents"].append(extracted)
            drugsheet["references"].append({
                "source": f"Uploaded document: {pdf_info.get('name', 'unknown')}",
                "url": "User-provided document",
                "accessed": today,
            })

    # Phase 1: Parallel data gathering
    _progress("Gathering data from BNF, EMC, and Formulary...")
    async with httpx.AsyncClient() as client:
        bnf_task = gather_bnf_data(client, drug_name)
        emc_task = gather_emc_data(client, drug_name)
        formulary_task = gather_formulary_data(client, drug_name, drug_form)
        interactions_task = gather_bnf_interactions(client, drug_name)

        bnf_data, emc_data, formulary_data, bnf_interactions = await asyncio.gather(
            bnf_task, emc_task, formulary_task, interactions_task
        )

    drugsheet["bnf_data"] = bnf_data
    drugsheet["emc_data"] = emc_data
    drugsheet["formulary_data"] = formulary_data

    # Add references
    if bnf_data.get("source"):
        drugsheet["references"].append({"source": "BNF", "url": bnf_data["source"], "accessed": today})
    if emc_data.get("source"):
        drugsheet["references"].append({"source": "EMC SmPC", "url": emc_data["source"], "accessed": today})
    if formulary_data.get("source"):
        drugsheet["references"].append({"source": "Birmingham Formulary", "url": formulary_data["source"], "accessed": today})

    # Build combined supplementary text from all uploaded PDFs
    supplementary_text = ""
    for doc in drugsheet.get("supplementary_documents", []):
        text = doc.get("full_text", "")
        if text:
            supplementary_text += f"\n--- {doc.get('filename', 'document')} ---\n{text}\n"

    # Phase 2: Analysis (all functions receive supplementary_text from uploaded PDFs)
    _progress("Checking controlled drug status...")
    drugsheet["controlled_drug"] = check_controlled_drug(drug_name, bnf_data, supplementary_text)

    _progress("Mapping drug classes...")
    drugsheet["drug_classes"] = kb.find_drug_classes(drug_name)
    drugsheet["tfqav_info"] = kb.get_tfqav_info(drug_name)

    _progress("Analyzing contraindications and ICD-10 mappings...")
    drugsheet["contraindications"] = analyze_contraindications(bnf_data, emc_data, kb, supplementary_text)

    _progress("Analyzing interactions...")
    drugsheet["interactions_analysis"] = analyze_interactions(bnf_interactions, bnf_data, emc_data, kb)
    drugsheet["human_review_flags"].extend(
        drugsheet["interactions_analysis"].get("human_review_flags", [])
    )

    _progress("Extracting unconditional messages...")
    drugsheet["unconditional_messages"] = extract_unconditional_messages(bnf_data, emc_data, supplementary_text)

    _progress("Extracting result warnings...")
    drugsheet["result_warnings"] = extract_result_warnings(bnf_data, emc_data, supplementary_text)

    # Phase 3: Dosing & Forms
    _progress("Extracting forms, routes, and dose limits...")
    drugsheet["forms_and_routes"] = extract_forms_and_routes(bnf_data, emc_data, kb)
    drugsheet["dose_limits"] = extract_dose_limits(bnf_data, emc_data, supplementary_text)

    # Formulary status for amber handling
    _progress("Compiling formulary details...")
    status = formulary_data.get("formulary_status", "").upper()
    amber_type = formulary_data.get("amber_type")
    drugsheet["is_amber"] = "AMBER" in status or amber_type is not None
    drugsheet["is_red"] = "RED" in status or "RESTRICTED" in status
    drugsheet["amber_type"] = amber_type

    if drugsheet["is_amber"]:
        amber_type = drugsheet.get("amber_type", "Pure Amber")
        if amber_type == "ESCA":
            drugsheet["unconditional_messages"].append({
                "message": f"This is an amber drug supported by ESCA. Please devolve prescribing back to primary care once stable. See APC website.",
                "target": "P", "form": "ALL", "warning_level": 1,
                "pics_message_code": "[TO BE COMPLETED]", "source": "Formulary",
            })
        elif amber_type == "RiCAD":
            drugsheet["unconditional_messages"].append({
                "message": f"This is an amber drug supported by RiCAD. Please devolve prescribing back to primary care once stable. See APC website.",
                "target": "P", "form": "ALL", "warning_level": 1,
                "pics_message_code": "[TO BE COMPLETED]", "source": "Formulary",
            })
        else:
            drugsheet["unconditional_messages"].append({
                "message": f"This is an amber drug. Please devolve prescribing back to primary care once stable. See APC website.",
                "target": "P", "form": "ALL", "warning_level": 1,
                "pics_message_code": "[TO BE COMPLETED]", "source": "Formulary",
            })

    _progress("Done!")
    return drugsheet


# ===========================================================================
# OUTPUT — REVIEW MARKDOWN
# ===========================================================================
def generate_review_markdown(ds: dict) -> str:
    """Generate human-reviewable markdown drug sheet."""
    today = ds.get("generated_date", date.today().isoformat())
    lines = [
        f"# Drug Sheet: {ds['drug_name']}",
        f"**Form:** {ds.get('drug_form', 'All forms')}",
        f"**Generated:** {today}",
        "",
    ]

    # Supplementary docs
    if ds.get("supplementary_documents"):
        lines.append("## Uploaded Supplementary Documents")
        for doc in ds["supplementary_documents"]:
            lines.append(f"- **{doc['filename']}** ({len(doc.get('pages', []))} pages)")
        lines.append("")

    # Table 1: Controlled Drug
    cd = ds.get("controlled_drug", {})
    lines.append("## Controlled Drug Status")
    lines.append(f"| Controlled Drug? | {'**Yes**' if cd.get('is_controlled') else 'No'} |")
    lines.append("|---|---|")
    if cd.get("is_controlled"):
        lines.append(f"| Schedule | {cd.get('schedule', '[CHECK]')} |")
        lines.append(f"| Description | {cd.get('description', '')} |")
    lines.append("")

    # Table 3: Formulary Status
    fd = ds.get("formulary_data", {})
    lines.append("## Formulary Status")
    lines.append(f"| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Primary Status | {fd.get('formulary_status', 'Not checked')} |")
    if ds.get("is_amber"):
        lines.append(f"| Amber Type | {ds.get('amber_type', 'Pure Amber')} |")
    if fd.get("local_notes"):
        notes = fd['local_notes'][:200]
        lines.append(f"| Local Notes | {notes} |")
    # Show all entries found across formulary pages
    all_entries = fd.get("all_entries", [])
    if len(all_entries) > 1:
        lines.append("")
        lines.append("### All Formulary Entries Found")
        lines.append("| Form/Context | Status |")
        lines.append("|---|---|")
        for entry in all_entries:
            # Extract a short description (first 80 chars of the entry text)
            desc = entry["text"][:80].replace("|", "/")
            lines.append(f"| {desc} | {entry['status']} |")
    lines.append("")

    # Table 5: Redirects
    lines.append("## Redirects")
    emc_name = ds.get("emc_data", {}).get("product_name", "")
    bnf_title = ds.get("bnf_data", {}).get("title", "")
    if emc_name and bnf_title and emc_name.lower() != bnf_title.lower():
        lines.append(f"- Brand: {emc_name} -> Generic: {bnf_title}")
    else:
        lines.append("- No redirects identified")
    lines.append("")

    # Table 9: Strengths & dm+d Codes
    lines.append("## Available Strengths & dm+d Codes")
    tfq = ds.get("tfqav_info", [])
    if tfq:
        lines.append("| Strength | Form | VTM | VMP/AMP Description | dm+d? |")
        lines.append("|---|---|---|---|---|")
        for t in tfq[:15]:
            lines.append(
                f"| {t['value']} {t['units']} | {t['form_desc']} | "
                f"{t['generic']} | {t['trade_desc']} | {t['is_dmd']} |"
            )
    else:
        lines.append("*No entries found in TFQavSummary. Check dm+d browser manually.*")
    lines.append("")

    # Table 10: Drug Classes
    lines.append("## Drug Classes")
    classes = ds.get("drug_classes", [])
    if classes:
        lines.append("| Drug Class | PICS Code |")
        lines.append("|---|---|")
        for c in classes:
            lines.append(f"| {c['class_description']} | {c['drug_class']} |")
    else:
        lines.append("*No matching drug classes found. Manual mapping required.*")
    lines.append("")

    # Table 11: Contraindications & Cautions
    lines.append("## Contraindications & Cautions")
    contras = ds.get("contraindications", [])
    if contras:
        lines.append("| Condition + ICD-10 | PICS Code | Message | Level |")
        lines.append("|---|---|---|---|")
        for c in contras:
            lines.append(
                f"| {c['description']} [{c['icd10_code']}] | "
                f"{c['pics_message_code']} | | {c['warning_level']} |"
            )
    lines.append("")

    # Table 12: Interactions
    lines.append("## Interactions")
    ix_data = ds.get("interactions_analysis", {})
    interactions = ix_data.get("interactions", [])
    if interactions:
        lines.append("| Drug/Class [Code] | Class? | PICS Code | Message | Level |")
        lines.append("|---|---|---|---|---|")
        for ix in interactions[:30]:
            code = ix.get("drug_class", ix.get("interacting_drug", ""))
            lines.append(
                f"| {ix['interacting_drug']} [{code}] | {ix['is_class']} | "
                f"{ix['pics_message_code']} | {ix['detail'][:80]} | {ix['warning_level']} |"
            )

    # Human review flags
    flags = ix_data.get("human_review_flags", [])
    if flags:
        lines.append("")
        for f in flags:
            lines.append(f"**{f}**")

    # Trends
    trends = ix_data.get("trends", [])
    if trends:
        lines.append("")
        lines.append("### Interaction Trends")
        for t in trends:
            lines.append(f"- **{t['effect']}**: {t['drug_count']} interacting drugs")
            if t.get("suggestion"):
                lines.append(f"  - {t['suggestion']}")
    lines.append("")

    # Table 13: Unconditional Messages
    lines.append("## Unconditional Messages")
    msgs = ds.get("unconditional_messages", [])
    if msgs:
        lines.append("| Message | PICS Code | P/N | Form | Level |")
        lines.append("|---|---|---|---|---|")
        for m in msgs:
            lines.append(
                f"| {m['message'][:100]} | {m['pics_message_code']} | "
                f"{m['target']} | {m['form']} | {m['warning_level']} |"
            )
    lines.append("")

    # Table 15: Result Warnings
    lines.append("## Result Warnings & Other Information")
    rw = ds.get("result_warnings", [])
    if rw:
        for w in rw:
            lines.append(f"- {w['pics_syntax']}")
    else:
        lines.append("*No result-based warnings extracted. Review BNF/EMC renal/hepatic sections manually.*")
    lines.append("")

    # Tables 16-17: Forms & Routes
    lines.append("## Forms & Routes")
    forms = ds.get("forms_and_routes", [])
    if forms:
        lines.append("| Form | Route | Licensed | Formulary |")
        lines.append("|---|---|---|---|")
        for f in forms:
            lines.append(f"| {f['form']} | {f['route']} | {f['licensed']} | {f['formulary_status']} |")
    lines.append("")

    # Table 20: Adult Dose Limits
    lines.append("## Dose Limits")
    dl = ds.get("dose_limits", {})
    adult = dl.get("adult", [])
    if adult:
        lines.append("### Adult")
        for a in adult:
            if "max_dose" in a:
                lines.append(f"- **Max dose:** {a['max_dose']} (Source: {a['source']})")
            else:
                lines.append(f"- {a['raw_text'][:200]} (Source: {a['source']})")

    # Table 22: Paediatric
    if not dl.get("same_paediatric_as_adult", True):
        lines.append("### Paediatric (differs from adult)")
        for p in dl.get("paediatric", []):
            lines.append(f"- {p['raw_text'][:200]} (Source: {p['source']})")
    else:
        lines.append("### Paediatric: Same as adult settings")
    lines.append("")

    # Manual fields
    lines.append("## Fields Requiring Manual Completion")
    lines.append("| Field | Status |")
    lines.append("|---|---|")
    lines.append("| TRAC Date / Ivanti Ticket | [TO BE COMPLETED] |")
    lines.append("| GENERIC / TRADE Codes | [TO BE COMPLETED] |")
    lines.append("| Prescriber Privilege Restriction | [TO BE COMPLETED] |")
    lines.append("| Directorate Availability | [TO BE COMPLETED] |")
    lines.append("| Blueteq Drug? | [TO BE COMPLETED — check Blueteq website] |")
    lines.append("| PICS Message Codes (all tables) | [TO BE COMPLETED] |")
    lines.append("| Review Sign-off | [TO BE COMPLETED] |")
    lines.append("")

    # Human review flags (all)
    all_flags = ds.get("human_review_flags", [])
    if all_flags:
        lines.append("## Items Requiring Human Review")
        for f in all_flags:
            lines.append(f"- **{f}**")
        lines.append("")

    # References
    lines.append("## References")
    lines.append("| Source | URL | Accessed |")
    lines.append("|---|---|---|")
    for ref in ds.get("references", []):
        lines.append(f"| {ref['source']} | {ref['url']} | {ref['accessed']} |")
    lines.append("")

    # Supplementary document summaries
    if ds.get("supplementary_documents"):
        lines.append("## Supplementary Document Extracts")
        for doc in ds["supplementary_documents"]:
            lines.append(f"### {doc['filename']}")
            text = doc.get("full_text", "")
            if text:
                lines.append(f"```\n{text[:3000]}\n```")
            if doc.get("error"):
                lines.append(f"*Error reading PDF: {doc['error']}*")
            lines.append("")

    return "\n".join(lines)


# ===========================================================================
# OUTPUT — EPMA JSON
# ===========================================================================
def generate_epma_json(ds: dict) -> dict:
    """Generate structured JSON for PICS EPMA data entry."""
    today = ds.get("generated_date", date.today().isoformat())

    epma = {
        "metadata": {
            "drug_name": ds["drug_name"],
            "drug_form": ds.get("drug_form"),
            "generated_date": today,
            "template_version": "Non-infusion Drugsheet v3.6",
        },
        "table_1_controlled_drug": ds.get("controlled_drug", {}),
        "table_3_formulary": {
            "status": ds.get("formulary_data", {}).get("formulary_status"),
            "amber_type": ds.get("amber_type"),
            "is_amber": ds.get("is_amber", False),
            "is_red": ds.get("is_red", False),
            "local_notes": ds.get("formulary_data", {}).get("local_notes"),
        },
        "table_5_redirects": {
            "brand_name": ds.get("emc_data", {}).get("product_name"),
            "generic_name": ds.get("bnf_data", {}).get("title"),
        },
        "table_7_prescriber_privilege": "[TO BE COMPLETED]",
        "table_8_directorates": "[TO BE COMPLETED]",
        "table_9_strengths": ds.get("tfqav_info", []),
        "table_10_drug_classes": ds.get("drug_classes", []),
        "table_11_contraindications": ds.get("contraindications", []),
        "table_12_interactions": ds.get("interactions_analysis", {}).get("interactions", []),
        "table_13_unconditional_messages": ds.get("unconditional_messages", []),
        "table_15_result_warnings": ds.get("result_warnings", []),
        "table_16_forms_routes": ds.get("forms_and_routes", []),
        "table_20_adult_dose_limits": ds.get("dose_limits", {}).get("adult", []),
        "table_21_same_paediatric": ds.get("dose_limits", {}).get("same_paediatric_as_adult", True),
        "table_22_paediatric_dose_limits": ds.get("dose_limits", {}).get("paediatric", []),
        "table_23_references": ds.get("references", []),
        "human_review_flags": ds.get("human_review_flags", []),
        "interaction_trends": ds.get("interactions_analysis", {}).get("trends", []),
    }

    return epma


# ===========================================================================
# SAVE OUTPUTS
# ===========================================================================
def save_outputs(ds: dict) -> tuple[str, str]:
    """Save both output formats and return file paths."""
    slug = ds["drug_name"].lower().replace(" ", "_")

    # Markdown
    md_path = OUTPUT_DIR / f"{slug}_drugsheet_review.md"
    md_content = generate_review_markdown(ds)
    md_path.write_text(md_content, encoding="utf-8")

    # JSON
    json_path = OUTPUT_DIR / f"{slug}_drugsheet_epma.json"
    epma = generate_epma_json(ds)
    json_path.write_text(json.dumps(epma, indent=2, default=str), encoding="utf-8")

    return str(md_path), str(json_path)
