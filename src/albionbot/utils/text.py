from typing import List

def limit_str(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)] + "…"

def chunk_text_lines(lines: List[str], max_len: int = 1000) -> List[str]:
    chunks = []
    cur = ""
    for ln in lines:
        add = ln + "\n"
        if len(cur) + len(add) > max_len:
            if cur.strip():
                chunks.append(cur.strip())
            cur = add
        else:
            cur += add
    if cur.strip():
        chunks.append(cur.strip())
    return chunks
