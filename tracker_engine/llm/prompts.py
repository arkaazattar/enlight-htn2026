"""System prompt for the Gemini identity analysis model.

Keep this file focused on prompt content only — no API calls, no parsing logic.
Edit this file to tune how Gemini extracts names and facts from conversation.
"""

IDENTITY_ANALYSIS_PROMPT = (
    "Extract the person's name and any explicitly stated facts (e.g., job, interests, origin) "
    "for the supplied participants from the conversation. "
    "If a person says their name or is addressed by name, extract their name. "
    "If no name is mentioned, return null for name. "
    "Extract facts as a list of clear, concise strings. "
    "Do not invent facts or infer attributes from appearance."
)
