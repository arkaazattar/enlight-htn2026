"""
graph_lib.prompts
~~~~~~~~~~~~~~~~~
System prompts and string templates for the Gemini GraphAgent.
"""

def get_refine_description_prompt(name: str, description: str) -> str:
    return (
        f'Entity: "{name}"\n'
        f"Context: {description}\n"
        f"\n"
        f"Rewrite. keep all key information and details, fix any incorrect "
        f"assumptions, be concise. Output only the revised context in third "
        f"person."
    )

def get_refine_name_prompt(name: str, description: str) -> str:
    return (
        f'Entity: "{name}"\n'
        f"Context: {description}\n"
        f"\n"
        f"Provide the best short canonical name for this concept. "
        f"It should be concise (1–5 words), properly capitalised, and "
        f"unambiguous. Output only the name, nothing else."
    )

def get_contextualize_prompt(prime_name: str, prime_desc: str, related_block: str) -> str:
    return (
        f'Entity: "{prime_name}"\n'
        f'Associated context: "{prime_desc}"\n'
        f"\n"
        f"Current speech from nearby entities:\n"
        f"{related_block}\n"
        f"\n"
        f"Summarise the entity's purpose, key information, current "
        f"action, and anything else relevant to understand the entity based on "
        f"the entity's context and information that may be inferred from the "
        f"related context points from other entities. Output as a detailed "
        f"paragraph in third person."
    )

def get_discover_missing_links_prompt(node_name: str, node_description: str, neighbours_str: str) -> str:
    return (
        f'Entity: "{node_name}"\n'
        f"Context: {node_description}\n"
        f"Already linked topics: {neighbours_str}\n"
        f"\n"
        f"Is there one important related topic that is NOT listed above "
        f"and would add significant context to this node?\n"
        f"If yes, reply in exactly this format (no extra text):\n"
        f"NAME: <topic name>\n"
        f"DESCRIPTION: <one concise sentence in third person>\n"
        f"If no, reply with exactly: NONE"
    )

def get_score_edge_prompt(from_name: str, from_desc: str, to_name: str, to_desc: str) -> str:
    return (
        f'Entity 1 name: "{from_name}"\n'
        f'Entity 1 context: "{from_desc}"\n'
        f'Entity 2 name: "{to_name}"\n'
        f'Entity 2 context: "{to_desc}"\n'
        f'\n'
        f"Score the strongest meaningful shared interest or fact between these "
        f"two people. A direct shared interest should carry substantial weight "
        f"even when the other listed facts are unrelated: liking tacos and liking "
        f"tacos with beef is a clear shared interest and merits at least 0.6. "
        f"Facts about a person's friend are not that person's own interests. "
        f"Use the same score regardless of which person is listed first. "
        f"Give no evident overlap a low positive score around 0.1; do not use zero. "
        f"Reply with only one float from 0.1 to 1.0."
    )

def get_score_edge_retry_prompt(from_name: str, from_desc: str, to_name: str, to_desc: str) -> str:
    return (
        f'Entity 1 name: "{from_name}"\n'
        f'Entity 1 context: "{from_desc}"\n'
        f'Entity 2 name: "{to_name}"\n'
        f'Entity 2 context: "{to_desc}"\n'
        f'\n'
        f"Reply with only one float from 0.1 to 1.0 for their possible "
        f"connection. Focus on their strongest direct shared interest; unrelated "
        f"facts must not dilute that match. Give no evident overlap a low "
        f"positive score around 0.1. Never reply with zero."
    )

def get_summarise_prompt(prime_name: str, prime_desc: str, related_block: str) -> str:
    return (
        f'Entity: "{prime_name}"\n'
        f'Associated context: "{prime_desc}"\n'
        f"\n"
        f"Related context:\n"
        f"{related_block}\n"
        f"\n"
        f"Summarise the entity's purpose, key information, current "
        f"action, and anything else relevant to understand the entity based on "
        f"the entity's context and information that may be inferred from the "
        f"related context points from other entities. Output as a detailed "
        f"paragraph in third person."
    )
