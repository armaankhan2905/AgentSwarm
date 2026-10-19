import { describe, expect, it } from 'vitest';
import { decodeResearchRoute } from './route';

describe('research routing', () => {
  it('decodes valid IDs without allowing a decoded path separator', () => {
    expect(decodeResearchRoute('/research/session%201/')).toBe('session 1');
    expect(decodeResearchRoute('/research/session%2Fchild')).toBeNull();
  });

  it('turns malformed encoded paths into an ordinary non-research route', () => {
    expect(decodeResearchRoute('/research/%E0%A4%A')).toBeNull();
    expect(decodeResearchRoute('/history')).toBeNull();
  });
});
