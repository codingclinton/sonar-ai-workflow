export function detectLaravelLayer(relPath) {
  if (/\/ui\/app\//i.test(relPath)) return 'frontend';
  if (/\/Services\//i.test(relPath)) return 'service';
  if (/\/Controllers\//i.test(relPath)) return 'controller';
  if (/\/Jobs\//i.test(relPath)) return 'job';
  if (/\/Requests\//i.test(relPath)) return 'request';
  if (/\/GraphQL\/|\/Mutations\//i.test(relPath)) return 'graphql';
  return 'other';
}

export function extractPhpMetadata(content, relPath) {
  const nsMatch = content.match(/^namespace\s+([\w\\]+);/m);
  const classMatch = content.match(/\bclass\s+(\w+)/);
  return {
    namespace: nsMatch?.[1] ?? null,
    className: classMatch?.[1] ?? null,
    layerType: detectLaravelLayer(relPath),
  };
}
