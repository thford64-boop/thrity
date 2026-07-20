#!/usr/bin/env python3
"""
Thrity Extension DSL - tokenizer + parser
--------------------------------------------
Turns an `extension.thrity` file's text into a small AST (nested
Python tuples/dicts - no external parser libraries, so extensions
keep working with nothing but the standard library, same as the
rest of Thrity).

The DSL is intentionally small and declarative, with one small
imperative pocket (inside `on <event> { ... }` and `action <name> {
... }` blocks) for reacting to browser events. There is no `eval`,
`exec`, or Python code path anywhere in this file or in
dsl_interpreter.py - see dsl_interpreter.py's docstring for why that
matters.

Grammar (informal):

    file        := "extension" STRING "{" entry* "}"
    entry       := permissions_block
                 | settings_block
                 | on_block
                 | action_block
                 | named_block      # toolbar_button "id" { ... }, panel "id" { ... }, ...
                 | plain_block      # any "keyword { ... }" not handled above
                 | kv_pair          # key: expr

    permissions_block := "permissions" "{" IDENT* "}"
    settings_block     := "settings" "{" kv_pair* "}"
    on_block            := "on" IDENT "{" statement* "}"
    action_block        := "action" IDENT "{" statement* "}"
    named_block         := IDENT STRING "{" entry* "}"
    plain_block         := IDENT "{" entry* "}"
    kv_pair             := IDENT ":" expr

    statement   := if_stmt | let_stmt | expr
    if_stmt     := "if" expr "{" statement* "}" ("else" "{" statement* "}")?
    let_stmt    := "let" IDENT "=" expr

    expr        := additive (("==" | "!=") additive)?
    additive    := primary ("+" primary)*
    primary     := STRING | NUMBER | "true" | "false"
                 | IDENT "(" (expr ("," expr)*)? ")"     # call
                 | IDENT "." IDENT                        # field access (event.url, settings.x)
                 | IDENT                                  # variable
                 | "(" expr ")"
"""

import re

TOKEN_SPEC = [
    ("COMMENT",  r"#[^\n]*"),
    ("WS",       r"[ \t\r\n]+"),
    ("STRING",   r'"(?:[^"\\]|\\.)*"'),
    ("NUMBER",   r"\d+(?:\.\d+)?"),
    ("IDENT",    r"[A-Za-z_][A-Za-z0-9_]*"),
    ("EQEQ",     r"=="),
    ("NEQ",      r"!="),
    ("EQ",       r"="),
    ("LBRACE",   r"\{"),
    ("RBRACE",   r"\}"),
    ("LPAREN",   r"\("),
    ("RPAREN",   r"\)"),
    ("COLON",    r":"),
    ("COMMA",    r","),
    ("DOT",      r"\."),
    ("PLUS",     r"\+"),
]
TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))

KEYWORDS = {"permissions", "settings", "on", "action", "if", "else", "let", "true", "false"}


class DSLSyntaxError(Exception):
    pass


