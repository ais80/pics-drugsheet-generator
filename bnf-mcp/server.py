import re
from fastmcp import FastMCP
import httpx
from bs4 import BeautifulSoup

mcp = FastMCP("BNF-Pro")

SECTIONS = {
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
    "patient_and_carer_advice": "patientAndCarerAdvice",
}


@mcp.tool()
async def get_interaction_detail(drug_a: str, drug_b: str) -> str:
    """Gets detailed interaction severity and clinical details between two drugs."""
    slug_a = drug_a.lower().replace(" ", "-")
    url = f"https://bnf.nice.org.uk/interactions/{slug_a}/"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return f"Interaction data for {drug_a} not found."

        soup = BeautifulSoup(resp.text, "html.parser")
        target = soup.find(string=re.compile(drug_b, re.IGNORECASE))
        if target:
            parent = target.find_parent("div", class_="interaction-message")
            return (
                parent.get_text(strip=True)
                if parent
                else "Interaction listed but details not found."
            )
        return f"No specific interaction found between {drug_a} and {drug_b} in BNF."


@mcp.tool()
async def analyze_drug(drug_name: str) -> dict:
    """
    Fetches comprehensive clinical data for a drug from the BNF.
    Includes: Dosing (by age), Safety, Renal/Hepatic adjustments, and Monitoring.
    """
    slug = drug_name.lower().replace(" ", "-")
    url = f"https://bnf.nice.org.uk/drugs/{slug}/"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, follow_redirects=True)
        if response.status_code != 200:
            return {"error": f"Drug '{drug_name}' not found on BNF. Checked URL: {url}"}

        soup = BeautifulSoup(response.text, "html.parser")
        results = {"drug": drug_name, "source": url}

        for key, section_id in SECTIONS.items():
            section = soup.find("div", {"id": section_id})
            if section:
                text = section.get_text(separator=" | ", strip=True)
                results[key] = text
            else:
                results[key] = "Information not available for this drug."

        return results


if __name__ == "__main__":
    mcp.run()
