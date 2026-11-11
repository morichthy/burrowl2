"""Office 公式（OMML）转 LaTeX（设计稿 03 D-20）。

Word 与 PowerPoint 把公式存成结构化的 OMML（`m:oMath`），不需要识别：按结构逐个元素转写成 LaTeX，
结果是确定的，可信度档与文字层解析相同（parsed）。转不了的元素保留其中的文字，不猜测。

只依赖 lxml 的元素接口（python-docx / python-pptx 解析出的元素都是 lxml 元素）。
"""
import unicodedata

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OMML_METHOD = "omml"  # latex_source.method 与 inline_math.source


def _m(tag: str) -> str:
    return f"{{{M_NS}}}{tag}"


def is_math(el, tag: str) -> bool:
    return getattr(el, "tag", None) == _m(tag)


def _local(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def _ns(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _child(el, tag: str):
    return el.find(_m(tag)) if el is not None else None


def _val(el, path: list[str], default: str | None = None) -> str | None:
    """取属性 m:val；元素存在但没有 m:val 时按 OMML 约定是 "on"。"""
    cur = el
    for tag in path:
        cur = _child(cur, tag)
        if cur is None:
            return default
    return cur.get(_m("val"), "on")


def _on(v: str | None) -> bool:
    return v not in (None, "0", "off", "false")


# ---------- 纯文字 ----------
def plain_text(el) -> str:
    """公式的纯文字：检索与引用用它。按阅读顺序取文字（m:t），并补上存在属性里、显示出来的符号：
    括号与分隔符、求和积分号、根号，分式写成 分子/分母；矩阵与多行公式的格之间加空格。
    数学字母（如 𝑚、𝛽）按 NFKC 还原成普通字符。"""
    return " ".join(unicodedata.normalize("NFKC", _plain(el)).split())


def _plain(el) -> str:
    out = []
    for child in el:
        if not isinstance(child.tag, str):
            continue
        tag, ns = _local(child), _ns(child)
        if tag == "t" and ns in (M_NS, W_NS):
            out.append(child.text or "")
        elif ns != M_NS or tag.endswith("Pr"):
            out.append(_plain(child) if ns == W_NS else "")
        elif tag == "d":
            pr = _child(child, "dPr")
            beg = _val(pr, ["begChr"], "(") if pr is not None else "("
            end = _val(pr, ["endChr"], ")") if pr is not None else ")"
            sep = _val(pr, ["sepChr"], "|") if pr is not None else "|"
            out.append(beg + sep.join(_plain(e) for e in child.findall(_m("e"))) + end)
        elif tag == "nary":
            out.append(_val(child, ["naryPr", "chr"], "∫") + _plain(child))
        elif tag == "rad":
            out.append("√" + _plain(child))
        elif tag == "f":
            out.append(f"{_plain_arg(child, 'num')}/{_plain_arg(child, 'den')}")
        elif tag in ("m", "eqArr"):
            rows = child.findall(_m("mr")) if tag == "m" else [child]
            out.append(" " + " ".join(" ".join(_plain(e) for e in r.findall(_m("e"))) for r in rows) + " ")
        elif tag == "acc":  # 重音写成组合字符，如 m̂
            out.append(_plain(child) + _val(child, ["accPr", "chr"], "̂"))
        elif tag == "groupChr":
            out.append(_plain(child) + _val(child, ["groupChrPr", "chr"], "⏟"))
        else:
            out.append(_plain(child))
    return "".join(out)


def _plain_arg(el, tag: str) -> str:
    sub = _child(el, tag)
    s = _plain(sub) if sub is not None else ""
    return s if len(s) <= 1 else f"({s})"


# ---------- 字符映射 ----------
GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "varepsilon", "ϵ": "epsilon", "ζ": "zeta",
    "η": "eta", "θ": "theta", "ϑ": "vartheta", "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu",
    "ξ": "xi", "π": "pi", "ϖ": "varpi", "ρ": "rho", "ϱ": "varrho", "σ": "sigma", "ς": "varsigma", "τ": "tau",
    "υ": "upsilon", "φ": "varphi", "ϕ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma",
    "Υ": "Upsilon", "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
}
SYMBOLS = {
    "≤": "le", "≥": "ge", "≠": "ne", "≈": "approx", "≡": "equiv", "∼": "sim", "≃": "simeq", "≅": "cong",
    "∝": "propto", "≪": "ll", "≫": "gg", "×": "times", "÷": "div", "·": "cdot", "⋅": "cdot", "∘": "circ",
    "±": "pm", "∓": "mp", "∞": "infty", "∂": "partial", "∇": "nabla", "∀": "forall", "∃": "exists",
    "∄": "nexists", "∈": "in", "∉": "notin", "∋": "ni", "⊂": "subset", "⊃": "supset", "⊆": "subseteq",
    "⊇": "supseteq", "∪": "cup", "∩": "cap", "∅": "emptyset", "¬": "neg", "∧": "land", "∨": "lor",
    "⊕": "oplus", "⊗": "otimes", "⊙": "odot", "⊥": "perp", "∥": "parallel", "∣": "mid", "→": "to",
    "←": "leftarrow", "↔": "leftrightarrow", "⇒": "Rightarrow", "⇐": "Leftarrow", "⇔": "Leftrightarrow",
    "↦": "mapsto", "↑": "uparrow", "↓": "downarrow", "…": "ldots", "⋯": "cdots", "⋮": "vdots",
    "⋱": "ddots", "ℏ": "hbar", "ℓ": "ell", "ℜ": "Re", "ℑ": "Im", "ℵ": "aleph", "⟨": "langle",
    "⟩": "rangle", "⌈": "lceil", "⌉": "rceil", "⌊": "lfloor", "⌋": "rfloor", "∠": "angle", "△": "triangle",
    "∴": "therefore", "∵": "because", "√": "surd", "∑": "sum", "∏": "prod", "∐": "coprod", "∫": "int",
    "∬": "iint", "∭": "iiint", "∮": "oint", "⋃": "bigcup", "⋂": "bigcap", "★": "star", "†": "dagger",
    "°": "circ",
}
PLAIN = {"−": "-", "∗": "*", "′": "'", "″": "''", "‖": r"\|",
         # 不可见字符：函数应用、隐含乘号、隐含逗号、零宽空格；不换行空格当作空格
         **dict.fromkeys(map(chr, (0x2061, 0x2062, 0x2063, 0x200B)), ""), chr(0xA0): " "}
# 数学斜体等变体里的希腊"符号"字形（ϵ、ϑ、ϕ…）：NFKC 会把它们并回普通字母（ε、θ、φ），要按名字区分
GREEK_SYMBOL = {"EPSILON SYMBOL": "ϵ", "THETA SYMBOL": "ϑ", "PHI SYMBOL": "ϕ", "RHO SYMBOL": "ϱ",
                "PI SYMBOL": "ϖ", "KAPPA SYMBOL": "ϰ"}
ESCAPE = {"{": "\\{", "}": "\\}", "#": "\\#", "%": "\\%", "$": "\\$", "_": "\\_", "&": "\\&",
          "~": "\\sim ", "\\": "\\backslash ", "^": "\\hat{}"}
STYLE_OF = (("DOUBLE-STRUCK", "mathbb"), ("FRAKTUR", "mathfrak"), ("SCRIPT", "mathcal"))
FUNCTIONS = {"sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
             "coth", "log", "ln", "lg", "exp", "lim", "max", "min", "sup", "inf", "det", "dim", "ker", "deg",
             "gcd", "arg", "Pr", "hom", "liminf", "limsup"}


def _char(c: str, *, align: bool = False) -> str:
    if c in GREEK:
        return f"\\{GREEK[c]} "
    if c in SYMBOLS:
        return "^{\\circ}" if c == "°" else f"\\{SYMBOLS[c]} "
    if c in PLAIN:
        return PLAIN[c]
    if c == "&" and align:
        return "&"
    if c in ESCAPE:
        return ESCAPE[c]
    if ord(c) < 128:
        return c
    name = unicodedata.name(c, "")
    nfd = unicodedata.normalize("NFD", c)
    if len(nfd) == 2 and nfd[1] in ACCENTS and nfd[0].isascii():  # 预组合的带重音字母：â → \hat{a}
        return f"\\{ACCENTS[nfd[1]]}{{{nfd[0]}}}"
    base = unicodedata.normalize("NFKC", c)
    symbol = next((v for k, v in GREEK_SYMBOL.items() if name.endswith(k)), None)
    if symbol and symbol != c:
        base = symbol
    if base != c and len(base) == 1:  # 数学字母：𝑚 → m，ℝ → \mathbb{R}
        for key, cmd in STYLE_OF:
            if key in name:
                return f"\\{cmd}{{{_char(base)}}}"
        inner = _char(base)
        return f"\\boldsymbol{{{inner.strip()}}}" if "BOLD" in name and base.isalpha() else inner
    return c


def _text(s: str, *, align: bool = False) -> str:
    return "".join(_char(c, align=align) for c in s)


# ---------- 结构 ----------
ACCENTS = {"̂": "hat", "̃": "tilde", "̄": "bar", "̅": "overline", "⃗": "vec",
           "̇": "dot", "̈": "ddot", "̌": "check", "́": "acute", "̀": "grave",
           "̆": "breve", "⃡": "overleftrightarrow", "⃖": "overleftarrow"}
WIDE = {"hat": "widehat", "tilde": "widetilde"}
DELIMS = {"(": "(", ")": ")", "[": "[", "]": "]", "{": "\\{", "}": "\\}", "|": "|", "‖": "\\|",
          "⟨": "\\langle", "⟩": "\\rangle", "⌈": "\\lceil", "⌉": "\\rceil", "⌊": "\\lfloor", "⌋": "\\rfloor",
          "": "."}


def _delim(c: str | None, default: str) -> str:
    c = default if c is None else c
    return DELIMS.get(c, _text(c).strip() or ".")


def _group(s: str) -> str:
    s = s.strip()
    return f"{{{s}}}"


def _script(base: str) -> str:
    """上下标的底数：单个字符或命令以外的内容加花括号，避免 a_b^c 绑错。"""
    b = base.strip()
    return b if len(b) == 1 or (b.startswith("\\") and b[1:].isalpha()) else f"{{{b}}}"


def convert(el, *, align: bool = False) -> str:
    """把一个 OMML 元素（m:oMath 或其中的任意部分）转成 LaTeX 片段。"""
    out = []
    for child in el:
        if not isinstance(child.tag, str):
            continue
        out.append(_element(child, align=align))
    return "".join(out)


def _arg(el, tag: str, *, align: bool = False) -> str:
    sub = _child(el, tag)
    return convert(sub, align=align).strip() if sub is not None else ""


# m:rPr 的字体：m:scr 是字体族（Word 输入 ℝ、𝒜 时存成普通字母加 m:scr），m:sty 是正体 / 粗体
SCRIPTS = {"double-struck": "mathbb", "script": "mathcal", "fraktur": "mathfrak", "sans-serif": "mathsf",
           "monospace": "mathtt"}
STYLES = {"b": "mathbf", "bi": "boldsymbol"}


def _run(el, *, align: bool = False) -> str:
    text = "".join(t.text or "" for t in el.iter(_m("t"), f"{{{W_NS}}}t"))
    if not text:
        return ""
    rpr = _child(el, "rPr")
    if rpr is not None and _on(_val(rpr, ["nor"])):
        return f"\\text{{{text}}}"
    sty = _val(rpr, ["sty"]) if rpr is not None else None
    scr = _val(rpr, ["scr"]) if rpr is not None else None
    norm = unicodedata.normalize("NFKC", text)
    if norm in FUNCTIONS:
        return f"\\{norm} "
    body = _text(text, align=align)
    if not any(c.isalpha() for c in norm):  # 数字、运算符不套字体命令
        return body
    cmd = SCRIPTS.get(scr or "") or STYLES.get(sty or "") or ("mathrm" if sty == "p" else None)
    if cmd == "mathrm" and len(norm) == 1:  # Word 常把单个正体字母（如 dx 的 d）记成 sty=p
        return f"\\mathrm{{{body.strip()}}}"
    return f"\\{cmd}{{{body.strip()}}}" if cmd else body


def _element(el, *, align: bool = False) -> str:
    if _ns(el) != M_NS:
        if _local(el) == "r" and _ns(el) == W_NS:  # 公式里夹的普通文字
            text = "".join(t.text or "" for t in el.iter(f"{{{W_NS}}}t"))
            return f"\\text{{{text}}}" if text else ""
        return ""
    tag = _local(el)
    if tag.endswith("Pr") or tag == "ctrlPr":
        return ""
    if tag == "r":
        return _run(el, align=align)
    if tag in ("oMath", "e", "num", "den", "sub", "sup", "deg", "lim", "fName", "box"):
        return convert(el, align=align)
    if tag == "f":
        num, den = _arg(el, "num"), _arg(el, "den")
        kind = _val(el, ["fPr", "type"], "bar")
        if kind == "lin":
            return f"{_script(num)}/{_script(den)}"
        if kind == "skw":
            return f"{{}}^{{{num}}}/_{{{den}}}"
        if kind == "noBar":
            return f"\\genfrac{{}}{{}}{{0pt}}{{}}{{{num}}}{{{den}}}"
        return f"\\frac{{{num}}}{{{den}}}"
    if tag == "sSub":
        return f"{_script(_arg(el, 'e'))}_{_group(_arg(el, 'sub'))}"
    if tag == "sSup":
        return f"{_script(_arg(el, 'e'))}^{_group(_arg(el, 'sup'))}"
    if tag == "sSubSup":
        return f"{_script(_arg(el, 'e'))}_{_group(_arg(el, 'sub'))}^{_group(_arg(el, 'sup'))}"
    if tag == "sPre":
        return f"{{}}_{_group(_arg(el, 'sub'))}^{_group(_arg(el, 'sup'))}{_arg(el, 'e')}"
    if tag == "rad":
        deg = _arg(el, "deg")
        if _on(_val(el, ["radPr", "degHide"])) or not deg:
            return f"\\sqrt{{{_arg(el, 'e')}}}"
        return f"\\sqrt[{deg}]{{{_arg(el, 'e')}}}"
    if tag == "nary":
        op = _val(el, ["naryPr", "chr"], "∫")
        cmd = _text(op).strip()
        if not _on(_val(el, ["naryPr", "subHide"])):
            sub = _arg(el, "sub")
            cmd += f"_{{{sub}}}" if sub else ""
        if not _on(_val(el, ["naryPr", "supHide"])):
            sup = _arg(el, "sup")
            cmd += f"^{{{sup}}}" if sup else ""
        return f"{cmd} {_arg(el, 'e')}"
    if tag == "d":
        pr = _child(el, "dPr")
        beg = _delim(_val(pr, ["begChr"]) if pr is not None else None, "(")
        end = _delim(_val(pr, ["endChr"]) if pr is not None else None, ")")
        sep_chr = _val(pr, ["sepChr"]) if pr is not None else None
        sep = "\\mid " if sep_chr is None else (_text(sep_chr) or "")
        es = el.findall(_m("e"))
        # 圆括号里只有一个无分数线的分式：二项式系数（Word 输入 (n¦k) 就是这样存的）
        inner = [c for c in es[0] if isinstance(c.tag, str) and not _local(c).endswith("Pr")] if len(es) == 1 else []
        if (beg, end) == ("(", ")") and len(inner) == 1 and is_math(inner[0], "f") \
                and _val(inner[0], ["fPr", "type"]) == "noBar":
            return f"\\binom{{{_arg(inner[0], 'num')}}}{{{_arg(inner[0], 'den')}}}"
        parts = [convert(e, align=align).strip() for e in es]
        return f"\\left{beg} {sep.join(parts)} \\right{end}"
    if tag == "m":
        rows = [" & ".join(convert(e).strip() for e in mr.findall(_m("e"))) for mr in el.findall(_m("mr"))]
        return "\\begin{matrix} " + " \\\\ ".join(rows) + " \\end{matrix}"
    if tag == "eqArr":
        rows = [convert(e, align=True).strip() for e in el.findall(_m("e"))]
        env = "aligned" if any("&" in r for r in rows) else "gathered"
        return f"\\begin{{{env}}} " + " \\\\ ".join(rows) + f" \\end{{{env}}}"
    if tag == "func":
        name = _arg(el, "fName")
        return f"{name} {_arg(el, 'e')}" if name.startswith("\\") else f"\\operatorname{{{name}}} {_arg(el, 'e')}"
    if tag in ("limLow", "limUpp"):
        base, lim = _arg(el, "e"), _arg(el, "lim")
        if base.startswith("\\") and base[1:].strip() in FUNCTIONS:
            return f"{base.strip()}{'_' if tag == 'limLow' else '^'}{{{lim}}}"
        return f"\\{'underset' if tag == 'limLow' else 'overset'}{{{lim}}}{{{base}}}"
    if tag == "acc":
        chr_ = _val(el, ["accPr", "chr"], "̂")
        name = ACCENTS.get(chr_, "hat")
        body = _arg(el, "e")
        if len(plain_text(_child(el, "e")) if _child(el, "e") is not None else "") > 1:
            name = WIDE.get(name, name)
        return f"\\{name}{{{body}}}"
    if tag == "bar":
        pos = _val(el, ["barPr", "pos"], "bot")
        return f"\\{'overline' if pos == 'top' else 'underline'}{{{_arg(el, 'e')}}}"
    if tag == "groupChr":
        chr_ = _val(el, ["groupChrPr", "chr"], "⏟")
        pos = _val(el, ["groupChrPr", "pos"], "bot")
        body = _arg(el, "e")
        if chr_ == "⏟":
            return f"\\underbrace{{{body}}}"
        if chr_ == "⏞":
            return f"\\overbrace{{{body}}}"
        mark = _text(chr_).strip()
        return f"\\{'underset' if pos == 'bot' else 'overset'}{{{mark}}}{{{body}}}"
    if tag == "borderBox":
        return f"\\boxed{{{_arg(el, 'e')}}}"
    if tag == "phant":
        show = _val(el, ["phantPr", "show"], "on")
        return _arg(el, "e") if _on(show) else f"\\phantom{{{_arg(el, 'e')}}}"
    if tag == "oMathPara":
        return " \\\\ ".join(to_latex(o) for o in el.findall(_m("oMath")))
    # 不认识的元素：保留里面的文字，不丢内容
    return convert(el, align=align)


def to_latex(omath) -> str:
    """一条 m:oMath 的 LaTeX（不加 $）。多余的空格合并。"""
    return " ".join(convert(omath).split())


def display_parts(omath_para) -> list[tuple[str, str]]:
    """m:oMathPara 里的每条公式：[(LaTeX, 纯文字)]。"""
    return [(to_latex(o), plain_text(o)) for o in omath_para.findall(_m("oMath"))]


def formula_block(parts: list[tuple[str, str]], **extra) -> dict:
    """行间公式块：文字是公式的纯文字（检索与引用），LaTeX 由公式结构直接转写。"""
    latex = [p[0] for p in parts if p[0]]
    block = {"type": "formula", "text": " ".join(p[1] for p in parts if p[1]).strip(), **extra}
    if latex:
        block["latex"] = latex[0] if len(latex) == 1 else "\\begin{gathered} " + " \\\\ ".join(latex) + \
            " \\end{gathered}"
        if len(latex) > 1:
            block["latex_parts"] = latex
        block["latex_source"] = {"method": OMML_METHOD, "fidelity": "parsed"}
    return block
