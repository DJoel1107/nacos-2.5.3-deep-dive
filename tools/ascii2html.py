#!/usr/bin/env python3
"""ASCII 字符画图 → Swiss 风格 HTML 图示转换器（Nacos deep-dive 专用）

策略：
1. 树形目录块（├──/└── 且无 ┌）→ dgm-tree
2. 盒子结构块 → 递归解析盒子嵌套/并列/箭头 → dgm-panel/dgm-box/dgm-cols/dgm-varrow
3. 解析失败的块 → 降级为暗底样式 pre（dgm-tree 容器），并记录待人工复核
"""
import html
import re
import sys

V = '│'
ARROW_DOWN = '▼'
ARROW_RIGHT = '▶'
ARROW_LEFT = '◀'


def esc(s):
    return html.escape(s, quote=False)


def clean_text(line):
    """去掉一行中的制表符，保留文本"""
    t = line
    for ch in '│┌┐└┘├┤┬┴┼':
        t = t.replace(ch, ' ')
    t = t.replace('─', '')
    return t.strip()


def find_bottom(rows, start, end, c, c2, tol=3):
    """在 [start,end) 中寻找与 ┌(c) 匹配的盒子底边（容错边缘不对齐）"""
    for r in range(start, end):
        line = rows[r]
        bl = _find_near(line, '└', c, tol)
        if bl is None:
            continue
        if line.find('└', bl + 1) != -1:
            continue  # 一行内有多个 └，可能是别的结构
        closes = [m.start() for m in re.finditer('┘', line) if m.start() > bl]
        if closes:
            return r
    return None


def _find_near(line, ch, col, tol):
    for m in re.finditer(re.escape(ch), line):
        if abs(m.start() - col) <= tol:
            return m.start()
    return None


def find_children(rows, r0, r1, c0=None, c1=None):
    """找出 (r0,r1) 行范围内、位于 (c0,c1) 列范围内的直接子盒子（不递归）"""
    children = []
    r = r0
    while r < r1:
        line = rows[r]
        found = False
        for m in re.finditer('┌', line):
            c = m.start()
            if c0 is not None and c < c0:
                continue
            if c1 is not None and c > c1:
                continue
            c2 = line.find('┐', c + 1)
            if c2 == -1:
                continue
            if c1 is not None and c2 > c1:
                continue
            rb = find_bottom(rows, r + 1, r1, c, c2)
            if rb is None:
                continue
            # 排除起止行落在已有子盒子内部的
            if any(cr <= r <= crb for cr, cc, cc2, crb in children):
                continue
            children.append((r, c, c2, rb))
            r = rb
            found = True
            break
        if not found:
            r += 1
    return children


def classify_items(text_lines):
    """把盒内文本行分成 [(kind, html), ...]，kind: title/sub/li/kv/p"""
    items = []
    for t in text_lines:
        if not t:
            continue
        if re.match(r'^[·•]\s*', t):
            items.append(('li', esc(re.sub(r'^[·•]\s*', '', t))))
        elif re.match(r'^[-–]\s+', t):
            items.append(('li', esc(re.sub(r'^[-–]\s+', '', t))))
        else:
            m = re.match(r'^([A-Za-z_][\w.\[\]<>@]*(?:\(\))?)\s*[:：]\s*(.+)$', t)
            if m and len(m.group(1)) <= 24:
                items.append(('kv', (f'<span class="fld">{esc(m.group(1))}</span>'
                                     f'<span class="typ">: {esc(m.group(2))}</span>')))
            else:
                items.append(('p', esc(t)))
    return items


def is_arrow_row(t):
    tt = t.replace('─', '').replace('│', '').strip()
    return tt != '' and all(ch in '▼▲▶◀►◄^v|+-' or ch.isspace() for ch in tt)


