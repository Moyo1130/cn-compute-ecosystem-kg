import csv
import re
from collections import defaultdict
from pathlib import Path

import pdfplumber


SOURCE_URL = "https://download.sourcefind.cn:65024/1/main/DTK-25.04.3/Document"
RUNTIME_ID = "runtime:dtk25043"
RUNTIME_NAME = "DTK 25.04.3"
PDF_NAME = "DTK 25.04.3 兼容性手册.pdf"

NODES_HEADER = [
    "id",
    "label",
    "name",
    "source_url",
    "extra/Type",
    "extra/area",
    "extra/Main-Task",
    "software_id",
    "framework_id",
    "extra/Vendor",
    "extra/release",
    "hardware_id",
    "runtime_id",
    "extra/library",
]
EDGES_HEADER = ["source_id", "relation", "target_id"]

TOP_HEADING_RE = re.compile(r"^([3-6])\s+(.+)$")
SECOND_HEADING_RE = re.compile(r"^([356]\.\d+)\s+(.+)$")
FULL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_:<>]*$")
META_WORDS = {"define", "enum", "struct", "typedef", "type"}
HEADER_WORDS = {
    "cuda",
    "hip",
    "nccl",
    "rccl",
    "version",
    "version*",
    "cuda version*",
    "nccl version",
    "type",
}


def normalize_cell(cell: str | None) -> str:
    if not cell:
        return ""
    return re.sub(r"\s+", "", cell)


def normalize_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def row_text(words: list[dict]) -> str:
    return normalize_heading(" ".join(word["text"] for word in words))


def api_id(name: str) -> str:
    return f"API:{name}"


def looks_like_api_name(name: str) -> bool:
    if not name or not FULL_NAME_RE.fullmatch(name):
        return False
    if name.isdigit():
        return False
    if name.endswith("_"):
        return False
    if name in {"HIP", "CUBLAS_GEMM_AL"}:
        return False
    if name.isupper() and "_" not in name and "::" not in name and len(name) > 6:
        return False
    return True


def looks_like_compat_start(name: str) -> bool:
    if not looks_like_api_name(name):
        return False
    lower = name.lower()
    if lower.startswith(
        (
            "cuda",
            "hip",
            "cublas",
            "hipblas",
            "cudnn",
            "hipdnn",
            "cufft",
            "hipfft",
            "cusolver",
            "hipsolver",
            "cusparse",
            "hipsparse",
            "curand",
            "hiprand",
            "nccl",
            "rccl",
            "cub::",
            "hipcub::",
            "thrust::",
            "__",
            "make_",
            "atomic",
        )
    ):
        return True
    if "::" in name or name.endswith("_t"):
        return True
    if name.isupper() and len(name) <= 12:
        return True
    if name in {"printf", "memcpy", "memset", "abort", "lock", "lock64", "clock", "clock64"}:
        return True
    return False


def add_api_node(api_nodes: dict[str, set[str]], name: str, library: str):
    if looks_like_api_name(name):
        api_nodes[name].add(library)


def add_edge(edges: set[tuple[str, str, str]], source_id: str, relation: str, target_id: str):
    if source_id and relation and target_id:
        edges.add((source_id, relation, target_id))


def group_rows(page) -> list[tuple[float, float, str]]:
    words = [
        word
        for word in page.extract_words(use_text_flow=True, keep_blank_chars=False)
        if 70 < word["top"] < 750
    ]
    words.sort(key=lambda word: (word["top"], word["x0"]))

    grouped: list[list[dict]] = []
    for word in words:
        if not grouped or abs(word["top"] - grouped[-1][0]["top"]) > 3:
            grouped.append([word])
        else:
            grouped[-1].append(word)

    return [(row[0]["top"], row[0]["x0"], row_text(row)) for row in grouped]


def library_from_state(current_top: int | None, current_top_title: str, current_second_title: str) -> str:
    if current_top == 4:
        return current_top_title
    return current_second_title or current_top_title


def support_mode(current_top: int | None, current_second_code: str | None) -> bool:
    return current_top == 4 or (current_top == 3 and current_second_code == "3.15")


def compat_mode(current_top: int | None, current_second_code: str | None) -> bool:
    return current_top in {3, 5, 6} and not (current_top == 3 and current_second_code == "3.15")


def flush_support_buffers(buffers: list[str], library: str, api_nodes: dict[str, set[str]], edges: set[tuple[str, str, str]]):
    for idx, value in enumerate(buffers):
        if not value:
            continue
        if looks_like_api_name(value):
            add_api_node(api_nodes, value, library)
            add_edge(edges, RUNTIME_ID, "SUPPORTS_API", api_id(value))
        buffers[idx] = ""


def support_should_append(cell: str, previous: str, nonempty_count: int) -> bool:
    if not previous or not cell:
        return False
    if nonempty_count == 1 and len(cell) <= 10:
        return True
    if nonempty_count <= 2 and len(cell) <= 6:
        return True
    return False


def process_support_table(
    table_rows: list[list[str]],
    library: str,
    buffers: list[str],
    api_nodes: dict[str, set[str]],
    edges: set[tuple[str, str, str]],
):
    for raw_row in table_rows:
        cells = [normalize_cell(cell) for cell in raw_row]
        nonempty_count = sum(1 for cell in cells if cell)
        if not nonempty_count:
            continue
        for idx, cell in enumerate(cells):
            if not cell:
                continue
            if support_should_append(cell, buffers[idx], nonempty_count):
                buffers[idx] += cell
            else:
                if looks_like_api_name(buffers[idx]):
                    add_api_node(api_nodes, buffers[idx], library)
                    add_edge(edges, RUNTIME_ID, "SUPPORTS_API", api_id(buffers[idx]))
                buffers[idx] = cell


