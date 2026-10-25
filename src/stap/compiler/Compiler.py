from __future__ import annotations  # noqa: N999

import ctypes
import os
import re
import sys
from ctypes import CFUNCTYPE, POINTER, c_char_p, c_int, c_void_p, cast
from typing import Any

from llvmlite import binding  # type: ignore[import]
from llvmlite import ir as llvmir  # type: ignore[import]

from stap.praser.Parser import (
    BinOp,
    Block,
    Call,
    Clear,
    Drop,
    Dup,
    If,
    List,
    Print,
    Program,
    Push,
    Read,
    Show,
    While,
    WordDef,
)


class CompilerError(Exception):
    def __init__(self, message: str, line: int = 0, column: int = 0) -> None:
        self.message = message
        self.line = line
        self.column = column
        super().__init__(
            f"Compiler error at line {line}, column {column}: {message}"
        )


TAG_MASK = 0x7
TAG_INT = 0x0
TAG_STR = 0x1
TAG_LIST = 0x2
INITIAL_CAPACITY = 4096


class Compiler:
    def __init__(self, program: Program, source: str = "") -> None:
        self.program = program
        self.source = source
        self.llvm_mod = llvmir.Module("stap")
        self.llvm_mod.triple = binding.get_default_triple()

        self.i8 = llvmir.IntType(8)
        self.i64 = llvmir.IntType(64)
        self.i32 = llvmir.IntType(32)
        self.i1 = llvmir.IntType(1)
        self.void = llvmir.VoidType()
        self.i8ptr = self.i8.as_pointer()
        self.i8ptrptr = self.i8ptr.as_pointer()
        self.i64ptr = self.i64.as_pointer()
        self.i64ptrptr = self.i64ptr.as_pointer()
        self.list_struct = llvmir.LiteralStructType([self.i64ptr, self.i64])
        self.list_structptr = self.list_struct.as_pointer()

        self.string_globals: dict[str, llvmir.GlobalVariable] = {}
        self.word_funcs: dict[str, llvmir.Function] = {}
        self.funcs: dict[str, Any] = {}
        self.builder: Any = None
        self.stack_ref: Any = None
        self.sp_ref: Any = None

        self._declare_runtime()

    def _declare_runtime(self) -> None:
        declarations = [
            ("malloc", self.i8ptr, [self.i64]),
            ("free", self.void, [self.i8ptr]),
            ("realloc", self.i8ptr, [self.i8ptr, self.i64]),
            ("strcmp", self.i32, [self.i8ptr, self.i8ptr]),
            ("stap_push", self.void, [self.i64ptrptr, self.i64ptr, self.i64]),
            ("stap_pop", self.i64, [self.i64ptrptr, self.i64ptr]),
            ("stap_dup", self.void, [self.i64ptrptr, self.i64ptr]),
            ("stap_drop", self.void, [self.i64ptr]),
            ("stap_clear", self.void, [self.i64ptr]),
            ("stap_print_cell", self.void, [self.i64]),
            ("stap_show_stack", self.void, [self.i64ptrptr, self.i64ptr]),
            ("stap_read_line", self.i64, []),
            ("stap_list_print", self.void, [self.i64]),
        ]
        for name, ret, args in declarations:
            fty = llvmir.FunctionType(ret, args)
            func = llvmir.Function(self.llvm_mod, fty, name)
            self.funcs[name] = func

    def _get_func(self, name: str) -> Any:
        return self.funcs[name]

    def _string_global(self, value: str) -> Any:
        if value in self.string_globals:
            return self.string_globals[value]
        bytes_val = bytearray(value.encode("utf-8") + b"\x00")
        arr_type = llvmir.ArrayType(self.i8, len(bytes_val))
        gv = llvmir.GlobalVariable(
            self.llvm_mod, arr_type, f"str_{len(self.string_globals)}"
        )
        gv.linkage = "private"
        gv.global_constant = True
        gv.alignment = 8
        gv.initializer = llvmir.Constant(arr_type, bytes_val)
        self.string_globals[value] = gv
        return gv

    def _tag_int(self, value: Any) -> Any:
        return self.builder.shl(value, self.i64(3))

    def _untag_int(self, cell: Any) -> Any:
        return self.builder.ashr(cell, self.i64(3))

    def _ptr_to_cell(self, ptr: Any, tag: int) -> Any:
        ptr_i = self.builder.ptrtoint(ptr, self.i64)
        return self.builder.or_(ptr_i, self.i64(tag))

    def _push(self, cell: Any) -> None:
        self.builder.call(
            self._get_func("stap_push"), [self.stack_ref, self.sp_ref, cell]
        )

    def _pop(self) -> Any:
        return self.builder.call(
            self._get_func("stap_pop"), [self.stack_ref, self.sp_ref]
        )

    def _codegen_expression_value(self, cell: Any) -> None:
        self._push(cell)

    def _codegen_stmt(self, stmt: Any) -> None:
        if isinstance(stmt, Push):
            self._codegen_push(stmt)
        elif isinstance(stmt, BinOp):
            self._codegen_binop(stmt)
        elif isinstance(stmt, Dup):
            self.builder.call(self._get_func("stap_dup"), [self.stack_ref, self.sp_ref])
        elif isinstance(stmt, Drop):
            self.builder.call(self._get_func("stap_drop"), [self.sp_ref])
        elif isinstance(stmt, Clear):
            self.builder.call(self._get_func("stap_clear"), [self.sp_ref])
        elif isinstance(stmt, Show):
            self.builder.call(
                self._get_func("stap_show_stack"), [self.stack_ref, self.sp_ref]
            )
        elif isinstance(stmt, Print):
            cell = self._pop()
            self.builder.call(self._get_func("stap_print_cell"), [cell])
        elif isinstance(stmt, Read):
            cell = self.builder.call(self._get_func("stap_read_line"), [])
            self._push(cell)
        elif isinstance(stmt, List):
            self._codegen_list(stmt)
        elif isinstance(stmt, Block):
            for inner in stmt.statements:
                self._codegen_stmt(inner)
        elif isinstance(stmt, Call):
            self._codegen_call(stmt)
        elif isinstance(stmt, If):
            continue_block = self.builder.basic_block.function.append_basic_block(
                "if.cont"
            )
            self._codegen_if(stmt, continue_block)
        elif isinstance(stmt, While):
            continue_block = self.builder.basic_block.function.append_basic_block(
                "while.cont"
            )
            self._codegen_while(stmt, continue_block)
        elif isinstance(stmt, WordDef):
            pass
        else:
            raise CompilerError(f"Unknown statement type: {type(stmt).__name__}")

    def _codegen_push(self, stmt: Push) -> None:
        if isinstance(stmt.value, int):
            cell = self._tag_int(self.i64(stmt.value))
            self._push(cell)
        elif isinstance(stmt.value, str):
            gv = self._string_global(stmt.value)
            ptr = self.builder.bitcast(gv, self.i8ptr)
            cell = self._ptr_to_cell(ptr, TAG_STR)
            self._push(cell)
        else:
            raise CompilerError(f"Cannot push value of type {type(stmt.value).__name__}")

    def _codegen_binop(self, stmt: BinOp) -> None:
        b_cell = self._pop()
        a_cell = self._pop()
        a_untag = self._untag_int(a_cell)
        b_untag = self._untag_int(b_cell)

        op = stmt.op
        if op == "+":
            result = self.builder.add(a_untag, b_untag)
        elif op == "-":
            result = self.builder.sub(a_untag, b_untag)
        elif op == "*":
            result = self.builder.mul(a_untag, b_untag)
        elif op == "/":
            result = self.builder.sdiv(a_untag, b_untag)
        elif op == "=":
            a_tag = self.builder.and_(a_cell, self.i64(TAG_MASK))
            both_int = self.builder.icmp_signed("==", a_tag, self.i64(TAG_INT))
            both_str = self.builder.icmp_signed("==", a_tag, self.i64(TAG_STR))

            main_func = self.builder.basic_block.function
            int_block = main_func.append_basic_block("eq.int")
            str_block = main_func.append_basic_block("eq.str")
            str_false_block = main_func.append_basic_block("eq.strfalse")
            false_block = main_func.append_basic_block("eq.false")
            done_block = main_func.append_basic_block("eq.done")

            self.builder.cbranch(both_int, int_block, str_false_block)

            self.builder.position_at_end(int_block)
            int_eq = self.builder.icmp_signed("==", a_untag, b_untag)
            self.builder.branch(done_block)

            self.builder.position_at_end(str_false_block)
            self.builder.cbranch(both_str, str_block, false_block)

            self.builder.position_at_end(str_block)
            a_ptr = self.builder.inttoptr(
                self.builder.and_(a_cell, self.i64(~TAG_MASK & 0xFFFFFFFFFFFFFFFF)),
                self.i8ptr,
            )
            b_ptr = self.builder.inttoptr(
                self.builder.and_(b_cell, self.i64(~TAG_MASK & 0xFFFFFFFFFFFFFFFF)),
                self.i8ptr,
            )
            strcmp_res = self.builder.call(
                self._get_func("strcmp"), [a_ptr, b_ptr]
            )
            str_eq = self.builder.icmp_signed("==", strcmp_res, self.i32(0))
            self.builder.branch(done_block)

            self.builder.position_at_end(false_block)
            false_val = self.i1(0)
            self.builder.branch(done_block)

            self.builder.position_at_end(done_block)
            result = self.builder.phi(self.i1)
            result.add_incoming(int_eq, int_block)
            result.add_incoming(str_eq, str_block)
            result.add_incoming(false_val, false_block)
            result = self.builder.zext(result, self.i64)
        else:
            raise CompilerError(f"Unknown binary operator: {op}")
        self._push(self._tag_int(result))

    def _codegen_list(self, stmt: List) -> None:
        n = len(stmt.items)
        size = self.i64(n * 8)
        items_ptr_raw = self.builder.call(self._get_func("malloc"), [size])
        items_ptr = self.builder.bitcast(items_ptr_raw, self.i64ptr)

        for index, item in enumerate(stmt.items):
            if isinstance(item, int):
                cell = self._tag_int(self.i64(item))
            elif isinstance(item, str):
                gv = self._string_global(item)
                ptr = self.builder.bitcast(gv, self.i8ptr)
                cell = self._ptr_to_cell(ptr, TAG_STR)
            else:
                raise CompilerError(
                    f"List item of unsupported type {type(item).__name__}"
                )
            self.builder.store(
                cell, self.builder.gep(items_ptr, [self.i64(index)])
            )

        list_raw = self.builder.call(self._get_func("malloc"), [self.i64(16)])
        items_field = self.builder.bitcast(list_raw, self.i64ptrptr)
        self.builder.store(items_ptr, items_field)
        len_field = self.builder.bitcast(
            self.builder.gep(list_raw, [self.i64(8)]), self.i64ptr
        )
        self.builder.store(self.i64(n), len_field)
        cell = self._ptr_to_cell(list_raw, TAG_LIST)
        self._push(cell)

    def _codegen_call(self, stmt: Call) -> None:
        if stmt.name not in self.word_funcs:
            raise CompilerError(f"Undefined word: {stmt.name}")
        self.builder.call(
            self._get_func(stmt.name), [self.stack_ref, self.sp_ref]
        )

    def _codegen_condition_branch(
        self, cond: list[Any], true_block: Any, false_block: Any
    ) -> None:
        for inner in cond:
            self._codegen_stmt(inner)
        cell = self._pop()
        truth = self.builder.icmp_signed("!=", cell, self.i64(0))
        self.builder.cbranch(truth, true_block, false_block)

    def _codegen_if(self, stmt: If, continue_block: Any) -> None:
        main_func = self.builder.basic_block.function
        then_block = main_func.append_basic_block("if.then")

        n_elseif = len(stmt.elseif_branches)
        econd_blocks = [
            main_func.append_basic_block(f"if.elseif.cond.{i}") for i in range(n_elseif)
        ]
        ebody_blocks = [
            main_func.append_basic_block(f"if.elseif.body.{i}") for i in range(n_elseif)
        ]
        else_bb = (
            main_func.append_basic_block("if.else") if stmt.else_branch else None
        )

        false_target = (
            econd_blocks[0]
            if n_elseif
            else (else_bb if else_bb is not None else continue_block)
        )
        self._codegen_condition_branch(stmt.condition, then_block, false_target)

        self.builder.position_at_end(then_block)
        for inner in stmt.then_branch.statements:
            self._codegen_stmt(inner)
        self.builder.branch(continue_block)

        for i in range(n_elseif):
            self.builder.position_at_end(econd_blocks[i])
            next_false = (
                econd_blocks[i + 1]
                if i + 1 < n_elseif
                else (else_bb if else_bb is not None else continue_block)
            )
            self._codegen_condition_branch(stmt.elseif_branches[i][0], ebody_blocks[i], next_false)
            self.builder.position_at_end(ebody_blocks[i])
            for inner in stmt.elseif_branches[i][1].statements:
                self._codegen_stmt(inner)
            self.builder.branch(continue_block)

        if stmt.else_branch is not None:
            self.builder.position_at_end(else_bb)
            for inner in stmt.else_branch.statements:
                self._codegen_stmt(inner)
            self.builder.branch(continue_block)

        self.builder.position_at_end(continue_block)

    def _codegen_while(self, stmt: While, continue_block: Any) -> None:
        main_func = self.builder.basic_block.function
        cond_block = main_func.append_basic_block("while.cond")
        body_block = main_func.append_basic_block("while.body")

        self.builder.branch(cond_block)

        self.builder.position_at_end(cond_block)
        self._codegen_condition_branch(stmt.condition, body_block, continue_block)

        self.builder.position_at_end(body_block)
        for inner in stmt.body:
            self._codegen_stmt(inner)
        self.builder.branch(cond_block)

        self.builder.position_at_end(continue_block)

    def _codegen_word(self, stmt: WordDef) -> None:
        f = self.word_funcs[stmt.name]
        entry = f.append_basic_block("entry")
        self.builder = llvmir.IRBuilder(entry)
        stack_param, sp_param = f.args
        self.stack_ref = stack_param
        self.sp_ref = sp_param
        for inner in stmt.body.statements:
            self._codegen_stmt(inner)
        self.builder.ret_void()

    def _codegen_main(self) -> None:
        mainfty = llvmir.FunctionType(self.i64, [self.i64, self.i8ptrptr])
        main = llvmir.Function(self.llvm_mod, mainfty, "main")
        self.funcs["main"] = main
        entry = main.append_basic_block("entry")
        self.builder = llvmir.IRBuilder(entry)
        _argc, _argv = main.args

        stack_var = self.builder.alloca(self.i64ptr)
        sp_var = self.builder.alloca(self.i64)

        stack_ptr_raw = self.builder.call(
            self._get_func("malloc"), [self.i64(INITIAL_CAPACITY * 8)]
        )
        stack_ptr = self.builder.bitcast(stack_ptr_raw, self.i64ptr)
        self.builder.store(stack_ptr, stack_var)
        self.builder.store(self.i64(0), sp_var)

        self.stack_ref = stack_var
        self.sp_ref = sp_var

        for stmt in self.program.statements:
            if not isinstance(stmt, WordDef):
                self._codegen_stmt(stmt)

        done = main.append_basic_block("done")
        if not self.builder.block.is_terminated:
            sp_val = self.builder.load(self.sp_ref)
            cond = self.builder.icmp_signed(">", sp_val, self.i64(0))
            print_top = main.append_basic_block("print_top")
            self.builder.cbranch(cond, print_top, done)

            self.builder.position_at_end(print_top)
            stack_ptr_val = self.builder.load(self.stack_ref)
            top_index = self.builder.sub(sp_val, self.i64(1))
            top_cell = self.builder.load(
                self.builder.gep(stack_ptr_val, [top_index])
            )
            self.builder.call(self._get_func("stap_print_cell"), [top_cell])
            self.builder.branch(done)

        self.builder.position_at_end(done)
        self.builder.ret(self.i64(0))

    def compile(self) -> str:
        for stmt in self.program.statements:
            if isinstance(stmt, WordDef):
                fty = llvmir.FunctionType(self.void, [self.i64ptrptr, self.i64ptr])
                f = llvmir.Function(self.llvm_mod, fty, stmt.name)
                self.word_funcs[stmt.name] = f
                self.funcs[stmt.name] = f

        self._codegen_main()

        for stmt in self.program.statements:
            if isinstance(stmt, WordDef):
                self._codegen_word(stmt)

        ir = str(self.llvm_mod)
        ir = re.sub(
            r'(@"str_\d+" = private constant \[[0-9]+ x i8\] c".*")',
            r'\1, align 8',
            ir,
        )
        return ir

    def compile_and_run(self) -> None:
        binding.initialize()
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()

        ir = self.compile()

        target = binding.Target.from_triple(self.llvm_mod.triple)
        target_machine = target.create_target_machine()
        mod_ref = binding.parse_assembly(ir)
        mod_ref.triple = self.llvm_mod.triple
        mod_ref.data_layout = str(target_machine.target_data)

        engine = binding.create_mcjit_compiler(mod_ref, target_machine)

        runtime_lib = ctypes.CDLL(None)
        if sys.platform == "win32":
            ext = "dll"
        elif sys.platform == "darwin":
            ext = "dylib"
        else:
            ext = "so"
        stap_lib_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), f"libstap_runtime.{ext}"
        )
        stap_lib = ctypes.CDLL(stap_lib_path)

        symbol_libs = {
            "malloc": runtime_lib,
            "free": runtime_lib,
            "realloc": runtime_lib,
            "strcmp": runtime_lib,
            "stap_push": stap_lib,
            "stap_pop": stap_lib,
            "stap_dup": stap_lib,
            "stap_drop": stap_lib,
            "stap_clear": stap_lib,
            "stap_print_cell": stap_lib,
            "stap_show_stack": stap_lib,
            "stap_read_line": stap_lib,
            "stap_list_print": stap_lib,
        }

        for name, lib in symbol_libs.items():
            func = mod_ref.get_function(name)
            addr = cast(getattr(lib, name), c_void_p).value
            engine.add_global_mapping(func, addr)

        engine.finalize_object()

        main_addr = engine.get_function_address("main")
        cfun = CFUNCTYPE(c_int, c_int, POINTER(c_char_p))(main_addr)
        argv = (c_char_p * 1)(b"stap")
        cfun(1, argv)