def render_box(rows, r0, c0, c1, r1, depth=0):
    """递归渲染一个盒子，返回 (header_text, head_html, parts)。

    支持盒内结构：
    - 子盒子（嵌套/并列）
    - ├───┤ 分隔条 → 分节，每节渲染为独立 dgm-box
    - ▼/▲ 箭头行 → 节间连接箭头（可带标签）
    """
    children = find_children(rows, r0 + 1, r1, c0, c1)

    covered_rows = set()
    for cr, cc, cc2, crb in children:
        for r in range(cr, crb + 1):
            covered_rows.add(r)

    # 逐行扫描，按分隔条/箭头行分节
    sections = [[]]
    seps = []  # 与 sections 对齐：seps[i] 是 sections[i] 之前的分隔类型
    for r in range(r0 + 1, r1):
        if r in covered_rows:
            continue
        left = c0 + 1 if c0 is not None else 0
        seg = rows[r][left:c1] if c1 is not None else rows[r][left:]
        t = clean_text(seg)
        if not t:
            continue
        # 分隔条行：仅由 ├ ─ ┤ 空格组成
        if '├' in seg and re.fullmatch(r'[\s├┤─]+', seg):
            sections.append([])
            seps.append(('divider', None))
            continue
        # 箭头行：含 ▼/▲ 且除箭头外文字较少
        if ('▼' in seg or '▲' in seg):
            direction = 'down' if '▼' in seg else 'up'
            lbl = t.replace('▼', '').replace('▲', '').strip()
            if len(lbl) <= 40:
                sections.append([])
                seps.append(('arrow', (direction, lbl)))
                continue
        sections[-1].append(t)

    def render_section(lines):
        """一节 → (header_line 或 None, body_html)"""
        items = classify_items(lines)
        header = []
        while items and items[0][0] == 'p' and len(header) < 2:
            header.append(items.pop(0)[1])
        parts = []
        buf_li = []
        for kind, frag in items:
            if kind == 'li':
                buf_li.append(f'<li>{frag}</li>')
                continue
            if buf_li:
                parts.append('<ul class="dgm-kv">' + ''.join(buf_li) + '</ul>')
                buf_li = []
            if kind == 'kv':
                parts.append(f'<ul class="dgm-kv"><li>{frag}</li></ul>')
            else:
                parts.append(f'<div class="dgm-note" style="border:none;background:none;padding:0;">{frag}</div>')
        if buf_li:
            parts.append('<ul class="dgm-kv">' + ''.join(buf_li) + '</ul>')
        return header, ''.join(parts)

    parts = []
    head_html = ''
    header = ''

    if len(sections) == 1 or all(not s for s in sections[1:]):
        # 无有效分节 → 原有单节逻辑
        text_lines = [l for s in sections for l in s]
        items = classify_items(text_lines)
        hdr = []
        while items and items[0][0] == 'p' and len(hdr) < 2:
            hdr.append(items.pop(0)[1])
        if hdr:
            sub = hdr[1] if len(hdr) > 1 else ''
            head_html = (f'<div class="dgm-box-h"><span class="t">{hdr[0]}</span>'
                         + (f'<span class="s">{sub}</span>' if sub else '') + '</div>')
            header = re.sub(r'<[^>]+>', '', hdr[0])
        body_parts = []
        buf_li = []
        for kind, frag in items:
            if kind == 'li':
                buf_li.append(f'<li>{frag}</li>')
                continue
            if buf_li:
                body_parts.append('<ul class="dgm-kv">' + ''.join(buf_li) + '</ul>')
                buf_li = []
            if kind == 'kv':
                body_parts.append(f'<ul class="dgm-kv"><li>{frag}</li></ul>')
            else:
                body_parts.append(f'<div class="dgm-note" style="border:none;background:none;padding:0;">{frag}</div>')
        if buf_li:
            body_parts.append('<ul class="dgm-kv">' + ''.join(buf_li) + '</ul>')
        parts = body_parts
    else:
        # 多节：首节若是紧邻分隔条的短标题 → 整盒 header；其余各节 → dgm-box
        first = sections[0]
        start_sep = seps[0] if seps else ('divider', None)
        if start_sep[0] == 'divider' and first and len(first) <= 2:
            hdr = [clean_line for l in first if (clean_line := l.strip())]
            hitems = classify_items(first)
            hh = []
            while hitems and hitems[0][0] == 'p' and len(hh) < 2:
                hh.append(hitems.pop(0)[1])
            if hh:
                sub = hh[1] if len(hh) > 1 else ''
                head_html = (f'<div class="dgm-box-h"><span class="t">{hh[0]}</span>'
                             + (f'<span class="s">{sub}</span>' if sub else '') + '</div>')
                header = re.sub(r'<[^>]+>', '', hh[0])
            sec_iter = sections[1:]
            sep_iter = seps[1:]
        else:
            sec_iter = sections
            sep_iter = seps

        first_section = True
        for si, sec in enumerate(sec_iter):
            if sec:
                hdr_lines, body = render_section(sec)
                box = ''
                if hdr_lines:
                    t0 = hdr_lines[0]
                    sub = hdr_lines[1] if len(hdr_lines) > 1 else ''
                    box = (f'<div class="dgm-box"><div class="dgm-box-h"><span class="t">{t0}</span>'
                           + (f'<span class="s">{sub}</span>' if sub else '') + '</div>'
                           + (f'<div class="dgm-box-b">{body}</div>' if body else '') + '</div>')
                elif body:
                    box = f'<div class="dgm-box"><div class="dgm-box-b">{body}</div></div>'
                if box:
                    parts.append(box)
                    first_section = False
            # 本节之后、下一节之前的箭头
            if si + 1 < len(sec_iter):
                nxt_sep = sep_iter[si + 1] if si + 1 < len(sep_iter) else ('divider', None)
                if nxt_sep[0] == 'arrow':
                    direction, lbl = nxt_sep[1]
                    cls = 'dgm-varrow' if direction == 'down' else 'dgm-varrow dgm-varrow--up'
                    lbl_html = f'<span class="lbl">{esc(lbl)}</span>' if lbl else ''
                    parts.append(f'<div class="dgm-link">{lbl_html}<div class="{cls}"></div></div>')

    # 子盒子分组：按行带分组，同带并列；带之间看箭头方向
    groups = []
    for cr, cc, cc2, crb in children:
        inner = render_box(rows, cr, cc, cc2, crb, depth + 1)
        box_html = render_inner_box(inner)
        if groups and overlaps_rowband(groups[-1]['rows'], (cr, crb)):
            groups[-1]['boxes'].append(box_html)
            groups[-1]['rows'] = (min(groups[-1]['rows'][0], cr), max(groups[-1]['rows'][1], crb))
        else:
            groups.append({'rows': (cr, crb), 'boxes': [box_html], 'arrow_after': None})

    for gi in range(len(groups) - 1):
        gap0, gap1 = groups[gi]['rows'][1] + 1, groups[gi + 1]['rows'][0]
        gap = ''.join(rows[r] for r in range(gap0, gap1))
        if ARROW_RIGHT in gap or ARROW_LEFT in gap:
            groups[gi]['arrow_after'] = 'h'
        else:
            groups[gi]['arrow_after'] = 'v'

    for gi, g in enumerate(groups):
        if len(g['boxes']) > 1:
            parts.append(f'<div class="dgm-cols dgm-cols-{min(len(g["boxes"]), 5)}">'
                         + ''.join(f'<div>{b}</div>' for b in g['boxes']) + '</div>')
        else:
            parts.append(g['boxes'][0])
        if g['arrow_after'] == 'v':
            parts.append('<div class="dgm-varrow"></div>')

    return (header, head_html, parts)


