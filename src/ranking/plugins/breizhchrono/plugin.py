import re


def normalize_breizhchrono(url: str, content: str) -> str:
    # usefull only for event list page, to avoid snapshot creation
    # on each fetch due to timestamp changes in the js code
    content = re.sub(r"ts=\d+", "ts=__TS__", content)
    return content
