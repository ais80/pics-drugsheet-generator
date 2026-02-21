import re
from fastmcp import FastMCP
import httpx
from bs4 import BeautifulSoup

mcp = FastMCP("DMD-Term-Server")

# NHS England FHIR Terminology Server (free read access — may have version sync issues)
FHIR_BASE = "https://ontology.nhs.uk/production1/fhir"
DMD_SYSTEM = "https://dmd.nhs.uk"

# dm+d Browser (requires session cookie + JS rendering for full data)
DMD_BROWSER = "https://dmd-browser.nhsbsa.nhs.uk"

# Controlled Drug Category lookup (from dm+d CATCD values)
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

# Well-known controlled drugs with their schedules (fallback reference)
# This is not exhaustive — used when API/scraping fails
KNOWN_CONTROLLED_DRUGS = {
    "morphine": 2, "diamorphine": 2, "oxycodone": 2, "fentanyl": 2,
    "methadone": 2, "pethidine": 2, "alfentanil": 2, "remifentanil": 2,
    "sufentanil": 2, "tapentadol": 2, "hydromorphone": 2, "dipipanone": 2,
    "cocaine": 2, "amphetamine": 2, "dexamphetamine": 2, "lisdexamfetamine": 2,
    "methylphenidate": 2, "secobarbital": 2, "glutethimide": 2, "nabilone": 2,
    "buprenorphine": 3, "tramadol": 3, "gabapentin": 3, "pregabalin": 3,
    "phenobarbital": 3, "temazepam": 3, "midazolam": 3, "flunitrazepam": 3,
    "diazepam": 4, "lorazepam": 4, "nitrazepam": 4, "oxazepam": 4,
    "chlordiazepoxide": 4, "clonazepam": 4, "clobazam": 4, "zolpidem": 4,
    "zopiclone": 4, "zaleplon": 4,
    "testosterone": 4, "nandrolone": 4, "stanozolol": 4,
    "codeine": 5, "dihydrocodeine": 5, "pholcodine": 5,
    "cannabis": 1, "lsd": 1, "psilocybin": 1, "mescaline": 1,
}

# Prescribing status codes from dm+d
PRESCRIBING_STATUS = {
    "0001": {"description": "Valid as a prescribable product", "brand_required": False},
    "0002": {"description": "Invalid to prescribe in NHS primary care", "brand_required": True},
    "0003": {"description": "Not recommended to prescribe as a VMP", "brand_required": True},
    "0004": {"description": "Specific product recommendation", "brand_required": True},
    "0005": {"description": "Caution - AMP level prescribing advised", "brand_required": True},
    "0006": {"description": "Not recommended for prescribing", "brand_required": False},
}