def overlaps_rowband(a, b):
    return not (a[1] < b[0] or b[1] < a[0])


def render_inner_box(inner):
    """渲染非最外层的盒子 → dgm-box"""
    header, head_html, parts = inner
    body = ''.join(parts)
    return f'<div class="dgm-box">{head_html}<div class="dgm-box-b">{body}</div></div>'


def convert_diagram(block_text, fig_label=None, fig_title=None):
    rows = block_text.split('\n')
    n = len(rows)

    # 顶层盒子
    children = find_children(rows, 0, n)
    if not children:
        return None

    cap = ''
    if fig_label:
        tt = f'<span class="tt">{esc(fig_title)}</span>' if fig_title else ''
        cap = (f'<div class="dgm-cap"><span class="no">{esc(fig_label)}</span>{tt}</div>')

    # 若首个盒子几乎覆盖整个块 → 作为外层面板
    cr, cc, cc2, crb = children[0]
    if len(children) == 1 and cr <= 1 and crb >= n - 3:
        header, head_html, parts = render_box(rows, cr, cc, cc2, crb)
        head_color = 'dgm-panel-head'
        head = head_html or f'<div class="dgm-panel-head"><span class="t">{header}</span></div>'
        if head_html:
            head = head_html.replace('dgm-box-h', 'dgm-panel-head ' + head_color, 1)
        return f'<div class="dgm">{cap}<div class="dgm-panel">{head}<div class="dgm-panel-body">{"".join(parts)}</div></div></div>'

    # 多个顶层盒子：垂直堆叠，带间箭头
    parts = []
    for gi, (cr, cc, cc2, crb) in enumerate(children):
        inner = render_box(rows, cr, cc, cc2, crb)
        header, head_html, body_parts = inner
        body = ''.join(body_parts)
        box_html = f'<div class="dgm-box">{head_html}<div class="dgm-box-b">{body}</div></div>'
        parts.append(box_html)
        if gi < len(children) - 1:
            nr = children[gi + 1][0]
            gap = ''.join(rows[r] for r in range(crb + 1, nr))
            t = clean_text(gap)
            if ARROW_DOWN in gap:
                parts.append('<div class="dgm-link"><div class="dgm-varrow"></div></div>')
            elif ARROW_RIGHT in gap:
                lbl = clean_text(gap.replace('▶', '').replace('◀', '').replace('─', '').replace('│', ''))
                lbl_html = f'<span class="lbl">{esc(lbl)}</span>' if lbl else ''
                parts.append(f'<div class="dgm-link">{lbl_html}<div class="dgm-varrow dgm-varrow--accent" style="transform:rotate(90deg);"></div></div>')
            elif t:
                parts.append(f'<div class="dgm-note">{esc(t)}</div>')
            elif '│' in gap:
                parts.append('<div class="dgm-link"><div class="dgm-varrow"></div></div>')
    return f'<div class="dgm">{cap}{"".join(parts)}</div>'


