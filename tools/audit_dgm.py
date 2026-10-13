#!/usr/bin/env python3
"""审计所有章节 md 中的 dgm 图质量：
- BAD-FLAT: 无结构化子盒（dgm-box-h==0）且大量摊平 note
- BAD-ARROW-TEXT: note 文本中残留字面箭头（▼/▲/──▶）
- FALLBACK: 降级 ASCII 块（dgm-tree 内含 ┌ 画框字符）
"""
import re
import glob

for path in sorted(glob.glob('/Users/juno/codes/github/nacos-2.2.3-deep-dive/chapters/nacos-chapter-*.md')):
    src = open(path, encoding='utf-8').read()
    # 按 dgm 起点切分块（每个 <div class="dgm"> 到下一个为止）
    starts = [m.start() for m in re.finditer(r'<div class="dgm">', src)]
    problems = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(src)
        b = src[s:e]
        name = path.split('/')[-1]
        # 块号：caption
        label = re.search(r'<span class="no">([^<]*)</span>', b)
        tt = re.search(r'<span class="tt">([^<]*)</span>', b)
        cap = f'{label.group(1) if label else "?"} {tt.group(1) if tt else ""}'[:40]
        # 找所属小节
        sec = ''
        for h in re.finditer(r'^#{2,4} .*$', src[:s], re.M):
            sec = h.group(0).lstrip('#').strip()
        n_box = b.count('dgm-box-h')
        n_flat = b.count('dgm-note" style="border:none')
        arrow_text = re.findall(r'[▼▲]|──[▶◀]', re.sub(r'<[^>]*>', '', b))
        is_tree_ascii = 'dgm-tree' in b and ('┌' in b or '▶' in b)
        if is_tree_ascii:
            problems.append(('FALLBACK-ASCII', sec[:36], cap))
        elif n_box == 0 and n_flat >= 3:
            problems.append(('BAD-FLAT', sec[:36], cap))
        elif len(arrow_text) >= 2 and n_box < 2:
            problems.append(('BAD-ARROW-TEXT', sec[:36], cap))
    if problems:
        name = path.split('/')[-1]
        for p in problems:
            print(f'{name}  [{p[0]:15}] {p[1]:38} {p[2]}')
    else:
        print(f'{path.split("/")[-1]}  ✓ 无问题')
