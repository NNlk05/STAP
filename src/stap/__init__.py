from stap.lexer.Lexer import Lexer

from click import command, argument, option, echo

@command
@argument("file", help="File to compile")
def main(file: str) -> None:
    """STAP: STAck Processing"""
    with open(file) as f:
        source = f.read()

        lexer = Lexer(source)
        tokens = Lexer.tokenize()
        parser = Parser(tokens, source)
        ast = parser.parse()
        # TODO: Compile