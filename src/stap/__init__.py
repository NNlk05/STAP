from click import argument, command

from stap.compiler.Compiler import Compiler
from stap.lexer.Lexer import Lexer
from stap.praser.Parser import Parser


@command()
@argument("file")
def main(file: str) -> None:
    """STAP: STAck Processing"""
    with open(file) as f:
        source = f.read()

        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens, source)
        ast = parser.parse()

        Compiler(ast, source=source).compile_and_run()
