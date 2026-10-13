#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将 chapter-html/*.html 增强为轻量 Wiki 站点（v3 · 三栏阅读布局）

布局：
- 顶部吸顶面包屑：章节路径（第 N 章 → 当前小节），随滚动更新，右侧集成视图工具
- 左侧侧边栏：仅章节级导航（四部分 / 16 章）+ 全文搜索
- 右侧小节导航：当前章的 h2/h3 目录，滚动高亮（宽屏显示）
- 源码引用链接、上/下章导航、暗色主题、阅读宽度、侧栏收起（localStorage 记忆）

用法：bash build/build-wiki.sh（内部先跑 build-html.sh 再跑本脚本，避免重复注入）
"""
import html
import json
import os
import re
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'chapter-html')
BUILD_STAMP = datetime.now().strftime('%Y-%m-%d %H:%M')

# 源码链接基址（可按需改为 fork / 内网 Git；注意官方 tag 无 v 前缀）
SOURCE_BASE = 'https://github.com/alibaba/nacos/blob/2.5.3/'

CHAPTERS = [
    ("01", "第 1 章", "Nacos 2.5.3 整体架构概述", "第一部分 · 架构与设计"),
    ("02", "第 2 章", "注册中心（Naming）源码深度分析", "第一部分 · 架构与设计"),
    ("03", "第 3 章", "配置中心（Config）源码深度分析", "第一部分 · 架构与设计"),
    ("04", "第 4 章", "一致性协议（JRaft & Distro）深度分析", "第一部分 · 架构与设计"),
    ("05", "第 5 章", "集群管理（Core）+ 客户端 SDK 深度分析", "第一部分 · 架构与设计"),
    ("06", "第 6 章", "持久化层（persistence）深度分析", "第二部分 · 持久化与扩展"),
    ("07", "第 7 章", "认证安全、控制台与周边模块", "第二部分 · 持久化与扩展"),
    ("08", "第 8 章", "插件体系与 SPI 扩展机制", "第二部分 · 持久化与扩展"),
    ("09", "第 9 章", "全量配置项详解", "第三部分 · 配置与部署"),
    ("10", "第 10 章", "生产环境部署架构", "第三部分 · 配置与部署"),
    ("11", "第 11 章", "高可用架构设计", "第三部分 · 配置与部署"),
    ("12", "第 12 章", "性能调优深度分析", "第三部分 · 配置与部署"),
    ("13", "第 13 章", "监控运维", "第四部分 · 运维与实践"),
    ("14", "第 14 章", "故障排查指南", "第四部分 · 运维与实践"),
    ("15", "第 15 章", "Spring Cloud Alibaba 集成最佳实践", "第四部分 · 运维与实践"),
    ("16", "第 16 章", "附录", "第四部分 · 运维与实践"),
]

# ============================================================ CSS
WIKI_CSS = """
<style>
/* === Wiki Shell v3 === */
:root { --wiki-side-w: 288px; --wiki-toc-w: 190px; --wiki-crumb-h: 52px; --content-w: 900px; }
html.wiki-narrow { --content-w: 820px; }
html { scroll-padding-top: calc(var(--wiki-crumb-h) + 20px); }

/* —— 左侧章节导航 —— */
.wiki-side {
  position: fixed; top: 0; left: 0; bottom: 0; width: var(--wiki-side-w); z-index: 60;
  overflow-y: auto; overflow-x: hidden; background: var(--paper);
  border-right: 1px solid var(--border-subtle);
  padding: 0 14px 48px; font-size: 13.5px;
  transition: transform .25s cubic-bezier(.2,.7,.3,1);
}
/* 滚动条：细圆角、平时隐形、悬停侧栏时淡入 */
.wiki-side { scrollbar-width: thin; scrollbar-color: transparent transparent; scroll-behavior: smooth; }
.wiki-side::-webkit-scrollbar { width: 6px; }
.wiki-side::-webkit-scrollbar-track { background: transparent; }
.wiki-side::-webkit-scrollbar-thumb { background: transparent; border-radius: 3px; }
.wiki-side:hover { scrollbar-color: rgba(10,10,10,.22) transparent; }
.wiki-side:hover::-webkit-scrollbar-thumb { background: rgba(10,10,10,.18); }
.wiki-side:hover::-webkit-scrollbar-thumb:hover { background: rgba(10,10,10,.32); }
html.dark .wiki-side:hover { scrollbar-color: rgba(255,255,255,.22) transparent; }
html.dark .wiki-side:hover::-webkit-scrollbar-thumb { background: rgba(255,255,255,.18); }
html.dark .wiki-side:hover::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,.32); }
.wiki-side a { border-bottom: none; word-break: break-word; }
body.wiki-side-hidden .wiki-side { transform: translateX(-100%); }

