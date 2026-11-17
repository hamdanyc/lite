import argparse
import json
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List
import xml.etree.ElementTree as ET

def validate_iso_datetime(dt_str: str) -> str:
    """Ensure datetime is ISO 8601; return empty string if invalid/missing."""
    if not dt_str:
        return ""
    try:
        # Parse flexible formats, output strict ISO
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.isoformat()
    except ValueError:
        print(f"Warning: Invalid createDateTime format '{dt_str}', omitting.", file=sys.stderr)
        return ""

def build_code_element(code_data: Dict[str, Any]) -> ET.Element:
    """Recursively builds an XML <Code> element with nested child codes."""
    code_elem = ET.Element("Code")

    # Mandatory ID (generate if missing)
    code_id = code_data.get("id") or str(uuid.uuid4())
    code_elem.set("id", str(code_id))

    # Name is highly recommended
    if name := code_data.get("name"):
        code_elem.set("name", str(name))

    # Color validation (REFI-QDA expects #RRGGBB)
    if color := code_data.get("color"):
        color_str = str(color).strip()
        if not color_str.startswith("#"):
            color_str = f"#{color_str}"
        # Basic hex validation
        if len(color_str) == 7 and all(c in "0123456789abcdefABCDEF" for c in color_str[1:]):
            code_elem.set("color", color_str)
        else:
            print(f"Warning: Invalid color format '{color}' for code {code_id}, ignoring.", file=sys.stderr)

    # Formulate <Description> content
    desc_text = ""
    if "raw_description" in code_data and code_data["raw_description"]:
        desc_text = code_data["raw_description"]
    elif "details" in code_data and isinstance(code_data["details"], dict):
        parts = []
        for k, v in code_data["details"].items():
            formatted_key = k.replace("_", " ").title()
            parts.append(f"{formatted_key}: {v}")
        desc_text = "\n".join(parts)

    if desc_text:
        desc_elem = ET.SubElement(code_elem, "Description")
        desc_elem.text = desc_text

    # Add Memo if present
    if "memo" in code_data and code_data["memo"]:
        memo_elem = ET.SubElement(code_elem, "Memo")
        memo_elem.text = str(code_data["memo"])

    # Recursively process nested child codes
    children = code_data.get("children", [])
    for child in children:
        code_elem.append(build_code_element(child))

    return code_elem

def convert_json_to_qdc(json_file_path: str, output_file_path: str) -> None:
    """Reads a JSON codebook and writes a REFI-QDA standard .qdc XML file."""
    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Error: Input file not found: {json_file_path}")
    except json.JSONDecodeError as e:
        sys.exit(f"Error: Invalid JSON in '{json_file_path}': {e}")

    # Validate required structure
    if "codes" not in data or not isinstance(data["codes"], list):
        sys.exit("Error: JSON root must contain a 'codes' list.")

    meta = data.get("metadata", {})
    origin = meta.get("origin", "QualCoder - REFI-QDA Export")
    create_time = validate_iso_datetime(meta.get("createDateTime", ""))

    # Create root <CodeBook> element conforming to REFI-QDA XML schema 1.0
    root = ET.Element("CodeBook")
    root.set("xmlns", "urn:QDA-XML:codebook:1.0")
    root.set("origin", origin)
    if create_time:
        root.set("createDateTime", create_time)

    codes_elem = ET.SubElement(root, "Codes")

    # Populate parent and nested codes
    codes_list = data.get("codes", [])
    for code_data in codes_list:
        codes_elem.append(build_code_element(code_data))

    # Modern pretty print (Python 3.9+)
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    try:
        tree.write(output_file_path, encoding="utf-8", xml_declaration=True)
    except OSError as e:
        sys.exit(f"Error writing output file: {e}")

    print(
        f"Successfully converted '{json_file_path}' to REFI-QDA XML format:"
        f" '{output_file_path}'"
    )

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a JSON qualitative codebook into a REFI-QDA Standard XML"
            " (.qdc) file."
        )
    )

    # Positional argument for the JSON input file
    parser.add_argument(
        "input_file",
        help=(
            "Path to the input JSON codebook file (e.g., qualcode_codebook_v2.json)"
        ),
    )

    # Optional flag for specifying a custom output filename
    parser.add_argument(
        "-o",
        "--output",
        default="qualcode_codebook.qdc",
        help="Path to output .qdc file (default: qualcode_codebook.qdc)",
    )

    args = parser.parse_args()
    try:
        convert_json_to_qdc(args.input_file, args.output)
    except SystemExit as e:
        # Re-raise SystemExit to preserve exit code
        raise
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
