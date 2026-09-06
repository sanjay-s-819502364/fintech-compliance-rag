#!/usr/bin/env python3
"""
Generate .metadata.json sidecar files for Bedrock Knowledge Base ingestion.

Bedrock reads <filename>.metadata.json sitting next to each source document and
writes those attributes into the custom_metadata column, where they can be used
as retrieval filters.

Usage:
    python generate_metadata.py                 # write sidecars into corpus/
    python generate_metadata.py --dry-run       # print what would be written
    python generate_metadata.py --check         # list files missing from DOC_INFO
"""

import argparse
import json
from pathlib import Path

CORPUS_ROOT = Path("corpus")

# Folder name -> jurisdiction + regulator.
# Add new folders here as the corpus grows (sg-mas, au-austrac, etc).
FOLDER_MAP = {
    "uk-fca": {"jurisdiction": "UK", "regulator": "FCA"},
    "au-asic": {"jurisdiction": "AU", "regulator": "ASIC"},
    "distractors": {"jurisdiction": "UNKNOWN", "regulator": "UNKNOWN"},
}

# Per-document attributes that can't be inferred from the folder.
#
# doc_type:  regulatory_guide | finalised_guidance | policy_statement
#            approach_document | info_sheet | consultation
# status:    current | superseded | proposed
# topic:     complaints | safeguarding | licensing | outsourcing
#            conduct | crypto | resilience | dispute_resolution
#
# topic is a list — a document can legitimately cover several.
DOC_INFO = {
    # --- UK / FCA ---
    "payment-services-electronic-money-approach.pdf": {
        "doc_id": "FCA-Approach",
        "doc_type": "approach_document",
        "status": "current",
        "topic": ["safeguarding", "licensing", "conduct", "complaints"],
    },
    "ps25-12.pdf": {
        "doc_id": "PS25/12",
        "doc_type": "policy_statement",
        "status": "current",
        "topic": ["safeguarding"],
    },
    "fg24-6.pdf": {
        "doc_id": "FG24/6",
        "doc_type": "finalised_guidance",
        "status": "current",
        "topic": ["conduct", "payments"],
    },
    "fg26-4.pdf": {
        "doc_id": "FG26/4",
        "doc_type": "finalised_guidance",
        "status": "current",
        "topic": ["outsourcing", "resilience"],
    },
    "fg26-5.pdf": {
        "doc_id": "FG26/5",
        "doc_type": "finalised_guidance",
        "status": "current",
        "topic": ["crypto", "conduct"],
    },
    "fg26-6.pdf": {
        "doc_id": "FG26/6",
        "doc_type": "finalised_guidance",
        "status": "current",
        "topic": ["crypto", "resilience"],
    },
    "fg26-7.pdf": {
        "doc_id": "FG26/7",
        "doc_type": "finalised_guidance",
        "status": "current",
        "topic": ["crypto", "licensing"],
    },
    # --- AU / ASIC ---
    "rg271.pdf": {
        "doc_id": "RG271",
        "doc_type": "regulatory_guide",
        "status": "current",
        "topic": ["complaints", "dispute_resolution"],
    },
    "rg267-published-2-september-2021.pdf": {
        "doc_id": "RG267",
        "doc_type": "regulatory_guide",
        "status": "current",
        "topic": ["dispute_resolution"],
    },
    "rg269-published-28-september-2018.pdf": {
        "doc_id": "RG269",
        "doc_type": "regulatory_guide",
        "status": "current",
        "topic": ["conduct"],
    },
    "rg262-published-18-october-2018-20260421.pdf": {
        "doc_id": "RG262",
        "doc_type": "regulatory_guide",
        "status": "current",
        "topic": ["conduct"],
    },
    "rg207-published-1-april-2020.pdf": {
        "doc_id": "RG207",
        "doc_type": "regulatory_guide",
        "status": "current",
        "topic": ["licensing"],
    },
    "rg138-published-21-november-2024-20260804.pdf": {
        "doc_id": "RG138",
        "doc_type": "regulatory_guide",
        "status": "current",
        "topic": ["conduct"],
    },
    "rg112-published-30-march-2011-20260421.pdf": {
        "doc_id": "RG112",
        "doc_type": "regulatory_guide",
        "status": "current",
        "topic": ["licensing"],
    },
    "Applying_for_a_limited_AFS_licence_0179.pdf": {
        "doc_id": "INFO-179",
        "doc_type": "info_sheet",
        "status": "current",
        "topic": ["licensing"],
    },
    "Licensing_administrative_action.pdf": {
        "doc_id": "ASIC-Licensing-Admin",
        "doc_type": "info_sheet",
        "status": "current",
        "topic": ["licensing"],
    },
    # --- Distractors (proposed rules, not current obligations) ---
    "attachment-2-to-cp360-published-17-march-2022.pdf": {
        "doc_id": "CP360-Att2",
        "doc_type": "consultation",
        "status": "proposed",
        "topic": ["conduct"],
    },
    "attachment-to-cp263-published-21-july-2016.pdf": {
        "doc_id": "CP263-Att",
        "doc_type": "consultation",
        "status": "proposed",
        "topic": ["conduct"],
    },
    "attachment-to-cp-378-published-6-may-2024.pdf": {
        "doc_id": "CP378-Att",
        "doc_type": "consultation",
        "status": "proposed",
        "topic": ["conduct"],
    },
}

