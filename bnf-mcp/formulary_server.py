import urllib.parse

from fastmcp import FastMCP
import httpx
from bs4 import BeautifulSoup

mcp = FastMCP("Birmingham-Formulary")

BASE_URL = "http://www.birminghamandsurroundsformulary.nhs.uk"


@mcp.tool()
async def get_local_formulary_status(drug_name: str) -> dict:
    """
    Searches the Birmingham and Surrounds Formulary for a drug's
    commissioning status (Green, Amber, Red, etc.) and local notes.
    """
    # 1. Search the formulary
    search_url = f"{BASE_URL}/search.asp?query={urllib.parse.quote(drug_name)}"

    async with httpx.AsyncClient() as client:
        response = await client.get(search_url, follow_redirects=True)
        if response.status_code != 200:
            return {"error": "Could not access the Birmingham Formulary."}

        soup = BeautifulSoup(response.text, "html.parser")

        # 2. Parse search results
        links = soup.find_all("a", href=lambda x: x and "drug_details.asp" in x)

        if not links:
            return {"message": f"No local formulary entry found for '{drug_name}'."}

        # Take the first match for analysis
        detail_url = BASE_URL + "/" + links[0]["href"]
        detail_resp = await client.get(detail_url)
        detail_soup = BeautifulSoup(detail_resp.text, "html.parser")

        # 3. Extract Status and Notes
        status_box = detail_soup.find(
            lambda tag: tag.name == "td"
            and any(
                c in tag.text.upper() for c in ["GREEN", "AMBER", "RED", "GREY"]
            )
        )
        status = (
            status_box.get_text(strip=True)
            if status_box
            else "Status not explicitly found."
        )

        notes = detail_soup.find("div", id="prescribing-notes")
        if not notes:
            notes = detail_soup.find(string=lambda s: "Notes" in s)

        return {
            "drug": drug_name,
            "formulary_status": status,
            "local_notes": (
                notes.get_text(strip=True)
                if notes
                else "No specific local notes found."
            ),
            "link": detail_url,
        }


if __name__ == "__main__":
    mcp.run()
