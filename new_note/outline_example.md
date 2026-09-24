---
name: Example_Note
template: Math-Note
levels: part, chapter, section
---

<!--
大纲示例（可直接复制改写）。要点：
  1. 上面 --- 之间是元信息块，可省；name / template / levels 都能省，省了就在交互里问。
  2. levels: 写预设名或命令序列，命令**由外到内**排列，几个命令就是几层目录。
     常用：bourbaki = part,chapter,section ／ textbook = chapter,section,subsection
  3. 标题层级 = 目录层级：# 是最外层，逐级往下，不能跳级（# 之后只能紧接 ##）。
  4. 每行写「目录名 | 中译名」：目录名用英文（不必写 1_ 编号，脚本按顺序自动补），
     中译名放 | 右边，会写进 \part{} / \chapter{} / \section{} 等标题命令里。
  5. 本文件用 bourbaki 模式：层1 → \part（写进 main.tex），层2 → \chapter，层3 → \section。
     若换成 levels: textbook（chapter,section,subsection），则下面应再深一层。
-->

# Description_of_Formal_Mathematic | 数学的形式化描述
## Terms_and_relations | 项与关系
### Terms | 项
### Formative_constructions | 合式构造
## Substitution | 替换
### Criteria_of_substitution | 替换的判定

# Set_Theory | 集合论
## Collectivizing_relations | 集合化关系
### The_relation_of_membership | 属于关系
