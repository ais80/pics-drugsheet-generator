"""
Drug Sheet Generator — Streamlit Web App
Simple interface to generate EPMA drug sheets for PICS.
Includes a cache system so previously generated sheets can be browsed.
"""

import asyncio
import json
import streamlit as st
from pathlib import Path

from generate import (
    generate_drugsheet,
    generate_review_markdown,
    generate_epma_json,
    save_outputs,
    search_drug_names,
    search_emc_products,
    validate_bnf_drug,
)

# ---------------------------------------------------------------------------
# Cache directory (stored alongside output/)
# ---------------------------------------------------------------------------
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_key(drug_name: str, drug_form: str | None = None) -> str:
    key = drug_name.strip().lower().replace(" ", "_")
    if drug_form:
        key += f"__{drug_form.strip().lower().replace(' ', '_')}"
    return key


def save_to_cache(drug_name: str, drug_form: str | None, drugsheet: dict):
    key = _cache_key(drug_name, drug_form)
    cache_file = CACHE_DIR / f"{key}.json"
    cache_file.write_text(json.dumps(drugsheet, indent=2, default=str), encoding="utf-8")


def load_from_cache(drug_name: str, drug_form: str | None = None) -> dict | None:
    key = _cache_key(drug_name, drug_form)
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    return None


def list_cached_drugs() -> list[str]:
    if not CACHE_DIR.exists():
        return []
    names = []
    for f in sorted(CACHE_DIR.glob("*.json")):
        name = f.stem.replace("_", " ").replace("  ", " (")
        if "__" in f.stem:
            parts = f.stem.split("__", 1)
            name = f"{parts[0].replace('_', ' ')} ({parts[1].replace('_', ' ')})"
        else:
            name = f.stem.replace("_", " ")
        names.append((name, f.stem))
    return names


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="PICS Drug Sheet Generator",
    page_icon="💊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("PICS Drug Sheet Generator")
st.caption("Non-infusion Drugsheet v3.6 — Birmingham")