def header_row(row: list[str]) -> bool:
    lowered = {normalize_cell(cell).lower() for cell in row if normalize_cell(cell)}
    return bool(lowered & HEADER_WORDS)


def row_source_target(cells: list[str]) -> tuple[str, str]:
    nonempty = [cell for cell in cells if cell]
    if not nonempty:
        return "", ""
    if nonempty[0].lower() in META_WORDS or nonempty[0].isdigit():
        source = nonempty[1] if len(nonempty) > 1 else ""
        target = nonempty[2] if len(nonempty) > 2 else ""
        return source, target
    source = nonempty[0]
    target = nonempty[1] if len(nonempty) > 1 else ""
    return source, target


def finalize_compat_pending(pending: dict | None, library: str, api_nodes: dict[str, set[str]], edges: set[tuple[str, str, str]]):
    if not pending:
        return
    source = pending["source"]
    target = pending["target"]
    if looks_like_api_name(source):
        add_api_node(api_nodes, source, library)
        add_edge(edges, RUNTIME_ID, "COMPATIBLE_WITH", api_id(source))
    if looks_like_api_name(target):
        add_api_node(api_nodes, target, library)
        if looks_like_api_name(source) and api_id(source) != api_id(target):
            add_edge(edges, api_id(source), "MAPS_TO", api_id(target))


def process_compat_table(
    table_rows: list[list[str]],
    library: str,
    pending: dict | None,
    api_nodes: dict[str, set[str]],
    edges: set[tuple[str, str, str]],
) -> dict | None:
    start_index = 1 if table_rows and header_row(table_rows[0]) else 0
    for raw_row in table_rows[start_index:]:
        cells = [normalize_cell(cell) for cell in raw_row]
        source, target = row_source_target(cells)
        if not source and not target:
            continue
        if not source:
            continue
        if pending is None:
            pending = {"source": source, "target": target}
            continue
        if not looks_like_compat_start(source):
            pending["source"] += source
            pending["target"] += target
            continue
        finalize_compat_pending(pending, library, api_nodes, edges)
        pending = {"source": source, "target": target}
    return pending


def write_nodes(path: Path, api_nodes: dict[str, set[str]]):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(NODES_HEADER)
        writer.writerow(
            [
                RUNTIME_ID,
                "Runtime",
                RUNTIME_NAME,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
        for name in sorted(api_nodes):
            writer.writerow(
                [
                    api_id(name),
                    "API",
                    name,
                    SOURCE_URL,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "|".join(sorted(api_nodes[name])),
                ]
            )


def write_edges(path: Path, edges: set[tuple[str, str, str]]):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(EDGES_HEADER)
        for edge in sorted(edges):
            writer.writerow(edge)


def main():
    root = Path(__file__).resolve().parent
    pdf_path = root / PDF_NAME

    api_nodes: dict[str, set[str]] = defaultdict(set)
    edges: set[tuple[str, str, str]] = set()
    support_buffers = ["", "", "", ""]
    compat_pending = None

    current_top = None
    current_top_title = ""
    current_second_code = None
    current_second_title = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            if page_number < 6 or page_number > 147:
                continue

            events = []
            for top, x0, text in group_rows(page):
                if "CUDA API" in text and "兼容性列表" in text and "3" in text:
                    events.append((top, "top", "3 CUDA API 兼容性列表"))
                elif "CUDA API" in text and "支持列表" in text and "4" in text:
                    events.append((top, "top", "4 CUDA API 支持列表"))
                elif "数学库" in text and "兼容性列表" in text and "5" in text:
                    events.append((top, "top", "5 数学库兼容性列表"))
                elif "通讯组件" in text and "兼容性列表" in text and "6" in text:
                    events.append((top, "top", "6 通讯组件兼容性列表"))
                elif x0 <= 110 and SECOND_HEADING_RE.match(text):
                    events.append((top, "second", text))

            for table in page.find_tables():
                events.append((table.bbox[1], "table", table.extract()))

            for _, kind, payload in sorted(events, key=lambda item: item[0]):
                library = library_from_state(current_top, current_top_title, current_second_title)
                if kind == "top":
                    flush_support_buffers(support_buffers, library, api_nodes, edges)
                    finalize_compat_pending(compat_pending, library, api_nodes, edges)
                    compat_pending = None
                    match = TOP_HEADING_RE.match(payload)
                    current_top = int(match.group(1))
                    current_top_title = match.group(2).strip()
                    current_second_code = None
                    current_second_title = ""
                    continue

                if kind == "second":
                    flush_support_buffers(support_buffers, library, api_nodes, edges)
                    finalize_compat_pending(compat_pending, library, api_nodes, edges)
                    compat_pending = None
                    match = SECOND_HEADING_RE.match(payload)
                    current_second_code = match.group(1)
                    current_second_title = match.group(2).strip()
                    continue

                library = library_from_state(current_top, current_top_title, current_second_title)
                if support_mode(current_top, current_second_code):
                    process_support_table(payload, library, support_buffers, api_nodes, edges)
                elif compat_mode(current_top, current_second_code):
                    compat_pending = process_compat_table(payload, library, compat_pending, api_nodes, edges)

    final_library = library_from_state(current_top, current_top_title, current_second_title)
    flush_support_buffers(support_buffers, final_library, api_nodes, edges)
    finalize_compat_pending(compat_pending, final_library, api_nodes, edges)
    write_nodes(root / "nodes.csv", api_nodes)
    write_edges(root / "edges.csv", edges)
    print(f"nodes={len(api_nodes) + 1}")
    print(f"edges={len(edges)}")


if __name__ == "__main__":
    main()
