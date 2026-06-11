from __future__ import annotations

from ranking.core.fetch import fetch_page


def main() -> None:
    html = fetch_page("https://www.google.fr")
    print(html)


if __name__ == "__main__":
    main()
