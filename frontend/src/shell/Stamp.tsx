// 印：三列的标记。底色是那一列的语义色，字（原 / 判 / 框）本身也能区分，不只靠颜色。
const CHAR: Record<string, string> = { original: "原", judgment: "判", framework: "框" };
const NAME: Record<string, string> = { original: "原件", judgment: "判断", framework: "框架" };

// 由条目 ID 前缀推出所在的列（只用于显示）
export function layerOf(id: string): string {
  if (id.startsWith("art_") || id.startsWith("rec_") || id.startsWith("rd_") || id.startsWith("evt_")) return "original";
  if (id.startsWith("jdg_")) return "judgment";
  if (id.startsWith("pg_") || id.startsWith("ent_") || id.startsWith("edg_")) return "framework";
  return "";
}

export function Stamp({ layer, small, large, title }: { layer?: string | null; small?: boolean; large?: boolean; title?: string }) {
  const l = layer ?? "";
  if (!CHAR[l]) return <span className={`stamp none${small ? " sm" : ""}${large ? " lg" : ""}`} aria-hidden="true">·</span>;
  return (
    <span className={`stamp ${l}${small ? " sm" : ""}${large ? " lg" : ""}`} title={title ?? NAME[l]} aria-label={NAME[l]} role="img">
      {CHAR[l]}
    </span>
  );
}