# Used when a PDF isn't listed in DOC_INFO, so ingestion still gets
# jurisdiction filtering rather than nothing.
FALLBACK = {
    "doc_id": "UNKNOWN",
    "doc_type": "unknown",
    "status": "unknown",
    "topic": [],
}


def build_attributes(pdf_path: Path) -> dict:
    """Combine folder-derived and per-document attributes for one PDF."""
    folder = pdf_path.parent.name
    folder_attrs = FOLDER_MAP.get(
        folder, {"jurisdiction": "UNKNOWN", "regulator": "UNKNOWN"}
    )
    doc_attrs = DOC_INFO.get(pdf_path.name, FALLBACK)

    return {
        "metadataAttributes": {
            **folder_attrs,
            "doc_id": doc_attrs["doc_id"],
            "doc_type": doc_attrs["doc_type"],
            "status": doc_attrs["status"],
            "topic": doc_attrs["topic"],
            "source_file": pdf_path.name,
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="print sidecars instead of writing them")
    parser.add_argument("--check", action="store_true",
                        help="list PDFs not present in DOC_INFO, then exit")
    parser.add_argument("--root", default=str(CORPUS_ROOT),
                        help="corpus root directory (default: corpus)")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Corpus root not found: {root.resolve()}")

    pdfs = sorted(root.rglob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found under {root.resolve()}")

    if args.check:
        missing = [p for p in pdfs if p.name not in DOC_INFO]
        if missing:
            print(f"{len(missing)} PDF(s) not in DOC_INFO — will use fallback:")
            for p in missing:
                print(f"  {p}")
        else:
            print(f"All {len(pdfs)} PDFs are described in DOC_INFO.")
        return

    written = 0
    for pdf in pdfs:
        attrs = build_attributes(pdf)
        sidecar = pdf.with_suffix(pdf.suffix + ".metadata.json")

        if args.dry_run:
            print(f"\n--- {sidecar} ---")
            print(json.dumps(attrs, indent=2))
        else:
            sidecar.write_text(json.dumps(attrs, indent=2))
            written += 1

    if args.dry_run:
        print(f"\nDry run: {len(pdfs)} sidecar(s) would be written.")
    else:
        print(f"Wrote {written} sidecar file(s) under {root}/")
        print("\nNext:")
        print("  aws s3 sync corpus/ s3://<bucket>/corpus/ "
              '--exclude "distractors/*"')
        print("  # then re-sync the knowledge base")


if __name__ == "__main__":
    main()
