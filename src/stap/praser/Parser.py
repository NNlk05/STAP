from dataclasses import dataclass

from stap.lexer.Lexer import Token


class ParserError(Exception):
    def __init__(self, message: str, line: int, column: int):
        self.message = message
        self.line = line
        self.column = column
        super().__init__(f"Parser error at line {line}, column {column}: {message}")


@dataclass
class Program:
    statements: list


@dataclass
class Push:
    value: object


@dataclass
class BinOp:
    op: str


@dataclass
class Dup:
    pass


@dataclass
class Drop:
    pass


@dataclass
class Show:
    pass


@dataclass
class Print:
    pass


@dataclass
class Read:
    pass


@dataclass
class Clear:
    pass


@dataclass
class List:
    items: list


@dataclass
class Block:
    statements: list


@dataclass
class WordDef:
    name: str
    body: Block


@dataclass
class Call:
    name: str


@dataclass
class If:
    condition: list
    then_branch: Block
    elseif_branches: list
    else_branch: Block | None


@dataclass
class While:
    condition: list
    body: list


STACK_OPS = {"dup": Dup, "drop": Drop, "show": Show, "print": Print, "read": Read, "clear": Clear}
BINOPS = {"+", "-", "*", "/", "="}


class Parser:
    def __init__(self, tokens: list[Token], source: str):
        self.tokens = tokens
        self.source = source
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def at_end(self) -> bool:
        return self.pos >= len(self.tokens)

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, type_: str, value: str | None = None) -> Token:
        tok = self.peek()
        if tok.type != type_ or (value is not None and tok.value != value):
            raise ParserError(
                f"Expected {type_}" + (f" {value!r}" if value is not None else "") + f", got {tok.type} {tok.value!r}",
                tok.line,
                tok.column,
            )
        return self.advance()

    def parse(self) -> Program:
        statements = self.parse_block(set())
        return Program(statements)

    def parse_block(self, stop_values: set) -> list:
        statements: list = []
        condition: list = []

        while not self.at_end():
            tok = self.peek()
            if tok.type == "EOF":
                break
            if tok.type == "SYMBOL" and tok.value in stop_values:
                break

            if tok.type == "KEYWORD":
                if tok.value == "def":
                    statements.extend(condition)
                    condition.clear()
                    statements.append(self.parse_word_def())
                elif tok.value in ("if", "while"):
                    cond = list(condition)
                    condition = []
                    kw = self.advance().value
                    self.expect("SYMBOL", "{")
                    body = Block(self.parse_block({"}"}))
                    self.expect("SYMBOL", "}")
                    if kw == "if":
                        statements.append(self.parse_if_rest(cond, body))
                    else:
                        statements.append(While(cond, body.statements))
                elif tok.value in ("elseif", "else"):
                    break
                else:
                    statements.extend(condition)
                    condition.clear()
                    statements.append(Call(tok.value))
                    self.advance()
            elif tok.type == "SYMBOL":
                if tok.value == "}":
                    break
                elif tok.value == "{":
                    statements.extend(condition)
                    condition.clear()
                    self.advance()
                    body = Block(self.parse_block({"}"}))
                    self.expect("SYMBOL", "}")
                    statements.append(Block(body.statements))
                elif tok.value == "(":
                    statements.extend(condition)
                    condition.clear()
                    self.advance()
                    items = self.parse_list_items()
                    self.expect("SYMBOL", ")")
                    statements.append(List(items))
                elif tok.value in BINOPS:
                    condition.append(BinOp(tok.value))
                    self.advance()
                else:
                    statements.extend(condition)
                    condition.clear()
                    statements.append(Call(tok.value))
                    self.advance()
            elif tok.type == "INT":
                condition.append(Push(int(tok.value)))
                self.advance()
            elif tok.type == "STRING":
                condition.append(Push(tok.value[1:-1]))
                self.advance()
            elif tok.type == "IDENT":
                if tok.value in STACK_OPS:
                    condition.append(STACK_OPS[tok.value]())
                else:
                    condition.append(Call(tok.value))
                self.advance()
            elif tok.type == "NEWLINE":
                statements.extend(condition)
                condition.clear()
                self.advance()
            else:
                raise ParserError(f"Unexpected token {tok.type} {tok.value!r}", tok.line, tok.column)

        statements.extend(condition)
        condition.clear()
        return statements

    def parse_word_def(self) -> WordDef:
        self.expect("KEYWORD", "def")
        name_tok = self.advance()
        if name_tok.type != "IDENT":
            raise ParserError(
                f"Expected word name, got {name_tok.type} {name_tok.value!r}",
                name_tok.line,
                name_tok.column,
            )
        self.expect("SYMBOL", "{")
        body = Block(self.parse_block({"}"}))
        self.expect("SYMBOL", "}")
        return WordDef(name_tok.value, body)

    def parse_if_rest(self, cond: list, then_branch: Block) -> If:
        elseif_branches: list = []
        else_branch: Block | None = None

        while not self.at_end():
            tok = self.peek()
            if tok.type == "KEYWORD" and tok.value == "else":
                self.advance()
                self.expect("SYMBOL", "{")
                else_branch = Block(self.parse_block({"}"}))
                self.expect("SYMBOL", "}")
                break

            econd: list = []
            while not self.at_end():
                peek_tok = self.peek()
                if peek_tok.type == "KEYWORD" and peek_tok.value in ("elseif", "else"):
                    break
                if peek_tok.type == "SYMBOL" and peek_tok.value == "}":
                    break
                self._parse_simple_into(econd)

            next_tok = self.peek()
            if not (next_tok.type == "KEYWORD" and next_tok.value == "elseif"):
                break

            self.advance()
            self.expect("SYMBOL", "{")
            ebody = Block(self.parse_block({"}"}))
            self.expect("SYMBOL", "}")
            elseif_branches.append((econd, ebody))

        return If(cond, then_branch, elseif_branches, else_branch)

    def _parse_simple_into(self, out: list):
        tok = self.peek()
        if tok.type == "INT":
            out.append(Push(int(tok.value)))
            self.advance()
        elif tok.type == "STRING":
            out.append(Push(tok.value[1:-1]))
            self.advance()
        elif tok.type == "SYMBOL" and tok.value in BINOPS:
            out.append(BinOp(tok.value))
            self.advance()
        elif tok.type == "IDENT":
            if tok.value in STACK_OPS:
                out.append(STACK_OPS[tok.value]())
            else:
                out.append(Call(tok.value))
            self.advance()
        else:
            raise ParserError(f"Unexpected token in condition {tok.type} {tok.value!r}", tok.line, tok.column)

    def parse_list_items(self) -> list:
        items: list = []
        while not self.at_end():
            tok = self.peek()
            if tok.type == "SYMBOL" and tok.value == ")":
                break
            if tok.type == "INT":
                items.append(int(tok.value))
                self.advance()
            elif tok.type == "STRING":
                items.append(tok.value[1:-1])
                self.advance()
            elif tok.type in ("NEWLINE", "SYMBOL"):
                self.advance()
            else:
                break
        return items