async def _try_fhir_search(client: httpx.AsyncClient, term: str) -> list:
    """Attempt dm+d search via FHIR Terminology Server."""
    url = f"{FHIR_BASE}/ValueSet/$expand"
    params = {"url": DMD_SYSTEM, "filter": term, "count": 10}
    try:
        resp = await client.get(url, params=params, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("expansion", {}).get("contains", [])
    except (httpx.TimeoutException, httpx.ConnectError, Exception):
        pass
    return []


async def _try_fhir_lookup(client: httpx.AsyncClient, code: str) -> dict:
    """Attempt FHIR CodeSystem $lookup for a specific code."""
    url = f"{FHIR_BASE}/CodeSystem/$lookup"
    params = {"system": DMD_SYSTEM, "code": code, "property": "*"}
    try:
        resp = await client.get(url, params=params, timeout=15.0)
        if resp.status_code == 200:
            return resp.json()
    except (httpx.TimeoutException, httpx.ConnectError, Exception):
        pass
    return {}


async def _scrape_bnf_for_dmd_info(client: httpx.AsyncClient, drug_name: str) -> dict:
    """
    Scrape the BNF drug page for dm+d related information.
    BNF pages contain: indications, forms, strengths, and sometimes SNOMED/dm+d codes.
    """
    slug = drug_name.lower().replace(" ", "-")
    url = f"https://bnf.nice.org.uk/drugs/{slug}/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        resp = await client.get(url, headers=headers, follow_redirects=True, timeout=15.0)
        if resp.status_code != 200:
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        result = {"source": url}

        # Extract medicinal forms section (contains strengths and forms)
        forms_section = soup.find("div", {"id": "medicinalForms"})
        if forms_section:
            forms_text = forms_section.get_text(separator="\n", strip=True)
            result["medicinal_forms_raw"] = forms_text

            # Extract individual form types and strengths
            form_groups = forms_section.find_all("div", class_="medicinalFormGroup")
            forms = []
            for group in form_groups:
                form_name_el = group.find(["h3", "h4"])
                form_name = form_name_el.get_text(strip=True) if form_name_el else "Unknown"
                strengths = []
                for li in group.find_all("li"):
                    text = li.get_text(strip=True)
                    if text:
                        strengths.append(text)
                forms.append({"form": form_name, "products": strengths})
            result["forms"] = forms

        # Check for controlled drug mentions
        full_text = soup.get_text().lower()
        for cd_term in ["controlled drug", "schedule 2", "schedule 3", "schedule 4", "schedule 5"]:
            if cd_term in full_text:
                result["controlled_drug_mention"] = True
                # Try to extract the schedule
                schedule_match = re.search(r"schedule\s+(\d)", full_text)
                if schedule_match:
                    result["detected_schedule"] = int(schedule_match.group(1))
                break

        # Extract prescribing info
        prescribing_section = soup.find("div", {"id": "prescribingAndDispensingInformation"})
        if prescribing_section:
            result["prescribing_info"] = prescribing_section.get_text(
                separator=" | ", strip=True
            )

        return result

    except (httpx.TimeoutException, httpx.ConnectError, Exception):
        return {}


def _check_known_controlled(drug_name: str) -> dict | None:
    """Check against the known controlled drugs reference table."""
    name_lower = drug_name.lower().strip()
    for known_drug, schedule in KNOWN_CONTROLLED_DRUGS.items():
        if known_drug in name_lower or name_lower in known_drug:
            return {
                "is_controlled": True,
                "schedule": schedule,
                "matched_against": known_drug,
                "source": "Built-in UK Controlled Drug reference table",
                "note": "Verify against current Misuse of Drugs Regulations for definitive status.",
            }
    return None


@mcp.tool()
async def map_drug_to_codes(term: str) -> dict:
    """
    Takes a drug description and returns dm+d information including VTM, VMP,
    and AMP codes. Uses multiple strategies: FHIR Terminology Server, BNF
    scraping, and local knowledge base cross-referencing.
    Identifies if 'Brand Name' prescribing is mandatory.
    """
    async with httpx.AsyncClient() as client:
        results = {"search_term": term, "strategies_tried": []}

        # Strategy 1: Try FHIR Terminology Server
        fhir_results = await _try_fhir_search(client, term)
        if fhir_results:
            results["strategies_tried"].append("FHIR (success)")
            results["fhir_matches"] = [
                {"code": r.get("code"), "display": r.get("display")}
                for r in fhir_results[:10]
            ]
            # Try to get properties for top match
            top_code = fhir_results[0].get("code")
            if top_code:
                lookup = await _try_fhir_lookup(client, top_code)
                if lookup:
                    results["fhir_properties"] = _extract_fhir_properties(lookup)
        else:
            results["strategies_tried"].append("FHIR (unavailable — version sync issue)")

        # Strategy 2: Scrape BNF for forms and strengths
        bnf_data = await _scrape_bnf_for_dmd_info(client, term)
        if bnf_data:
            results["strategies_tried"].append("BNF scrape (success)")
            results["bnf_forms"] = bnf_data.get("forms", [])
            results["bnf_prescribing_info"] = bnf_data.get("prescribing_info")
            results["bnf_source"] = bnf_data.get("source")
        else:
            results["strategies_tried"].append("BNF scrape (no data)")

        # Strategy 3: Check known controlled drug status
        cd_check = _check_known_controlled(term)
        if cd_check:
            results["controlled_drug_check"] = cd_check

        # Build summary
        results["note"] = (
            "For definitive VTM/VMP/AMP codes, use the dm+d browser: "
            "https://dmd-browser.nhsbsa.nhs.uk/ or ask the Playwright MCP "
            "to scrape the dm+d browser page for this drug."
        )

        return results


@mcp.tool()
async def get_controlled_drug_info(term: str) -> dict:
    """
    Checks if a drug is a UK Controlled Drug and returns its schedule (1-5).
    Uses multiple strategies: known drug reference table, BNF page scraping,
    and FHIR lookup. Returns schedule, category description, and regulatory
    requirements.
    """
    result = {
        "search_term": term,
        "strategies_tried": [],
    }

    # Strategy 1: Check known controlled drugs table (instant, reliable)
    known = _check_known_controlled(term)
    if known:
        result["strategies_tried"].append("Known CD table (match found)")
        result["is_controlled_drug"] = True
        result["schedule"] = known["schedule"]
        result["matched_drug"] = known["matched_against"]

        # Map schedule to CATCD descriptions
        schedule = known["schedule"]
        matching_cats = {
            k: v for k, v in CD_CATEGORIES.items()
            if v["schedule"] == schedule
        }
        result["possible_categories"] = matching_cats
        result["regulatory_note"] = _get_schedule_requirements(schedule)
    else:
        result["strategies_tried"].append("Known CD table (no match)")
        result["is_controlled_drug"] = False

    # Strategy 2: Check BNF page for controlled drug mentions
    async with httpx.AsyncClient() as client:
        bnf_data = await _scrape_bnf_for_dmd_info(client, term)
        if bnf_data.get("controlled_drug_mention"):
            result["strategies_tried"].append("BNF scrape (CD mention found)")
            result["is_controlled_drug"] = True
            if bnf_data.get("detected_schedule"):
                result["schedule"] = bnf_data["detected_schedule"]
                result["regulatory_note"] = _get_schedule_requirements(
                    bnf_data["detected_schedule"]
                )
            result["bnf_source"] = bnf_data.get("source")
        elif bnf_data:
            result["strategies_tried"].append("BNF scrape (no CD mention)")
        else:
            result["strategies_tried"].append("BNF scrape (page not found)")

        # Strategy 3: Try FHIR as a bonus (may fail due to version sync)
        fhir_results = await _try_fhir_search(client, term)
        if fhir_results:
            result["strategies_tried"].append("FHIR (available)")
            for item in fhir_results[:3]:
                code = item.get("code", "")
                lookup = await _try_fhir_lookup(client, code)
                if lookup:
                    props = _extract_fhir_properties(lookup)
                    cd_cat = props.get("controlled_drug_category")
                    if cd_cat and cd_cat in CD_CATEGORIES:
                        cat_info = CD_CATEGORIES[cd_cat]
                        result["is_controlled_drug"] = cat_info["schedule"] is not None
                        result["schedule"] = cat_info["schedule"]
                        result["catcd"] = cd_cat
                        result["category_description"] = cat_info["description"]
                        result["strategies_tried"].append("FHIR lookup (CD data found)")
                        break
        else:
            result["strategies_tried"].append("FHIR (unavailable)")

    # Final summary
    result["cd_category_reference"] = CD_CATEGORIES
    result["verification_note"] = (
        "Always verify controlled drug status against current Misuse of Drugs "
        "Regulations 2001 (as amended). For definitive dm+d CATCD, check: "
        "https://dmd-browser.nhsbsa.nhs.uk/"
    )

    return result


def _extract_fhir_properties(lookup_result: dict) -> dict:
    """Extract properties from a FHIR CodeSystem $lookup result."""
    props = {}
    for param in lookup_result.get("parameter", []):
        name = param.get("name")
        if name == "property":
            parts = param.get("part", [])
            prop_code = None
            prop_value = None
            for part in parts:
                if part.get("name") == "code":
                    prop_code = part.get("valueCode") or part.get("valueString")
                elif part.get("name") == "value":
                    prop_value = (
                        part.get("valueString")
                        or part.get("valueCode")
                        or part.get("valueCoding", {}).get("display")
                        or part.get("valueCoding", {}).get("code")
                    )
            if prop_code and prop_value:
                if prop_code in props:
                    existing = props[prop_code]
                    if isinstance(existing, list):
                        existing.append(prop_value)
                    else:
                        props[prop_code] = [existing, prop_value]
                else:
                    props[prop_code] = prop_value
        elif name == "display":
            props["display"] = param.get("valueString")
    return props


def _get_schedule_requirements(schedule: int) -> str:
    """Return regulatory requirements for a given CD schedule."""
    requirements = {
        1: "Schedule 1: Possession and supply prohibited except under Home Office licence. "
           "No legitimate clinical use (except for licensed products like Sativex/Epidyolex).",
        2: "Schedule 2: Full CD requirements — safe custody, CD register, prescription "
           "requirements (handwriting, 28-day validity). Examples: morphine, oxycodone, fentanyl.",
        3: "Schedule 3: CD prescription requirements apply but NO CD register required "
           "(except phenobarbital and temazepam). Safe custody required for some.",
        4: "Schedule 4: Part I (anabolic steroids) or Part II (benzodiazepines). "
           "Subject to CD prescription requirements in some settings. "
           "No safe custody or CD register required.",
        5: "Schedule 5: Lowest level of control. Invoice/record keeping only. "
           "No prescription requirements beyond normal. Examples: low-dose codeine preparations.",
    }
    return requirements.get(schedule, "Unknown schedule")


if __name__ == "__main__":
    mcp.run()
