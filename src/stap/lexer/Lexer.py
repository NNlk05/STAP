import re
from dataclasses import dataclass


class LexerError(Exception):
    def __init__(self, message: str, line: int, column: int):
        self.message = message
        self.line = line
        self.column = column
        super().__init__(f"Lexer error at line {line}, column {column}: {message}")


@dataclass(frozen=True)
class Token:
    type: str
    value: str
    line: int
    column: int


KEYWORDS = {"if", "elseif", "else", "while", "def"}

_TOKEN_SPEC = [
    ("STRING", r'"(?:[^"\\]|\\.)*"'),
    ("SYMBOL", r"[+\-*/=(),{}:\[\]]"),
    ("INT", r"[0-9]+"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
]
_TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))

NEWLINE_RE = re.compile(r"\n")
WHITESPACE_RE = re.compile(r"[ \t\r]+")
COMMENT_RE = re.compile(r"#[^\n]*")
EOF_RE = re.compile(r"$")


class Lexer:
    def __init__(self, source: str):
        self.source = source

    def _error(self, message: str) -> LexerError:
        line = self.source.count("\n", 0, self.pos) + 1
        column = self.pos - self.source.rfind("\n", 0, self.pos)
        return LexerError(message, line, column)

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        self.pos = 0
        self.line = 1
        self.column = 1

        while self.pos < len(self.source):
            m = NEWLINE_RE.match(self.source, self.pos)
            if m:
                self.pos = m.end()
                self.line += 1
                self.column = 1
                tokens.append(Token("NEWLINE", "\n", self.line, self.column - 1))
                continue

            m = WHITESPACE_RE.match(self.source, self.pos)
            if m:
                self.pos = m.end()
                self.column += m.end() - m.start()
                continue

            m = COMMENT_RE.match(self.source, self.pos)
            if m:
                self.pos = m.end()
                self.column += m.end() - m.start()
                continue

            m = _TOKEN_RE.match(self.source, self.pos)
            if m:
                kind = m.lastgroup
                assert kind is not None
                value = m.group()
                start_line = self.line
                start_column = self.column
                self.pos = m.end()
                self.column += len(value)

                if kind == "IDENT" and value in KEYWORDS:
                    kind = "KEYWORD"

                tokens.append(Token(kind, value, start_line, start_column))
                continue

            raise self._error(f"Illegal character {self.source[self.pos]!r}")

        tokens.append(Token("EOF", "", self.line, self.column))
        return tokens