/* 书名固定在侧栏顶部，不随章节列表滚动 */
.wiki-brand {
  position: sticky; top: 0; z-index: 2;
  margin: 0 -14px 12px; padding: 18px 14px 12px;
  background: var(--paper);
  border-bottom: 1px solid var(--border-subtle);
}
.wiki-brand-row { display: flex; align-items: flex-start; gap: 8px; }
.wiki-logo { font-weight: 900; font-size: 15px; letter-spacing: -.01em; display: block; flex: 1; }
.wiki-logo a { color: var(--ink); text-decoration: none; }
.wiki-logo a:hover { color: var(--accent); }
.wiki-close { flex-shrink: 0; width: 26px; height: 26px; margin-top: -2px;
  border: none; background: none; border-radius: 5px; cursor: pointer;
  color: var(--text-helper); font-size: 13px; line-height: 1; transition: color .15s, background .15s; }
.wiki-close:hover { color: var(--ink); background: var(--grey-1); }
.wiki-sub-logo { font-family: var(--mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-helper); display: block; margin-top: 4px; }

.wiki-search-wrap { position: relative; margin: 0 0 10px; }
.wiki-search { width: 100%; box-sizing: border-box; font: inherit; font-size: 13px;
  padding: 8px 12px; border: 1.5px solid var(--border-subtle); border-radius: 6px;
  background: var(--grey-1); color: var(--ink); outline: none; transition: border-color .15s; }