# ---------------------------------------------------------------------------
# Sidebar — Mode Selection
# ---------------------------------------------------------------------------
with st.sidebar:
    mode = st.radio("Mode", ["Generate New", "Browse Cached"], horizontal=True)

    st.divider()

    if mode == "Generate New":
        st.header("Drug Details")

        drug_query = st.text_input(
            "Drug Name",
            placeholder="e.g. Amoxicillin, Methotrexate, Morphine",
            help="Start typing to search — matching drugs will appear below",
        )

        # Show search suggestions as user types
        drug_name = drug_query  # default: use what they typed
        if drug_query and len(drug_query.strip()) >= 2:
            matches = search_drug_names(drug_query.strip(), max_results=10)
            if matches:
                # Build display options
                options = []
                for m in matches:
                    label = m["name"]
                    if m.get("trade") and m["trade"] != m["name"]:
                        label += f"  (trade: {m['trade']})"
                    options.append(label)

                selected = st.selectbox(
                    "Matching drugs",
                    options=["(use typed name)"] + options,
                    index=0,
                    help="Select a match or keep your typed name",
                )

                if selected != "(use typed name)":
                    # Extract just the drug name (before any trade name annotation)
                    drug_name = selected.split("  (trade:")[0].strip()
            else:
                st.caption("No matches found in Knowledge base — will try BNF directly")

        drug_form = st.text_input(
            "Form (optional)",
            placeholder="e.g. Tablet, Capsule, Injection, or leave blank for all",
            help="Leave blank to generate for all available forms",
        )

        st.divider()

        st.header("Supplementary Documents")
        st.markdown(
            "Upload any research documents to include in the drug sheet generation. "
            "Supported: **PDF files**."
        )

        uploaded_files = st.file_uploader(
            "Upload PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            help="BNF printouts, MHRA/EMEA documents, Liverpool drug interactions, NICE TAs, trust guidelines",
        )

        if uploaded_files:
            st.success(f"{len(uploaded_files)} file(s) uploaded")
            for f in uploaded_files:
                st.caption(f"- {f.name} ({f.size // 1024} KB)")

        st.divider()

        # EMC SmPC product selection
        st.header("EMC SmPC Sources")
        selected_emc = None
        if drug_name.strip() and len(drug_name.strip()) >= 3:
            if "emc_products" not in st.session_state or st.session_state.get("emc_search_drug") != drug_name.strip():
                with st.spinner("Searching EMC..."):
                    st.session_state.emc_products = asyncio.run(search_emc_products(drug_name.strip()))
                    st.session_state.emc_search_drug = drug_name.strip()

            emc_products = st.session_state.emc_products
            if emc_products:
                st.caption(f"{len(emc_products)} SmPC(s) found on EMC")
                emc_options = [p["name"] for p in emc_products]
                selected_indices = []
                for i, name in enumerate(emc_options):
                    if st.checkbox(name, value=(i == 0), key=f"emc_{i}"):
                        selected_indices.append(i)

                if selected_indices:
                    selected_emc = [emc_products[i] for i in selected_indices]
                    st.caption(f"{len(selected_emc)} selected")
                else:
                    st.warning("Select at least one SmPC")
            else:
                st.caption("No SmPC results found on EMC")

        st.divider()

        # Check if cached version exists
        use_cache = False
        if drug_name.strip():
            cached = load_from_cache(drug_name.strip(), drug_form.strip() if drug_form.strip() else None)
            if cached:
                st.info(f"Cached version available (generated {cached.get('generated_date', 'unknown')})")
                use_cache = st.checkbox("Use cached version", value=False)

        generate_btn = st.button(
            "Generate Drug Sheet",
            type="primary",
            use_container_width=True,
            disabled=not drug_name.strip(),
        )

    else:
        # Browse cached mode
        drug_name = ""
        drug_form = ""
        uploaded_files = None
        generate_btn = False
        use_cache = False

        st.header("Cached Drug Sheets")
        cached_list = list_cached_drugs()
        if not cached_list:
            st.warning("No cached drug sheets yet. Generate one first!")
        else:
            st.caption(f"{len(cached_list)} drug sheet(s) available")


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------
def display_drugsheet(drugsheet: dict, drug_label: str):
    """Render a drugsheet in all three tab views."""
    st.success(f"Drug sheet: **{drug_label}**")

    tab_review, tab_epma, tab_raw = st.tabs([
        "Human Review Format",
        "Programmer/EPMA Format",
        "Raw Data",
    ])

    with tab_review:
        md_content = generate_review_markdown(drugsheet)
        st.markdown(md_content)

        st.divider()
        st.download_button(
            "Download Review Markdown",
            data=md_content,
            file_name=f"{drug_label.lower().replace(' ', '_')}_drugsheet_review.md",
            mime="text/markdown",
        )

    with tab_epma:
        epma = generate_epma_json(drugsheet)
        json_str = json.dumps(epma, indent=2, default=str)
        st.code(json_str, language="json")

        st.divider()
        st.download_button(
            "Download EPMA JSON",
            data=json_str,
            file_name=f"{drug_label.lower().replace(' ', '_')}_drugsheet_epma.json",
            mime="application/json",
        )

    with tab_raw:
        st.subheader("BNF Data")
        if drugsheet.get("bnf_data", {}).get("status") == "ok":
            with st.expander("BNF Clinical Data", expanded=False):
                for key in [
                    "indications_and_dose", "contraindications", "cautions",
                    "interactions", "pregnancy", "breast_feeding",
                    "hepatic_impairment", "renal_impairment", "monitoring_requirements",
                    "medicinal_forms",
                ]:
                    val = drugsheet["bnf_data"].get(key)
                    if val:
                        st.markdown(f"**{key.replace('_', ' ').title()}**")
                        st.text(val[:1000])
        else:
            st.warning(f"BNF data: {drugsheet.get('bnf_data', {}).get('status', 'unknown')}")

        st.subheader("EMC SmPC Data")
        emc = drugsheet.get("emc_data", {})
        if emc.get("status") == "ok":
            smpc_count = emc.get("smpc_count", 1)
            if smpc_count > 1:
                st.info(f"Data merged from {smpc_count} SmPCs")
                if emc.get("all_sources"):
                    for src in emc["all_sources"]:
                        st.caption(f"- {src['product_name']}: {src['url']}")

            # Show individual SmPC details if available
            all_smpcs = emc.get("all_smpcs", [])
            if all_smpcs and len(all_smpcs) > 1:
                for smpc in all_smpcs:
                    if smpc.get("status") == "ok":
                        with st.expander(f"SmPC: {smpc['product_name']}", expanded=False):
                            for key in [
                                "4.2_posology", "4.3_contraindications", "4.4_special_warnings",
                                "4.5_interactions", "4.6_fertility_pregnancy", "4.8_undesirable_effects",
                            ]:
                                val = smpc.get(key)
                                if val:
                                    st.markdown(f"**Section {key}**")
                                    st.text(val[:1000])
            else:
                with st.expander("EMC SmPC Sections", expanded=False):
                    for key in [
                        "4.2_posology", "4.3_contraindications", "4.4_special_warnings",
                        "4.5_interactions", "4.6_fertility_pregnancy", "4.8_undesirable_effects",
                    ]:
                        val = emc.get(key)
                        if val:
                            st.markdown(f"**Section {key}**")
                            st.text(val[:1000])
        else:
            st.warning(f"EMC data: {emc.get('status', 'unknown')}")

        st.subheader("Formulary")
        st.json(drugsheet.get("formulary_data", {}))

        if drugsheet.get("supplementary_documents"):
            st.subheader("Uploaded Documents")
            for doc in drugsheet["supplementary_documents"]:
                with st.expander(doc["filename"]):
                    if doc.get("error"):
                        st.error(doc["error"])
                    else:
                        st.text(doc.get("full_text", "")[:5000])

    # Warnings in sidebar
    flags = drugsheet.get("human_review_flags", [])
    if flags:
        st.sidebar.divider()
        st.sidebar.subheader("Review Flags")
        for f in flags:
            st.sidebar.warning(f)


