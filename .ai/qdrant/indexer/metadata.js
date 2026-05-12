export function detectLaravelLayer(relPath) {
  const normalizedPath = relPath.replace(/\\/g, '/');

  if (/\/ui\/app\//i.test(normalizedPath)) return 'frontend';
  if (/\/Services\//i.test(normalizedPath)) return 'service';
  if (/\/Http\/Controllers\//i.test(normalizedPath)) return 'controller';
  if (/\/Jobs\//i.test(normalizedPath)) return 'job';
  if (/\/Http\/Requests\//i.test(normalizedPath)) return 'request';
  if (/\/GraphQL\/|\/Mutations\//i.test(normalizedPath)) return 'graphql';
  if (/\/Console\//i.test(normalizedPath)) return 'console';
  if (/\/Events\//i.test(normalizedPath)) return 'event';
  if (/\/Listeners\//i.test(normalizedPath)) return 'listener';
  if (/\/Notifications\//i.test(normalizedPath)) return 'notification';
  if (/\/Observers\//i.test(normalizedPath)) return 'observer';
  if (/\/Providers\//i.test(normalizedPath)) return 'provider';
  if (/\/Models\//i.test(normalizedPath)) return 'model';
  if (/\/app\/[^/]+\.php$/i.test(normalizedPath)) return 'model';
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
