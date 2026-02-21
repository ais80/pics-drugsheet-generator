from fastmcp import FastMCP
import httpx
from bs4 import BeautifulSoup

emc_mcp = FastMCP("EMC-SmPC-Analyzer")


@emc_mcp.tool()
async def get_smpc_details(drug_name: str) -> dict:
    """Fetches the official SmPC from EMC including Sections 4.2 (Dose) and 4.3 (Contraindications)."""
    # 1. Search for the drug to get the first product URL
    search_url = f"https://www.medicines.org.uk/emc/search?q={drug_name}"

    async with httpx.AsyncClient() as client:
        search_resp = await client.get(search_url)
        soup = BeautifulSoup(search_resp.text, "html.parser")

        # Find the first result link
        result_link = soup.find("a", class_="emc-product-name")
        if not result_link:
            return {"error": "Product not found on EMC."}

        product_url = "https://www.medicines.org.uk" + result_link["href"] + "/smpc"

        # 2. Fetch the actual SmPC
        smpc_resp = await client.get(product_url)
        smpc_soup = BeautifulSoup(smpc_resp.text, "html.parser")

        # Standard SmPC Section Mapping
        sections = {
            "4.2_posology": "4.2",
            "4.3_contraindications": "4.3",
            "4.4_special_warnings": "4.4",
            "4.5_interactions": "4.5",
            "4.6_fertility_pregnancy": "4.6",
            "4.8_undesirable_effects": "4.8",
        }

        results = {"source": product_url, "drug": drug_name}
        for key, section_num in sections.items():
            # EMC sections are usually identified by headers containing the section number
            header = smpc_soup.find(
                lambda tag: tag.name in ["h2", "h3"] and section_num in tag.text
            )
            if header:
                content = []
                for sibling in header.find_next_siblings():
                    if sibling.name in ["h2", "h3"]:
                        break  # Stop at next section
                    content.append(sibling.get_text(strip=True))
                results[key] = " ".join(content)

        return results


if __name__ == "__main__":
    emc_mcp.run()