# ---------------------------------------------------------------------------
# Main area — Browse Cached
# ---------------------------------------------------------------------------
if mode == "Browse Cached":
    cached_list = list_cached_drugs()
    if cached_list:
        selected = st.selectbox(
            "Select a drug sheet",
            options=[c[0] for c in cached_list],
            index=0,
        )
        # Find the stem for the selected name
        stem = next(c[1] for c in cached_list if c[0] == selected)
        cache_file = CACHE_DIR / f"{stem}.json"
        drugsheet = json.loads(cache_file.read_text(encoding="utf-8"))
        display_drugsheet(drugsheet, selected)
    else:
        st.info("No cached drug sheets yet. Switch to **Generate New** to create one.")
    st.stop()

# ---------------------------------------------------------------------------
# Main area — Generate New
# ---------------------------------------------------------------------------
if not drug_name.strip() and not generate_btn:
    st.info(
        "Enter a drug name in the sidebar and click **Generate Drug Sheet** to begin. "
        "You can optionally upload PDF documents (BNF, MHRA, Liverpool interactions, "
        "NICE TAs, guidelines) to include in the analysis."
    )
    st.stop()

if generate_btn and drug_name.strip():
    # Use cached version if selected
    if use_cache:
        drugsheet = load_from_cache(drug_name.strip(), drug_form.strip() if drug_form.strip() else None)
        if drugsheet:
            st.info("Loaded from cache")
            display_drugsheet(drugsheet, drug_name.strip())
            st.stop()

    # Process uploaded files
    pdf_data = []
    if uploaded_files:
        for f in uploaded_files:
            pdf_data.append({"name": f.name, "bytes": f.read()})

    # Run generation
    progress_bar = st.progress(0)
    status_text = st.empty()
    progress_state = {"done": 0, "total": 10}

    def update_progress(msg: str):
        progress_state["done"] += 1
        progress_bar.progress(min(progress_state["done"] / progress_state["total"], 1.0))
        status_text.text(msg)

    with st.spinner(f"Generating drug sheet for **{drug_name}**..."):
        try:
            drugsheet = asyncio.run(
                generate_drugsheet(
                    drug_name=drug_name.strip(),
                    drug_form=drug_form.strip() if drug_form.strip() else None,
                    uploaded_pdfs=pdf_data if pdf_data else None,
                    progress_callback=update_progress,
                    selected_emc_products=selected_emc,
                )
            )

            progress_bar.progress(1.0)
            status_text.text("Complete!")

            # Save to cache
            save_to_cache(drug_name.strip(), drug_form.strip() if drug_form.strip() else None, drugsheet)

            # Save to output/
            try:
                md_path, json_path = save_outputs(drugsheet)
                st.sidebar.divider()
                st.sidebar.subheader("Output Files")
                st.sidebar.text(f"Review: {md_path}")
                st.sidebar.text(f"EPMA: {json_path}")
            except Exception:
                pass  # save_outputs may fail on cloud (read-only fs)

            # Display results
            display_drugsheet(drugsheet, drug_name.strip())

        except Exception as e:
            st.error(f"Error generating drug sheet: {e}")
            import traceback
            st.code(traceback.format_exc())
