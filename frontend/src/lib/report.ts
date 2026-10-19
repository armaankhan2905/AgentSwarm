import { unified } from 'unified';
import remarkParse from 'remark-parse';

interface AstNode { type: string; value?: string; depth?: number; children?: AstNode[]; url?: string; data?: { hProperties?: Record<string, unknown> } }
export interface TocEntry { id: string; title: string; depth: number }
function nodeText(node: AstNode): string { return node.value ?? node.children?.map(nodeText).join('') ?? ''; }
export function decorateReport(tree: AstNode): TocEntry[] {
  const toc: TocEntry[] = []; const slugs = new Map<string, number>();
  function walk(node: AstNode, insideLink = false) {
    if (node.type === 'heading') {
      const title = nodeText(node); const slug = title.toLowerCase().normalize('NFKD').replace(/[^a-z0-9\s-]/g, '').trim().replace(/\s+/g, '-') || 'section';
      const count = (slugs.get(slug) || 0) + 1; slugs.set(slug, count);
      const id = `report-${slug}${count > 1 ? `-${count}` : ''}`;
      node.data = { ...node.data, hProperties: { ...node.data?.hProperties, id } };
      toc.push({ id, title, depth: node.depth || 2 });
    }
    if (!node.children || node.type === 'code' || node.type === 'inlineCode') return;
    const linked = insideLink || node.type === 'link' || node.type === 'linkReference';
    node.children = node.children.flatMap(child => {
      if (child.type !== 'text' || linked) { walk(child, linked); return [child]; }
      const value = child.value || ''; const matches = [...value.matchAll(/\[(S\d+)\]/g)];
      if (!matches.length) return [child];
      let last = 0; const nodes: AstNode[] = [];
      for (const match of matches) {
        if (match.index! > last) nodes.push({ type: 'text', value: value.slice(last, match.index) });
        nodes.push({ type: 'link', url: `#evidence-${match[1]}`, children: [{ type: 'text', value: match[0] }] });
        last = match.index! + match[0].length;
      }
      if (last < value.length) nodes.push({ type: 'text', value: value.slice(last) }); return nodes;
    });
  }
  walk(tree); return toc;
}
export function reportToc(markdown: string): TocEntry[] { return decorateReport(unified().use(remarkParse).parse(markdown)); }
export function remarkResearch() { return (tree: AstNode) => { decorateReport(tree); }; }
