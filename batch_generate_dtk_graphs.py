import re
from pathlib import Path

from extract_dtk_api_graph import extract_graph, parse_pdf_metadata


def sanitize_stem(stem: str) -> str:
    sanitized = re.sub(r"\s+", "_", stem.strip())
    sanitized = sanitized.replace("-", "_")
    sanitized = re.sub(r"[\\\\/:*?\"<>|]+", "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized.strip("_")


def main():
    root = Path(__file__).resolve().parent
    pdf_dir = root / "dtk文档"
    output_dir = root / "补充内容"
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    print(f"pdf_count={len(pdf_files)}")

    for pdf_path in pdf_files:
        prefix = sanitize_stem(pdf_path.stem)
        nodes_output = output_dir / f"{prefix}_nodes.csv"
        edges_output = output_dir / f"{prefix}_edges.csv"
        result = extract_graph(pdf_path, nodes_output, edges_output)
        metadata = parse_pdf_metadata(pdf_path)
        print(
            f"{pdf_path.name}|runtime_id={metadata['runtime_id']}|"
            f"runtime_name={metadata['runtime_name']}|nodes={result['nodes']}|edges={result['edges']}"
        )


if __name__ == "__main__":
    main()
