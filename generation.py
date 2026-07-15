"""
generation.py

Gemini-based generation layer with tool calling.
The LLM decides when to invoke search_judgments().
"""

import os
import logging

from google import genai
from google.genai import types

from dotenv import load_dotenv

load_dotenv()

from tools import search_judgments, tools
from conversation import conversation

log = logging.getLogger(__name__)

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Add it to your .env file before "
        "starting the app."
    )

client = genai.Client(api_key=API_KEY)

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """
You are a legal research assistant for Sindh High Court judgments.

Rules:

1. Use the search_judgments tool when the user asks about:
- specific cases
- citations
- judges
- legal doctrines
- statutes
- previous judgments
- case examples

2. Do NOT use the tool for:
- greetings
- casual conversation
- unrelated questions

3. Answer only from retrieved judgments.

4. If information is unavailable, clearly say so.

If the current user message is a follow-up to the previous search results,
answer using the previous tool results already available in the conversation.

Do NOT call search_judgments again unless a new search is needed.
"""

_TOOL_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=tools[0]["function_declarations"])],
)

_NO_TOOL_CONFIG = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)


def _call_gemini(config: types.GenerateContentConfig):
    """Thin wrapper so a transient API error doesn't crash the request."""
    try:
        return client.models.generate_content(
            model=MODEL,
            contents=conversation.get_history(),
            config=config,
        )
    except Exception:
        log.exception("Gemini API call failed")
        raise


def generate_answer(question: str):

    # 1. Add the user's new message to the running conversation history
    conversation.add_user_message(question)

    # 2. Send the FULL history so Gemini can see earlier turns and
    #    previous tool results if this is a follow-up question
    response = _call_gemini(_TOOL_CONFIG)

    # 3. Did Gemini decide to call the tool?
    if response.function_calls:

        call = response.function_calls[0]

        try:
            tool_result = search_judgments(**call.args)
        except Exception as exc:
            log.exception("search_judgments failed")
            tool_result = {
                "status": "error",
                "message": f"Search failed: {exc}",
            }

        # Save Gemini's function-call turn into history
        conversation.add_model_message(response.candidates[0].content)

        # The function's result goes back in as role='tool' -- this is the
        # documented python-genai convention (see googleapis/python-genai
        # README), NOT 'user'. Using 'user' here confuses the turn
        # structure and weakens grounding on the tool result.
        tool_response_content = types.Content(
            role="tool",
            parts=[
                types.Part.from_function_response(
                    name=call.name,
                    response={"results": tool_result},
                )
            ],
        )
        conversation.history.append(tool_response_content)

        # 4. Ask Gemini to produce the final answer using the tool result
        try:
            final_response = _call_gemini(_NO_TOOL_CONFIG)
        except Exception:
            return {
                "answer": (
                    "I found some results but couldn't generate a summary "
                    "right now. Please try again."
                ),
                "tool_used": call.name,
                "results": tool_result,
            }

        # Save the final answer into history too, so future follow-ups
        # can reference it
        conversation.add_model_message(final_response.candidates[0].content)

        # Remember these results for "tell me more about case #2" style
        # follow-ups. search_judgments returns a dict (not a list) when
        # the classifier rejected the query or an error occurred --
        # only real result lists are worth remembering.
        if isinstance(tool_result, list):
            conversation.set_last_results(tool_result)

        return {
            "answer": final_response.text,
            "tool_used": call.name,
            "results": tool_result,
        }

    else:
        # No tool call -- plain conversational answer (greeting, small
        # talk, or a follow-up Gemini chose to answer from history directly)
        conversation.add_model_message(response.candidates[0].content)

        return {
            "answer": response.text,
            "tool_used": None,
            "results": [],
        }