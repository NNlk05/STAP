from click import argument, command, echo, option

from stap.lexer.Lexer import Lexer
from stap.praser.Parser import Parser


@command
@argument("file", help="File to compile")
def main(file: str) -> None:
    """STAP: STAck Processing"""
    with open(file) as f:
        source = f.read()

        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens, source)
        ast = parser.parse()
        # TODO: Compile