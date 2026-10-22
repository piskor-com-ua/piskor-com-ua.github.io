"""Generate agent-readable facts from the same rendered content visitors can read."""
from html.parser import HTMLParser
from pathlib import Path
import json
import re


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        if self.tag in {'script', 'style'} or 'hidden' in self.attrs or self.attrs.get('aria-hidden') == 'true':
            return ''
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def find(self, predicate):
        found = []
        for child in self.children:
            if isinstance(child, Node):
                if predicate(child):
                    found.append(child)
                found.extend(child.find(predicate))
        return found

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.root = Node()
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def read_agent_projects(output):
    """Read current public cards and case facts without modifying the artifact."""
    output = Path(output)
    projects = []
    for language, route in [('uk', 'portfolio'), ('en', 'en/portfolio')]:
        catalog = Document((output / route / 'index.html').read_text()).root
        for card in catalog.find(lambda n: n.tag == 'a' and n.has_class('portfolio-card')):
            url = card.attrs['href']
            if not re.fullmatch(r'/(?:en/)?portfolio/\d{4}/[\w-]+/', url):
                raise ValueError('Invalid project URL: ' + url)
            page = Document((output / url.lstrip('/') / 'index.html').read_text()).root
            facts = page.find(lambda n: n.has_class('project-facts'))
            fact_pairs = []
            if facts:
                terms = facts[0].find(lambda n: n.tag == 'dt')
                values = facts[0].find(lambda n: n.tag == 'dd')
                fact_pairs = [{'label': a.text(), 'value': b.text()} for a, b in zip(terms, values)]
            sections = []
            for section in page.find(lambda n: n.tag == 'section' and n.has_class('case-chapter')):
                headings = section.find(lambda n: n.tag == 'h2')
                sections.append({
                    'title': headings[0].text(),
                    'url': url + '#' + section.attrs['id'],
                    'text': ' '.join(n.text() for n in section.find(lambda n: n.tag == 'p')),
                })
            headings = card.find(lambda n: n.tag == 'h3')
            summaries = card.find(lambda n: n.tag == 'p' and not n.has_class('eyebrow'))
            labels = card.find(lambda n: n.tag == 'p' and n.has_class('eyebrow'))
            projects.append({
                'id': card.attrs['data-project-id'], 'language': language,
                'year': int(url.strip('/').split('/')[-2]),
                'name': headings[0].text(), 'url': url,
                'summary': summaries[0].text(), 'label': labels[0].text(),
                'facts': fact_pairs, 'sections': sections,
            })
    return projects


def generate_agent_catalog(output):
    output = Path(output)
    projects = read_agent_projects(output)
    (output / 'project-catalog.json').write_text(json.dumps(
        {'version': 1, 'projects': projects}, ensure_ascii=False, separators=(',', ':')) + '\n')
    lines = ['# PISKOR Architect', '',
             '> Архітектура, інтер’єри та автоматизація просторів. Architecture, interiors and space automation.', '',
             'Project facts and implementation status are described on each linked case page.', '',
             '## Navigation', '',
             '- [Портфоліо](https://piskor.com.ua/portfolio/)',
             '- [Portfolio](https://piskor.com.ua/en/portfolio/)',
             '- [Інженерна автоматизація](https://piskor.com.ua/engineering-automation/)',
             '- [Building automation](https://piskor.com.ua/en/engineering-automation/)',
             '- [Контакти / Contact](https://piskor.com.ua/#contact)', '',
             '## Agent skills', '',
             '- [Agent Skills discovery index](https://piskor.com.ua/.well-known/agent-skills/index.json)',
             '- [Portfolio browsing guide](https://piskor.com.ua/agent-skills/piskor-portfolio/SKILL.md)', '']
    for language, heading in [('uk', 'Проєкти українською'), ('en', 'Projects in English')]:
        lines += ['## ' + heading, '']
        lines += ['- [' + p['name'].replace('[', '').replace(']', '') + '](https://piskor.com.ua' + p['url'] + '): ' + p['label']
                  for p in projects if p['language'] == language]
        lines += ['']
    (output / 'llms.txt').write_text('\n'.join(lines))
    return projects
