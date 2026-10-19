export function decodeResearchRoute(pathname: string): string | null {
  const match = pathname.match(/^\/research\/([^/]+)\/?$/);
  if (!match) return null;
  try {
    const id = decodeURIComponent(match[1]);
    if (!id || id.includes('/') || /[\u0000-\u001f\u007f]/.test(id)) return null;
    return id;
  } catch {
    return null;
  }
}
