"""
graph_lib.prompts
~~~~~~~~~~~~~~~~~
System prompts and string templates for the Gemini GraphAgent.
"""

def get_refine_description_prompt(name: str, description: str) -> str:
    return (
        f'Concept: "{name}"\n'
        f"Description: {description}\n\n"
        f"Rewrite: keep all key information and details, fix any incorrect "
        f"assumptions, be concise. Output only the revised description."
    )

def get_refine_name_prompt(name: str, description: str) -> str:
    return (
        f'Concept name: "{name}"\n'
        f"Description: {description}\n\n"
        f"Provide the best short canonical name for this concept. "
        f"It should be concise (1–5 words), properly capitalised, and "
        f"unambiguous. Output only the name, nothing else."
    )

def get_discover_missing_links_prompt(node_name: str, node_description: str, neighbours_str: str) -> str:
    return (
        f'Node: "{node_name}"\n'
        f"Description: {node_description}\n"
        f"Already linked topics: {neighbours_str}\n\n"
        f"Is there one important related topic that is NOT listed above "
        f"and would add significant context to this node?\n"
        f"If yes, reply in exactly this format (no extra text):\n"
        f"NAME: <topic name>\n"
        f"DESCRIPTION: <one concise sentence>\n"
        f"If no, reply with exactly: NONE"
    )

def get_score_edge_prompt(from_name: str, from_desc: str, to_name: str, to_desc: str) -> str:
    return (
        f'Source: "{from_name}" — {from_desc}\n'
        f'Target: "{to_name}" — {to_desc}\n\n'
        f"Reply with only a float 0.0-1.0: probability that target is "
        f"related to source."
    )

def get_score_edge_retry_prompt(from_name: str, from_desc: str, to_name: str, to_desc: str) -> str:
    return (
        f'Source: "{from_name}" — {from_desc}\n'
        f'Target: "{to_name}" — {to_desc}\n\n'
        f"You must reply with ONLY a single float between 0.0 and 1.0. "
        f"No words, no explanation — just the number."
    )

def get_summarise_prompt(prime_name: str, prime_desc: str, related_block: str) -> str:
    return (
        f'Prime node: "{prime_name}"\n'
        f"Description: {prime_desc}\n\n"
        f"Related context:\n{related_block}\n\n"
        f"Summarise the prime node's purpose, key information, and current "
        f"action. Supplement with relevant context from the related nodes. "
        f"Be brief. Output as bullet points only."
    )
