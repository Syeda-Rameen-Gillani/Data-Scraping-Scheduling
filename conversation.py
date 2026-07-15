"""
conversation.py

Stores chat history and the last search results so that follow-up
questions ("tell me more about case #2") can be answered without
running another search.

History is kept as a list of google.genai.types.Content objects
throughout (not a mix of plain dicts and Content objects), since that's
what generate_content's `contents` argument expects and it avoids any
ambiguity about how a raw dict gets interpreted by the SDK.
"""

from google.genai import types


class ConversationManager:

    def __init__(self):
        self.history = []
        self.last_results = []

    def add_user_message(self, text: str):
        self.history.append(
            types.Content(role="user", parts=[types.Part.from_text(text=text)])
        )

    def add_model_message(self, content):
        self.history.append(content)

    def set_last_results(self, results):
        self.last_results = results

    def get_last_results(self):
        return self.last_results

    def get_history(self):
        return list(self.history)

    def clear(self):
        self.history.clear()
        self.last_results.clear()


conversation = ConversationManager()