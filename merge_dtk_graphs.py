import csv
from pathlib import Path

from extract_dtk_api_graph import EDGES_HEADER, NODES_HEADER


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                reader = csv.DictReader(file)
                header = reader.fieldnames or []
                return header, list(reader)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("csv", b"", 0, 1, f"Unable to decode {path}")


def write_nodes(path: Path, rows: list[dict[str, str]]):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=NODES_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def write_edges(path: Path, rows: list[dict[str, str]]):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=EDGES_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def merge_nodes(paths: list[Path]) -> list[dict[str, str]]:
    seen_ids: set[str] = set()
    merged: list[dict[str, str]] = []
    for path in paths:
        header, rows = read_csv_rows(path)
        if header != NODES_HEADER:
            raise ValueError(f"Unexpected nodes header in {path}")
        for row in rows:
            node_id = row["id"]
            if node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            merged.append({key: row.get(key, "") for key in NODES_HEADER})
    return merged


def merge_edges(paths: list[Path]) -> list[dict[str, str]]:
    seen_edges: set[tuple[str, str, str]] = set()
    merged: list[dict[str, str]] = []
    for path in paths:
        header, rows = read_csv_rows(path)
        if header != EDGES_HEADER:
            raise ValueError(f"Unexpected edges header in {path}")
        for row in rows:
            edge_key = (row["source_id"], row["relation"], row["target_id"])
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            merged.append({key: row.get(key, "") for key in EDGES_HEADER})
    return merged


def main():
    root = Path(__file__).resolve().parent
    supplement_dir = root / "补充内容"
    origin_dir = root / "源数据"
    final_dir = root / "最终版本"
    final_dir.mkdir(parents=True, exist_ok=True)

    supplement_nodes = sorted(supplement_dir.glob("*_nodes.csv"))
    supplement_edges = sorted(supplement_dir.glob("*_edges.csv"))
    all_node_paths = [origin_dir / "nodes_origin.csv", *supplement_nodes]
    all_edge_paths = [origin_dir / "edges_origin.csv", *supplement_edges]

    merged_nodes = merge_nodes(all_node_paths)
    merged_edges = merge_edges(all_edge_paths)

    write_nodes(final_dir / "nodes.csv", merged_nodes)
    write_edges(final_dir / "edges.csv", merged_edges)

    print(f"supplement_nodes={len(supplement_nodes)}")
    print(f"supplement_edges={len(supplement_edges)}")
    print(f"merged_nodes={len(merged_nodes)}")
    print(f"merged_edges={len(merged_edges)}")


if __name__ == "__main__":
    main()
