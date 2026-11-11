// 把 LaTeX 风格的公式分隔符 \[ … \]、\( … \) 换成 remark-math 认识的 $$ … $$、$ … $。
// 代码块与行内代码里的内容保持原样。AI 与论文转写常用前一种写法。
// （阅读器目录不能依赖本文件，viewers/markdown/mathText.ts 是同样内容的副本，改动时一起改。）
const CODE = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g;

export function normalizeMath(text: string): string {
  if (!text.includes("\\[") && !text.includes("\\(")) return text;
  return text
    .split(CODE)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part
            .replace(/\\\[([\s\S]+?)\\\]/g, (_all, tex: string) => `\n$$\n${tex.trim()}\n$$\n`)
            .replace(/\\\(([\s\S]+?)\\\)/g, (_all, tex: string) => `$${tex.trim()}$`),
    )
    .join("");
}
