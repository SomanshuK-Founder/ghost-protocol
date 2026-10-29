from collections.abc import Callable


MAX_TEXT_LENGTH = 500


def echo_tool(arguments: dict) -> dict:
    if (
        set(arguments) - {"message"}
        or not isinstance(arguments.get("message"), str)
        or not arguments["message"]
        or len(arguments["message"]) > MAX_TEXT_LENGTH
    ):
        raise ValueError("arguments must contain only a non-empty message of at most 500 characters")
    return {"message": arguments["message"]}


def text_stats_tool(arguments: dict) -> dict:
    if set(arguments) - {"text"} or not isinstance(arguments.get("text"), str):
        raise ValueError("arguments must contain only a text string of at most 500 characters")

    text = arguments["text"]
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError("text must be at most 500 characters")

    return {
        "character_count": len(text),
        "word_count": len(text.split()),
        "line_count": len(text.splitlines()) if text else 0,
        "is_empty": text == "",
    }


TOOLS: dict[str, Callable[[dict], dict]] = {
    "echo": echo_tool,
    "text_stats": text_stats_tool,
}
