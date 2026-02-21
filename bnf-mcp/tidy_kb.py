"""
Knowledge Base Tidying Script
Cleans and organizes Excel files in the Knowledge base folder.
"""

import os
import re
import shutil
import pandas as pd


KB_DIR = os.path.join(os.path.dirname(__file__), "..", "Knowledge base")
OUTPUT_DIR = os.path.join(KB_DIR, "cleaned")


def clean_drugs_to_classes(input_path: str, output_path: str):
    """Clean drugsToClasses — trim whitespace, normalize drug descriptions."""
    df = pd.read_excel(input_path)
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].str.strip()
    # Remove (dm+d) references
    if "drugDesc" in df.columns:
        df["drugDesc"] = df["drugDesc"].str.replace(
            r"\(dm\+d\)", "", regex=True, flags=re.IGNORECASE
        ).str.strip()
    df = df.dropna(how="all")
    df.to_excel(output_path, index=False)
    print(f"  Cleaned drugsToClasses -> {output_path} ({len(df)} rows)")


def clean_form_route(input_path: str, output_path: str):
    """Clean FormRoute — drop fully empty unnamed columns, fix header row."""
    df = pd.read_excel(input_path)
    # Drop columns that are entirely NaN
    df = df.dropna(axis=1, how="all")
    # Drop rows that are entirely NaN
    df = df.dropna(how="all")
    df.to_excel(output_path, index=False)
    print(f"  Cleaned FormRoute -> {output_path} ({df.shape[0]} rows, {df.shape[1]} cols)")


def clean_icd10_usage(input_path: str, output_path: str):
    """Clean ICD10_usage — promote the actual header row, drop empty rows."""
    df = pd.read_excel(input_path, header=None)
    # Find the row with 'CI description' to use as header
    header_idx = None
    for i, row in df.iterrows():
        if any(str(v).strip() == "CI description" for v in row.values if pd.notna(v)):
            header_idx = i
            break
    if header_idx is not None:
        df.columns = df.iloc[header_idx].values
        df = df.iloc[header_idx + 1 :].reset_index(drop=True)
    df = df.dropna(how="all")
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].str.strip()
    df.to_excel(output_path, index=False)
    print(f"  Cleaned ICD10_usage -> {output_path} ({len(df)} rows)")


def clean_tfqav_summary(input_path: str, output_path: str):
    """Clean TFQavSummary — trim strings, remove (dm+d) from descriptions."""
    df = pd.read_excel(input_path)
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].str.strip()
        df[col] = df[col].str.replace(
            r"\(dm\+d\)", "", regex=True, flags=re.IGNORECASE
        ).str.strip()
    df = df.dropna(how="all")
    df.to_excel(output_path, index=False)
    print(f"  Cleaned TFQavSummary -> {output_path} ({len(df)} rows)")


def organize_files():
    """Rename files to consistent snake_case .xlsx format and sort into subfolders."""
    renames = {
        "drugs_to_classes.xlsx": "cleaned/drugsToClasses.xlsx",
        "form_route.xlsx": "cleaned/FormRoute.xlsx",
        "icd10_usage.xlsx": "cleaned/ICD10_usage.xlsx",
        "tfqav_summary.xlsx": "cleaned/TFQavSummary.xlsx",
    }
    organized_dir = os.path.join(KB_DIR, "organized")
    subdirs = {
        "drug_classifications": ["drugs_to_classes.xlsx"],
        "formulary": ["form_route.xlsx", "tfqav_summary.xlsx"],
        "clinical_codes": ["icd10_usage.xlsx"],
    }
    for subdir, files in subdirs.items():
        dest_dir = os.path.join(organized_dir, subdir)
        os.makedirs(dest_dir, exist_ok=True)
        for fname in files:
            src = os.path.join(OUTPUT_DIR, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dest_dir, fname))
                print(f"  Organized {fname} -> organized/{subdir}/")


def run():
    print(f"Knowledge base directory: {KB_DIR}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    file_cleaners = {
        "drugsToClasses.xls": ("drugs_to_classes.xlsx", clean_drugs_to_classes),
        "FormRoute.xlsx": ("form_route.xlsx", clean_form_route),
        "ICD10_usage.xlsx": ("icd10_usage.xlsx", clean_icd10_usage),
        "TFQavSummary.xlsx": ("tfqav_summary.xlsx", clean_tfqav_summary),
    }

    print("\n--- Cleaning files ---")
    for original_name, (clean_name, cleaner_fn) in file_cleaners.items():
        input_path = os.path.join(KB_DIR, original_name)
        output_path = os.path.join(OUTPUT_DIR, clean_name)
        if os.path.exists(input_path):
            cleaner_fn(input_path, output_path)
        else:
            print(f"  Skipping {original_name} (not found)")

    print("\n--- Organizing into subfolders ---")
    organize_files()

    print("\nDone! Originals are untouched. Cleaned files are in 'Knowledge base/cleaned/'.")
    print("Organized copies are in 'Knowledge base/organized/'.")


if __name__ == "__main__":
    run()