def tokenize(text):
    tokens = []
    pos = 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            bad = text[pos:pos + 20].splitlines()[0]
            raise DSLSyntaxError(f"Unexpected text near: {bad!r}")
        kind = m.lastgroup
        value = m.group()
        pos = m.end()
        if kind in ("WS", "COMMENT"):
            continue
        if kind == "STRING":
            value = value[1:-1]
            value = value.replace("\\n", "\n").replace("\\t", "\t")
            value = value.replace('\\"', '"').replace("\\\\", "\\")
        elif kind == "NUMBER":
            value = float(value) if "." in value else int(value)
        tokens.append((kind, value))
    tokens.append(("EOF", None))
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # -- low level helpers --
    def peek(self, offset=0):
        return self.tokens[self.pos + offset]

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind):
        tok = self.advance()
        if tok[0] != kind:
            raise DSLSyntaxError(f"Expected {kind}, got {tok[0]} ({tok[1]!r})")
        return tok

    def at_ident(self, name=None):
        kind, value = self.peek()
        if kind != "IDENT":
            return False
        return value == name if name is not None else True

    # -- top level --
    def parse_file(self):
        self.expect("IDENT")  # 'extension' (checked by caller via keyword match)
        name_tok = self.expect("STRING")
        self.expect("LBRACE")
        entries = self.parse_entries()
        self.expect("RBRACE")
        return {"kind": "extension", "name": name_tok[1], "entries": entries}

    def parse_entries(self):
        entries = []
        while self.peek()[0] != "RBRACE" and self.peek()[0] != "EOF":
            entries.append(self.parse_entry())
        return entries

    def parse_entry(self):
        kind, value = self.peek()
        if kind != "IDENT":
            raise DSLSyntaxError(f"Expected a block or key, got {kind} ({value!r})")

        if value == "permissions":
            return self.parse_permissions_block()
        if value == "settings":
            return self.parse_settings_block()
        if value == "on":
            return self.parse_on_block()
        if value == "action":
            return self.parse_action_block()

        # lookahead to tell named block / plain block / kv pair apart
        nxt = self.peek(1)
        nxt2 = self.peek(2)
        if nxt[0] == "STRING" and nxt2[0] == "LBRACE":
            return self.parse_named_block()
        if nxt[0] == "LBRACE":
            return self.parse_plain_block()
        if nxt[0] == "COLON":
            return self.parse_kv()
        raise DSLSyntaxError(f"Don't know how to parse entry starting with {value!r}")

    def parse_permissions_block(self):
        self.advance()  # 'permissions'
        self.expect("LBRACE")
        names = []
        while self.peek()[0] != "RBRACE":
            tok = self.expect("IDENT")
            names.append(tok[1])
            if self.peek()[0] == "COMMA":
                self.advance()
        self.expect("RBRACE")
        return {"kind": "permissions", "names": names}

    def parse_settings_block(self):
        self.advance()  # 'settings'
        self.expect("LBRACE")
        pairs = {}
        while self.peek()[0] != "RBRACE":
            key = self.expect("IDENT")[1]
            self.expect("COLON")
            pairs[key] = self.parse_expr()
        self.expect("RBRACE")
        return {"kind": "settings", "values": pairs}

    def parse_on_block(self):
        self.advance()  # 'on'
        event_name = self.expect("IDENT")[1]
        self.expect("LBRACE")
        stmts = self.parse_statements()
        self.expect("RBRACE")
        return {"kind": "on", "event": event_name, "body": stmts}

    def parse_action_block(self):
        self.advance()  # 'action'
        action_name = self.expect("IDENT")[1]
        self.expect("LBRACE")
        stmts = self.parse_statements()
        self.expect("RBRACE")
        return {"kind": "action", "name": action_name, "body": stmts}

    def parse_named_block(self):
        block_type = self.expect("IDENT")[1]
        label = self.expect("STRING")[1]
        self.expect("LBRACE")
        entries = self.parse_entries()
        self.expect("RBRACE")
        return {"kind": "block", "type": block_type, "label": label, "entries": entries}

    def parse_plain_block(self):
        block_type = self.expect("IDENT")[1]
        self.expect("LBRACE")
        entries = self.parse_entries()
        self.expect("RBRACE")
        return {"kind": "block", "type": block_type, "label": None, "entries": entries}

    def parse_kv(self):
        key = self.expect("IDENT")[1]
        self.expect("COLON")
        expr = self.parse_expr()
        return {"kind": "kv", "key": key, "value": expr}

    # -- statements (only inside on/action bodies) --
    def parse_statements(self):
        stmts = []
        while self.peek()[0] != "RBRACE" and self.peek()[0] != "EOF":
            stmts.append(self.parse_statement())
        return stmts

    def parse_statement(self):
        if self.at_ident("if"):
            return self.parse_if()
        if self.at_ident("let"):
            return self.parse_let()
        expr = self.parse_expr()
        return {"kind": "expr_stmt", "expr": expr}

    def parse_if(self):
        self.advance()  # 'if'
        cond = self.parse_expr()
        self.expect("LBRACE")
        then_body = self.parse_statements()
        self.expect("RBRACE")
        else_body = []
        if self.at_ident("else"):
            self.advance()
            self.expect("LBRACE")
            else_body = self.parse_statements()
            self.expect("RBRACE")
        return {"kind": "if", "cond": cond, "then": then_body, "else": else_body}

    def parse_let(self):
        self.advance()  # 'let'
        name = self.expect("IDENT")[1]
        self.expect("EQ")
        expr = self.parse_expr()
        return {"kind": "let", "name": name, "expr": expr}

    # -- expressions --
    def parse_expr(self):
        left = self.parse_additive()
        if self.peek()[0] in ("EQEQ", "NEQ"):
            op = self.advance()[0]
            right = self.parse_additive()
            return {"kind": "binop", "op": "==" if op == "EQEQ" else "!=", "left": left, "right": right}
        return left

    def parse_additive(self):
        left = self.parse_primary()
        while self.peek()[0] == "PLUS":
            self.advance()
            right = self.parse_primary()
            left = {"kind": "binop", "op": "+", "left": left, "right": right}
        return left

    def parse_primary(self):
        kind, value = self.peek()
        if kind == "STRING":
            self.advance()
            return {"kind": "str", "value": value}
        if kind == "NUMBER":
            self.advance()
            return {"kind": "num", "value": value}
        if kind == "IDENT" and value == "true":
            self.advance()
            return {"kind": "bool", "value": True}
        if kind == "IDENT" and value == "false":
            self.advance()
            return {"kind": "bool", "value": False}
        if kind == "IDENT":
            self.advance()
            if self.peek()[0] == "LPAREN":
                self.advance()
                args = []
                if self.peek()[0] != "RPAREN":
                    args.append(self.parse_expr())
                    while self.peek()[0] == "COMMA":
                        self.advance()
                        args.append(self.parse_expr())
                self.expect("RPAREN")
                return {"kind": "call", "name": value, "args": args}
            if self.peek()[0] == "DOT":
                self.advance()
                field = self.expect("IDENT")[1]
                return {"kind": "field", "base": value, "name": field}
            return {"kind": "var", "name": value}
        if kind == "LPAREN":
            self.advance()
            e = self.parse_expr()
            self.expect("RPAREN")
            return e
        raise DSLSyntaxError(f"Unexpected token {kind} ({value!r}) in expression")


def parse(text):
    """Parses `extension.thrity` source text into an AST dict.
    Raises DSLSyntaxError on malformed input."""
    tokens = tokenize(text)
    if tokens[0] != ("IDENT", "extension"):
        raise DSLSyntaxError("File must start with: extension \"Name\" { ... }")
    parser = Parser(tokens)
    ast = parser.parse_file()
    if parser.peek()[0] != "EOF":
        raise DSLSyntaxError("Unexpected content after the closing '}' of the extension block")
    return ast
