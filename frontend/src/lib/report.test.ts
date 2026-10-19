import { describe, expect, it } from 'vitest';
import { reportToc } from './report';

describe('report navigation', () => {
  it('creates stable heading ids and recognizes citation labels', () => {
    expect(reportToc('# Findings\n\n## Findings\n\nThe result is [S1].\n\n## Next steps').map(item => item.id)).toEqual(['report-findings', 'report-findings-2', 'report-next-steps']);
  });
});
