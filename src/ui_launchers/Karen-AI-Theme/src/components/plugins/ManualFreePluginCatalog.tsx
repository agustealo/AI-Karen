'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

type Offering = { plugin_id: string; category: 'essential' | 'premium'; name: string; version: string; description: string; installation: 'manual' };
function valid(x: unknown): x is Offering {
  if (!x || typeof x !== 'object') return false;
  const p = x as Record<string, unknown>;
  return typeof p.plugin_id === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(p.plugin_id) &&
    (p.category === 'essential' || p.category === 'premium') && p.installation === 'manual' &&
    typeof p.name === 'string' && typeof p.version === 'string' && typeof p.description === 'string';
}

export default function ManualFreePluginCatalog() {
  const [offerings, setOfferings] = useState<Offering[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    setLoading(true);
    fetch('/api/extensions/free-catalog', { credentials: 'include', signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Plugin catalog unavailable');
        const data: unknown = await response.json();
        const list = data && typeof data === 'object' ? (data as { offerings?: unknown }).offerings : null;
        if (!Array.isArray(list) || !list.every(valid)) throw new Error('Invalid plugin catalog response');
        if (!controller.signal.aborted) setOfferings(list);
      })
      .catch((err: unknown) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Catalog unavailable'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);

  return <main className="space-y-6">
    <header className="space-y-2">
      <h1 className="text-2xl font-semibold">Free Plugins</h1>
      <p className="text-sm text-muted-foreground">Browse available packages. Users install plugins manually. No catalog entry is automatically installed, activated or verified healthy.</p>
      <Button type="button" variant="outline" disabled={loading} onClick={() => setRefresh(n => n + 1)}>Refresh catalog</Button>
    </header>
    <Card><CardHeader><CardTitle>Manual installation</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>From the Karen repository root, run the listed command for the plugin you want. Restart Karen or refresh the plugin registry afterward, then enable it separately.</p>
        <code className="block rounded bg-muted p-3">python scripts/manage_free_plugins.py list</code>
        <p className="text-muted-foreground">Existing packages will not be overwritten. Installing a package does not prove runtime or UI health.</p>
      </CardContent>
    </Card>
    {loading && <p role="status">Loading plugin catalog…</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {!loading && !error && (['essential', 'premium'] as const).map(category =>
      <section key={category} className="space-y-3">
        <h2 className="text-lg font-semibold capitalize">{category}</h2>
        {offerings.filter(p => p.category === category).length === 0 && <p className="text-sm text-muted-foreground">No packages available.</p>}
        <div className="grid gap-3 md:grid-cols-2">
          {offerings.filter(p => p.category === category).map(plugin =>
            <Card key={plugin.plugin_id}><CardHeader><CardTitle>{plugin.name} (v{plugin.version})</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm">{plugin.description}</p>
                <code className="block break-all rounded bg-muted p-3 text-xs">{['python scripts/manage_free_plugins.py install', category, plugin.plugin_id].join(' ')}</code>
                <p className="text-xs text-muted-foreground">Available for manual installation. Installation state is not asserted.</p>
              </CardContent>
            </Card>
          )}
        </div>
      </section>
    )}
  </main>;
}
