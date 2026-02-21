"""
Drug Sheet Generator — Streamlit Web App
Simple interface to generate EPMA drug sheets for PICS.
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
)

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
# Sidebar — Drug Input
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Drug Details")

    drug_name = st.text_input(
        "Drug Name",
        placeholder="e.g. Amoxicillin, Methotrexate, Morphine",
        help="Enter the generic (non-proprietary) drug name",
    )

    drug_form = st.text_input(
        "Form (optional)",
        placeholder="e.g. Tablet, Capsule, Injection, or leave blank for all",
        help="Leave blank to generate for all available forms",
    )

    st.divider()

    # ---------------------------------------------------------------------------
    # File Upload
    # ---------------------------------------------------------------------------
    st.header("Supplementary Documents")
    st.markdown(
        """
        Upload any research documents to include in the drug sheet generation.
        Supported: **PDF files** from any of these sources:
        """
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

    # Source labels for reference
    st.markdown(
        """
        **Recognised sources:**
        - BNF / BNFC printouts
        - MHRA Safety alerts
        - EMEA / EMA documents
        - Liverpool Drug Interactions
        - NICE Technology Appraisals
        - Trust guidelines / protocols
        - SmPC printouts
        """
    )

    st.divider()
    generate_btn = st.button(
        "Generate Drug Sheet",
        type="primary",
        use_container_width=True,
        disabled=not drug_name.strip(),
    )

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
if not drug_name.strip() and not generate_btn:
    st.info(
        "Enter a drug name in the sidebar and click **Generate Drug Sheet** to begin. "
        "You can optionally upload PDF documents (BNF, MHRA, Liverpool interactions, "
        "NICE TAs, guidelines) to include in the analysis."
    )
    st.stop()

if generate_btn and drug_name.strip():
    # Process uploaded files
    pdf_data = []
    if uploaded_files:
        for f in uploaded_files:
            pdf_data.append({"name": f.name, "bytes": f.read()})

    # Run generation
    progress_bar = st.progress(0)
    status_text = st.empty()
    steps_done = 0
    total_steps = 10

    def update_progress(msg: str):
        nonlocal steps_done
        steps_done += 1
        progress_bar.progress(min(steps_done / total_steps, 1.0))
        status_text.text(msg)

    with st.spinner(f"Generating drug sheet for **{drug_name}**..."):
        try:
            drugsheet = asyncio.run(
                generate_drugsheet(
                    drug_name=drug_name.strip(),
                    drug_form=drug_form.strip() if drug_form.strip() else None,
                    uploaded_pdfs=pdf_data if pdf_data else None,
                    progress_callback=update_progress,
                )
            )

            progress_bar.progress(1.0)
            status_text.text("Complete!")

            # Save outputs
            md_path, json_path = save_outputs(drugsheet)

            # Display results
            st.success(f"Drug sheet generated for **{drug_name}**")

            # Tabs for different views
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
                    file_name=f"{drug_name.lower().replace(' ', '_')}_drugsheet_review.md",
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
                    file_name=f"{drug_name.lower().replace(' ', '_')}_drugsheet_epma.json",
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
                if drugsheet.get("emc_data", {}).get("status") == "ok":
                    with st.expander("EMC SmPC Sections", expanded=False):
                        for key in [
                            "4.2_posology", "4.3_contraindications", "4.4_special_warnings",
                            "4.5_interactions", "4.6_fertility_pregnancy", "4.8_undesirable_effects",
                        ]:
                            val = drugsheet["emc_data"].get(key)
                            if val:
                                st.markdown(f"**Section {key}**")
                                st.text(val[:1000])
                else:
                    st.warning(f"EMC data: {drugsheet.get('emc_data', {}).get('status', 'unknown')}")

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

            # Summary sidebar
            st.sidebar.divider()
            st.sidebar.subheader("Output Files")
            st.sidebar.text(f"Review: {md_path}")
            st.sidebar.text(f"EPMA: {json_path}")

            # Warnings
            flags = drugsheet.get("human_review_flags", [])
            if flags:
                st.sidebar.divider()
                st.sidebar.subheader("Review Flags")
                for f in flags:
                    st.sidebar.warning(f)

        except Exception as e:
            st.error(f"Error generating drug sheet: {e}")
            import traceback
            st.code(traceback.format_exc())