def convert_tree(block_text, fig_label=None, fig_title=None):
    out = []
    for line in block_text.split('\n'):
        e = esc(line.rstrip())
        if not e.strip():
            out.append('')
            continue
        e = re.sub(r'((?:├──|└──)\s*)([\w.-]+/)', r'\1<span class="dir">\2</span>', e)
        e = re.sub(r'(\s)(#[^<]*)$', r'\1<span class="cmt">\2</span>', e)
        e = re.sub(r'\b(persistence/|logger-adapter-impl/)\b', r'<span class="new">\1</span>', e)
        out.append(e)
    body = '\n'.join(out)
    cap = ''
    if fig_label:
        tt = f'<span class="tt">{esc(fig_title)}</span>' if fig_title else ''
        cap = f'<div class="dgm-cap"><span class="no">{esc(fig_label)}</span>{tt}</div>'
    return f'<div class="dgm">{cap}<div class="dgm-tree">{body}</div></div>'


FIG_RE = re.compile(r'/\*\s*(图\s*[\d.-]+)\s*[：:]?\s*(.*?)\s*\*/')


def parse_caption(block_text):
    m = FIG_RE.search(block_text)
    if m:
        title = m.group(2).strip()
        # 仅当全角括号成对时去掉最外层
        if title.startswith('（') and title.endswith('）'):
            title = title[1:-1].strip()
        return m.group(1), title or None
    return None, None


def is_tree(block_text):
    lines = [l for l in block_text.split('\n') if l.strip()]
    has_tree = sum(1 for l in lines if re.search(r'[├└]──', l))
    has_box = sum(1 for l in lines if '┌' in l)
    return has_tree >= 2 and has_box == 0


def looks_like_diagram(block_text):
    return ('┌' in block_text or '├' in block_text or '└' in block_text
            or '│' in block_text)


def convert_block(block_text):
    """返回 (html, status)，status: ok/tree/fallback"""
    if not looks_like_diagram(block_text):
        return None, 'skip'
    if is_tree(block_text):
        label, title = parse_caption(block_text)
        return convert_tree(block_text, label, title), 'tree'
    label, title = parse_caption(block_text)
    text = re.sub(r'/\*\s*图\s*[\d.-]+[^*]*\*/', '', block_text, count=1)
    try:
        h = convert_diagram(text, label, title)
    except Exception as e:
        h = None
        print(f'    [parse-error] {e}', file=sys.stderr)
    if h:
        return h, 'ok'
    label_html = f'{label} {title}' if label else '图示'
    body = esc(block_text)
    return (f'<div class="dgm"><div class="dgm-cap"><span class="no">{esc(label or "图示")}</span>'
            f'<span class="tt">{esc(title or "")}</span></div>'
            f'<div class="dgm-tree">{body}</div></div>'), 'fallback'


def process_md(path, dry=False):
    src = open(path, encoding='utf-8').read()
    lines = src.split('\n')
    out = []
    i = 0
    n = len(lines)
    stats = {'ok': 0, 'tree': 0, 'fallback': 0, 'skip': 0}
    fallbacks = []
    while i < n:
        s = lines[i].strip()
        if s.startswith('```'):
            lang = s[3:].strip()
            j = i + 1
            while j < n and lines[j].strip() != '```':
                j += 1
            if j >= n:
                out.append(lines[i]); i += 1; continue
            body = '\n'.join(lines[i + 1:j])
            result, status = (None, 'skip')
            if lang == '':
                result, status = convert_block(body)
            if result:
                out.append(result)
                stats[status] += 1
                if status == 'fallback':
                    label, title = parse_caption(body)
                    fallbacks.append((path.split("/")[-1], i + 1, label or body.strip()[:30]))
            else:
                stats['skip'] += 1
                out.extend(lines[i:j + 1])
            i = j + 1
            continue
        out.append(lines[i])
        i += 1
    if not dry:
        open(path, 'w', encoding='utf-8').write('\n'.join(out))
    return stats, fallbacks


if __name__ == '__main__':
    import glob
    paths = sys.argv[1:] or sorted(glob.glob('/Users/juno/codes/github/nacos-2.2.3-deep-dive/chapters/nacos-chapter-*.md'))
    all_fb = []
    for p in paths:
        stats, fb = process_md(p)
        name = p.split('/')[-1]
        print(f"{name}: ok={stats['ok']} tree={stats['tree']} fallback={stats['fallback']} skip={stats['skip']}")
        all_fb.extend(fb)
    print('\n待人工复核（fallback）:')
    for f in all_fb:
        print(' ', f)
