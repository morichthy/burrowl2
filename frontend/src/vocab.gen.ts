// 由 tools/gen_reference.py 从 src/burrowl/core/vocab.py 生成，不要手改（设计稿 10 D-16）。
export const VOCAB = {
  "layers": {
    "original": "原件",
    "judgment": "判断",
    "framework": "框架"
  },
  "sources": {
    "local": "本地实证",
    "external:peer_reviewed": "外部报告（同行评议）",
    "external:preprint": "外部报告（预印本）",
    "external:vendor": "外部报告（厂商资料）",
    "external:web": "外部报告（网页）",
    "external": "外部报告",
    "inferred": "推断"
  },
  "kinds": {
    "artifact": "原件",
    "event": "过程日志",
    "record": "事实记录",
    "read": "读取记录",
    "conclusion": "结论",
    "thought": "思路",
    "constraint": "约束",
    "entity": "实体页",
    "concept": "概念页",
    "synthesis": "综合页",
    "description": "描述页",
    "point": "要点",
    "edge": "关联边"
  },
  "validity": {
    "current": "当前有效",
    "replaced": "被替代",
    "withdrawn": "已撤回",
    "retired": "已退役",
    "lapsed": "依据失效"
  },
  "review": {
    "none": "未复核",
    "ai_confirmed": "AI 已复核",
    "ai_flagged": "AI 认为有问题",
    "ai_unsure": "AI 拿不准",
    "human_confirmed": "人已复核",
    "human_rejected": "人驳回"
  },
  "authors": {
    "human": "人",
    "ai": "AI",
    "system": "系统"
  },
  "subkinds": {
    "question": "提问",
    "attempt": "尝试",
    "stopped": "停下的路线",
    "hypothesis": "假设",
    "association": "联想",
    "aim": "目的",
    "action": "行动",
    "usage": "使用"
  },
  "categories": {
    "evidence": "证据流",
    "stance": "立场与结构",
    "replace": "替代",
    "process": "过程",
    "framework": "框架推断（不作为依据）",
    "free": "自由标签（系统不赋予含义）"
  },
  "category_order": [
    "stance",
    "replace",
    "evidence",
    "process",
    "framework",
    "free"
  ],
  "predicates": {
    "cites": {
      "label": "依据",
      "inverse": "被依据",
      "category": "evidence",
      "origin": "judgment",
      "writers": [
        "human",
        "ai",
        "system"
      ],
      "evidential": true,
      "basis": true,
      "flow": "object_to_subject",
      "qualifiers": [],
      "required": []
    },
    "supports": {
      "label": "佐证",
      "inverse": "被佐证",
      "category": "evidence",
      "origin": "judgment",
      "writers": [
        "human",
        "ai"
      ],
      "evidential": true,
      "basis": false,
      "flow": "subject_to_object",
      "qualifiers": [],
      "required": []
    },
    "opposes": {
      "label": "反驳",
      "inverse": "被反驳",
      "category": "evidence",
      "origin": "judgment",
      "writers": [
        "human",
        "ai"
      ],
      "evidential": false,
      "basis": false,
      "flow": "subject_to_object",
      "qualifiers": [],
      "required": []
    },
    "coexists_under": {
      "label": "条件并存",
      "inverse": "条件并存",
      "category": "stance",
      "origin": "judgment",
      "writers": [
        "human",
        "ai"
      ],
      "qualifiers": [
        "condition"
      ],
      "required": [
        "condition"
      ],
      "evidential": false,
      "basis": false,
      "flow": null
    },
    "answers": {
      "label": "回答",
      "inverse": "被回答",
      "category": "stance",
      "origin": "judgment",
      "writers": [
        "human",
        "ai"
      ],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "targets": {
      "label": "针对",
      "inverse": "被针对",
      "category": "stance",
      "origin": "judgment",
      "writers": [
        "human",
        "ai"
      ],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "assumes": {
      "label": "前提",
      "inverse": "是……的前提",
      "category": "stance",
      "origin": "judgment",
      "writers": [
        "human",
        "ai"
      ],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "supersedes": {
      "label": "替代",
      "inverse": "被替代",
      "category": "replace",
      "origin": "judgment",
      "writers": [
        "human"
      ],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "consumed": {
      "label": "用到",
      "inverse": "被用到",
      "category": "process",
      "origin": "mechanical",
      "writers": [
        "human",
        "ai",
        "system"
      ],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "produced": {
      "label": "产出",
      "inverse": "产出自",
      "category": "process",
      "origin": "mechanical",
      "writers": [
        "human",
        "ai",
        "system"
      ],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "relates": {
      "label": "关系",
      "inverse": "关系",
      "category": "free",
      "origin": "judgment",
      "writers": [
        "human",
        "ai"
      ],
      "required": [
        "label"
      ],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": []
    },
    "may_contradict": {
      "label": "可能矛盾",
      "inverse": "可能矛盾",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "may_supersede": {
      "label": "可能替代",
      "inverse": "可能被替代",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "may_support": {
      "label": "可能佐证",
      "inverse": "可能被佐证",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "similar": {
      "label": "相似",
      "inverse": "相似",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "analogy": {
      "label": "类比",
      "inverse": "类比",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "related": {
      "label": "相关",
      "inverse": "相关",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "refines": {
      "label": "细化",
      "inverse": "被细化",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "mentions": {
      "label": "提及",
      "inverse": "被提及",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "about": {
      "label": "关于",
      "inverse": "相关条目",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "derived_from": {
      "label": "综合自",
      "inverse": "被综合进",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    },
    "subject_of": {
      "label": "是……的主题",
      "inverse": "主题",
      "category": "framework",
      "origin": "framework",
      "writers": [],
      "evidential": false,
      "basis": false,
      "flow": null,
      "qualifiers": [],
      "required": []
    }
  },
  "marks": {
    "corroborated": {
      "group": "state",
      "label": "被佐证",
      "severity": "info",
      "rule": "有入边 supports；出处带佐证方与它的依据来源"
    },
    "opposed": {
      "group": "state",
      "label": "被反驳",
      "severity": "warn",
      "rule": "有入边 opposes"
    },
    "basis_changed": {
      "group": "state",
      "label": "依据有变化",
      "severity": "warn",
      "rule": "出边 cites 所指版本已不是当前版、被撤回，或所引段落的指纹对不上；出处带当前版"
    },
    "basis_lapsed": {
      "group": "state",
      "label": "部分依据已失效",
      "severity": "warn",
      "rule": "出边 cites 所指原件已退役或已删除；全部失效时有效性为依据失效"
    },
    "defective": {
      "group": "state",
      "label": "本版有缺陷",
      "severity": "warn",
      "rule": "人在本版标了缺陷"
    },
    "inputs_changed": {
      "group": "state",
      "label": "输入已变化",
      "severity": "warn",
      "rule": "框架页的输入有变化"
    },
    "unchecked": {
      "group": "state",
      "label": "未核查",
      "severity": "info",
      "rule": "框架页尚未核查"
    },
    "recognition_unverified": {
      "group": "notes",
      "label": "依据含未确认的识别",
      "severity": "warn",
      "rule": "出边 cites 所指段落来自未经人确认的 OCR / AI 识别（含公式 LaTeX）"
    },
    "conditions_unstated": {
      "group": "notes",
      "label": "转述但没写条件",
      "severity": "warn",
      "rule": "有原作者的结论没有写条件"
    },
    "scope_unclear": {
      "group": "notes",
      "label": "适用范围未明",
      "severity": "warn",
      "rule": "写的人声明了 scope_unclear（适用范围尚不清晰，条件里写明哪些清楚、哪些不清楚）"
    },
    "basis_incomplete": {
      "group": "notes",
      "label": "依据边界不完整",
      "severity": "info",
      "rule": "所引事实记录的边界不完整，或所引判断依据不完整"
    },
    "no_basis": {
      "group": "notes",
      "label": "结论没有依据",
      "severity": "warn",
      "rule": "结论没有出边 cites"
    },
    "premise_changed": {
      "group": "state",
      "label": "前提有变化",
      "severity": "warn",
      "rule": "出边 assumes 所指的前提被反驳、撤回或已不是当前版（设计稿 15 D-28）"
    },
    "same_source_support": {
      "group": "notes",
      "label": "只有同源佐证",
      "severity": "info",
      "rule": "入边 supports 的一方与本条依据同一份原件，不计入被佐证（设计稿 15 D-18）"
    },
    "has_cautions": {
      "group": "notes",
      "label": "有使用前须知",
      "severity": "warn",
      "rule": "有当前有效、未被反驳的使用约束针对本条（设计稿 15 D-38）"
    },
    "local_observation": {
      "group": "notes",
      "label": "人标了本地实证",
      "severity": "info",
      "rule": "人写判断时勾了本地实证"
    },
    "local_roots": {
      "group": "notes",
      "label": "本地依据的独立来源",
      "severity": "info",
      "rule": "本地实证依据来自互不相同的原件与会话，计数"
    }
  },
  "role_hints": {
    "cites": [
      "定义",
      "方法",
      "数据",
      "条件",
      "直接依据",
      "背景"
    ],
    "supports": [
      "数值一致",
      "方法不同但结论一致",
      "条件更宽"
    ],
    "opposes": [
      "数值冲突",
      "条件不同",
      "方法不同"
    ]
  },
  "note_keys": [
    "why",
    "role",
    "marker"
  ]
} as const;
