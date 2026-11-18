#!/usr/bin/env python3
"""Add locally verified game icons to an existing, preserved document edition.

Only presentation and verified item labels are enriched. Numerical inputs,
quantities, calculation results and evidence documents remain unchanged.
Uses the standard library; the output has no runtime/network dependencies.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit


VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
REWARD = re.compile(r'(?P<name>.*?)\s*\[(?P<id>\d+)\]\s*×\s*(?P<quantity>.+)', re.S)
DICTIONARY = '재화_콘텐츠_사전'


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return ''.join(c.text() if isinstance(c, Node) else c for c in self.children)

    def html(self):
        inside = ''.join(c.html() if isinstance(c, Node) else escape(c, quote=False) for c in self.children)
        if not self.tag:
            return inside
        attrs = ''.join(' ' + k + ('' if v is None else '="' + escape(str(v), quote=True) + '"') for k, v in self.attrs.items())
        return '<' + self.tag + attrs + '>' + ('' if self.tag in VOID else inside + '</' + self.tag + '>')

    def walk(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk(tag)


def node(tag, *children, **attrs):
    return Node(tag, {k.replace('_', '-'): v for k, v in attrs.items()}, list(children))


class Parser(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node('')
        self.stack = [self.root]
        self.feed(text)
        self.close()
        if len(self.stack) != 1:
            raise ValueError('Unclosed document tags')

    def handle_starttag(self, tag, attrs):
        n = Node(tag, dict(attrs))
        self.stack[-1].children.append(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack[-1].tag != tag:
            raise ValueError('Mismatched document tag: ' + tag)
        self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def clean(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', str(value or ''))).strip()


PURPOSES = {
    1: '계정의 연각 레벨을 올리는 경험치',
    2: '공명자·무기·에코 성장에 공통으로 쓰는 재화',
    3: '캐릭터·무기 모집 등에 사용하는 재화',
    5: '문서의 행동력. 반복 성장 콘텐츠의 보상 수령 시 소비',
    36000004: '에코 레벨을 올리는 경험치 재료',
    36000014: '5성 에코의 부옵션을 개방하는 재료',
    43010004: '공명자 레벨을 올리는 경험치 재료',
    43020004: '무기 레벨을 올리는 경험치 재료',
}

CSS = '''
/* Verified local Wuthering Waves icons; text remains the source of meaning. */
:root{--icon-bg:#27313b;--icon-line:#3f505f}
.game-icon{display:inline-block;width:36px;height:36px;object-fit:contain;flex:0 0 auto;padding:3px;border:1px solid var(--icon-line);border-radius:7px;background:var(--icon-bg);vertical-align:middle}
.game-icon[data-quality="2"]{border-bottom:3px solid #78be7e}.game-icon[data-quality="3"]{border-bottom:3px solid #73bafa}.game-icon[data-quality="4"]{border-bottom:3px solid #c09aee}.game-icon[data-quality="5"]{border-bottom:3px solid #e2b766}
.icon-link{display:inline-flex;align-items:center;gap:10px;max-width:100%;text-decoration:none;line-height:1.5}.icon-link:hover .icon-label{text-decoration:underline}
.icon-heading{display:flex;align-items:center;gap:18px}.icon-heading .game-icon{width:68px;height:68px;padding:7px;border-radius:12px}
.currency-label{display:inline-flex;align-items:center;gap:7px}.currency-label .game-icon{width:27px;height:27px;padding:2px;border-radius:5px}
.reward-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:9px;min-width:280px}.reward-entry{display:flex;align-items:center;gap:10px;border:1px solid #dce5e9;background:#fbfcfd;border-radius:8px;padding:9px 11px;text-decoration:none;color:var(--ink);line-height:1.4}.reward-entry:hover{border-color:#75a49e;background:#f1f8f6}.reward-entry .game-icon{width:44px;height:44px}.reward-entry strong{font-size:.9rem;display:block}.reward-entry small{font-size:.72rem;color:var(--muted);display:block;margin-top:3px}.reward-quantity{display:block;font-size:.83rem;margin-top:4px;font-variant-numeric:tabular-nums}.reward-quantity.unknown{color:#855b23}.reward-copy{min-width:0;overflow-wrap:anywhere}
.icon-missing{background:#eef1f3;border:1px dashed #9daab2;color:#596975;display:inline-flex;align-items:center;justify-content:center;flex:0 0 44px;width:44px;height:44px;border-radius:7px;font-size:.65rem;text-align:center;line-height:1.3}
.resource-guide{background:#f4f8f8;border:1px solid #d5e3e2;padding:18px;border-radius:10px;margin:24px 0}.resource-guide h2{border:0;padding:0;margin:0 0 12px;font-size:1rem}.resource-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px}.resource-count-4{grid-template-columns:repeat(4,minmax(0,1fr))}.resource-card{display:flex;align-items:center;gap:11px;color:var(--ink);text-decoration:none;font-size:.9rem;line-height:1.45}.resource-card:hover strong{text-decoration:underline}.resource-card small{display:block;color:var(--muted);font-size:.76rem;margin-top:3px}.resource-card .game-icon{width:46px;height:46px}.icon-note{font-size:.8rem;color:var(--muted);margin:12px 0 0}.icon-nav{display:flex;flex-wrap:wrap;gap:14px;margin:16px 0;font-size:.86rem}.icon-nav a{margin:0}
.dictionary-tabs{display:flex;flex-wrap:wrap;gap:12px}.dictionary-tabs a{background:#edf5f3;padding:8px 14px;border-radius:6px;text-decoration:none}.dictionary-table td:first-child{min-width:230px}.dictionary-table td:nth-child(2){min-width:100px}.dictionary-table small{display:block;color:var(--muted)}.dictionary-table tr:target{background:#fff4d5;outline:2px solid #d3b057;outline-offset:-2px}html{scroll-padding-top:20px}
@media(max-width:700px){.icon-heading{gap:12px}.icon-heading .game-icon{width:52px;height:52px}.reward-list{grid-template-columns:1fr;min-width:215px}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.resource-card{align-items:flex-start;font-size:.8rem}.resource-card .game-icon{width:36px;height:36px}.resource-guide{padding:12px}.icon-link .game-icon{width:32px;height:32px}}
@media print{.game-icon{-webkit-print-color-adjust:exact;print-color-adjust:exact}.reward-list{grid-template-columns:repeat(2,minmax(160px,1fr));min-width:0}.reward-entry{break-inside:avoid}.resource-guide{break-inside:avoid}.icon-nav{position:static}}
'''


class Enricher:
    def __init__(self, source, mapping, out):
        self.source, self.out = source, out
        self.original = load(mapping)
        self.records = {r['key']: dict(r) for r in self.original['records']}
        self.stats = Counter()
        self.parent = load(source / '문서_명세.json')
        for filename, expected in self.parent['files'].items():
            if sha(source / filename) != expected:
                raise ValueError('Source edition changed: ' + filename)
        if out.exists():
            raise ValueError('Output must be a new directory')
        shutil.copytree(source, out)
        (out / 'assets/icons').mkdir(parents=True)
        for r in self.records.values():
            r['name'] = clean(r['name'])
            if r['status'] != 'decoded':
                continue
            if sha(r['file']) != r['sha256']:
                raise ValueError('Icon hash mismatch: ' + r['key'])
            rel = 'assets/icons/' + r['sha256'][:20] + '.png'
            target = out / rel
            if not target.exists():
                shutil.copy2(r['file'], target)
            r['document_file'] = rel
        self.mapping = mapping

    def relative(self, rel, page):
        return Path(os.path.relpath(self.out / rel, (self.out / page).parent)).as_posix()

    def icon(self, r, page, size=36):
        if r.get('document_file'):
            self.stats['icon_uses'] += 1
            return node('img', src=self.relative(r['document_file'], page), alt=r['name'],
                        title=r['name'] + ' · ' + r['key'], width=size, height=size,
                        loading='lazy', decoding='async', **{'class': 'game-icon', 'data-icon-key': r['key'], 'data-quality': r.get('quality', '')})
        self.stats['missing_icon_uses'] += 1
        return node('span', '이미지\n미확인', role='img', aria_label=r['name'] + ' 이미지 미확인', **{'class': 'icon-missing'})

    def target_record(self, href):
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            return None
        p = Path(unquote(parsed.path))
        if p.suffix not in ['.html', '.md']:
            return None
        if p.parent.name == '개별콘텐츠':
            return self.records.get('dungeon:' + p.stem)
        return self.records.get('category:' + p.stem)

    def badge(self, r, page, label=None, href=None):
        return node('a' if href else 'span', self.icon(r, page), node('span', label or r['name'], **{'class': 'icon-label'}),
                    **({'href': href} if href else {}), **{'class': 'icon-link'})

    def guide(self, page, compact=False):
        keys = [5, 2, 3, 36000004, 36000014, 1]
        if compact:
            keys = [5, 2, 36000004, 36000014] if page.stem == 'tacet' else [5, 2, 1]
            if page.stem == 'role_exp': keys = [5, 43010004, 2, 1]
            if page.stem == 'weapon_exp': keys = [5, 43020004, 2, 1]
            if page.stem in ['tower', 'whimpering', 'matrix', 'hologram', 'tutorial', 'training', 'daily', 'rogue_archive', 'event_framework']:
                keys = [3, 2, 1]
        cards = []
        for item_id in keys:
            r = self.records.get('item:' + str(item_id))
            if not r:
                continue
            label = r['name'] + (' (행동력)' if item_id == 5 else '')
            cards.append(node('a', self.icon(r, page), node('span', node('strong', label), node('small', PURPOSES[item_id])),
                              href=self.relative(DICTIONARY + '.html', page) + '#item-' + str(item_id), **{'class': 'resource-card'}))
        return node('aside', node('h2', '재화 한눈에 보기'), node('div', *cards, **{'class': 'resource-grid resource-count-' + str(len(cards))}),
                    node('p', '아이콘은 종류를, 이름·등급·수량은 정확한 보상을 나타냅니다. EXP는 경험치량이며 재료 개수와 구분합니다.', **{'class': 'icon-note'}), **{'class': 'resource-guide', 'aria-label': '재화 안내'})

    def reward(self, match, page):
        item_id = match['id']
        r = self.records.get('item:' + item_id)
        if not r:
            raise ValueError('Missing item record ' + item_id)
        quality = (' · 등급 ' + str(r['quality'])) if r.get('quality') else ''
        preview = ' · 미리보기' if r.get('source_table') == 'previewitem' else ''
        qty = match['quantity'].strip()
        self.stats['reward_uses'] += 1
        return node('a', self.icon(r, page, 44), node('span', node('strong', r['name']),
                    node('small', 'ID ' + item_id + quality + preview),
                    node('span', '× ' + qty, **{'class': 'reward-quantity' + (' unknown' if '미확인' in qty else '')}), **{'class': 'reward-copy'}),
                    href=self.relative(DICTIONARY + '.html', page) + '#item-' + item_id,
                    data_item_id=item_id, data_quantity=qty, **{'class': 'reward-entry'})

    def html_page(self, page):
        root = Parser((self.source / page).read_text(encoding='utf-8')).root
        for a in list(root.walk('a')):
            r = self.target_record(a.attrs.get('href', ''))
            if r:
                a.children = [self.icon(r, page), node('span', *a.children, **{'class': 'icon-label'})]
                a.attrs['class'] = (a.attrs.get('class', '') + ' icon-link').strip()
        r = self.target_record(str(page))
        if r:
            h1 = next(root.walk('h1'))
            h1.children = [self.icon(r, page, 68), node('span', *h1.children)]
            h1.attrs['class'] = 'icon-heading'
        for cell in list(root.walk()):
            if cell.tag not in ['td', 'th']:
                continue
            rewards = []
            only_rewards = True
            for child in cell.children:
                if isinstance(child, str) and child.strip():
                    match = REWARD.fullmatch(child.strip())
                    if match:
                        rewards.append(self.reward(match, page))
                    else:
                        only_rewards = False
                elif isinstance(child, Node) and child.tag != 'br':
                    only_rewards = False
            if rewards and only_rewards:
                cell.children = [node('div', *rewards, **{'class': 'reward-list'})]
                continue
            if any(isinstance(c, Node) for c in cell.children):
                continue
            label = cell.text().strip()
            for text, item_id in [('특급 튜너',36000014),('특급 비밀음파 통',36000004),('클램 코인',2),('별의 소리',3),('연각 경험치',1),('행동력',5)]:
                if label == text or label.startswith(text + ' ') or label.startswith(text + '/'):
                    rec = self.records.get('item:' + str(item_id))
                    if rec:
                        cell.children = [node('span', self.icon(rec, page, 27), node('span', label), **{'class': 'currency-label'})]
                    break
        # Event register and any plain-text guide rows are keyed by ID, never by guessed names.
        for row in list(root.walk('tr')):
            cells = [c for c in row.children if isinstance(c, Node) and c.tag == 'td']
            if len(cells) < 2:
                continue
            key = cells[0].text().strip()
            if not key.isdigit() or any(c.tag == 'img' for c in cells[1].walk()):
                continue
            rec = self.records.get('activity:' + key) or self.records.get('dungeon:' + key)
            if rec and clean(cells[1].text()) == rec['name']:
                cells[1].children = [self.badge(rec, page)]
        main = next(root.walk('main'))
        main.children = [c for c in main.children if not (isinstance(c, Node) and c.tag == 'p' and c.text().strip() == '명조 문서 모음')]
        header = next(root.walk('header'))
        nav = node('nav', node('a', '문서 모음', href=self.relative('index.html', page)),
                   node('a', '재화·콘텐츠 사전', href=self.relative(DICTIONARY + '.html', page)),
                   **{'class': 'icon-nav', 'aria-label': '문서 안내'})
        main.children.insert(main.children.index(header) + 1, nav)
        if page.name == 'index.html' or page.parts[0] == '기획서' and r and r['kind'] == 'category':
            # After the existing lead, before the first main section/table.
            index = next((i for i,c in enumerate(main.children) if isinstance(c,Node) and c.attrs.get('class') == 'callout'), main.children.index(nav))
            main.children.insert(index + 1, self.guide(page, page.name != 'index.html'))
        (self.out / page).write_text('<!doctype html>' + root.html() + '\n', encoding='utf-8')
        self.stats['html_documents'] += 1

    def md_icon(self, r, page, size=30):
        if not r.get('document_file'):
            return ''
        src = self.relative(r['document_file'], page)
        return '<img src="' + escape(src, quote=True) + '" alt="' + escape(r['name'], quote=True) + '" width="' + str(size) + '" height="' + str(size) + '" style="background:#27313b;border-radius:5px;vertical-align:middle;padding:2px"> '

    def markdown_page(self, page):
        text = (self.source / page).read_text(encoding='utf-8')
        r = self.target_record(str(page))
        if r:
            text = re.sub(r'^# ', '# ' + self.md_icon(r, page, 44), text, count=1)
        def link(match):
            rec = self.target_record(match[2])
            return (self.md_icon(rec, page) if rec else '') + match[0]
        text = re.sub(r'\[([^\]\n]+)\]\(<([^>]+)>\)', link, text)
        def reward(match):
            r = self.records.get('item:' + match['id'])
            if not r:
                raise ValueError('Missing markdown item')
            quality = ' · 등급 ' + str(r['quality']) if r.get('quality') else ''
            return self.md_icon(r,page) + r['name'] + ' [' + match['id'] + ']' + quality + ' × ' + match['quantity']
        text = re.sub(r'(?P<name>[^\[\]\n|<>]+?)\s*\[(?P<id>\d+)\]\s*×\s*(?P<quantity>[^<|\n]+)', reward, text)
        first = text.index('\n')
        text = text[:first] + '\n\n[재화·콘텐츠 사전](<' + self.relative(DICTIONARY + '.md',page) + '>)' + text[first:]
        (self.out / page).write_text(text,encoding='utf-8')
        self.stats['markdown_documents'] += 1

    def dictionary(self):
        page = Path(DICTIONARY + '.html')
        sections = [node('header', node('p','WUTHERING WAVES / 명조', **{'class':'meta'}),node('h1','재화·콘텐츠 사전')),
                    node('nav',node('a','문서 모음',href='index.html'),**{'class':'icon-nav'}),
                    node('p','보상표와 콘텐츠 목록에서 사용하는 실제 게임 아이콘입니다. 아이콘과 이름을 함께 읽고, 비슷한 항목은 등급·ID로 구분하세요.'),
                    node('div',node('a','재화·보상',href='#items'),node('a','콘텐츠 유형',href='#categories'),node('a','개별 던전·도전',href='#dungeons'),**{'class':'dictionary-tabs'}),
                    self.guide(page),
                    node('p','미리보기 항목은 보상 종류를 표시하는 항목으로, 특정 개체나 수량의 확정 지급을 뜻하지 않습니다. 던전 아이콘에는 입구 그림뿐 아니라 해당 콘텐츠에 설정된 보스·공명자·에코 세트 그림도 포함됩니다.',**{'class':'icon-note'})]
        md=['# 재화·콘텐츠 사전','','[문서 모음](<index.md>)','','설치본의 아이콘과 명칭입니다. 등급·ID로 구분하며 미리보기 아이콘은 확정 지급을 뜻하지 않습니다.','']
        for kind, anchor, title, heads in [('item','items','재화·보상',['아이콘 / 이름','ID / 등급','용도·표시 의미']),('category','categories','콘텐츠 유형',['아이콘 / 이름','유형','기획서 / 분석서 / 제안서']),('dungeon','dungeons','개별 던전·도전',['아이콘 / 이름','가이드 ID / 지역','연결 분석서'])]:
            recs=[r for r in self.records.values() if r['kind']==kind]
            sections.append(node('h2',title + ' · ' + str(len(recs)) + '개',id=anchor))
            sections.append(node('div',node('label','이름 또는 ID ',node('input',type='search',placeholder='이름 · ID · 지역 검색',aria_label=title+' 검색')),node('output'),data_filter_table=anchor+'-table',**{'class':'filters'}))
            rows=[]
            md.extend(['','## '+title,'','| '+' | '.join(heads)+' |','| --- | --- | --- |'])
            for r in recs:
                if kind=='item':
                    desc=PURPOSES.get(r['id']) or clean(r.get('description','')) or '설치본에 등록된 보상 항목'
                    if r.get('source_table')=='previewitem': desc='보상 미리보기 · '+desc
                    if r['status']!='decoded': desc+=' · 원본 이미지 확인 필요'
                    detail=str(r['id'])+(' · 등급 '+str(r['quality']) if r.get('quality') else '')
                    last=node('span',desc)
                    mdlast=desc
                elif kind=='category':
                    detail=str(r['id'])
                    last=node('span',node('a','기획서',href='기획서/'+r['id']+'.html'),' · ',node('a','분석서',href='분석서/'+r['id']+'.html'),' · ',node('a','제안서',href='제안서/'+r['id']+'.html'))
                    mdlast=' · '.join('['+v+'](<'+v+'/'+r['id']+'.md>)' for v in ['기획서','분석서','제안서'])
                else:
                    detail=str(r['id'])+' · '+r.get('region','')
                    last=node('a','개별 보상 근거표',href='분석서/개별콘텐츠/'+str(r['id'])+'.html')
                    mdlast='[개별 보상 근거표](<분석서/개별콘텐츠/'+str(r['id'])+'.md>)'
                rows.append(node('tr',node('td',self.badge(r,page)),node('td',detail),node('td',last),id=kind+'-'+str(r['id'])))
                md.append('| '+self.md_icon(r,Path(DICTIONARY+'.md'))+r['name'].replace('|','/')+' | '+detail+' | '+mdlast.replace('|','/')+' |')
            sections.append(node('div',node('table',node('thead',node('tr',*(node('th',h) for h in heads))),node('tbody',*rows),id=anchor+'-table',**{'class':'dictionary-table'}),**{'class':'scroll'}))
        sections.extend([node('h2','아이콘 출처'),node('p','명조 설치본 3.8.0의 아이템·미리보기·에코·콘텐츠 가이드·이벤트 테이블에 연결된 리소스입니다. 문서와 함께 저장되어 인터넷 연결 없이 표시됩니다.'),
                         node('p',node('a','아이콘과 원본 리소스 연결 명세',href='아이콘_출처.json'),' · ',node('a','문서 생성·검증 명세',href='문서_명세.json'))])
        root=node('html',node('head',node('meta',charset='utf-8'),node('meta',name='viewport',content='width=device-width,initial-scale=1'),node('title','명조 · 재화·콘텐츠 사전'),node('link',rel='stylesheet',href='style.css')),node('body',node('main',*sections),node('script',src='filter.js')),lang='ko')
        (self.out/page).write_text('<!doctype html>'+root.html()+'\n',encoding='utf-8')
        (self.out/(DICTIONARY+'.md')).write_text('\n'.join(md)+'\n',encoding='utf-8')

    def run(self):
        for p in sorted(self.source.rglob('*.html')):
            self.html_page(p.relative_to(self.source))
        for p in sorted(self.source.rglob('*.md')):
            self.markdown_page(p.relative_to(self.source))
        self.dictionary()
        with (self.out/'style.css').open('a',encoding='utf-8') as f:
            f.write(CSS)
        save(self.out/'아이콘_출처.json',dict(game='명조',client='3.8.0',mapping_file=str(self.mapping),mapping_sha256=sha(self.mapping),
                note='Item and content IDs select configured icons; identical icons may represent different qualities. Preview icons are not guaranteed drops.',
                records=list(self.records.values())))
        save(self.out/'이전_문서_명세.json',self.parent)
        manifest=dict(self.parent)
        manifest['presentation']={'edition':'20261118_아이콘보강','base_manifest':'이전_문서_명세.json','icon_manifest':'아이콘_출처.json',
                                  'statistics':dict(self.stats),'unique_images':len(list((self.out/'assets/icons').glob('*.png'))),
                                  'records_by_status':dict(Counter(r['kind']+':'+r['status'] for r in self.records.values()))}
        manifest['source_files']=dict(manifest['source_files'])
        manifest['source_files'].update({str(Path(__file__).resolve()):sha(__file__),str(self.mapping):sha(self.mapping)})
        manifest['files']={str(p.relative_to(self.out)):sha(p) for p in sorted(self.out.rglob('*')) if p.is_file() and p.name!='문서_명세.json'}
        save(self.out/'문서_명세.json',manifest)
        print(json.dumps(manifest['presentation'],ensure_ascii=False,indent=2))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--documents',type=Path,required=True)
    ap.add_argument('--icons',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    Enricher(a.documents.resolve(),a.icons.resolve(),a.out.resolve()).run()


if __name__=='__main__':
    main()
