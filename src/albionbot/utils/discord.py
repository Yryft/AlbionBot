import re
from typing import List, Optional
import nextcord

def parse_ids(text: str) -> List[int]:
    ids = re.findall(r"\d{5,}", text or "")
    out = []
    for s in ids:
        try:
            out.append(int(s))
        except ValueError:
            pass
    # unique stable
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    return uniq

def mention(user_id: int) -> str:
    return f"<@{user_id}>"

def channel_mention(ch_id: Optional[int]) -> str:
    return f"<#{ch_id}>" if ch_id else "*non défini*"

def has_any_role(member: nextcord.Member, role_ids: List[int]) -> bool:
    if not role_ids:
        return True
    ids = {r.id for r in member.roles}
    return any(rid in ids for rid in role_ids)