.wiki-search:focus { border-color: var(--accent); background: #fff; }
html.dark .wiki-search:focus { background: #181b21; }
.wiki-results { border: 1px solid var(--border-subtle); border-radius: 6px; overflow: hidden;
  margin: 6px 0 10px; display: none; background: #fff; box-shadow: 0 8px 24px rgba(10,10,10,.08); }
html.dark .wiki-results { background: #181b21; }
.wiki-results a { display: block; padding: 8px 11px; color: var(--ink);
  border-bottom: 1px solid var(--border-subtle); font-size: 12.5px; line-height: 1.5; }
.wiki-results a:last-child { border-bottom: none; }
.wiki-results a:hover { background: var(--grey-1); }
.wiki-results .r-sec { color: var(--accent); font-weight: 600; display: block; }
.wiki-results .r-snip { color: var(--text-helper); font-size: 11.5px; display: block; margin-top: 2px; }

.wiki-part { font-family: var(--mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-helper); margin: 16px 0 6px; padding-left: 8px; }
.wiki-stamp { font-family: var(--mono); font-size: 9.5px; color: var(--text-helper);
  opacity: .65; margin: 28px 0 0 8px; letter-spacing: .04em; }
.wiki-ch { display: flex; align-items: baseline; gap: 8px; padding: 6px 9px; border-radius: 6px;
  color: var(--ink); line-height: 1.45; border-left: 2px solid transparent; }
.wiki-ch:hover { background: var(--grey-1); }
.wiki-ch .cn { font-family: var(--mono); font-size: 11px; font-weight: 600; color: var(--text-helper);
  flex-shrink: 0; min-width: 20px; }
.wiki-ch.active { background: #e8eaf6; color: var(--accent); font-weight: 600; border-left-color: var(--accent); }
html.dark .wiki-ch.active { background: #1c2340; }
.wiki-ch.active .cn { color: var(--accent); }

/* —— 顶部吸顶面包屑（纯色底，兼容性优先） —— */
.wiki-crumb {
  position: fixed; top: 0; right: 0; left: var(--wiki-side-w); height: var(--wiki-crumb-h); z-index: 55;
  display: flex; align-items: center; gap: 10px;
  box-sizing: border-box;
  background: var(--paper);
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px; color: var(--text-secondary);
  /* 路径起点 = 正文左缘 = 居中偏移 + 正文内边距（left 已含侧栏宽度） */
  padding-left: max(32px, calc((100% - var(--wiki-side-w) - var(--content-w)) / 2 + var(--sp-8)));
  padding-right: var(--sp-8);
}
body.wiki-side-hidden .wiki-crumb {
  left: 0;
  padding-left: max(56px, calc((100% - var(--content-w)) / 2 + var(--sp-8)));
}
.wiki-crumb .c-ch { font-weight: 600; color: var(--ink); white-space: nowrap; flex-shrink: 0; }
.wiki-crumb .c-ch:hover { color: var(--accent); }
.wiki-crumb .c-sep { color: var(--text-helper); flex-shrink: 0; }
.wiki-crumb .c-sec { color: var(--text-secondary); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; flex: 1 1 auto; min-width: 0; margin-right: 20px; }
.wiki-crumb .c-tools { margin-left: auto; display: flex; gap: 6px; flex-shrink: 0; }
.wiki-crumb .c-tools button { height: 30px; padding: 0 11px; border-radius: 6px; border: 1px solid var(--border-subtle);
  background: transparent; color: var(--ink); font-size: 12px; cursor: pointer;
  display: flex; align-items: center; gap: 5px; transition: border-color .15s, color .15s; }
.wiki-crumb .c-tools button:hover { border-color: var(--accent); color: var(--accent); }
.wiki-crumb .c-tools button.on { border-color: var(--accent); color: var(--accent); }

body { padding-top: calc(var(--wiki-crumb-h) + 24px); max-width: var(--content-w); }
/* 正文相对「视口 - 左侧大导航」横向居中；右侧小节目录纯悬浮，不参与布局 */
body {
  margin-left: calc(var(--wiki-side-w) + max(0px, (100% - var(--wiki-side-w) - var(--content-w)) / 2));
  margin-right: 0;
}
body.wiki-side-hidden {
  margin-left: auto;
  margin-right: auto;
}
html.wiki-narrow body { max-width: var(--content-w); }

/* —— 右侧小节导航：仅左侧栏收起时展示（互斥设计） —— */
.wiki-pagetoc {
  position: fixed; top: 50%; right: 10px; transform: translateY(-50%);
  width: var(--wiki-toc-w); max-height: min(76vh, 700px); overflow-y: auto; z-index: 40;
  font-size: 11.5px; display: none;
  padding: 4px 0; box-sizing: border-box;
}
body.wiki-side-hidden .wiki-pagetoc.has { display: block; }
.wiki-pagetoc { scrollbar-width: thin; scrollbar-color: transparent transparent; scroll-behavior: smooth; }
.wiki-pagetoc::-webkit-scrollbar { width: 4px; }
.wiki-pagetoc::-webkit-scrollbar-track { background: transparent; }
.wiki-pagetoc::-webkit-scrollbar-thumb { background: transparent; border-radius: 2px; }
.wiki-pagetoc:hover { scrollbar-color: rgba(10,10,10,.22) transparent; }
.wiki-pagetoc:hover::-webkit-scrollbar-thumb { background: rgba(10,10,10,.18); }
html.dark .wiki-pagetoc:hover { scrollbar-color: rgba(255,255,255,.22) transparent; }
html.dark .wiki-pagetoc:hover::-webkit-scrollbar-thumb { background: rgba(255,255,255,.18); }
.wiki-pagetoc .pt-title { font-family: var(--mono); font-size: 9px; letter-spacing: .14em;
  text-transform: uppercase; color: var(--text-helper); opacity: .75; padding: 2px 12px 6px; }
.wiki-pagetoc a { display: block; padding: 2.5px 12px; color: var(--text-helper); text-decoration: none;
  border-bottom: none;
  line-height: 1.4; border-left: 2px solid transparent;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wiki-pagetoc a.is-h3 { padding-left: 24px; font-size: 11px; opacity: .85; }
.wiki-pagetoc a:hover { color: var(--accent); white-space: normal; }
.wiki-pagetoc a.current { color: var(--accent); font-weight: 600; border-left-color: var(--accent); }
@media (max-width: 1279px) { .wiki-pagetoc { display: none !important; } }

/* 窄窗口收起侧栏时正文已全宽，目录悬浮会压字 → 隐藏 */
@media (max-width: 1299px) { .wiki-pagetoc { display: none !important; } }

/* —— 悬浮按钮：侧栏收起时的菜单入口 —— */
.wiki-fab { position: fixed; top: 11px; left: 12px; z-index: 70; display: none;
  width: 36px; height: 36px; border-radius: 8px; border: 1px solid var(--border-subtle);
  background: #fff; color: var(--ink); font-size: 16px; cursor: pointer;
  box-shadow: 0 2px 10px rgba(10,10,10,.08); }
html.dark .wiki-fab { background: #181b21; }
body.wiki-side-hidden .wiki-fab { display: block; }

/* —— 上/下章 —— */
.wiki-pager { display: flex; gap: 12px; margin: 64px 0 0; }
.wiki-pager a { flex: 1; text-decoration: none; color: var(--ink); border: 1px solid var(--border-subtle);
  border-radius: 6px; padding: 14px 18px; transition: border-color .15s; }
.wiki-pager a:hover { border-color: var(--accent); }
.wiki-pager a.next { text-align: right; }
.wiki-pager .dir { display: block; font-family: var(--mono); font-size: 11px; letter-spacing: .1em;
  text-transform: uppercase; color: var(--text-helper); margin-bottom: 4px; }
.wiki-pager .pt { font-weight: 600; font-size: .95em; }

/* —— 源码链接 —— */
.src-link { border-bottom: 1px solid var(--accent-bright); color: var(--accent); text-decoration: none; }
.src-link:hover { border-bottom-color: var(--accent); }

/* —— 暗色主题 —— */
html.dark {
  --paper: #121418; --ink: #e6e9f0; --text-secondary: #a9aeb9; --text-helper: #7b8190;
  --border-subtle: #262a32; --grey-1: #1a1d23; --accent: #7b93ff; --accent-bright: #93a6ff;
  --blue-tint: #161d33; --blue-tint-border: #2a3560;
  --lane-blue: #1b2440; --lane-blue-border: #2a3560;
  --bright-text: #93a6ff; --bright-soft: #1c2340;
}
html.dark body { background: var(--paper); }
html.dark .dgm-panel, html.dark .dgm-box, html.dark .dgm-card, html.dark .dgm-ecochip,
html.dark .dgm-step, html.dark .dgm-chip, html.dark .dgm-nest, html.dark .dgm-layer,
html.dark .dgm-infra { background: #181b21; }
html.dark .dgm-box-h { background: #1c2027; border-bottom-color: var(--border-subtle); }
html.dark .dgm-box-h--blue { background: #1b2440; border-bottom-color: #2a3560; }
html.dark .dgm-panel-head { background: #1e2f6e; }
html.dark .dgm-panel-head--ink { background: #08090b; }
html.dark .dgm-panel-head--grey { background: var(--grey-1); color: var(--ink); }
html.dark .dgm-layer-label { background: #1c2027; }
html.dark .dgm-note { background: #1c2027; }
html.dark .dgm-badge--ap { background: #1c2340; }
html.dark .dgm-badge--cp { background: #e6e9f0; color: #121418; }
html.dark .dgm-badge--new { color: #0d1117; }
html.dark .dgm-panel-head, html.dark .dgm-box-h--ink { color: #eef1fd; }
html.dark .dgm-card .m { background: #1c2027; color: var(--text-secondary); }
html.dark .dgm-cap { border-bottom-color: var(--border-subtle); }
html.dark code { background: #1c2027; color: var(--accent-bright); }
html.dark .dgm-tree { background: #0a0b0d; }
html.dark .wiki-results a:hover, html.dark .wiki-pagetoc a.current { background: #1c2027; }
html.dark .wiki-ch:hover { background: #1c2027; }

@media (max-width: 1000px) {
  .wiki-side { transform: translateX(-100%); }
  .wiki-crumb { left: 0; }
  body.wiki-side-mobile-open .wiki-side { transform: none; box-shadow: 0 0 60px rgba(0,0,0,.3); }
  body { margin-left: 0 !important; margin-right: 0 !important; --res-l: 0px; --res-r: 0px; }
}
@media print { .wiki-side, .wiki-pager, .wiki-crumb, .wiki-fab, .wiki-pagetoc { display: none; }
  body { margin-left: 0 !important; padding-top: 0 !important; } }
</style>
"""

# ============================================================ JS
WIKI_JS = """
<script>
(function () {
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };

  /* —— 视图状态恢复（支持 ?theme=dark|light&width=narrow URL 参数覆盖） —— */
  var qp = new URLSearchParams(location.search);
  var qpTheme = qp.get('theme');
  if (qpTheme === 'dark' || (qpTheme !== 'light' && store.get('wiki-dark', false)))
    document.documentElement.classList.add('dark');
  if (qp.get('width') === 'narrow' || store.get('wiki-narrow', false))
    document.documentElement.classList.add('wiki-narrow');
  if (store.get('wiki-side-hidden', false)) document.body.classList.add('wiki-side-hidden');

  function bindTool(id, fn) {
    /* 事件委托绑定：不依赖按钮存在的时序 */
    document.addEventListener('click', function (ev) {
      var t = ev.target;
      var b = t && t.closest ? t.closest('#' + id) : null;
      if (b) fn.call(b, ev);
    });
  }

  bindTool('wiki-btn-theme', function () {
    var on = document.documentElement.classList.toggle('dark');
    store.set('wiki-dark', on); this.classList.toggle('on', on);
  });
  bindTool('wiki-btn-width', function () {
    var on = document.documentElement.classList.toggle('wiki-narrow');
    store.set('wiki-narrow', on); this.classList.toggle('on', on);
  });
  /* 汉堡按钮：展开左侧栏 */
  bindTool('wiki-fab', function () {
    document.body.classList.remove('wiki-side-hidden');
    document.body.classList.remove('wiki-side-mobile-open');
  });
  /* 侧栏内 ✕：收起左侧栏 */
  bindTool('wiki-close', function () {
    document.body.classList.add('wiki-side-hidden');
    document.body.classList.remove('wiki-side-mobile-open');
  });

  function syncBtn(id, on) { var b = document.getElementById(id); if (b) b.classList.toggle('on', on); }
  syncBtn('wiki-btn-theme', store.get('wiki-dark', false));
  syncBtn('wiki-btn-width', store.get('wiki-narrow', false));

  /* —— 搜索 —— */
  var input = document.getElementById('wiki-search');
  var box = document.getElementById('wiki-results');
  if (input && box) {
    var INDEX = window.WIKI_INDEX || [];
    function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    input.addEventListener('input', function () {
      var q = input.value.trim().toLowerCase();
      if (q.length < 2) { box.style.display = 'none'; box.innerHTML = ''; return; }
      var hits = [];
      for (var i = 0; i < INDEX.length && hits.length < 20; i++) {
        var e = INDEX[i];
        if ((e.t + ' ' + e.s + ' ' + e.x).toLowerCase().indexOf(q) !== -1) hits.push(e);
      }
      box.innerHTML = hits.length
        ? hits.map(function (e) {
            return '<a href="' + e.u + '#' + e.a + '"><span class="r-sec">' + esc(e.t) + ' · ' + esc(e.s) + '</span>'
              + '<span class="r-snip">' + esc(e.x.slice(0, 90)) + '…</span></a>';
          }).join('')
        : '<a>无匹配结果</a>';
      box.style.display = 'block';
    });
    document.addEventListener('click', function (ev) {
      if (!box.contains(ev.target) && ev.target !== input) box.style.display = 'none';
    });
  }

  /* —— 滚动监听：更新面包屑当前小节 + 右侧目录高亮 —— */
  var crumbSec = document.getElementById('wiki-crumb-sec');
  var tocLinks = Array.prototype.slice.call(document.querySelectorAll('.wiki-pagetoc a'));
  var byId = {};
  tocLinks.forEach(function (a) { byId[a.getAttribute('href').split('#')[1]] = a; });
  if ('IntersectionObserver' in window) {
    var current = null;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var id = en.target.id;
        if (current) current.classList.remove('current');
        current = byId[id];
        if (current) current.classList.add('current');
        if (crumbSec) {
          var a = byId[id];
          crumbSec.textContent = a ? a.textContent : '';
          crumbSec.href = '#' + id;
        }
      });
    }, { rootMargin: '0px 0px -72% 0px' });
    Object.keys(byId).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) io.observe(el);
    });
  }
})();
</script>
"""


def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s)


def extract_toc(page_html):
    toc = []
    for m in re.finditer(r'<h([23]) id="([^"]+)"[^>]*>(.*?)</h\1>', page_html, re.S):
        toc.append((int(m.group(1)), m.group(2), strip_tags(m.group(3)).strip()))
    return toc


def section_snippets(page_html, toc):
    cuts = []
    for lv, aid, _ in toc:
        m = re.search(r'<h%d id="%s"' % (lv, re.escape(aid)), page_html)
        if m:
            cuts.append((m.start(), aid))
    snippets = {}
    for i, (pos, aid) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(page_html)
        seg = strip_tags(page_html[pos:end])
        seg = re.sub(r'\s+', ' ', seg).strip()
        snippets[aid] = seg[:180]
    return snippets


# ============================================================ 源码链接
JAVA_FULL = re.compile(r'\b((?:[A-Za-z0-9_$-]+/)+[A-Za-z0-9_$-]+)\.java')
JAVA_ANY = re.compile(r'\b([A-Za-z0-9_./$-]+)\.java(:\d{1,5}(?:-\d{1,5})?)?')

MODULE_ROOTS = ['logger-adapter-impl/', 'plugin-default-impl/', 'plugin/', 'api/', 'client/',
                'common/', 'config/', 'console/', 'core/', 'naming/', 'persistence/',
                'auth/', 'istio/', 'prometheus/', 'sys/', 'address/', 'cmdb/', 'control/', 'lock/']


def normalize_java_path(path):
    p = re.sub(r'^nacos-[\d.]+/', '', path)
    best = None
    for root in MODULE_ROOTS:
        i = p.find(root)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, root)
    if best:
        return p[best[0]:]
    return p


def build_path_index(all_pages):
    by_base, by_suffix = {}, {}
    for raw in all_pages:
        for m in JAVA_FULL.finditer(raw):
            full = normalize_java_path(m.group(1) + '.java')
            if 'src/main/java' not in full:
                continue
            base = full.split('/')[-1]
            cur = by_base.get(base)
            if cur is None or ('src/main/java' in full and 'src/main/java' not in cur):
                by_base[base] = full
            pos = full.find('/')
            while pos != -1:
                suf = full[pos + 1:]
                if '/' in suf:
                    cur = by_suffix.get(suf)
                    if cur is None or ('src/main/java' in full and 'src/main/java' not in cur):
                        by_suffix[suf] = full
                pos = full.find('/', pos + 1)
    return by_base, by_suffix


def resolve_path(pathpart, by_base, by_suffix):
    if '/' in pathpart:
        cand = pathpart + '.java' if not pathpart.endswith('.java') else pathpart
        norm = normalize_java_path(cand)
        if 'src/main/java' in norm:
            return norm
        resolved = by_suffix.get(norm)
        if resolved is None:
            parts = norm.split('/')
            for i in range(1, len(parts)):
                resolved = by_suffix.get('/'.join(parts[i:]))
                if resolved:
                    break
        if resolved is None:
            resolved = by_base.get(norm.split('/')[-1])
        if resolved is None:
            return None
        return resolved
    return by_base.get(pathpart + '.java')


def link_source_refs(page_html, by_base, by_suffix):
    parts = re.split(r'(<[^>]+>)', page_html)
    out = []
    linked = 0
    for seg in parts:
        if seg.startswith('<'):
            out.append(seg)
            continue

        def rep(m):
            nonlocal linked
            pathpart, lns = m.group(1), m.group(2) or ''
            full = resolve_path(pathpart, by_base, by_suffix)
            if not full:
                return m.group(0)
            l1 = re.match(r':(\d+)', lns)
            href = f'{SOURCE_BASE}{full}'
            if l1:
                href += f'#L{l1.group(1)}'
                l2 = re.match(r':\d+-(\d+)', lns)
                if l2:
                    href += f'-L{l2.group(1)}'
            linked += 1
            return (f'<a class="src-link" href="{href}" target="_blank" rel="noopener" '
                    f'title="{html.escape(full)}">{m.group(0)}</a>')

        out.append(JAVA_ANY.sub(rep, seg))
    return ''.join(out), linked


# ============================================================ 页面构件
def build_sidebar(chapters_meta, active_num=None):
    """左侧：仅章节级导航"""
    h = ['<aside class="wiki-side" id="wiki-side">']
    h.append('<div class="wiki-brand"><div class="wiki-brand-row">'
             '<span class="wiki-logo"><a href="index.html">Nacos 2.5.3 深度研究</a></span>'
             '<button class="wiki-close" id="wiki-close" title="收起侧栏">✕</button>'
             '</div><span class="wiki-sub-logo">Source-level Deep Dive</span></div>')
    h.append('<div class="wiki-search-wrap"><input class="wiki-search" id="wiki-search" type="search" '
             'placeholder="搜索章节内容…" autocomplete="off"></div>')
    h.append('<div class="wiki-results" id="wiki-results"></div>')
    cur_part = None
    for num, label, title, part in chapters_meta:
        if part != cur_part:
            h.append(f'<div class="wiki-part">{html.escape(part)}</div>')
            cur_part = part
        file_name = f'nacos-chapter-{num}.html'
        active = ' active' if num == active_num else ''
        chno = label.replace('第 ', '').replace(' 章', '')
        h.append(f'<a class="wiki-ch{active}" href="{file_name}">'
                 f'<span class="cn">{chno}</span><span>{html.escape(title)}</span></a>')
    h.append(f'<div class="wiki-stamp">build {BUILD_STAMP}</div>')
    h.append('</aside>')
    h.append('<button class="wiki-fab" id="wiki-fab" aria-label="打开菜单">☰</button>')
    return ''.join(h)


def build_crumb(chapters_meta, active_num, toc_map_first):
    """顶部吸顶面包屑 + 视图工具"""
    num, label, title, _ = next(c for c in chapters_meta if c[0] == active_num)
    h = ['<div class="wiki-crumb" id="wiki-crumb">']
    h.append(f'<span class="c-ch"><a href="nacos-chapter-{num}.html" '
             f'style="color:inherit;text-decoration:none;">{label}：{html.escape(title)}</a></span>')
    h.append('<span class="c-sep">→</span>')
    first_sec = toc_map_first.get(num, '')
    h.append(f'<span class="c-sec" id="wiki-crumb-sec">{html.escape(first_sec)}</span>')
    h.append('<span class="c-tools">'
             '<button id="wiki-btn-theme" title="切换暗色/亮色主题">🌙 主题</button>'
             '<button id="wiki-btn-width" title="切换阅读宽度">↔ 宽度</button>'
             '</span>')
    h.append('</div>')
    return ''.join(h)


def build_pagetoc(toc):
    """右侧小节导航"""
    if not toc:
        return ''
    h = ['<nav class="wiki-pagetoc has" id="wiki-pagetoc">']
    h.append('<div class="pt-title">本页目录</div>')
    for lv, aid, text in toc:
        cls = 'is-h3' if lv == 3 else ''
        h.append(f'<a class="{cls}" href="#{aid}">{html.escape(text)}</a>')
    h.append('</nav>')
    return ''.join(h)


def build_pager(chapters_meta, active_num):
    idx = next(i for i, c in enumerate(chapters_meta) if c[0] == active_num)
    h = ['<nav class="wiki-pager">']
    if idx > 0:
        p = chapters_meta[idx - 1]
        h.append(f'<a href="nacos-chapter-{p[0]}.html"><span class="dir">← 上一章</span>'
                 f'<span class="pt">{p[1]} {html.escape(p[2])}</span></a>')
    else:
        h.append('<a href="index.html"><span class="dir">← 返回</span><span class="pt">总目录</span></a>')
    if idx + 1 < len(chapters_meta):
        n = chapters_meta[idx + 1]
        h.append(f'<a class="next" href="nacos-chapter-{n[0]}.html"><span class="dir">下一章 →</span>'
                 f'<span class="pt">{n[1]} {html.escape(n[2])}</span></a>')
    else:
        h.append('<a class="next" href="index.html"><span class="dir">返回</span><span class="pt">总目录</span></a>')
    h.append('</nav>')
    return ''.join(h)


def inject(page_html, inject_html):
    if '</head>' in page_html:
        page_html = page_html.replace('</head>', WIKI_CSS + '</head>', 1)
    if '</body>' in page_html:
        page_html = page_html.replace('</body>', inject_html + '\n</body>', 1)
    return page_html


def main():
    pages = {}
    for num, label, title, part in CHAPTERS:
        path = os.path.join(OUT, f'nacos-chapter-{num}.html')
        if os.path.exists(path):
            pages[num] = open(path, encoding='utf-8').read()

    # PASS 1：全站源码路径索引
    by_base, by_suffix = build_path_index(pages.values())
    print(f'源码路径索引：{len(by_base)} 个文件（后缀 {len(by_suffix)} 条）')

    # PASS 2：源码链接 + TOC + 搜索索引
    toc_map, search_index, linked_pages, total_links = {}, [], {}, 0
    for num, label, title, part in CHAPTERS:
        if num not in pages:
            continue
        raw, n = link_source_refs(pages[num], by_base, by_suffix)
        total_links += n
        linked_pages[num] = raw
        toc = extract_toc(raw)
        toc_map[num] = toc
        snips = section_snippets(raw, toc)
        for lv, aid, text in toc:
            search_index.append({'u': f'nacos-chapter-{num}.html', 't': f'{label} {title}',
                                 's': text, 'a': aid, 'x': snips.get(aid, '')})
    print(f'源码链接：{total_links} 个')

    with open(os.path.join(OUT, 'search-index.js'), 'w', encoding='utf-8') as f:
        f.write('window.WIKI_INDEX = ')
        f.write(json.dumps(search_index, ensure_ascii=False, separators=(',', ':')))
        f.write(';\n')

    # PASS 3：注入三栏布局
    for num in linked_pages:
        label, title = next((c[1], c[2]) for c in CHAPTERS if c[0] == num)
        shell = (build_sidebar(CHAPTERS, active_num=num)
                 + build_crumb(CHAPTERS, num, {n: (t[0][2] if t else '') for n, t in toc_map.items()})
                 + build_pagetoc(toc_map[num])
                 + '<script src="search-index.js"></script>' + WIKI_JS
                 + build_pager(CHAPTERS, num))
        open(os.path.join(OUT, f'nacos-chapter-{num}.html'), 'w', encoding='utf-8').write(
            inject(linked_pages[num], shell))
        print(f'wiki ✓ 第{num}章 (小节 {len(toc_map[num])})')

    idx_path = os.path.join(OUT, 'index.html')
    if os.path.exists(idx_path):
        raw = open(idx_path, encoding='utf-8').read()
        shell = (build_sidebar(CHAPTERS, active_num=None)
                 + '<script src="search-index.js"></script>' + WIKI_JS)
        # index 无面包屑（自身即目录）
        open(idx_path, 'w', encoding='utf-8').write(inject(raw, shell))
        print('wiki ✓ index')


if __name__ == '__main__':
    main()
